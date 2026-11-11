import os
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from backend.security import require_token
from backend.services.inference import available
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.routes.reconstruction import router as reconstruction_router, lifespan
from backend.routes.providers import router as providers_router
from backend.routes.slicer import router as slicer_router
from backend.routes.printers import router as printer_router
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan,
              openapi_url=f"{settings.API_PREFIX}/openapi.json", docs_url=f"{settings.API_PREFIX}/docs")
if settings.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Meshy-Api-Key"])
app.include_router(reconstruction_router, prefix=settings.API_PREFIX)
app.include_router(providers_router, prefix=settings.API_PREFIX)
app.include_router(slicer_router, prefix=settings.API_PREFIX)
app.include_router(printer_router, prefix=settings.API_PREFIX)

@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    if request.url.path.startswith(f"{settings.API_PREFIX}/printers/vendor"):
        # Pydantic's default model-level error embeds the full input object,
        # including a LAN access code. Never echo printer request bodies.
        return JSONResponse(status_code=422, content={"detail": "Invalid vendor printer request"})
    return await request_validation_exception_handler(request, error)

@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.VERSION}

@app.get("/ready", dependencies=[Depends(require_token)])
async def ready():
    inference = any(available(provider) for provider in ("TRELLIS_2", "HUNYUAN_3D", "MESHY_SINGLE"))
    executable = os.getenv("XR3D_SLICER_EXECUTABLE", "")
    profile = os.getenv("XR3D_SLICER_PROFILE", "")
    return JSONResponse(status_code=200 if inference else 503, content={
        "ready": inference, "inferenceConfigured": inference,
        "slicingConfigured": bool(executable and Path(executable).is_file() and profile and Path(profile).is_file()),
        "deployment": "private-single-owner", "liveInferenceVerified": False,
    })
