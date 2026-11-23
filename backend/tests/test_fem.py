import json
from pathlib import Path
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import numpy as np
import pytest
import trimesh

from backend.config import settings
from backend.main import app
from backend.routes import fem
from backend.services.fem import FemOptions, gmsh_installed, solver_executable
from backend.workers.fem import boundary_conditions


OPTIONS = {
    "elementSizeMm": 4,
    "youngsModulusMpa": 200_000,
    "poissonsRatio": 0.3,
    "fixed": [{"minMm": [-0.01, -5.01, -5.01], "maxMm": [0.01, 5.01, 5.01]}],
    "loads": [{"region": {"minMm": [99.99, -5.01, -5.01], "maxMm": [100.01, 5.01, 5.01]},
               "forceN": [0, 0, -100]}],
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "API_TOKEN", "fem-test-token")
    # Avoid starting reconstruction recovery against the live owner's job store.
    client = TestClient(app, headers={"Authorization": "Bearer fem-test-token"})
    yield client
    client.close()


def beam_stl():
    mesh = trimesh.creation.box(extents=(100, 10, 10))
    mesh.apply_translation((50, 0, 0))
    return mesh.export(file_type="stl")


def solve(client, model, options=OPTIONS):
    return client.post("/api/v1/fem/solve", files={"model": model}, data={"config": json.dumps(options)})


def test_fem_requires_auth_and_reports_missing_runtime(client, monkeypatch):
    monkeypatch.setattr(fem, "solver_executable", lambda: None)
    assert client.get("/api/v1/fem", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/fem").json()["configured"] is False
    assert solve(client, ("beam.stl", beam_stl())).status_code == 503
    assert solve(client, ("beam.glb", b"data")).status_code == 422
    assert solve(client, ("beam.stl", beam_stl()), {**OPTIONS, "loads": []}).status_code == 422


def test_quadratic_face_load_preserves_the_total_applied_force():
    face = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [.5, 0, 0], [.5, .5, 0], [0, .5, 0]])
    points = np.vstack((face, face + [0, 0, 1])).astype(float)
    surfaces = {1: np.arange(6).reshape(1, 6), 2: np.arange(6, 12).reshape(1, 6)}
    options = FemOptions.model_validate({**OPTIONS, "fixed": [{"faceId": 1}],
                                        "loads": [{"region": {"faceId": 2}, "forceN": [3, 9, -15]}]})
    fixed, loads = boundary_conditions(options, points, surfaces)
    np.testing.assert_equal(fixed, np.arange(6))
    np.testing.assert_allclose(loads.sum(axis=0), [3, 9, -15])
    np.testing.assert_allclose(loads[6:9], 0)
    np.testing.assert_allclose(loads[9:], [[1, 3, -5]] * 3)


def make_step(path: Path):
    import gmsh

    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.addBox(0, -5, -5, 100, 10, 10)
        gmsh.model.occ.synchronize()
        fixed = [tag for _, tag in gmsh.model.getEntities(2) if abs(gmsh.model.occ.getCenterOfMass(2, tag)[0]) < 0.01]
        loaded = [tag for _, tag in gmsh.model.getEntities(2) if abs(gmsh.model.occ.getCenterOfMass(2, tag)[0] - 100) < 0.01]
        gmsh.write(str(path))
        return fixed[0], loaded[0]
    finally:
        gmsh.finalize()


requires_fem = pytest.mark.skipif(not (gmsh_installed() and solver_executable()), reason="Install Gmsh and CalculiX to run a native solve")


@requires_fem
@pytest.mark.parametrize("format", ["stl", "step"])
def test_authentic_cantilever_solve(client, tmp_path, format):
    options = OPTIONS
    if format == "step":
        path = tmp_path / "beam.step"
        fixed, loaded = make_step(path)
        model = path.read_bytes()
        options = {**OPTIONS, "fixed": [{"faceId": fixed}],
                   "loads": [{"region": {"faceId": loaded}, "forceN": [0, 0, -100]}]}
    else:
        model = beam_stl()
    result = solve(client, (f"beam.{format}", model), options)
    assert result.status_code == 200, result.text[:400]
    assert result.headers["content-disposition"].endswith('"xr3d-fem.vtu"')
    # Euler–Bernoulli: tip deflection for F=100 N, L=100 mm, E=200,000 MPa and a 10 mm square.
    displacement_mm = float(result.headers["x-xr3d-max-displacement-mm"])
    assert displacement_mm == pytest.approx(0.200, rel=0.05)
    assert 50 < float(result.headers["x-xr3d-max-stress-mpa"]) < 80
    piece = ET.fromstring(result.content).find("UnstructuredGrid/Piece")
    assert int(piece.get("NumberOfCells")) > 100
    assert int(piece.get("NumberOfPoints")) == int(result.headers["x-xr3d-fem-nodes"])
    data = piece.find("PointData")
    assert data.get("Scalars") == "Stress"
    pa = np.fromstring(data.find("DataArray[@Name='Stress']").text, sep=" ")
    assert pa.max() / 1e6 == pytest.approx(float(result.headers["x-xr3d-max-stress-mpa"]))
    assert not list(settings.DATA_DIR.iterdir())


@requires_fem
def test_open_stl_and_regions_without_faces_are_rejected(client):
    open_mesh = trimesh.creation.box()
    open_mesh.update_faces(np.arange(len(open_mesh.faces)) != 0)
    result = solve(client, ("open.stl", open_mesh.export(file_type="stl")))
    assert result.status_code == 422 and "closed" in result.json()["detail"]
    result = solve(client, ("beam.stl", beam_stl()), {**OPTIONS, "fixed": [{"minMm": [200, 0, 0], "maxMm": [201, 1, 1]}]})
    assert result.status_code == 422 and "exterior triangles" in result.json()["detail"]
    assert not list(settings.DATA_DIR.iterdir())
