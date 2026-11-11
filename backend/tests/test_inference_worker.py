import asyncio
import json
import sys
from PIL import Image
import trimesh
from backend.config import settings
from backend.services.inference import infer


def test_real_subprocess_contract(tmp_path, monkeypatch):
    # A fixture worker validates process/file transport; this is not an AI quality test.
    worker = tmp_path / "fixture_worker.py"
    worker.write_text("import json,sys,trimesh\nr=json.load(open(sys.argv[1]))\ntrimesh.Scene(trimesh.creation.box()).export(r['output'])\n")
    monkeypatch.setattr(settings, "LOCAL_COMMAND", json.dumps([sys.executable, str(worker)]))
    monkeypatch.setattr(settings, "LOCAL_PROVIDER", "TRELLIS_2")
    source = tmp_path / "input.png"
    Image.new("RGB", (16,16)).save(source)
    job = {"provider":"TRELLIS_2", "request":{"max_poly_count":10000,"target_format":"GLB"}}
    result = asyncio.run(infer(job, [source], tmp_path, lambda **fields: None))
    assert result.is_file()
    assert len(trimesh.load(result).to_mesh().faces) == 12


def test_worker_failure_is_not_substituted(tmp_path, monkeypatch):
    import pytest
    worker = tmp_path / "failing_worker.py"
    worker.write_text("raise SystemExit(2)\n")
    monkeypatch.setattr(settings,"LOCAL_COMMAND",json.dumps([sys.executable,str(worker)]))
    monkeypatch.setattr(settings,"LOCAL_PROVIDER","TRELLIS_2")
    with pytest.raises(RuntimeError, match="Local inference failed"):
        asyncio.run(infer({"provider":"TRELLIS_2","request":{}}, [], tmp_path, lambda **fields: None))
