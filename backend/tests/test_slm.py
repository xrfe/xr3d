from io import BytesIO
from importlib.util import find_spec
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
import numpy as np
import pytest
import trimesh

from backend.config import settings
from backend.main import app
from backend.routes import layer_previews, slm


OPTIONS = {"layerThicknessMm": 0.5, "hatchSpacingMm": 0.4, "hatchAngleDeg": 5, "layerRotationDeg": 67}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "API_TOKEN", "slm-test-token")
    client = TestClient(app, headers={"Authorization": "Bearer slm-test-token"})
    yield client
    client.close()


def preview(client, mesh_bytes, config=OPTIONS):
    return client.post("/api/v1/slm/preview", files={"model": ("sample.stl", mesh_bytes)},
                       data={"config": json.dumps(config)})


def test_slm_validates_requests_without_optional_runtime(client, monkeypatch, tmp_path):
    monkeypatch.setattr(layer_previews, "worker_python", lambda: tmp_path / "missing-python")
    bad_headers = {"Authorization": "Bearer wrong"}
    assert client.get("/api/v1/slm", headers=bad_headers).status_code == 401
    assert client.post("/api/v1/slm/preview", headers=bad_headers).status_code == 401
    assert client.get("/api/v1/slm").json()["configured"] is False
    assert preview(client, b"data").status_code == 503
    assert preview(client, b"data", {**OPTIONS, "hatchSpacingMm": 0}).status_code == 422
    assert preview(client, b"data", {**OPTIONS, "laserPower": 100}).status_code == 422


@pytest.mark.parametrize("strategy", ["parallel", "stripe", "island"])
def test_real_preview_preserves_internal_holes(client, strategy):
    if find_spec("pyslm") is None:
        pytest.skip("Install the XR3D backend dependencies")
    assert client.get("/api/v1/slm").json()["configured"] is True
    mesh = trimesh.creation.annulus(r_min=3, r_max=6, height=2.25, sections=48)
    mesh.apply_translation((4, 9, 7))
    response = preview(client, mesh.export(file_type="stl"), {**OPTIONS, "strategy": strategy})
    assert response.status_code == 200, response.text[:400] if response.status_code != 200 else None

    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        layers = [json.loads(line) for line in archive.read("layers.jsonl").splitlines()]

    assert manifest["engine"] == "PySLM"
    assert manifest["machineReady"] is False
    assert manifest["layerCount"] == len(layers) == 5
    np.testing.assert_allclose(manifest["translationMm"], [0, 0, -5.875])
    assert [layer["hatchAngleDeg"] for layer in layers] == [5, 72, 139, 26, 93]
    assert layers[-1]["zMm"] == 2.125
    assert layers[-1]["thicknessMm"] == 0.25
    assert manifest["scanLengthMm"] == pytest.approx(sum(layer["scanLengthMm"] for layer in layers))
    for layer in layers:
        assert sum(path["kind"] == "contour" for path in layer["paths"]) == 2
        hatches = [np.array(path["xyMm"]).reshape(-1, 2, 2) for path in layer["paths"] if path["kind"] == "hatch"]
        assert hatches and len(hatches[0]) > 0
        for lines in hatches:
            delta = lines[:, 1] - lines[:, 0]
            from_center = lines[:, 0] - [4, 9]
            nearest_fraction = np.clip(-np.sum(from_center * delta, axis=1) / np.sum(delta ** 2, axis=1), 0, 1)
            distance = np.linalg.norm(from_center + nearest_fraction[:, None] * delta, axis=1)
            # The tessellated 3 mm hole has a slightly smaller inscribed radius.
            assert np.min(distance) >= 2.99
    assert list(settings.DATA_DIR.iterdir()) == []


def test_slm_rejects_open_mesh_and_excessive_layer_count(client):
    if find_spec("pyslm") is None:
        pytest.skip("Install the XR3D backend dependencies")
    mesh = trimesh.creation.box(extents=(10, 10, 25))
    response = preview(client, mesh.export(file_type="stl"), {**OPTIONS, "layerThicknessMm": 0.01})
    assert response.status_code == 422, response.text
    assert "complexity limit" in response.json()["detail"]
    mesh.update_faces(np.arange(len(mesh.faces) - 1))
    response = preview(client, mesh.export(file_type="stl"))
    assert response.status_code == 422, response.text
    assert "watertight" in response.json()["detail"]
    assert list(settings.DATA_DIR.iterdir()) == []
