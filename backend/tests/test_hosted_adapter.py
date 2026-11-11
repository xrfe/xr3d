import asyncio
import json
import httpx
import trimesh
from PIL import Image
from backend.config import settings
from backend.services import inference

def test_hosted_queue_and_cdn_transport(tmp_path, monkeypatch):
    geometry = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.host == "queue.fal.run":
            assert request.headers["Authorization"] == "Key fixture-secret"
        else:
            assert "Authorization" not in request.headers
        if request.method == "POST":
            payload=json.loads(request.content)
            assert payload["image_url"].startswith("data:image/png;base64,")
            assert payload["decimation_target"] == 10000
            return httpx.Response(200,json={"status_url":"https://queue.fal.run/status", "response_url":"https://queue.fal.run/result", "cancel_url":"https://queue.fal.run/cancel"})
        if request.url.path == "/status":
            return httpx.Response(200,json={"status":"COMPLETED"})
        if request.url.path == "/result":
            return httpx.Response(200,json={"model_glb":{"url":"https://cdn.example/model.glb"}})
        return httpx.Response(200,content=geometry)
    original=httpx.AsyncClient
    monkeypatch.setattr(inference.httpx,"AsyncClient",lambda **kwargs: original(transport=httpx.MockTransport(handle),**kwargs))
    monkeypatch.setattr(settings,"LOCAL_COMMAND", "")
    monkeypatch.setattr(settings,"FAL_KEY", "fixture-secret")
    source=tmp_path/"image.png"
    Image.new("RGB",(16,16)).save(source)
    job={"provider":"TRELLIS_2","request":{"quality_preset":"BALANCED","max_poly_count":10000,"texture_resolution":2048}}
    output=asyncio.run(inference.infer(job,[source],tmp_path,lambda **fields:None))
    assert output.read_bytes() == geometry
    assert len(seen) == 4
