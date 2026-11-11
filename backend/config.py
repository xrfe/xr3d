import os
from pathlib import Path

class Settings:
    APP_NAME = "AI 3D Studio Backend API"
    VERSION = "1.1.0"
    API_PREFIX = "/api/v1"
    DATA_DIR = Path(os.getenv("XR3D_DATA_DIR", "backend-data")).resolve()
    API_TOKEN = os.getenv("XR3D_API_TOKEN", "")
    CORS_ORIGINS = [x for x in os.getenv("XR3D_CORS_ORIGINS", "").split(",") if x]
    MAX_IMAGE_BYTES = 20 * 1024 * 1024
    MAX_MODEL_BYTES = 256 * 1024 * 1024
    JOB_TIMEOUT_SECONDS = int(os.getenv("XR3D_JOB_TIMEOUT_SECONDS", "3600"))
    MAX_PENDING_JOBS = max(1, int(os.getenv("XR3D_MAX_PENDING_JOBS", "8")))
    LOCAL_COMMAND = os.getenv("XR3D_LOCAL_COMMAND", "")
    LOCAL_PROVIDER = os.getenv("XR3D_LOCAL_PROVIDER", "TRELLIS_2")
    FAL_KEY = os.getenv("FAL_KEY", "")
    MESHY_API_KEY = os.getenv("MESHY_API_KEY", "")
    MESHY_MODEL = os.getenv("MESHY_MODEL", "meshy-7.1")
    FAL_TRELLIS_MODEL = os.getenv("FAL_TRELLIS_MODEL", "fal-ai/trellis-2")
    FAL_HUNYUAN_MODEL = os.getenv("FAL_HUNYUAN_MODEL", "")

settings = Settings()
