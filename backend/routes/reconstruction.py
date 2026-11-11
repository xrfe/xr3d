import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from backend.config import settings
from backend.schemas import ReconstructionRequest, ReconstructionJobResponse
from backend.security import require_token
from backend.services.redis_queue import JobStore
from backend.services.inference import available, infer, convert_model

router = APIRouter(prefix="/reconstruct", tags=["Reconstruction"], dependencies=[Depends(require_token)])
store = JobStore(settings.DATA_DIR)
tasks = {}
gpu_lock = asyncio.Lock()
logger = logging.getLogger(__name__)
from backend.services.meshy import PROVIDERS as MESHY_PROVIDERS, key_for

def get_job(job_id):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Reconstruction job not found")
    return job

@router.post("/jobs", response_model=ReconstructionJobResponse, status_code=201)
async def create_job(request: ReconstructionRequest):
    if sum(job["status"] in ("QUEUED", "PROCESSING") for job in store.all()) >= settings.MAX_PENDING_JOBS:
        raise HTTPException(429, "Job queue is full. Finish or cancel an existing job before retrying.", headers={"Retry-After": "30"})
    if request.provider.value == "CUSTOM_REST":
        from backend.schemas import ProviderType
        request = request.model_copy(update={"provider": ProviderType(settings.LOCAL_PROVIDER)})
    if not available(request.provider.value) and not (request.provider.value in MESHY_PROVIDERS and request.meshy_key_source == "USER"):
        raise HTTPException(503, "Provider is not configured. Configure local inference or a hosted provider on the server.")
    if request.prompt_text:
        raise HTTPException(422, "This image-to-3D adapter does not support text prompts")
    job_id = str(uuid.uuid4())
    now = time.time()
    job = {"job_id": job_id, "project_id": request.project_id, "provider": request.provider.value,
           "status": "QUEUED", "progress_percent": 0, "current_step_name": "Waiting for source images",
           "output_model_url": None, "error_message": None, "created_at": now, "updated_at": now,
           "request": request.model_dump(mode="json"), "submitted": False}
    store.save(job)
    return ReconstructionJobResponse(**job)

async def execute(job_id, paths, meshy_key=None):
    directory = settings.DATA_DIR / job_id
    directory.mkdir(parents=True,exist_ok=True)
    try:
        async with asyncio.timeout(settings.JOB_TIMEOUT_SECONDS):
            async with gpu_lock:
                store.update(job_id, status="PROCESSING", progress_percent=10, current_step_name="Running image-to-3D model")
                job = get_job(job_id)
                if job["provider"] in MESHY_PROVIDERS:
                    job = {**job, "_meshy_api_key": meshy_key}
                source = await infer(job, paths, directory, lambda **fields: store.update(job_id, **fields))
                store.update(job_id, progress_percent=90, current_step_name="Validating and exporting model")
                request = get_job(job_id)["request"]
                await asyncio.to_thread(convert_model, source, directory, request["target_format"], request["max_poly_count"], request["generate_textures"])
                store.update(job_id, status="COMPLETED", progress_percent=100, current_step_name="Reconstruction complete",
                             output_model_url=f"{settings.API_PREFIX}/reconstruct/jobs/{job_id}/download")
    except asyncio.CancelledError:
        job = store.get(job_id)
        if job and job["status"] != "CANCELLED":
            if job["provider"] in MESHY_PROVIDERS and job.get("meshy_task_id"):
                store.update(job_id, status="QUEUED", current_step_name="Reconnect to resume existing Meshy task")
            else:
                store.update(job_id, status="FAILED", error_message="Server stopped; check provider task history before retrying")
        raise
    except Exception:
        # HTTP exceptions contain request headers/body; never log Meshy credentials/data URIs.
        logger.error("Reconstruction failed for job %s", job_id)
        store.update(job_id, status="FAILED", current_step_name="Reconstruction failed",
                     error_message="Meshy failed or timed out. Check your Meshy task history and credits before retrying." if get_job(job_id)["provider"] in MESHY_PROVIDERS else "Inference failed or timed out. Check server configuration and worker logs, then retry.")
    finally:
        tasks.pop(job_id, None)

