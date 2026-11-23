from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest
import trimesh

from backend.config import settings
from backend.main import app
from backend.routes.layer_previews import worker_python


OPTIONS = {"layerThicknessMm": 0.5, "pixelSizeMm": 0.1, "buildVolumeMm": [120, 68, 150], "rotationDeg": [0, 0]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "API_TOKEN", "resin-test-token")
    client = TestClient(app, headers={"Authorization": "Bearer resin-test-token"})
    yield client
    client.close()


def preview(client, mesh, **options):
    return client.post("/api/v1/resin/preview", files={"model": ("sample.stl", mesh.export(file_type="stl"))},
                       data={"config": json.dumps({**OPTIONS, **options})})


def test_resin_requires_auth_and_valid_options(client, monkeypatch, tmp_path):
    monkeypatch.setenv("XR3D_SLM_PYTHON", str(tmp_path / "missing-python"))
    assert client.get("/api/v1/resin", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/resin").json()["configured"] is False
    mesh = trimesh.creation.box()
    assert preview(client, mesh).status_code == 503
    assert preview(client, mesh, pixelSizeMm=0).status_code == 422
    assert preview(client, mesh, exposureSeconds=2).status_code == 422


@pytest.mark.skipif(not worker_python().is_file(), reason="Install the optional PySLM runtime")
def test_resin_masks_preserve_holes_and_report_area_volume(client):
    assert client.get("/api/v1/resin").json()["configured"] is True
    mesh = trimesh.creation.annulus(r_min=3, r_max=6, height=2.25, sections=96)
    mesh.apply_translation((4, 9, 7))
    response = preview(client, mesh)
    assert response.status_code == 200, response.text[:400] if not response.is_success else None
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["kind"] == "resinPreview" and not manifest["machineReady"]
        assert manifest["modelSizeMm"] == pytest.approx([12, 12, 2.25])
        assert len(manifest["layers"]) == 5
        for index, layer in enumerate(manifest["layers"]):
            with Image.open(BytesIO(archive.read(f"layers/{index}.png"))) as image:
                assert image.mode == "1"
                mask = np.asarray(image)
                cy, cx = (length // 2 for length in mask.shape)
                assert not mask[cy, cx] and mask[cy, cx + 45]
                assert layer["exposedAreaMm2"] == pytest.approx(mask.sum() * 0.1**2)
                assert layer["exposedAreaMm2"] == pytest.approx(np.pi * (6**2 - 3**2), abs=1.0)
        assert manifest["layers"][-1]["thicknessMm"] == 0.25
        measured = sum(layer["exposedAreaMm2"] * layer["thicknessMm"] for layer in manifest["layers"])
        assert manifest["estimatedCuredVolumeMm3"] == pytest.approx(measured)
    assert list(settings.DATA_DIR.iterdir()) == []


@pytest.mark.skipif(not worker_python().is_file(), reason="Install the optional PySLM runtime")
def test_resin_build_volume_checks_rotated_geometry(client):
    mesh = trimesh.creation.box(extents=(16, 6, 4))
    assert preview(client, mesh, buildVolumeMm=[8, 8, 20]).status_code == 422
    response = preview(client, mesh, buildVolumeMm=[8, 8, 20], rotationDeg=[0, 90])
    assert response.status_code == 200, response.text[:400] if not response.is_success else None
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["modelSizeMm"] == pytest.approx([4, 6, 16])
    assert len(manifest["layers"]) == 32
    assert list(settings.DATA_DIR.iterdir()) == []
