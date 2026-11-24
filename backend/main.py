import os
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from backend.security import require_token
from backend.services.inference import available
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.config import settings
from backend.routes.pairing import router as pairing_router
from backend.routes.docs import ASSETS as DOCS_ASSETS, router as docs_router
from backend.routes.reconstruction import router as reconstruction_router, lifespan
from backend.routes.providers import router as providers_router
from backend.routes.slicer import router as slicer_router
from backend.routes.printers import router as printer_router
from backend.routes.print_engine import router as print_engine_router
from backend.routes.fem import router as fem_router
from backend.routes.slm import router as slm_router
from backend.routes.resin import router as resin_router
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan,
              openapi_url=f"{settings.API_PREFIX}/openapi.json", docs_url=None, redoc_url=None)
if settings.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Meshy-Api-Key"])
app.include_router(reconstruction_router, prefix=settings.API_PREFIX)
app.include_router(providers_router, prefix=settings.API_PREFIX)
app.include_router(slicer_router, prefix=settings.API_PREFIX)
app.include_router(printer_router, prefix=settings.API_PREFIX)
app.include_router(print_engine_router, prefix=settings.API_PREFIX)
app.include_router(fem_router, prefix=settings.API_PREFIX)
app.include_router(slm_router, prefix=settings.API_PREFIX)
app.include_router(resin_router, prefix=settings.API_PREFIX)
app.include_router(pairing_router, prefix=settings.API_PREFIX)
app.include_router(docs_router)
app.mount(f"{settings.API_PREFIX}/docs-assets", StaticFiles(directory=DOCS_ASSETS), name="docs_assets")

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
