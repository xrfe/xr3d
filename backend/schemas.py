from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class ProviderType(str, Enum):
    MESHY_SINGLE = "MESHY_SINGLE"
    MESHY_MULTI = "MESHY_MULTI"
    TRELLIS_2 = "TRELLIS_2"
    HUNYUAN_3D = "HUNYUAN_3D"
    TRIPO_3D = "TRIPO_3D"
    PIXAL_3D = "PIXAL_3D"
    CUSTOM_REST = "CUSTOM_REST"
    MOCK = "MOCK"

class QualityPreset(str, Enum):
    DRAFT_FAST = "DRAFT_FAST"
    BALANCED = "BALANCED"
    HIGH_DETAIL = "HIGH_DETAIL"
    ULTRA_PRECISION = "ULTRA_PRECISION"

class OutputFormat(str, Enum):
    GLB = "GLB"
    OBJ = "OBJ"
    STL = "STL"
    PLY = "PLY"

class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class ReconstructionRequest(ApiModel):
    meshy_key_source: str = Field(default="SERVER", pattern="^(SERVER|USER)$")
    project_id: str = Field(min_length=1, max_length=128)
    provider: ProviderType = ProviderType.TRELLIS_2
    prompt_text: str | None = Field(default=None, max_length=2000)
    quality_preset: QualityPreset = QualityPreset.BALANCED
    generate_textures: bool = True
    texture_resolution: int = Field(default=2048, ge=256, le=4096)
    target_format: OutputFormat = OutputFormat.GLB
    max_poly_count: int = Field(default=100000, ge=1000, le=1000000)

class ReconstructionJobResponse(ApiModel):
    job_id: str
    project_id: str
    provider: ProviderType
    status: JobStatus
    progress_percent: float = 0
    current_step_name: str = "Waiting for source images"
    output_model_url: str | None = None
    error_message: str | None = None
    created_at: float
    updated_at: float

class ProviderCapabilities(ApiModel):
    provider_id: str
    name: str
    supported_formats: list[str]
    max_image_inputs: int
    supports_text_prompt: bool = False
    supports_texture_generation: bool = True
    estimated_time_seconds: int = 0
    status: str
