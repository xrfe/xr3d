"""Run XR3D against an isolated local Meshy HTTP fixture."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import httpx
import trimesh
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "build/reports/xr3d-meshy-mock"
REPORT.mkdir(parents=True, exist_ok=True)
PORT = 8874
SERVER_TOKEN = "xr3d-mock-server-token"
MESHY_KEY = "xr3d-mock-meshy-key"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--glb", type=Path, help="Optional model to serve instead of the synthetic fixture")
args = parser.parse_args()

os.environ.update(
    XR3D_DATA_DIR=tempfile.mkdtemp(prefix="backend-", dir=REPORT),
    XR3D_API_TOKEN=SERVER_TOKEN,
    MESHY_API_KEY=MESHY_KEY,
    MESHY_MODEL="meshy-7.1",
)
sys.path.insert(0, str(ROOT))
from backend.main import app
from backend.services import meshy

fixture = (
    args.glb.read_bytes() if args.glb
    else trimesh.Scene(trimesh.creation.box(extents=[0.035, 0.025, 0.020])).export(file_type="glb")
)
if not fixture.startswith(b"glTF"):
    parser.error("--glb must point to a binary glTF file")
(REPORT / "fixture.glb").write_bytes(fixture)
photo = Image.new("RGB", (480, 360), "#eee9e1")
draw = ImageDraw.Draw(photo)
draw.polygon([(105, 132), (288, 84), (373, 159), (196, 211)], fill="#e4a049")
draw.polygon([(105, 132), (196, 211), (196, 299), (105, 218)], fill="#b26627")
draw.polygon([(196, 211), (373, 159), (373, 247), (196, 299)], fill="#d4893a")
photo.save(REPORT / "XR3D-Meshy-Mock-Input.jpg")

events = REPORT / "upstream.jsonl"
events.write_text("", encoding="utf-8")
tasks = {}
mock = FastAPI()


def record(**event):
    with events.open("a", encoding="utf-8") as items:
        items.write(json.dumps(event) + "\n")


@mock.post("/openapi/v1/{endpoint}")
async def create(endpoint: str, request: Request):
    assert request.headers.get("authorization") == f"Bearer {MESHY_KEY}"
    body = await request.json()
    assert body["target_formats"] == ["glb"]
    if endpoint == "image-to-3d":
        images = [body["image_url"]]
    else:
        assert endpoint == "multi-image-to-3d"
        images = body["image_urls"]
        assert 2 <= len(images) <= 4
    sizes = []
    for image in images:
        prefix, data = image.split(",", 1)
        assert prefix == "data:image/png;base64"
        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as decoded:
            decoded.load()
            sizes.append(decoded.size)
    task = f"mock-task-{len(tasks) + 1:04d}"
    tasks[task] = (endpoint, 0)
    record(method="POST", endpoint=endpoint, task=task, images=sizes, model=body["ai_model"])
    return JSONResponse({"result": task}, status_code=202)


@mock.get("/openapi/v1/{endpoint}/{task}")
async def poll(endpoint: str, task: str, request: Request):
    assert request.headers.get("authorization") == f"Bearer {MESHY_KEY}"
    expected_endpoint, count = tasks[task]
    assert endpoint == expected_endpoint
    tasks[task] = (endpoint, count + 1)
    status, progress = [("PENDING", 0), ("IN_PROGRESS", 42), ("SUCCEEDED", 100)][min(count, 2)]
    record(method="GET", endpoint=endpoint, task=task, status=status, progress=progress)
    result = {"id": task, "status": status, "progress": progress}
    if status == "SUCCEEDED":
        result["model_urls"] = {"glb": f"https://assets.meshy.ai/models/{task}.glb"}
    return result


@mock.get("/models/{task}.glb")
async def asset(task: str, request: Request):
    assert task in tasks
    assert "authorization" not in request.headers and "x-meshy-api-key" not in request.headers
    record(method="GET", task=task, asset="glb", authorized=False, bytes=len(fixture))
    return Response(fixture, media_type="model/gltf-binary")


app.mount("/test-upstream", mock)


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        assert request.url.host in {"api.meshy.ai", "assets.meshy.ai"}
        local_url = f"http://127.0.0.1:{PORT}/test-upstream{request.url.raw_path.decode()}"
        headers = request.headers.copy()
        headers.pop("host")
        local = httpx.Request(request.method, local_url, headers=headers, content=await request.aread(),
                              extensions=request.extensions)
        return await self.transport.handle_async_request(local)

    async def aclose(self):
        await self.transport.aclose()


meshy.httpx = SimpleNamespace(AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=FixtureTransport(), **kwargs))
uvicorn.run(app, host="127.0.0.1", port=PORT)
