"""Geometry-based FDM slicing through an installed PrusaSlicer CLI."""
import asyncio
import os
from pathlib import Path
import tempfile
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from backend.security import require_token
from backend.config import settings
from backend.services.slicing import SlicingOptions
from pydantic import ValidationError

router = APIRouter(prefix="/slicer", tags=["Slicer"], dependencies=[Depends(require_token)])
slicer_lock = asyncio.Lock()


@router.post("/slice")
async def slice_model(model: UploadFile = File(...), config: str = Form(...)):
    executable = os.getenv("XR3D_SLICER_EXECUTABLE", "")
    if not executable or not Path(executable).is_file():
        raise HTTPException(503, "Install PrusaSlicer CLI and configure XR3D_SLICER_EXECUTABLE on the server")
    try:
        options = SlicingOptions.model_validate_json(config)
    except ValidationError as error:
        raise HTTPException(422, "Unsupported or invalid slicing settings. Use FDM, a listed infill, and None/Normal/Organic supports.") from error
    profile = os.getenv("XR3D_SLICER_PROFILE", "")
    if not profile or not Path(profile).is_file():
        raise HTTPException(503, "Configure XR3D_SLICER_PROFILE with a calibrated PrusaSlicer printer profile (.ini)")
    import trimesh
    with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as folder:
        source = Path(folder) / "input.stl"
        output = Path(folder) / "output.gcode"
        size = 0
        try:
            with source.open("wb") as stream:
                while chunk := await model.read(65536):
                    size += len(chunk)
                    if size > settings.MAX_MODEL_BYTES:
                        raise HTTPException(413, "Model exceeds size limit")
                    stream.write(chunk)
        finally:
            await model.close()
        try:
            mesh = await asyncio.to_thread(trimesh.load, source, force="mesh")
            if len(mesh.faces) == 0 or not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
                raise ValueError("Repair mesh holes before slicing")
            if any(actual > limit for actual, limit in zip(mesh.extents, [options.buildWidthMm, options.buildDepthMm, options.buildHeightMm])):
                raise ValueError("Model exceeds printer build volume")
        except Exception as error:
            raise HTTPException(422, "Provide a watertight STL that fits the printer build volume") from error
        args = [executable, "--load", profile, "--export-gcode", "--output", str(output),
                "--center", f"{options.buildWidthMm/2},{options.buildDepthMm/2}",
                *options.cli_options(), str(source)]
        async with slicer_lock:
            with (Path(folder) / "slicer.log").open("wb") as log:
                process = await asyncio.create_subprocess_exec(*args, stdout=log, stderr=log)
                try:
                    await asyncio.wait_for(process.wait(), 300)
                    if process.returncode != 0 or not output.is_file():
                        raise HTTPException(502, "PrusaSlicer failed; verify the installed CLI and settings")
                    if output.stat().st_size > settings.MAX_MODEL_BYTES:
                        raise HTTPException(413, "Generated toolpath exceeds size limit")
                    return Response(output.read_bytes(), media_type="text/plain")
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
