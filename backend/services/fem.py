"""Request contract and runtime discovery for the Strecs3D FEM workflow."""
import os
import sys
from importlib.util import find_spec
from math import hypot
from pathlib import Path
from shutil import which
from typing import Literal

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


class TransverseIsotropy(FemOptionsModel):
    inPlaneYoungsModulusMpa: float = Field(ge=1e-6, le=1e7)
    throughLayerYoungsModulusMpa: float = Field(ge=1e-6, le=1e7)
    inPlanePoissonsRatio: float = Field(gt=-1, lt=1)
    crossPlanePoissonsRatio: float
    crossPlaneShearModulusMpa: float = Field(ge=1e-6, le=1e7)
    buildDirection: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_material(self):
        norm = hypot(*self.buildDirection)
        if not 1e-10 <= norm < float("inf"):
            raise ValueError("Specify a nonzero build direction in the model's XYZ coordinates")
        ratio = self.throughLayerYoungsModulusMpa / self.inPlaneYoungsModulusMpa
        # Positive definiteness of the normal compliance block. The shear compliances are positive.
        coupling = abs(self.crossPlanePoissonsRatio) * ratio**0.5
        limit = ((1 - self.inPlanePoissonsRatio) / 2)**0.5
        if self.inPlanePoissonsRatio < -1 + 1e-10 or limit < 1e-5 or coupling >= limit * (1 - 1e-10):
            raise ValueError("The elastic constants do not define a stable material")
        return self

    @property
    def in_plane_shear(self):
        return self.inPlaneYoungsModulusMpa / (2 * (1 + self.inPlanePoissonsRatio))


class FemOptions(FemOptionsModel):
    elementSizeMm: float = Field(ge=0.05, le=500)
    meshMode: Literal["uniform", "automatic", "adaptive"] = "adaptive"
    repairToleranceMm: float | None = Field(default=None, gt=0, le=25)
    youngsModulusMpa: float | None = Field(default=None, gt=0, le=1e7)
    poissonsRatio: float | None = Field(default=None, gt=-1, lt=0.5)
    transverseIsotropy: TransverseIsotropy | None = None
    fixed: list[Face | SurfaceBox] = Field(min_length=1, max_length=16)
    loads: list[SurfaceLoad] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def one_material_model(self):
        if self.transverseIsotropy is None:
            if self.youngsModulusMpa is None or self.poissonsRatio is None:
                raise ValueError("Specify both isotropic elastic constants")
        elif self.youngsModulusMpa is not None or self.poissonsRatio is not None:
            raise ValueError("Select one elastic material model")
        return self


class InvalidModel(ValueError):
    pass


def managed_solver_path() -> Path:
    return Path(sys.prefix) / "tools" / "calculix" / "ccx_i4_static.exe"


def solver_executable() -> str | None:
    configured = os.getenv("XR3D_CCX_EXECUTABLE", "").strip()
    executable = which(configured) if configured else None
    if executable:
        return str(Path(executable).resolve())
    managed = managed_solver_path()
    if sys.platform == "win32" and managed.is_file():
        return str(managed)
    executable = which("ccx")
    return str(Path(executable).resolve()) if executable else None


def fem_dependencies_available() -> bool:
    return all(find_spec(package) is not None for package in ("gmsh", "igl", "rtree", "scipy", "fast_simplification"))
