import json
import sqlite3
import time
import uuid
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.services.redis_queue import JobStore
from backend.maintenance import backup, prune, job_directory
from backend.routes import reconstruction as routes


def test_readiness_requires_auth_and_does_not_claim_live_validation(monkeypatch):
    monkeypatch.setattr(settings, "API_TOKEN", "test-token")
    monkeypatch.setattr(settings, "LOCAL_COMMAND", "")
    monkeypatch.setattr(settings, "FAL_KEY", "")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 401
    response = client.get("/ready", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 503 and response.json()["inferenceConfigured"] is False
    monkeypatch.setattr(settings, "FAL_KEY", "configured-but-not-validated")
    response = client.get("/ready", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200 and response.json()["liveInferenceVerified"] is False
    client.close()


def test_queue_limit_released_after_cancel(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    monkeypatch.setattr(routes, "store", store)
    monkeypatch.setattr(routes, "available", lambda _: True)
    monkeypatch.setattr(settings, "API_TOKEN", "test-token")
    monkeypatch.setattr(settings, "MAX_PENDING_JOBS", 1)
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    first = client.post("/api/v1/reconstruct/jobs", json={"projectId": "project"})
    assert first.status_code == 201
    assert client.post("/api/v1/reconstruct/jobs", json={"projectId": "project"}).status_code == 429
    client.post(f"/api/v1/reconstruct/jobs/{first.json()['jobId']}/cancel")
    assert client.post("/api/v1/reconstruct/jobs", json={"projectId": "project"}).status_code == 201
    client.close(); store.db.close()


def test_backup_restore_and_retention_leave_active_and_recent_jobs(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    store = JobStore(root)
    ids = []
    for status, age in [("COMPLETED", 60), ("FAILED", 60), ("CANCELLED", 60), ("PROCESSING", 60), ("COMPLETED", 1)]:
        job_id = str(uuid.uuid4()); ids.append(job_id)
        folder = root / job_id; folder.mkdir(); (folder / "model.glb").write_bytes(b"model contents")
        job = {"job_id": job_id, "status": status, "updated_at": time.time() - age * 86400}
        store.db.execute("INSERT INTO jobs VALUES (?,?)", (job_id, json.dumps(job)))
    store.db.commit(); store.db.close()
    archive_path = tmp_path / "backup.zip"
    backup(root, archive_path)
    with pytest.raises(FileExistsError): backup(root, archive_path)
    assert prune(root, 30) == ids[:3]
    assert all((root / job_id).exists() for job_id in ids)
    assert prune(root, 30, apply=True) == ids[:3]
    assert all(not (root / job_id).exists() for job_id in ids[:3])
    assert all((root / job_id).is_dir() for job_id in ids[3:])
    restored = tmp_path / "restored"
    with zipfile.ZipFile(archive_path) as archive: archive.extractall(restored)
    with sqlite3.connect(restored / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 5
    assert (restored / ids[0] / "model.glb").read_bytes() == b"model contents"


def test_maintenance_rejects_paths_outside_volume(tmp_path):
    with pytest.raises(ValueError): job_directory(tmp_path, "../outside")
    with pytest.raises(ValueError): backup(tmp_path, tmp_path / "recursive.zip")
