"""Meshy single/multi-image API. No automatic retries of paid submissions.

Docs: https://docs.meshy.ai/en/api/image-to-3d and /multi-image-to-3d
"""
import asyncio
import base64
import re
from urllib.parse import urlparse
import httpx
from PIL import Image
from backend.config import settings

PROVIDERS = ("MESHY_SINGLE", "MESHY_MULTI")


def key_for(job, supplied=None):
    source = job["request"].get("meshy_key_source", "SERVER")
    key = supplied if source == "USER" else settings.MESHY_API_KEY
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", key):
        raise ValueError("Provide a valid Meshy API key for the selected key source")
    return key


def asset_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.hostname != "assets.meshy.ai" or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError("Meshy returned an unsupported model download host")
    return url


async def infer_meshy(job, images, directory, update):
    # Ephemeral key is attached only to the in-memory execution copy, never JobStore.
    key = key_for(job, job.get("_meshy_api_key"))
    endpoint = "image-to-3d" if job["provider"] == "MESHY_SINGLE" else "multi-image-to-3d"
    base = f"https://api.meshy.ai/openapi/v1/{endpoint}"
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
        remote_id = job.get("meshy_task_id")
        if not remote_id:
            if job.get("meshy_submission_started"):
                raise ValueError("Meshy submission outcome is unknown; check Meshy task history before retrying")
            uris = []
            for path in images:
                with Image.open(path) as image:
                    if min(image.size) < 32: raise ValueError("Meshy images must be at least 32 pixels on each side")
                uris.append("data:image/png;base64," + base64.b64encode(path.read_bytes()).decode())
            request = job["request"]
            payload = {"ai_model": settings.MESHY_MODEL, "target_formats": ["glb"],
                       "should_texture": request["generate_textures"], "should_remesh": True,
                       "topology": "triangle", "target_polycount": min(request["max_poly_count"], 300000)}
            quality = request.get("quality_preset","BALANCED")
            payload["geometry_resolution"] = "4k" if endpoint == "image-to-3d" and quality == "ULTRA_PRECISION" else "2k" if quality in ("HIGH_DETAIL","ULTRA_PRECISION") else "standard"
            if request["generate_textures"]:
                payload.update(texture_model="meshy-7", enable_pbr=True,
                               texture_resolution="4k" if request["texture_resolution"] >= 4096 else "2k")
            payload["image_url" if endpoint == "image-to-3d" else "image_urls"] = uris[0] if endpoint == "image-to-3d" else uris
            # Persist the intent first. If a response is lost, never submit again on restart.
            update(meshy_submission_started=True, current_step_name="Submitting paid Meshy generation")
            response = await client.post(base, headers=headers, json=payload)
            response.raise_for_status()
            remote_id = response.json().get("result")
            if not isinstance(remote_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", remote_id):
                raise ValueError("Meshy returned an invalid task ID")
            update(meshy_task_id=remote_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}",remote_id): raise ValueError("Invalid saved Meshy task ID")
        while True:
            response = await client.get(f"{base}/{remote_id}", headers=headers)
            response.raise_for_status()
            result = response.json()
            status = result.get("status")
            if status == "SUCCEEDED": break
            if status in ("FAILED", "CANCELED"): raise ValueError("Meshy task failed or was canceled")
            if status not in ("PENDING", "IN_PROGRESS"): raise ValueError("Unknown Meshy task state")
            progress = result.get("progress",0)
            update(progress_percent=max(10,min(89,float(progress)*.79+10)), current_step_name="Meshy queued" if status=="PENDING" else "Meshy generation running")
            await asyncio.sleep(3)
        url = asset_url((result.get("model_urls") or {}).get("glb"))
        output = directory / "source.glb"
        # No API key on the signed CDN request; redirects are rejected.
        async with client.stream("GET",url) as response:
            response.raise_for_status()
            total=0
            with output.open("wb") as target:
                async for chunk in response.aiter_bytes():
                    total+=len(chunk)
                    if total>settings.MAX_MODEL_BYTES: raise ValueError("Meshy model exceeds download size limit")
                    target.write(chunk)
        return output
