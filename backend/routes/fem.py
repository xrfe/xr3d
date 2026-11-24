"""Authenticated Strecs3D-style static FE analysis."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from backend.config import settings
from backend.security import require_token
from backend.services.fem import (
    FEM_TIMEOUT_SECONDS, MAX_FEM_MODEL_BYTES, SUPPORTED_MODELS, FemOptions, fem_dependencies_available, solver_executable,
)

router = APIRouter(prefix="/fem", tags=["Strecs3D FEM"], dependencies=[Depends(require_token)])
fem_slot = asyncio.Lock()
ROOT = Path(__file__).resolve().parents[2]
MAX_ADAPTIVE_PASSES = 3
ENERGY_ERROR_TARGET = 0.075
WORK_CHANGE_TARGET = 0.02


@router.get("")
async def fem_status():
    return {"configured": fem_dependencies_available() and solver_executable() is not None,
            "analysis": "linear-static-solid", "inputFormats": ["STEP", "STL"], "outputFormat": "VTU",
            "meshModes": ["uniform", "automatic", "adaptive"],
            "materialModels": ["isotropic", "transversely-isotropic"],
            "plannedAnalyses": ["residual-stress", "print-warping", "thermo-mechanical-coupling"]}


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


async def solve_pass(directory, source, executable, mobile, log, previous=None):
    worker = (sys.executable, "-m", "backend.workers.fem")
    prepare = "prepare-mobile" if mobile else "prepare"
    convert = "convert-mobile" if mobile else "convert"
    previous_arg = (str(previous),) if previous is not None else ()
    try:
        await run_stage((*worker, prepare, str(directory), str(source), *previous_arg), ROOT, log, "Could not prepare the FEM mesh")
        await run_stage((executable, "-i", "analysis"), directory, log, "CalculiX failed to solve the model")
        await run_stage((*worker, convert, str(directory), str(source)), ROOT, log, "CalculiX did not produce valid FEM results")
    except HTTPException as error:
        invalid = directory / "invalid-model.txt"
        if invalid.is_file():
            raise HTTPException(422, invalid.read_text(encoding="utf-8")) from error
        raise
    return json.loads((directory / "summary.json").read_text(encoding="utf-8"))


async def solve_model(folder, source, options, executable, mobile):
    deadline = asyncio.get_running_loop().time() + FEM_TIMEOUT_SECONDS
    request = options.model_dump_json()
    (folder / "request.json").write_text(request, encoding="utf-8")
    best = folder
    with (folder / "worker.log").open("wb") as log:
        async with asyncio.timeout_at(deadline):
            summary = await solve_pass(folder, source, executable, mobile, log)
        history = [summary]
        status = "single-pass"
        if options.meshMode == "adaptive":
            status = "pass-limit"
            for iteration in range(1, MAX_ADAPTIVE_PASSES):
                if "energyError" not in summary:
                    status = "estimate-unavailable"
                    break
                if asyncio.get_running_loop().time() >= deadline - 5:
                    status = "time-limit"
                    break
                candidate = folder / f"pass-{iteration + 1}"
                candidate.mkdir()
                (candidate / "request.json").write_text(request, encoding="utf-8")
                try:
                    async with asyncio.timeout_at(deadline - 2):
                        refined = await solve_pass(candidate, source, executable, mobile, log, previous=best)
                except TimeoutError:
                    status = "time-limit"
                    break
                except HTTPException as error:
                    status = "refinement-stopped"
                    reason = str(error.detail)
                    log.write((reason + "\n").encode("utf-8"))
                    summary = {**summary, "stopReason": reason}
                    break
                if "energyError" not in refined:
                    status = "estimate-unavailable"
                    break
                work_change = abs(refined["complianceNmm"] / summary["complianceNmm"] - 1)
                refined["workChange"] = work_change
                best, summary = candidate, refined
                history.append(summary)
                if summary["energyError"] <= ENERGY_ERROR_TARGET and work_change <= WORK_CHANGE_TARGET:
                    status = "converged"
                    break
    return best, summary, status, history


@router.post("/solve", response_class=FileResponse)
async def solve(model: UploadFile = File(...), config: str = Form(...),
                output_format: Literal["vtu", "mobile"] = Form("vtu")):
    try:
        options = FemOptions.model_validate_json(config)
    except ValidationError as error:
        issue = error.errors()[0]
        if issue["type"] == "value_error":
            raise HTTPException(422, issue["msg"].removeprefix("Value error, ")) from error
        raise HTTPException(422, "Invalid FEM settings. Specify mesh size, elastic properties, fixed regions, and loads") from error
    suffix = Path(model.filename or "").suffix.lower()
    if suffix not in SUPPORTED_MODELS:
        raise HTTPException(422, "Select a STEP or closed STL model")
    executable = solver_executable()
    if not executable or not fem_dependencies_available():
        raise HTTPException(503, "Run Install XR3D Server and check that CalculiX is available")
    if fem_slot.locked():
        raise HTTPException(429, "A FEM solve is already running; try again when it finishes")
    mobile = output_format == "mobile"

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
            try:
                best, summary, status, history = await solve_model(folder, source, options, executable, mobile)
            except TimeoutError as error:
                raise HTTPException(504, "FE analysis exceeded its time limit") from error

            result = best / ("mobile.zip" if mobile else "result.vtu")
            if max(result.stat().st_size, (best / "result.vtu").stat().st_size) > settings.MAX_MODEL_BYTES:
                raise HTTPException(413, "FEM result exceeds the download limit")
            headers = {"X-XR3D-FEM-Nodes": str(summary["nodes"]),
                       "X-XR3D-FEM-Elements": str(summary["elements"]),
                       "X-XR3D-Max-Stress-MPa": str(summary["maxStressMpa"]),
                       "X-XR3D-Max-Displacement-Mm": str(summary["maxDisplacementMm"]),
                       "X-XR3D-FEM-Mesh-Method": summary["method"],
                       "X-XR3D-FEM-Mesh-Status": status,
                       "X-XR3D-FEM-Material-Model": ("transversely-isotropic" if options.transverseIsotropy else "isotropic"),
                       "X-XR3D-FEM-Mesh-Passes": str(len(history)),
                       "X-XR3D-FEM-Preview-Simplified": str(summary["previewSimplified"]).lower()}
            for key, name in (("energyError", "Energy-Error"), ("sampledDeviationMm", "Surface-Deviation-Mm")):
                if key in summary:
                    headers[f"X-XR3D-FEM-{name}"] = str(summary[key])
            if "stopReason" in summary:
                headers["X-XR3D-FEM-Stop-Reason"] = " ".join(summary["stopReason"].split())[:256]
            keys = ("elements", "energyError", "complianceNmm", "workChange", "minQuality")
            headers["X-XR3D-FEM-Mesh-History"] = json.dumps(
                [{key: item[key] for key in keys if key in item} for item in history], separators=(",", ":"))
            response = FileResponse(result, filename="xr3d-fem.zip" if mobile else "xr3d-fem.vtu",
                                    media_type="application/zip" if mobile else "application/xml",
                                    headers=headers,
                                    background=BackgroundTask(temporary.cleanup))
            downloaded = True
            return response
    finally:
        await model.close()
        if not downloaded:
            temporary.cleanup()
