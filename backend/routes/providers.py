from fastapi import APIRouter, Depends
from backend.security import require_token
from backend.schemas import ProviderCapabilities
from backend.services.inference import available
router = APIRouter(prefix="/providers", tags=["Providers"], dependencies=[Depends(require_token)])

@router.get("", response_model=list[ProviderCapabilities])
async def list_providers():
    return [ProviderCapabilities(provider_id=provider, name=name, supported_formats=["GLB", "OBJ", "STL", "PLY"],
                                 max_image_inputs=4 if provider == "MESHY_MULTI" else 1, status="ONLINE" if available(provider) else "NOT_CONFIGURED")
            for provider, name in [("TRELLIS_2", "TRELLIS.2"), ("HUNYUAN_3D", "Hunyuan3D"), ("MESHY_SINGLE", "Meshy Single Image"), ("MESHY_MULTI", "Meshy Multi Image")]]
