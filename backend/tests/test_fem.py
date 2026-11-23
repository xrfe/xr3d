import json
from io import BytesIO
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from fastapi.testclient import TestClient
import numpy as np
import pytest
import trimesh

from backend.config import settings
from backend.main import app
from backend.routes import fem
from backend.services.fem import FemOptions, fem_dependencies_available, solver_executable
from backend.workers.fem import MAX_PREVIEW_TRIANGLES, boundary_conditions, inherited_regions, preview_surface
from backend.workers.fem_adaptive import bisect_volume, element_errors
from backend.workers.fem_geometry import fallback_boundary, has_surface_overlap


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


def test_surface_preflight_distinguishes_adjacent_faces_from_intersections():
    pytest.importorskip("rtree")
    box = trimesh.creation.box()
    assert not has_surface_overlap(box)
    intersecting = box.copy()
    intersecting.apply_translation([0.25, 0.25, 0.25])
    assert has_surface_overlap(trimesh.util.concatenate([box, intersecting]))
    assert has_surface_overlap(trimesh.util.concatenate([box, box.copy()]))


def test_stress_recovery_reproduces_constant_integration_stress():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [.5, 0, 0], [.5, .5, 0],
                         [0, .5, 0], [0, 0, .5], [.5, 0, .5], [0, .5, .5]])
    stress = np.tile([50., 0, 0, 1, 0, 0], (1, 4, 1))
    errors, estimate = element_errors(vertices, np.arange(10).reshape(1, 10), stress, 0.3)
    np.testing.assert_allclose(errors, 0, atol=1e-20)
    assert estimate < 1e-12


def test_local_bisection_splits_all_cells_on_a_shared_edge():
    points = np.array([[-1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1]], dtype=float)
    tets = np.array([[0, 1, 2, 3], [0, 2, 1, 4]])
    new_points, refined = bisect_volume((points, tets, np.full(len(points), .5)), max_elements=8, max_nodes=20)
    assert len(refined) == 4
    vertices, _, exterior = fallback_boundary(new_points, refined, 8)
    surface = trimesh.Trimesh(vertices=vertices, faces=exterior, process=False)
    assert surface.is_volume and surface.euler_number == 2
    assert surface.volume == pytest.approx(2 / 3)
    assert not np.all(vertices[exterior, 2] == 0, axis=1).any()


def test_refined_boundary_facets_keep_their_parent_load_and_support_labels():
    pytest.importorskip("igl")
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
    before = {"points": points, "exterior": np.array([[0, 1, 2], [1, 3, 2]]),
              "selected": np.array([[True, False], [False, True]])}
    refined = np.vstack((points, [1, 1, 0]))
    after = np.array([[0, 1, 4], [1, 3, 4], [3, 2, 4], [0, 4, 2]])
    np.testing.assert_equal(inherited_regions(refined, after, before), before["selected"][[0, 1, 1, 0]])


def test_large_preview_keeps_a_connected_surface_and_transfers_solved_values():
    pytest.importorskip("rtree")
    pytest.importorskip("scipy")
    mesh = trimesh.creation.icosphere(subdivisions=5)
    values = np.column_stack((mesh.vertices[:, 0] + 2, np.full(len(mesh.vertices), 3.0)))
    preview, faces = preview_surface(mesh.vertices, mesh.faces, values)
    assert len(mesh.faces) > MAX_PREVIEW_TRIANGLES >= len(faces) > 0
    assert trimesh.Trimesh(vertices=preview[:, :3], faces=faces, process=False).is_watertight
    np.testing.assert_allclose(preview[:, 3], preview[:, 0] + 2, atol=0.005)
    np.testing.assert_allclose(preview[:, 4], 3)


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


requires_fem = pytest.mark.skipif(not (fem_dependencies_available() and solver_executable()),
                                  reason="Install the FEM requirements and CalculiX to run a native solve")


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
    history = json.loads(result.headers["x-xr3d-fem-mesh-history"])
    assert len(history) == int(result.headers["x-xr3d-fem-mesh-passes"]) and 2 <= len(history) <= 3
    assert history[-1]["elements"] > history[0]["elements"]
    assert history[-1]["energyError"] < history[0]["energyError"]
    assert history[-1]["workChange"] < 0.05
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


@requires_fem
def test_mobile_bundle_uses_solved_exterior_fields_and_keeps_vtu(client):
    result = client.post("/api/v1/fem/solve", files={"model": ("beam.stl", beam_stl())},
                         data={"config": json.dumps(OPTIONS), "output_format": "mobile"})
    assert result.status_code == 200, result.text[:240] if result.status_code != 200 else ""
    assert result.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(result.content)) as bundle:
        assert set(bundle.namelist()) == {"surface.bin", "result.vtu"}
        surface = bundle.read("surface.bin")
        piece = ET.fromstring(bundle.read("result.vtu")).find("UnstructuredGrid/Piece")
    magic, nodes, triangles = struct.unpack_from("<4sII", surface)
    assert magic == b"XRF1" and 0 < triangles <= 12_000
    assert 0 < nodes < int(piece.get("NumberOfPoints"))
    values = np.frombuffer(surface, dtype="<f4", count=nodes * 5, offset=12).reshape(-1, 5)
    indices = np.frombuffer(surface, dtype="<i4", offset=12 + nodes * 20)
    assert len(indices) == triangles * 3 and indices.min() == 0 and indices.max() == nodes - 1
    vtu_nodes = np.fromstring(piece.find("Points/DataArray").text, sep=" ").reshape(-1, 3)
    corresponding = [np.argmin(np.linalg.norm(vtu_nodes - point, axis=1)) for point in values[:, :3]]
    # VTU prints nine significant digits while the phone bundle stores float32.
    np.testing.assert_allclose(values[:, :3], vtu_nodes[corresponding], rtol=1e-6, atol=1e-7)
    stress = np.fromstring(piece.find("PointData/DataArray[@Name='Stress']").text, sep=" ") / 1e6
    displacement = np.fromstring(piece.find("PointData/DataArray[@Name='Displacement']").text, sep=" ").reshape(-1, 3)
    np.testing.assert_allclose(values[:, 3], stress[corresponding], rtol=1e-6)
    np.testing.assert_allclose(values[:, 4], np.linalg.norm(displacement[corresponding], axis=1), rtol=1e-6)
    assert not list(settings.DATA_DIR.iterdir())
