from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.routes import pairing


def test_local_setup_code_is_single_use(monkeypatch):
    setup = pairing.LanPairing()
    monkeypatch.setattr(app.state, "lan_pairing", setup, raising=False)
    monkeypatch.setattr(settings, "API_TOKEN", "private-test-token")
    local = TestClient(app, client=("192.168.1.12", 50000))
    remote = TestClient(app, client=("198.51.100.12", 50000))
    assert remote.post("/api/v1/pair", json={"code": setup.display_code}).status_code == 404
    assert local.post("/api/v1/pair", json={"code": "wrong"}).status_code == 403
    paired = local.post("/api/v1/pair", json={"code": setup.display_code.lower()})
    assert paired.status_code == 200
    assert paired.headers["cache-control"] == "no-store"
    assert paired.json() == {"serverToken": "private-test-token"}
    assert local.post("/api/v1/pair", json={"code": setup.display_code}).status_code == 403


def test_disabled_expired_and_attempt_limited_setup(monkeypatch):
    local = TestClient(app, client=("127.0.0.1", 50000))
    assert local.post("/api/v1/pair", json={"code": "test"}).status_code == 404
    setup = pairing.LanPairing()
    other = pairing.LanPairing()
    for _ in range(12):
        assert not setup.claim("wrong")
    assert not setup.claim(setup.code)
    monkeypatch.setattr(pairing, "monotonic", lambda: other.expires)
    assert not other.claim(other.code)
