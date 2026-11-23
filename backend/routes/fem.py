"""Authenticated Strecs3D-style static FEM analysis."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from backend.config import settings
from backend.security import require_token
from backend.services.fem import FEM_TIMEOUT_SECONDS, MAX_FEM_MODEL_BYTES, SUPPORTED_MODELS, FemOptions, gmsh_installed, solver_executable

router = APIRouter(prefix="/fem", tags=["Strecs3D FEM"], dependencies=[Depends(require_token)])
fem_slot = asyncio.Lock()
ROOT = Path(__file__).resolve().parents[2]


@router.get("")
async def fem_status():
    return {"configured": gmsh_installed() and solver_executable() is not None,
            "analysis": "linear-static-solid", "inputFormats": ["STEP", "STL"], "outputFormat": "VTU"}


async def run_stage(args, cwd, log, failure):
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH") if key in os.environ}
    env["OMP_NUM_THREADS"] = "1"
    try:
        process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, stdout=log, stderr=log)
    except OSError as error:
        raise HTTPException(502, failure) from error
    try:
        if await process.wait() != 0:
            raise HTTPException(502, failure)
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


@router.post("/solve", response_class=FileResponse)
async def solve(model: UploadFile = File(...), config: str = Form(...)):
    try:
        options = FemOptions.model_validate_json(config)
    except ValidationError as error:
        raise HTTPException(422, "Invalid FEM settings. Specify mesh size, elastic properties, fixed regions, and loads") from error
    suffix = Path(model.filename or "").suffix.lower()
    if suffix not in SUPPORTED_MODELS:
        raise HTTPException(422, "Select a STEP or closed STL model")
    executable = solver_executable()
    if not executable or not gmsh_installed():
        raise HTTPException(503, "Install requirements.fem.txt and configure XR3D_CCX_EXECUTABLE")
    if fem_slot.locked():
        raise HTTPException(429, "A FEM solve is already running; try again when it finishes")

    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="fem-", dir=settings.DATA_DIR)
    downloaded = False
    try:
        async with fem_slot:
            folder = Path(temporary.name).resolve()
            source = folder / f"solid{suffix}"
            total = 0
            with source.open("wb") as output:
                while chunk := await model.read(65_536):
                    total += len(chunk)
                    if total > MAX_FEM_MODEL_BYTES:
                        raise HTTPException(413, "FEM model exceeds the 24 MB limit")
                    output.write(chunk)
            if not total:
                raise HTTPException(422, "The FEM model is empty")
            (folder / "request.json").write_text(options.model_dump_json(), encoding="utf-8")

            worker = (sys.executable, "-m", "backend.workers.fem")
            try:
                async with asyncio.timeout(FEM_TIMEOUT_SECONDS):
                    with (folder / "worker.log").open("wb") as log:
                        try:
                            await run_stage((*worker, "prepare", str(folder), source.name), ROOT, log, "Could not prepare the FEM mesh")
                        except HTTPException as error:
                            invalid = folder / "invalid-model.txt"
                            if invalid.is_file():
                                raise HTTPException(422, invalid.read_text(encoding="utf-8")) from error
                            raise
                        await run_stage((executable, "-i", "analysis"), folder, log, "CalculiX failed to solve the model")
                        await run_stage((*worker, "convert", str(folder), source.name), ROOT, log, "CalculiX did not produce valid FEM results")
            except TimeoutError as error:
                raise HTTPException(504, "FEM analysis exceeded its time limit") from error

            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
            result = folder / "result.vtu"
            if result.stat().st_size > settings.MAX_MODEL_BYTES:
                raise HTTPException(413, "FEM result exceeds the download limit")
            response = FileResponse(result, filename="xr3d-fem.vtu", media_type="application/xml",
                                    headers={"X-XR3D-FEM-Nodes": str(summary["nodes"]),
                                             "X-XR3D-FEM-Elements": str(summary["elements"]),
                                             "X-XR3D-Max-Stress-MPa": str(summary["maxStressMpa"]),
                                             "X-XR3D-Max-Displacement-Mm": str(summary["maxDisplacementMm"])},
                                    background=BackgroundTask(temporary.cleanup))
            downloaded = True
            return response
    finally:
        await model.close()
        if not downloaded:
            temporary.cleanup()
