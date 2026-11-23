"""Authenticated bitmap previews for resin model preparation."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.routes.layer_previews import preview_response, runtime_configured
from backend.security import require_token

router = APIRouter(prefix="/resin", tags=["Resin preparation"], dependencies=[Depends(require_token)])
PlateDimension = Annotated[float, Field(ge=1, le=500)]
Angle = Annotated[float, Field(ge=-180, le=180)]


class ResinOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    layerThicknessMm: float = Field(ge=0.01, le=1)
    pixelSizeMm: float = Field(ge=0.05, le=1)
    buildVolumeMm: tuple[PlateDimension, PlateDimension, PlateDimension]
    rotationDeg: tuple[Angle, Angle] = (0, 0)


@router.get("")
async def resin_status():
    return {"configured": await runtime_configured("check-resin"), "inputFormat": "STL",
            "outputFormat": "XR3D resin preview ZIP", "machineExport": False}


@router.post("/preview", response_class=FileResponse)
async def resin_preview(model: UploadFile = File(...), config: str = Form(...)):
    return await preview_response(model, config, ResinOptions, "Resin", "resin")
