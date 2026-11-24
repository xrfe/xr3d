"""Run and download bounded PySLM preview jobs."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from backend.config import settings

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend" / "workers" / "slm.py"
MAX_MODEL_BYTES = 24 * 1024 * 1024
UNAVAILABLE = "Run Install XR3D Server to set up PySLM."
preview_slot = asyncio.Lock()


def worker_python() -> Path:
    return Path(sys.executable)


async def run_worker(executable: Path, *arguments: str, timeout: int) -> int:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LD_LIBRARY_PATH"}
    environment = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    async with asyncio.timeout(timeout):
        process = await asyncio.create_subprocess_exec(
            str(executable), "-I", str(WORKER), *arguments, cwd=ROOT, env=environment,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await process.wait()
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()


async def runtime_configured(check: str) -> bool:
    executable = worker_python()
    if executable.is_file():
        try:
            return await run_worker(executable, check, timeout=10) == 0
        except (OSError, TimeoutError):
            pass
    return False


async def preview_response(model, config, options_type, feature, operation):
    temporary = None
    try:
        try:
            options = options_type.model_validate_json(config)
        except ValidationError as error:
            raise HTTPException(422, f"Invalid {feature} preview settings") from error
        if Path(model.filename or "").suffix.lower() != ".stl":
            raise HTTPException(422, "Select a closed STL model in millimetres")
        executable = worker_python()
        if not executable.is_file():
            raise HTTPException(503, UNAVAILABLE)
        if preview_slot.locked():
            raise HTTPException(429, "A layer preview is already running")

        async with preview_slot:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.TemporaryDirectory(prefix=f"{feature.lower()}-", dir=settings.DATA_DIR)
            folder = Path(temporary.name)
            size = 0
            with (folder / "model.stl").open("wb") as output:
                while chunk := await model.read(65_536):
                    size += len(chunk)
                    if size > MAX_MODEL_BYTES:
                        raise HTTPException(413, f"STL exceeds the 24 MB {feature} preview limit")
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "The STL model is empty")
            (folder / "config.json").write_text(options.model_dump_json(), encoding="utf-8")

            try:
                status = await run_worker(executable, operation, str(folder), timeout=90)
            except OSError as error:
                raise HTTPException(503, UNAVAILABLE) from error
            except TimeoutError as error:
                raise HTTPException(504, f"{feature} preparation exceeded its 90-second time limit") from error
            if status == 3:
                raise HTTPException(503, UNAVAILABLE)
            if status == 2:
                raise HTTPException(422, (folder / "input-error.txt").read_text(encoding="utf-8"))
            result = folder / "preview.zip"
            if status != 0 or not result.is_file():
                raise HTTPException(502, "PySLM could not generate the layer preview")
            response = FileResponse(result, filename=f"xr3d-{feature.lower()}-preview.zip", media_type="application/zip",
                                    background=BackgroundTask(temporary.cleanup))
            temporary = None
            return response
    finally:
        if temporary is not None:
            temporary.cleanup()
        await model.close()
