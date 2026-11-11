import json
import sys
import pytest
import trimesh
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.main import app
from backend.config import settings
from backend.routes import slicer
from backend.services.slicing import SlicingOptions


def config(**changes):
    return dict(technology="FDM_PLASTIC", layerHeightMm=.2, initialLayerHeightMm=.24,
                nozzleDiameterMm=.4, nozzleTempC=240, bedTempC=75, infillPercent=25,
                printSpeedMms=45, buildWidthMm=200, buildDepthMm=200, buildHeightMm=200,
                wallLineCount=3, topLayers=6, bottomLayers=5, infillPattern="TRIANGLES",
                supportType="ORGANIC", supportAngleDegrees=50, enableBrim=False, brimWidthMm=7,
                filamentDiameterMm=1.75, filamentDensityGcm3=1.27, **changes)


@pytest.mark.parametrize("pattern", ["GRID", "GYROID", "HONEYCOMB", "TRIANGLES", "CONCENTRIC", "CUBIC"])
def test_selected_infill_is_never_substituted(pattern):
    data = config(); data["infillPattern"] = pattern
    args = SlicingOptions(**data).cli_options()
    assert args[args.index("--fill-pattern") + 1] == pattern.lower()


@pytest.mark.parametrize("style,expected", [("NORMAL", "grid"), ("ORGANIC", "organic"), ("NONE", None)])
def test_support_styles_are_distinct(style, expected):
    data = config(); data["supportType"] = style
    args = SlicingOptions(**data).cli_options()
    if expected is None:
        assert "--no-support-material" in args and "--support-material-style" not in args
    else:
        assert args[args.index("--support-material-style") + 1] == expected


@pytest.mark.parametrize("field,value", [("supportType", "TREE"), ("infillPattern", "unknown"),
    ("wallLineCount", 2.5), ("layerHeightMm", float("nan")), ("brimWidthMm", -1),
    ("enableBrim", "false"), ("technology", "SLM_METAL"), ("unknownSetting", True)])
def test_unsupported_settings_fail_instead_of_using_defaults(field, value):
    data = config(); data[field] = value
    with pytest.raises(ValidationError):
        SlicingOptions(**data)


def test_http_slicing_preserves_settings_and_requires_calibrated_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "API_TOKEN", "test-token")
    monkeypatch.setenv("XR3D_SLICER_EXECUTABLE", sys.executable)
    monkeypatch.delenv("XR3D_SLICER_PROFILE", raising=False)
    mesh = trimesh.creation.box(extents=[10, 10, 10]).export(file_type="stl")
    # No lifespan: this test must not recover or modify the real job store.
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    def submit(data):
        return client.post("/api/v1/slicer/slice", files={"model": ("part.stl", mesh)}, data={"config": json.dumps(data)})
    assert submit(config()).status_code == 503
    profile = tmp_path / "printer.ini"; profile.write_text("gcode_flavor = klipper\n")
    monkeypatch.setenv("XR3D_SLICER_PROFILE", str(profile))
    captured = []
    class Process:
        returncode = 0
        async def wait(self): return 0
    async def run(*args, **kwargs):
        from pathlib import Path
        captured.extend(args)
        Path(args[args.index("--output") + 1]).write_text(";LAYER_CHANGE\nG1 X1 Y1 E1\n")
        return Process()
    monkeypatch.setattr(slicer.asyncio, "create_subprocess_exec", run)
    result = submit(config())
    assert result.status_code == 200 and b"G1 X1" in result.content
    expected = {"--fill-pattern": "triangles", "--support-material-style": "organic", "--first-layer-height": "0.24",
                "--top-solid-layers": "6", "--bottom-solid-layers": "5", "--support-material-threshold": "50.0",
                "--filament-density": "1.27", "--brim-width": "0", "--load": str(profile)}
    for option, value in expected.items():
        assert captured[captured.index(option) + 1] == value
    captured.clear()
    bad = config(); bad["supportType"] = "TREE"
    assert submit(bad).status_code == 422 and not captured
    client.close()
