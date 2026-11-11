"""Validated Android-to-PrusaSlicer settings contract (PrusaSlicer 2.9.2+).

Option names: https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/PrintConfig.cpp
"""
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Infill(str, Enum):
    GRID = "GRID"
    GYROID = "GYROID"
    HONEYCOMB = "HONEYCOMB"
    TRIANGLES = "TRIANGLES"
    CONCENTRIC = "CONCENTRIC"
    CUBIC = "CUBIC"


class Support(str, Enum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    ORGANIC = "ORGANIC"


class SlicingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    technology: str = Field(pattern="^FDM_PLASTIC$")
    layerHeightMm: float = Field(ge=.05, le=.6)
    initialLayerHeightMm: float = Field(default=.28, ge=.05, le=.6)
    nozzleDiameterMm: float = Field(ge=.2, le=1.2)
    nozzleTempC: float = Field(ge=150, le=300)
    bedTempC: float = Field(ge=0, le=120)
    infillPercent: float = Field(ge=0, le=100)
    printSpeedMms: float = Field(ge=5, le=300)
    buildWidthMm: float = Field(ge=20, le=2000)
    buildDepthMm: float = Field(ge=20, le=2000)
    buildHeightMm: float = Field(ge=20, le=2000)
    wallLineCount: int = Field(ge=1, le=10)
    topLayers: int = Field(default=4, ge=0, le=100)
    bottomLayers: int = Field(default=3, ge=0, le=100)
    infillPattern: Infill
    supportType: Support = Support.NONE
    supportAngleDegrees: float = Field(default=45, ge=0, le=90)
    enableBrim: StrictBool = False
    brimWidthMm: float = Field(default=5, ge=0, le=50)
    filamentDiameterMm: float = Field(default=1.75, ge=1, le=3.5)
    filamentDensityGcm3: float = Field(default=1.24, ge=.5, le=3)

    def cli_options(self) -> list[str]:
        values = {
            "layer-height": self.layerHeightMm,
            "first-layer-height": self.initialLayerHeightMm,
            "nozzle-diameter": self.nozzleDiameterMm,
            "temperature": self.nozzleTempC,
            "first-layer-temperature": self.nozzleTempC,
            "bed-temperature": self.bedTempC,
            "first-layer-bed-temperature": self.bedTempC,
            "fill-density": f"{self.infillPercent}%",
            "fill-pattern": self.infillPattern.value.lower(),
            "perimeters": self.wallLineCount,
            "top-solid-layers": self.topLayers,
            "bottom-solid-layers": self.bottomLayers,
            "perimeter-speed": self.printSpeedMms,
            "infill-speed": self.printSpeedMms,
            "support-material-threshold": self.supportAngleDegrees,
            "filament-diameter": self.filamentDiameterMm,
            "filament-density": self.filamentDensityGcm3,
            "brim-width": self.brimWidthMm if self.enableBrim else 0,
            "bed-shape": f"0x0,{self.buildWidthMm}x0,{self.buildWidthMm}x{self.buildDepthMm},0x{self.buildDepthMm}",
            "max-print-height": self.buildHeightMm,
        }
        args = [part for key, value in values.items() for part in (f"--{key}", str(value))]
        if self.supportType == Support.NONE:
            args += ["--no-support-material", "--no-support-material-auto", "--support-material-enforce-layers", "0"]
        else:
            args += ["--support-material", "--support-material-auto", "--support-material-style",
                     "grid" if self.supportType == Support.NORMAL else "organic"]
        return args
