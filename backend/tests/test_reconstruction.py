import asyncio
import io
import time
from pathlib import Path
import pytest
import trimesh
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.routes import reconstruction as routes
from backend.services.redis_queue import JobStore
from backend.services.inference import convert_model


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "API_TOKEN", "test-token")
    monkeypatch.setattr(routes, "store", JobStore(tmp_path))
    monkeypatch.setattr(routes, "gpu_lock", asyncio.Lock())
    monkeypatch.setattr(routes, "available", lambda provider: provider == "TRELLIS_2")
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as test_client:
        yield test_client
    routes.store.db.close()


def image():
    data = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(data, "PNG")
    return data.getvalue()


def create(client, **fields):
    return client.post("/api/v1/reconstruct/jobs", json={"projectId": "test-project", **fields})


def poll(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/v1/reconstruct/jobs/{job_id}").json()
        if job["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return job
        time.sleep(0.02)
    pytest.fail("Job did not finish")


def test_auth_and_unknown_jobs(client):
    assert client.get("/api/v1/reconstruct/jobs/missing", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/reconstruct/jobs/missing").status_code == 404


def test_invalid_or_unconfigured_provider(client):
    assert create(client, provider="PIXAL_3D").status_code == 503
    assert create(client, targetFormat="USDZ").status_code == 422
    assert create(client, promptText="unsupported").status_code == 422
    assert create(client, maxPolyCount=-1).status_code == 422


def test_upload_validation_and_cancel_before_submit(client):
    job_id = create(client).json()["jobId"]
    url = f"/api/v1/reconstruct/jobs/{job_id}"
    assert client.post(url + "/images", files={"images": ("bad.png", b"not an image")}).status_code == 422
    assert client.post(url + "/images", files=[("images", ("a.png", image())), ("images", ("b.png", image()))]).status_code == 422
    assert client.post(url + "/cancel").json()["status"] == "CANCELLED"
    assert client.post(url + "/images", files={"images": ("a.png", image())}).status_code == 409
    assert client.get(url + "/download").status_code == 409


def test_success_requires_real_downloadable_geometry(client, monkeypatch):
    async def inference(job, images, directory, update):
        with Image.open(images[0]) as decoded:
            assert decoded.size == (16, 16)
        path = directory / "source.glb"
        path.write_bytes(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
        return path
    monkeypatch.setattr(routes, "infer", inference)
    job_id = create(client).json()["jobId"]
    assert client.post(f"/api/v1/reconstruct/jobs/{job_id}/images", files={"images": ("a.png", image())}).status_code == 200
    job = poll(client, job_id)
    assert job["status"] == "COMPLETED"
    download = client.get(job["outputModelUrl"])
    assert download.status_code == 200 and download.content[:4] == b"glTF"
    geometry = trimesh.load(io.BytesIO(download.content), file_type="glb").to_mesh()
    assert len(geometry.faces) == 12
    assert client.post(f"/api/v1/reconstruct/jobs/{job_id}/cancel").status_code == 409


@pytest.mark.parametrize("invalid_output", [False, True])
def test_inference_error_never_falls_back_to_sample(client, monkeypatch, invalid_output):
    async def inference(job, images, directory, update):
        if not invalid_output:
            raise RuntimeError("Provider unavailable")
        path = directory / "source.glb"
        path.write_bytes(b"invalid model")
        return path
    monkeypatch.setattr(routes, "infer", inference)
    job_id = create(client).json()["jobId"]
    client.post(f"/api/v1/reconstruct/jobs/{job_id}/images", files={"images": ("a.png", image())})
    job = poll(client, job_id)
    assert job["status"] == "FAILED" and job["outputModelUrl"] is None
    assert client.get(f"/api/v1/reconstruct/jobs/{job_id}/download").status_code == 409


def test_running_cancellation_is_terminal(client, monkeypatch):
    async def inference(*args):
        await asyncio.sleep(30)
    monkeypatch.setattr(routes, "infer", inference)
    job_id = create(client).json()["jobId"]
    client.post(f"/api/v1/reconstruct/jobs/{job_id}/images", files={"images": ("a.png", image())})
    assert client.post(f"/api/v1/reconstruct/jobs/{job_id}/cancel").json()["status"] == "CANCELLED"
    assert poll(client, job_id)["status"] == "CANCELLED"


def test_job_store_survives_restart(tmp_path):
    first = JobStore(tmp_path)
    first.save({"job_id": "j1", "status": "QUEUED"})
    first.db.close()
    second = JobStore(tmp_path)
    assert second.get("j1")["status"] == "QUEUED"
    second.db.close()


@pytest.mark.parametrize("format", ["GLB", "STL", "OBJ", "PLY"])
def test_actual_geometry_conversion(tmp_path, format):
    source = tmp_path / "source.glb"
    source.write_bytes(trimesh.Scene(trimesh.creation.icosphere(subdivisions=1)).export(file_type="glb"))
    output = convert_model(source, tmp_path, format, 10000)
    result = trimesh.load(output, force="scene").to_mesh()
    assert len(result.faces) == 80
