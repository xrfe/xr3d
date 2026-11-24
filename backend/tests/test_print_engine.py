"""Regression checks for the print worker and its authenticated API."""
import json
from importlib.util import find_spec
from pathlib import Path
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh
from fastapi.testclient import TestClient
from backend.config import settings
from backend.main import app
from backend.services import print_engine
from backend.services.vendor_printers import VendorProfile


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "API_TOKEN", "local-engine-fixture")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setenv("XR3D_DATA_DIR", str(tmp_path))
    client = TestClient(app, headers={"Authorization": "Bearer local-engine-fixture"})
    yield client
    client.close()


def test_inspection_requires_auth_and_stl(api):
    assert api.get("/api/v1/print-engine", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.post("/api/v1/print-engine/inspect", files={"model": ("model.obj", b"v 0 0 0")}).status_code == 422
    assert api.post("/api/v1/print-engine/inspect", files={"model": ("model.stl", b"")}).status_code == 422


def test_missing_engine_returns_an_explanation(api, tmp_path, monkeypatch):
    monkeypatch.setattr(print_engine, "python_path", lambda: tmp_path / "missing-python")
    response = api.get("/api/v1/print-engine")
    assert response.status_code == 503
    assert "XR3D Print Engine" in response.json()["detail"] or "XR3D print engine" in response.json()["detail"]


@pytest.mark.skipif(find_spec("kiln") is None, reason="Install the XR3D backend dependencies")
def test_default_engine_inspects_real_stl(api):
    assert api.get("/api/v1/print-engine").json()["name"] == "XR3D Print Engine"
    model = trimesh.creation.box(extents=(16, 16, 2))
    model.apply_translation((0, 0, 1))
    response = api.post("/api/v1/print-engine/inspect", files={"model": ("box.stl", model.export(file_type="stl"))})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["printable"] and report["triangleCount"] == 12
    assert report["dimensionsMm"] == {"width_mm": 16, "depth_mm": 16, "height_mm": 2}
    assert all("kiln" not in item.lower() for item in report["recommendations"])
    assert not list(Path(settings.DATA_DIR).glob("inspect-*"))


@contextmanager
def printer_fixture():
    addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    host = None
    for address in addresses:
        try:
            host = VendorProfile.model_validate({"type": "OCTOPRINT", "host": address[4][0], "port": 80}).host
            break
        except ValueError:
            pass
    if not host:
        pytest.skip("A local private IPv4 interface is needed for the printer fixture")
    calls = []
    state = {"filename": "", "state": "idle"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data=None):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            output = json.dumps(data).encode() if data is not None else b""
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)

        def do_GET(self):
            if self.headers.get("X-Api-Key") != "fixture-only":
                return self.reply(401)
            if self.path == "/api/printer":
                return self.reply(200, {"temperature": {"tool0": {"actual": 25}, "bed": {"actual": 24}},
                    "state": {"flags": {"operational": True, "ready": state["state"] == "idle",
                                        "printing": state["state"] == "printing", "paused": state["state"] == "paused"}}})
            if self.path == "/api/job":
                return self.reply(200, {"job": {"file": {"name": state["filename"]}},
                                        "progress": {"completion": 25, "printTimeLeft": 120}})
            return self.reply(404)

        def do_POST(self):
            if self.headers.get("X-Api-Key") != "fixture-only":
                return self.reply(401)
            content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/api/files/local":
                component = content.partition(b'filename="')[2].partition(b'"')[0]
                state["filename"] = component.decode("ascii")
                calls.append("upload")
                return self.reply(201, {"files": {"local": {"name": state["filename"]}}})
            if self.path == "/api/files/local/" + state["filename"]:
                assert json.loads(content) == {"command": "select", "print": True}
                calls.append("start")
                state["state"] = "printing"
                return self.reply(204)
            if self.path == "/api/job":
                command = json.loads(content)
                name = command.get("action") or command.get("command")
                calls.append(name)
                state["state"] = {"pause": "paused", "resume": "printing", "cancel": "idle"}[name]
                return self.reply(204)
            return self.reply(404)

    server = ThreadingHTTPServer((host, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"type": "OCTOPRINT", "host": host, "port": server.server_port, "accessCode": "fixture-only"}, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(find_spec("kiln") is None, reason="Install the XR3D backend dependencies")
def test_real_adapter_fallback_upload_start_and_controls(api):
    with printer_fixture() as (profile, calls):
        path = "/api/v1/printers/vendor/"
        original = api.post(path + "status", json=profile)
        assert original.json()["connectionState"] == "CONNECTED", original.text
        uploaded = api.post(path + "upload", data={"profile": json.dumps(profile)}, files={"file": ("part.gcode", b"G90\n")})
        assert uploaded.status_code == 200, uploaded.text
        assert calls == ["upload"]
        request = {"profile": profile, "receipt": uploaded.json()["receipt"]}
        started = api.post(path + "start", json=request)
        assert started.status_code == 200, started.text
        assert api.post(path + "start", json=request).status_code == 409
        assert api.post(path + "status", json=profile).json()["connectionState"] == "PRINTING"
        for action in ("pause", "resume", "cancel"):
            response = api.post(path + "action", json={"profile": profile, "action": action})
            assert response.status_code == 200, response.text
        assert calls == ["upload", "start", "pause", "resume", "cancel"]
