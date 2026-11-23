"""Request contract and runtime discovery for the Strecs3D FEM workflow."""
import os
from importlib.util import find_spec
from pathlib import Path
from shutil import which

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FEM_MODEL_BYTES = 24 * 1024 * 1024
FEM_TIMEOUT_SECONDS = 180
SUPPORTED_MODELS = {".step", ".stp", ".stl"}


class FemOptionsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Face(FemOptionsModel):
    faceId: int = Field(gt=0)


class SurfaceBox(FemOptionsModel):
    minMm: tuple[float, float, float]
    maxMm: tuple[float, float, float]

    @model_validator(mode="after")
    def ordered_bounds(self):
        if any(low > high for low, high in zip(self.minMm, self.maxMm)):
            raise ValueError("Every lower bound must be at or below its upper bound")
        return self


class SurfaceLoad(FemOptionsModel):
    region: Face | SurfaceBox
    forceN: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_load(self):
        if not 1e-6 <= max(map(abs, self.forceN)) <= 1e7:
            raise ValueError("Specify a nonzero force in newtons within the supported range")
        return self


class FemOptions(FemOptionsModel):
    elementSizeMm: float = Field(ge=0.05, le=500)
    youngsModulusMpa: float = Field(gt=0, le=1e7)
    poissonsRatio: float = Field(gt=-1, lt=0.5)
    fixed: list[Face | SurfaceBox] = Field(min_length=1, max_length=16)
    loads: list[SurfaceLoad] = Field(min_length=1, max_length=16)


def solver_executable() -> str | None:
    executable = which(os.getenv("XR3D_CCX_EXECUTABLE", "") or "ccx")
    return str(Path(executable).resolve()) if executable else None


def gmsh_installed() -> bool:
    return find_spec("gmsh") is not None
