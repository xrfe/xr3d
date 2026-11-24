"""Geometry-based FDM slicing through an installed PrusaSlicer CLI."""
import asyncio
import os
from pathlib import Path
import tempfile
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from backend.security import require_token
from backend.config import settings
from backend.services.slicing import SlicingOptions
from pydantic import ValidationError

router = APIRouter(prefix="/slicer", tags=["Slicer"], dependencies=[Depends(require_token)])
slicer_lock = asyncio.Lock()


async def wait_for_disconnect(request: Request):
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def run_prusa_slicer(request: Request, args: list[str], log_path: Path) -> int:
    async def run():
        async with slicer_lock:
            with log_path.open("wb") as log:
                launched = asyncio.create_task(asyncio.create_subprocess_exec(*args, stdout=log, stderr=log))
                try:
                    process = await asyncio.shield(launched)
                    await asyncio.wait_for(process.wait(), 300)
                    return process.returncode
                finally:
                    # Finish spawning before releasing the lock, even if the client went away.
                    process = await launched
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        await process.wait()

    if await request.is_disconnected():
        raise HTTPException(499, "Slicing client disconnected")
    work = asyncio.create_task(run())
    disconnected = asyncio.create_task(wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait((work, disconnected), return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return await work
        raise HTTPException(499, "Slicing client disconnected")
    except TimeoutError as error:
        raise HTTPException(504, "PrusaSlicer exceeded its time limit") from error
    finally:
        disconnected.cancel()
        if not work.done():
            work.cancel()
        await asyncio.gather(disconnected, work, return_exceptions=True)


@router.post("/slice")
async def slice_model(request: Request, model: UploadFile = File(...), config: str = Form(...)):
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
    try:
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=settings.DATA_DIR)
    except OSError as error:
        raise HTTPException(503, "The server slicing directory is unavailable") from error
    keep_output = False
    try:
        folder = Path(temporary.name)
        source = folder / "input.stl"
        output = folder / "output.gcode"
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
        return_code = await run_prusa_slicer(request, args, folder / "slicer.log")
        if return_code != 0 or not output.is_file():
            raise HTTPException(502, "PrusaSlicer failed; verify the installed CLI and settings")
        if output.stat().st_size > settings.MAX_MODEL_BYTES:
            raise HTTPException(413, "Generated toolpath exceeds size limit")
        response = FileResponse(output, media_type="text/plain", background=BackgroundTask(temporary.cleanup))
        keep_output = True
        return response
    finally:
        if not keep_output:
            temporary.cleanup()
