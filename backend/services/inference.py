"""Real local-process and fal queue adapters. No substitute geometry."""
import asyncio
import base64
import json
import httpx
from backend.config import settings

def available(provider):
    if provider in ("MESHY_SINGLE", "MESHY_MULTI"):
        return bool(settings.MESHY_API_KEY)
    return bool((settings.LOCAL_COMMAND and provider == settings.LOCAL_PROVIDER) or
                (settings.FAL_KEY and (provider == "TRELLIS_2" or
                 (provider == "HUNYUAN_3D" and settings.FAL_HUNYUAN_MODEL))))

async def infer(job, images, directory, update):
    if job["provider"] in ("MESHY_SINGLE", "MESHY_MULTI"):
        from backend.services.meshy import infer_meshy
        return await infer_meshy(job, images, directory, update)
    if settings.LOCAL_COMMAND and job["provider"] == settings.LOCAL_PROVIDER:
        argv = json.loads(settings.LOCAL_COMMAND)
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise ValueError("XR3D_LOCAL_COMMAND must be a JSON argv array")
        request_file = directory / "request.json"
        output_file = directory / "source.glb"
        request_file.write_text(json.dumps({**job["request"], "images": [str(p.resolve()) for p in images],
                                           "output": str(output_file.resolve())}), encoding="utf-8")
        with (directory / "worker.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(*argv, str(request_file.resolve()), stdout=log, stderr=log)
            try:
                if await process.wait() != 0:
                    raise RuntimeError("Local inference failed; inspect worker.log")
            finally:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 10)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
        if not output_file.is_file():
            raise RuntimeError("Local inference produced no GLB")
        return output_file
    model = settings.FAL_TRELLIS_MODEL if job["provider"] == "TRELLIS_2" else settings.FAL_HUNYUAN_MODEL
    headers = {"Authorization": f"Key {settings.FAL_KEY}"}
    from PIL import Image
    with Image.open(images[0]) as image:
        mime = Image.MIME[image.format]
    payload = {"image_url": f"data:{mime};base64," + base64.b64encode(images[0].read_bytes()).decode()}
    if job["provider"] == "TRELLIS_2":
        payload["resolution"] = {"DRAFT_FAST": "512", "BALANCED": "1024", "HIGH_DETAIL": "1536", "ULTRA_PRECISION": "1536"}[job["request"]["quality_preset"]]
        payload["decimation_target"] = job["request"]["max_poly_count"]
        payload["texture_size"] = str(max(1024, job["request"]["texture_resolution"]))
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"https://queue.fal.run/{model}", headers=headers, json=payload)
        response.raise_for_status()
        ticket = response.json()
        from urllib.parse import urlparse
        for key in ("status_url", "response_url", "cancel_url"):
            parsed = urlparse(ticket[key])
            if parsed.scheme != "https" or parsed.hostname != "queue.fal.run":
                raise RuntimeError("Invalid provider queue URL")
        try:
            while True:
                response = await client.get(ticket["status_url"], headers=headers)
                response.raise_for_status()
                state = response.json()
                if state.get("error"):
                    raise RuntimeError("AI provider reported an inference error")
                if state["status"] == "COMPLETED":
                    break
                update(current_step_name="Waiting for AI provider" if state["status"] == "IN_QUEUE" else "AI inference running")
                await asyncio.sleep(3)
            response = await client.get(ticket["response_url"], headers=headers)
            response.raise_for_status()
            result = response.json()
            asset = result.get("model_glb") or result.get("model_mesh")
            url = asset.get("url") if isinstance(asset, dict) else None
            if not url or not url.startswith("https://"):
                raise RuntimeError("AI provider returned no HTTPS model asset")
            output = directory / "source.glb"
            async with client.stream("GET", url, follow_redirects=True) as download:
                download.raise_for_status()
                size = 0
                with output.open("wb") as target:
                    async for chunk in download.aiter_bytes():
                        size += len(chunk)
                        if size > settings.MAX_MODEL_BYTES:
                            raise RuntimeError("Model exceeds download size limit")
                        target.write(chunk)
            return output
        except BaseException:
            try:
                await client.put(ticket["cancel_url"], headers=headers)
            except Exception:
                pass
            raise

def convert_model(source, directory, target_format, max_poly_count, generate_textures=True):
    import trimesh
    import numpy as np
    scene = trimesh.load(source, force="scene")
    mesh = scene.to_mesh()
    if len(mesh.vertices) < 3 or len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ValueError("AI provider returned empty or invalid geometry")
    if len(mesh.faces) > max_poly_count:
        mesh = mesh.simplify_quadric_decimation(face_count=max_poly_count)
        scene = trimesh.Scene(mesh)
    destination = directory / f"model.{target_format.lower()}"
    if not generate_textures:
        scene = trimesh.Scene(trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces))
    if target_format == "GLB":
        destination.write_bytes(scene.export(file_type="glb"))
    else:
        # glTF uses metres and Y-up; print formats use millimetres and Z-up.
        mesh.apply_transform(np.array([[1000, 0, 0, 0], [0, 0, -1000, 0], [0, 1000, 0, 0], [0, 0, 0, 1]]))
        if target_format == "PLY":
            mesh.export(destination, file_type="ply", encoding="ascii")
        else:
            mesh.export(destination, file_type=target_format.lower())
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("Model export produced an empty file")
    return destination
