"""XR3D's authenticated server discovery and advanced model checks."""
import asyncio
from pathlib import Path
import tempfile
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.config import settings
from backend.security import require_token
from backend.services.print_engine import EngineError, EngineTimeout, EngineUnavailable, run_engine

router = APIRouter(prefix="/print-engine", tags=["XR3D Print Engine"], dependencies=[Depends(require_token)])
advanced_slots = asyncio.Semaphore(2)
discovery_slot = asyncio.Lock()
MAX_INSPECTION_BYTES = 24 * 1024 * 1024


class ModelOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nozzleMm: float = Field(default=0.4, ge=0.1, le=2)
    buildVolumeMm: tuple[float, float, float] | None = None


async def execute(operation, **parameters):
    try:
        async with advanced_slots:
            job = asyncio.create_task(asyncio.to_thread(run_engine, operation, **parameters))
            try:
                return await asyncio.shield(job)
            except asyncio.CancelledError:
                await asyncio.gather(job, return_exceptions=True)
                raise
    except EngineUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except EngineTimeout as error:
        raise HTTPException(504, str(error)) from error
    except EngineError as error:
        raise HTTPException(422 if operation == "inspect" else 502, str(error)) from error


@router.get("")
async def engine_status():
    return await execute("health", timeout=10)


@router.get("/discover")
async def discover():
    async with discovery_slot:
        return await execute("discover", timeout=18)


@router.post("/inspect")
async def inspect(model: UploadFile = File(...), config: str = Form("{}")):
    try:
        try:
            options = ModelOptions.model_validate_json(config)
        except ValidationError as error:
            raise HTTPException(422, "Invalid print inspection settings") from error
        volume = options.buildVolumeMm
        if volume and not all(20 <= size <= 3000 for size in volume):
            raise HTTPException(422, "Build dimensions must be between 20 and 3000 mm")
        if not (model.filename or "").lower().endswith(".stl"):
            raise HTTPException(422, "Select an STL model")
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="inspect-", dir=settings.DATA_DIR) as folder:
            source = Path(folder) / "model.stl"
            size = 0
            with source.open("wb") as output:
                while chunk := await model.read(65536):
                    size += len(chunk)
                    if size > MAX_INSPECTION_BYTES:
                        raise HTTPException(413, "STL exceeds the 24 MB inspection limit")
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "The STL model is empty")
            return await execute("inspect", path=str(source.resolve()), nozzle=options.nozzleMm,
                                 build_volume=volume, timeout=60)
    finally:
        await model.close()
