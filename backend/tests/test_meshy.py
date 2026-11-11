"""Controlled Meshy transport only; no paid API submissions."""
import asyncio
import io
import json
import time
import httpx
import pytest
import trimesh
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.routes import reconstruction as routes
from backend.services import meshy
from backend.services.redis_queue import JobStore


def image():
    output=io.BytesIO(); Image.new("RGB",(64,64),"red").save(output,"PNG"); return output.getvalue()


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,"DATA_DIR",tmp_path)
    monkeypatch.setattr(settings,"API_TOKEN","server-token")
    monkeypatch.setattr(settings,"MESHY_API_KEY","server-meshy-key")
    monkeypatch.setattr(settings,"LOCAL_COMMAND","")
    store=JobStore(tmp_path); monkeypatch.setattr(routes,"store",store)
    monkeypatch.setattr(routes,"gpu_lock",asyncio.Lock())
    seen=[]; state={"status":"SUCCEEDED","reject":False,"bad_url":False}
    glb=trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    def handle(request):
        seen.append(request)
        if request.url.host=="assets.meshy.ai":
            assert "Authorization" not in request.headers and "X-Meshy-Api-Key" not in request.headers
            return httpx.Response(200,content=glb)
        assert request.url.host=="api.meshy.ai"
        assert request.headers["Authorization"] in ("Bearer personal-meshy-key","Bearer server-meshy-key")
        if state["reject"]: return httpx.Response(401,json={"message":"rejected"})
        if request.method=="POST": return httpx.Response(202,json={"result":"remote-meshy-id"})
        return httpx.Response(200,json={"status":state["status"],"progress":50,
            "model_urls":{"glb":"http://127.0.0.1/private" if state["bad_url"] else "https://assets.meshy.ai/test/model.glb"}})
    original=httpx.AsyncClient
    monkeypatch.setattr(meshy.httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    # No lifespan: don't mutate unrelated global state.
    with TestClient(app,headers={"Authorization":"Bearer server-token"}) as client:
        yield client,seen,state,store
    store.db.close()


def create(client,provider="MESHY_SINGLE",source="SERVER"):
    result=client.post("/api/v1/reconstruct/jobs",json={"projectId":"test-project","provider":provider,"meshyKeySource":source})
    assert result.status_code==201,result.text
    return result.json()["jobId"]


def upload(client,job_id,count=1,key=None):
    return client.post(f"/api/v1/reconstruct/jobs/{job_id}/images",files=[("images",(f"view{i}.png",image())) for i in range(count)],
        headers={"X-Meshy-Api-Key":key} if key else {})


def finish(client,job_id):
    for _ in range(150):
        result=client.get(f"/api/v1/reconstruct/jobs/{job_id}")
        assert result.status_code==200,result.text
        job=result.json()
        if job["status"] in ("COMPLETED","FAILED","CANCELLED"): return job
        time.sleep(.02)
    pytest.fail("Meshy job did not finish")


@pytest.mark.parametrize("provider,count,field",[("MESHY_SINGLE",1,"image_url"),("MESHY_MULTI",4,"image_urls")])
@pytest.mark.parametrize("source,key",[("SERVER",None),("USER","personal-meshy-key")])
def test_real_geometry_for_single_and_multi_with_both_key_sources(transport,provider,count,field,source,key):
    client,seen,state,store=transport
    job_id=create(client,provider,source)
    assert upload(client,job_id,count,key).status_code==200
    job=finish(client,job_id)
    assert job["status"]=="COMPLETED",job
    submitted=next(request for request in seen if request.method=="POST")
    assert submitted.url.path==("/openapi/v1/image-to-3d" if count==1 else "/openapi/v1/multi-image-to-3d")
    assert submitted.headers["Authorization"]==f"Bearer {key or 'server-meshy-key'}"
    payload=json.loads(submitted.content)
    assert field in payload and payload["ai_model"]==settings.MESHY_MODEL
    if count>1: assert len(payload[field])==count
    assert payload["enable_pbr"] is True and payload["texture_resolution"]=="2k"
    data=client.get(job["outputModelUrl"]).content
    assert data[:4]==b"glTF" and len(trimesh.load(io.BytesIO(data),file_type="glb").to_mesh().faces)==12
    saved=json.dumps(store.get(job_id))
    assert "personal-meshy-key" not in saved and "server-meshy-key" not in saved
    assert store.get(job_id)["meshy_task_id"]=="remote-meshy-id"


def test_personal_key_works_without_server_key_and_never_falls_back(transport,monkeypatch):
    client,seen,state,_=transport
    monkeypatch.setattr(settings,"MESHY_API_KEY","")
    assert client.post("/api/v1/reconstruct/jobs",json={"projectId":"p","provider":"MESHY_SINGLE"}).status_code==503
    job=create(client,source="USER")
    assert upload(client,job).status_code==422
    assert not seen
    assert upload(client,job,key="personal-meshy-key").status_code==200
    assert finish(client,job)["status"]=="COMPLETED"


@pytest.mark.parametrize("provider,count",[("MESHY_SINGLE",2),("MESHY_MULTI",1),("MESHY_MULTI",5)])
def test_invalid_image_counts_do_not_submit_paid_tasks(transport,provider,count):
    client,seen,_,_=transport
    assert upload(client,create(client,provider),count).status_code==422
    assert not seen


@pytest.mark.parametrize("failure",["reject","bad_url","FAILED"])
def test_failures_have_no_model_or_secret_echo(transport,failure):
    client,_,state,store=transport
    if failure=="FAILED": state["status"]="FAILED"
    else: state[failure]=True
    job=create(client,source="USER"); upload(client,job,key="personal-meshy-key")
    result=finish(client,job)
    assert result["status"]=="FAILED" and result["outputModelUrl"] is None
    assert "personal-meshy-key" not in json.dumps(result) and "personal-meshy-key" not in json.dumps(store.get(job))


def test_restart_reuses_remote_id_and_requires_personal_key(transport):
    client,seen,_,store=transport
    job_id=create(client,source="USER")
    store.update(job_id,submitted=True,status="PROCESSING",meshy_task_id="existing-remote-id",meshy_submission_started=True)
    # Persist/recover same job store as a server restart would.
    with TestClient(app,headers={"Authorization":"Bearer server-token"}) as restarted:
        result=restarted.get(f"/api/v1/reconstruct/jobs/{job_id}")
        assert result.status_code==422
        assert restarted.get(f"/api/v1/reconstruct/jobs/{job_id}",headers={"X-Meshy-Api-Key":"personal-meshy-key"}).status_code==200
        assert finish(restarted,job_id)["status"]=="COMPLETED"
    assert all(request.method!="POST" for request in seen)
    assert any(request.url.path.endswith("existing-remote-id") for request in seen)


def test_stop_tracking_preserves_cloud_task_and_credit_warning(transport):
    client,seen,state,store=transport
    state["status"]="IN_PROGRESS"
    job_id=create(client); assert upload(client,job_id).status_code==200
    for _ in range(100):
        if store.get(job_id).get("meshy_task_id"): break
        time.sleep(.01)
    result=client.post(f"/api/v1/reconstruct/jobs/{job_id}/cancel").json()
    assert result["status"]=="CANCELLED" and "credits" in result["currentStepName"]
    assert not any(request.method=="DELETE" for request in seen)


def test_ambiguous_submission_is_not_automatically_repeated(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"MESHY_API_KEY","server-meshy-key")
    job={"provider":"MESHY_SINGLE","request":{"meshy_key_source":"SERVER"},"meshy_submission_started":True}
    with pytest.raises(ValueError,match="outcome is unknown"):
        asyncio.run(meshy.infer_meshy(job,[],tmp_path,lambda **fields:None))
