"""Authenticated SLM layer preparation using an optional PySLM worker."""
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.routes.layer_previews import preview_response, runtime_configured
from backend.security import require_token

router = APIRouter(prefix="/slm", tags=["SLM preparation"], dependencies=[Depends(require_token)])


class PreviewOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    layerThicknessMm: float = Field(ge=0.01, le=1)
    hatchSpacingMm: float = Field(ge=0.01, le=5)
    strategy: Literal["parallel", "stripe", "island"] = "parallel"
    hatchAngleDeg: float = Field(default=0, ge=0, lt=180)
    layerRotationDeg: float = Field(default=0, ge=0, lt=180)


@router.get("")
async def slm_status():
    return {"configured": await runtime_configured("check"), "inputFormat": "STL", "outputFormat": "XR3D SLM preview ZIP",
            "strategies": ["parallel", "stripe", "island"], "machineExport": False}


@router.post("/preview", response_class=FileResponse)
async def slm_preview(model: UploadFile = File(...), config: str = Form(...)):
    return await preview_response(model, config, PreviewOptions, "SLM", "preview")