@router.post("/jobs/{job_id}/images")
async def upload_images(job_id: str, images: list[UploadFile] = File(...), x_meshy_api_key: str | None = Header(default=None)):
    job = get_job(job_id)
    if job["submitted"] or job["status"] != "QUEUED":
        raise HTTPException(409, "Job has already been submitted")
    if job["provider"] == "MESHY_MULTI" and not 2 <= len(images) <= 4:
        raise HTTPException(422, "Meshy multi-image requires 2 to 4 views of the same object")
    if job["provider"] != "MESHY_MULTI" and len(images) != 1:
        raise HTTPException(422, "This adapter requires exactly one source image; select single-view capture")
    meshy_key = None
    if job["provider"] in MESHY_PROVIDERS:
        try: meshy_key = key_for(job,x_meshy_api_key)
        except ValueError as error: raise HTTPException(422,str(error)) from error
    directory = settings.DATA_DIR / job_id
    directory.mkdir(exist_ok=True)
    paths = []
    try:
        from PIL import Image, ImageOps
        for index, image in enumerate(images):
            path = directory / f"input-{uuid.uuid4().hex}.image"
            size = 0
            with path.open("wb") as output:
                while chunk := await image.read(65536):
                    size += len(chunk)
                    if size > settings.MAX_IMAGE_BYTES:
                        raise HTTPException(413, "Image exceeds 20 MB")
                    output.write(chunk)
            try:
                with Image.open(path) as decoded:
                    if decoded.format not in ("JPEG", "PNG", "WEBP"):
                        raise ValueError("Unsupported image")
                    if decoded.width * decoded.height > 50_000_000:
                        raise ValueError("Image resolution exceeds limit")
                    if job["provider"] in MESHY_PROVIDERS and min(decoded.size) < 32:
                        raise ValueError("Meshy images need at least 32 pixels per side")
                    decoded.verify()
                with Image.open(path) as decoded:
                    normalized = ImageOps.exif_transpose(decoded).convert("RGBA")
                    normalized.thumbnail((4096, 4096))
                    normalized_path = path.with_suffix(".png")
                    normalized.save(normalized_path, format="PNG")
                if normalized_path.stat().st_size > settings.MAX_IMAGE_BYTES:
                    raise ValueError("Normalized image exceeds upload size limit")
                path.unlink()
                path = normalized_path
            except Exception as error:
                raise HTTPException(422, "Provide a valid JPEG, PNG or WebP image") from error
            paths.append(path)
        current = get_job(job_id)
        if current["submitted"] or current["status"] != "QUEUED":
            raise HTTPException(409, "Job has already been submitted or cancelled")
        store.update(job_id, submitted=True, image_paths=[str(path) for path in paths], current_step_name="Queued for inference")
        tasks[job_id] = asyncio.create_task(execute(job_id, paths, meshy_key))
        return {"jobId": job_id, "uploadedCount": len(paths), "status": "QUEUED"}
    finally:
        for image in images:
            await image.close()

@router.get("/jobs/{job_id}", response_model=ReconstructionJobResponse)
async def status(job_id: str, x_meshy_api_key: str | None = Header(default=None)):
    job = get_job(job_id)
    if job["provider"] in MESHY_PROVIDERS and job.get("meshy_task_id") and job["status"] in ("QUEUED","PROCESSING") and job_id not in tasks:
        try: key = key_for(job,x_meshy_api_key)
        except ValueError as error: raise HTTPException(422,"Re-enter your Meshy key to resume the existing task") from error
        tasks[job_id] = asyncio.create_task(execute(job_id, [], key))
    return ReconstructionJobResponse(**job)

@router.post("/jobs/{job_id}/cancel", response_model=ReconstructionJobResponse)
async def cancel(job_id: str):
    job = get_job(job_id)
    if job["status"] in ("COMPLETED", "FAILED"):
        raise HTTPException(409, "Job has already finished")
    job = store.update(job_id, status="CANCELLED", current_step_name="Tracking stopped; Meshy generation may continue and use credits" if job["provider"] in MESHY_PROVIDERS else "Cancelled")
    task = tasks.get(job_id)
    if task:
        task.cancel()
    return ReconstructionJobResponse(**job)

@router.get("/jobs/{job_id}/download")
async def download(job_id: str):
    job = get_job(job_id)
    if job["status"] != "COMPLETED":
        raise HTTPException(409, "Model is not ready")
    path = settings.DATA_DIR / job_id / f"model.{job['request']['target_format'].lower()}"
    if not path.is_file():
        raise HTTPException(410, "Model file is no longer available")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

@asynccontextmanager
async def lifespan(app):
    for job in store.all():
        if job["status"] in ("PROCESSING", "QUEUED") and job["submitted"]:
            if job["provider"] in MESHY_PROVIDERS and job.get("meshy_task_id"):
                store.update(job["job_id"],status="QUEUED",current_step_name="Reconnect to resume existing Meshy task")
            else:
                store.update(job["job_id"], status="FAILED", error_message="Server restarted; check provider history before retrying inference")
    yield
    pending = list(tasks.values())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
