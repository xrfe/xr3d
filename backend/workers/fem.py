"""Headless adaptation of Strecs3D's mesh, CalculiX, and VTU workflow."""
import json
import sys
from pathlib import Path
import struct
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from backend.services.fem import Face, FemOptions, InvalidModel
from backend.workers.fem_adaptive import bisect_volume, element_errors, mesh_fields, read_integration_stress, target_sizes
from backend.workers.fem_geometry import (
    fallback_boundary, has_surface_overlap, read_stl, repair_intersections, tetrahedral_fallback, thin_regions,
)

MAX_NODES = 100_000
MAX_TETRAHEDRA = 80_000
GMSH_TETRA10 = 11
GMSH_TRIANGLE6 = 9
MAX_PREVIEW_TRIANGLES = 12_000
MIN_TET_QUALITY = 1e-7
# Gmsh orders the last two mid-edge nodes differently from CalculiX and VTK.
TETRA_ORDER = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


def check_mesh_budget(volume, area, element_size):
    if volume / element_size**3 > MAX_TETRAHEDRA / 3 or area / element_size**2 > MAX_NODES / 2:
        raise InvalidModel("Increase elementSizeMm to keep the FEM mesh within its size budget")


def import_solid(gmsh, source, size, method):
    if method in ("gmsh-stl", "preserve-stl"):
        gmsh.merge(str(source))
        if method == "gmsh-stl":
            gmsh.model.mesh.classifySurfaces(np.pi / 4, True, True)
            gmsh.model.mesh.createGeometry()
        else:
            gmsh.option.setNumber("Mesh.MeshOnlyEmpty", 1)
        surfaces = [tag for _, tag in gmsh.model.getEntities(2)]
        gmsh.model.geo.addVolume([gmsh.model.geo.addSurfaceLoop(surfaces)])
        gmsh.model.geo.synchronize()
    else:
        gmsh.model.occ.importShapes(str(source))
        gmsh.model.occ.synchronize()
        solids = gmsh.model.getEntities(3)
        if len(solids) != 1:
            raise InvalidModel("Provide a STEP file with exactly one solid body")
        volume = gmsh.model.occ.getMass(*solids[0])
        area = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in gmsh.model.getBoundary(solids, oriented=False))
        if not np.isfinite([area, volume]).all() or volume <= 0:
            raise InvalidModel("STEP geometry must have a closed positive volume")
        check_mesh_budget(volume, area, size)


def import_tetrahedra(gmsh, vertices, tets, exterior):
    surface = gmsh.model.addDiscreteEntity(2)
    volume = gmsh.model.addDiscreteEntity(3, boundary=[surface])
    gmsh.model.mesh.addNodes(3, volume, np.arange(1, len(vertices) + 1), vertices.ravel())
    gmsh.model.mesh.addElementsByType(surface, 2, [], (exterior + 1).ravel())
    gmsh.model.mesh.addElementsByType(volume, 4, [], (tets + 1).ravel())
    gmsh.model.mesh.reclassifyNodes()


def generate_mesh(source, options, method, regions, sizing, fallback=None, boundary=None):
    import gmsh

    gmsh.initialize(readConfigFiles=False, interruptible=False)
    try:
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("xr3d-fem")
        size = options.elementSizeMm
        try:
            if fallback is None:
                if boundary is None:
                    import_solid(gmsh, source, size, method)
                else:
                    vertices, faces = boundary
                    surface = gmsh.model.addDiscreteEntity(2)
                    gmsh.model.mesh.addNodes(2, surface, np.arange(1, len(vertices) + 1), vertices.ravel())
                    gmsh.model.mesh.addElementsByType(surface, 2, [], faces.ravel() + 1)
                    gmsh.model.geo.addVolume([gmsh.model.geo.addSurfaceLoop([surface])])
                    gmsh.model.geo.synchronize()
                    gmsh.option.setNumber("Mesh.MeshOnlyEmpty", 1)
                if options.meshMode == "uniform":
                    gmsh.option.setNumber("Mesh.MeshSizeMin", size)
                    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
                else:
                    mesh_fields(gmsh, options, regions, sizing)
                gmsh.model.mesh.generate(3)
            else:
                import_tetrahedra(gmsh, *fallback)
            if method in ("preserve-stl", "cgal-stl", "ftetwild"):
                gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
            if len(gmsh.model.mesh.getElementsByType(4)[0]) > MAX_TETRAHEDRA:
                raise InvalidModel("Increase elementSizeMm to keep the FEM mesh within its size budget")
            gmsh.model.mesh.setOrder(2)
        except InvalidModel:
            raise
        except Exception as error:
            raise InvalidModel("Gmsh could not generate a volume mesh. Check the solid or increase the element size") from error

        tags, coordinates, _ = gmsh.model.mesh.getNodes()
        types, element_tags, connectivities = gmsh.model.mesh.getElements(3)
        if list(types) != [GMSH_TETRA10] or not len(connectivities[0]):
            raise InvalidModel("The model did not produce a quadratic tetrahedral mesh")
        tetrahedra = connectivities[0].reshape(-1, 10)
        if len(tags) > MAX_NODES or len(tetrahedra) > MAX_TETRAHEDRA:
            raise InvalidModel("Increase elementSizeMm to keep the FEM mesh within its size budget")
        jacobian = gmsh.model.mesh.getElementQualities(element_tags[0], "minDetJac")
        quality = gmsh.model.mesh.getElementQualities(element_tags[0], "minSICN")
        if (not np.isfinite(coordinates).all() or not np.isfinite(jacobian).all()
                or not np.isfinite(quality).all() or (jacobian <= 0).any() or (quality < MIN_TET_QUALITY).any()):
            raise InvalidModel("The volume mesh contains inverted or nearly degenerate elements")
        order = np.argsort(tags)
        coordinates = coordinates.reshape(-1, 3)[order]
        sorted_tags = tags[order]
        connectivity = np.searchsorted(sorted_tags, tetrahedra[:, TETRA_ORDER])
        volume_tags = gmsh.model.getEntities(3)
        surfaces = {}
        for _, tag in gmsh.model.getBoundary(volume_tags, oriented=False):
            surface_types, _, elements = gmsh.model.mesh.getElements(2, tag)
            if list(surface_types) != [GMSH_TRIANGLE6]:
                raise InvalidModel("The volume mesh has an invalid exterior surface")
            surfaces[tag] = np.searchsorted(sorted_tags, elements[0].reshape(-1, 6))
        if not surfaces:
            raise InvalidModel("The volume mesh has no valid exterior surface")
        return coordinates, connectivity, surfaces, float(quality.min())
    finally:
        gmsh.finalize()


def mesh_solid(source, options, sizing=None, previous_report=None):
    previous_method = previous_report["method"] if previous_report is not None else None
    if source.suffix != ".stl":
        points, tets, surfaces, quality = generate_mesh(source, options, "gmsh-step", [], sizing)
        return points, tets, surfaces, {"method": "gmsh-step", "minQuality": quality}

    size = options.elementSizeMm
    if previous_method in ("cgal-stl", "ftetwild"):
        # Bisect shared edges so that the repaired boundary stays geometrically identical.
        refined = fallback_boundary(*bisect_volume(sizing, MAX_TETRAHEDRA, MAX_NODES), MAX_TETRAHEDRA)
        points, tets, surfaces, quality = generate_mesh(source, options, previous_method, [], None, refined)
        return points, tets, surfaces, {**previous_report, "minQuality": quality}
    mesh = read_stl(source)
    check_mesh_budget(mesh.volume, mesh.area, size)
    intersects = previous_method is None and has_surface_overlap(mesh)
    methods = [previous_method] if previous_method else ([] if intersects else ["gmsh-stl", "preserve-stl"])
    regions = thin_regions(mesh, size) if options.meshMode != "uniform" and "gmsh-stl" in methods else []
    failure = None
    for method in methods:
        try:
            points, tets, surfaces, quality = generate_mesh(source, options, method, regions, sizing)
            return points, tets, surfaces, {"method": method, "minQuality": quality}
        except InvalidModel as error:
            failure = error
            print(f"{method}: {error} ({error.__cause__})", file=sys.stderr, flush=True)

    if previous_method is not None or options.meshMode == "uniform":
        if failure is not None:
            raise failure
        raise InvalidModel("The STL has overlapping surface triangles. Repair it or use automatic meshing")
    tolerance = options.repairToleranceMm or min(1.0, mesh.scale * 0.0005, size * 0.05)
    if intersects:
        try:
            repaired, deviation = repair_intersections(mesh, tolerance)
            regions = thin_regions(repaired, size)
            points, tets, surfaces, quality = generate_mesh(source, options, "cgal-stl", regions, None,
                                                             boundary=(repaired.vertices, repaired.faces))
            return points, tets, surfaces, {"method": "cgal-stl", "minQuality": quality,
                                             "sampledDeviationMm": deviation, "repairToleranceMm": tolerance}
        except (ImportError, ValueError, RuntimeError) as error:
            print(f"Surface intersection repair: {error}", file=sys.stderr, flush=True)
    print(f"Attempting fTetWild with surface tolerance {tolerance:.6g} mm", file=sys.stderr, flush=True)
    try:
        vertices, tets, exterior, deviation = tetrahedral_fallback(mesh, size, tolerance, MAX_TETRAHEDRA)
    except (ValueError, RuntimeError) as error:
        if isinstance(error, InvalidModel):
            raise
        raise InvalidModel("The STL could not be tetrahedralized within the repair tolerance. Try the original STEP or repair the surface") from error
    points, tets, surfaces, quality = generate_mesh(source, options, "ftetwild", [], None, (vertices, tets, exterior))
    print(f"fTetWild succeeded with sampled surface deviation {deviation:.6g} mm", file=sys.stderr, flush=True)
    return points, tets, surfaces, {"method": "ftetwild", "minQuality": quality,
                                     "sampledDeviationMm": deviation, "repairToleranceMm": tolerance}


def select_exterior(region, points, exterior, surface_tags):
    if isinstance(region, Face):
        selection = surface_tags == region.faceId
    else:
        corners = points[exterior[:, :3]]
        selection = np.all((corners >= np.asarray(region.minMm) - 1e-7)
                           & (corners <= np.asarray(region.maxMm) + 1e-7), axis=(1, 2))
    if not selection.any():
        raise InvalidModel("A fixed or load region did not select any complete exterior triangles")
    return selection


def selected_regions(options, points, surfaces, exterior):
    tags = np.repeat(list(surfaces), [len(triangles) for triangles in surfaces.values()])
    return np.column_stack([select_exterior(region, points, exterior, tags)
                            for region in [*options.fixed, *(load.region for load in options.loads)]])


def inherited_regions(points, exterior, previous):
    import igl

    old_points = previous["points"]
    centroids = points[exterior[:, :3]].mean(axis=1)
    squared_distance, parents, _ = igl.point_mesh_squared_distance(centroids, old_points, previous["exterior"][:, :3])
    tolerance = np.linalg.norm(np.ptp(old_points, axis=0)) * 1e-9
    if not np.isfinite(squared_distance).all() or (squared_distance > tolerance**2).any():
        raise InvalidModel("Could not transfer the original loads and supports onto the refined surface")
    return previous["selected"][parents]


def boundary_conditions(options, points, surfaces, selected=None):
    exterior = np.concatenate(list(surfaces.values()))
    if selected is None:
        selected = selected_regions(options, points, surfaces, exterior)
    fixed = np.unique(exterior[selected[:, :len(options.fixed)].any(axis=1)])
    loads = np.zeros_like(points)
    for index, load in enumerate(options.loads, start=len(options.fixed)):
        triangles = exterior[selected[:, index]]
        a, b, c = points[triangles[:, :3]].transpose(1, 0, 2)
        areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        if not (np.isfinite(areas).all() and (areas > 0).all()):
            raise InvalidModel("A loaded surface has degenerate elements")
        # Uniform traction on a quadratic triangle integrates to A/3 at each mid-edge node.
        weights = np.repeat(areas / (3 * areas.sum()), 3)
        np.add.at(loads, triangles[:, 3:].ravel(), weights[:, None] * load.forceN)
    free_loads = loads.copy()
    free_loads[fixed] = 0
    if not np.any(np.abs(free_loads) > 1e-12):
        raise InvalidModel("The loads cancel out or act only on fixed nodes")
    return fixed, loads


def boundary_regions(points, exterior, selected):
    summaries = []
    for mask in selected.T:
        corners = points[exterior[mask, :3]]
        if not len(corners):
            raise InvalidModel("Could not retain a fixed or loaded surface")
        areas = np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1) / 2
        if not np.isfinite(areas).all() or not (areas > 0).all():
            raise InvalidModel("A fixed or loaded surface has degenerate elements")
        summaries.append(np.r_[areas.sum(), np.average(corners.mean(axis=1), axis=0, weights=areas)])
    return np.asarray(summaries)


def prepare(folder, source, mobile=False, previous=None):
    options = FemOptions.model_validate_json((folder / "request.json").read_text())
    if source.suffix == ".stl" and any(isinstance(region, Face) for region in [*options.fixed, *(load.region for load in options.loads)]):
        raise InvalidModel("Use coordinate regions for STL; face IDs are only supported for STEP")
    sizing = None
    previous_report = None
    if previous is not None:
        previous_report = json.loads((previous / "mesh-report.json").read_text())
        with np.load(previous / "sizing.npz") as data:
            sizing = (data["points"], data["tetrahedra"], data["sizes"])
    points, tetrahedra, surfaces, report = mesh_solid(source, options, sizing, previous_report)
    exterior = np.concatenate(list(surfaces.values()))
    nested = previous is not None and report["method"] in ("cgal-stl", "ftetwild")
    if nested:
        with np.load(previous / "mesh.npz") as data:
            selected = inherited_regions(points, exterior, data)
    else:
        selected = selected_regions(options, points, surfaces, exterior)
    regions = boundary_regions(points, exterior, selected)
    fixed, loads = boundary_conditions(options, points, surfaces, selected)
    if previous is not None:
        with np.load(previous / "mesh.npz") as data:
            baseline = data["regions"]
        area_change = np.abs(regions[:, 0] / baseline[:, 0] - 1)
        movement = np.linalg.norm(regions[:, 1:] - baseline[:, 1:], axis=1)
        if (area_change > 0.12).any() or (movement > 0.25 * options.elementSizeMm).any():
            raise InvalidModel("Remeshing shifted a fixed or loaded surface. Select complete faces for adaptive refinement")
        # Keep checking every pass against the original load regions to prevent cumulative drift.
        regions = baseline
    np.savez(folder / "mesh.npz", points=points, tetrahedra=tetrahedra, exterior=exterior, loads=loads,
             regions=regions, selected=selected)
    (folder / "mesh-report.json").write_text(json.dumps(report), encoding="utf-8")
    with (folder / "analysis.inp").open("w", encoding="ascii", newline="\n") as output:
        output.write("*HEADING\nXR3D static FEM (N, mm, MPa)\n*NODE\n")
        for index, point in enumerate(points, 1):
            output.write(f"{index},{','.join(format(value, '.12g') for value in point)}\n")
        output.write("*ELEMENT,TYPE=C3D10,ELSET=PART\n")
        for index, nodes in enumerate(tetrahedra, 1):
            output.write(f"{index},{','.join(str(node + 1) for node in nodes)}\n")
        output.write("*MATERIAL,NAME=PART_MATERIAL\n*ELASTIC\n")
        output.write(f"{options.youngsModulusMpa:.12g},{options.poissonsRatio:.12g}\n")
        output.write("*SOLID SECTION,ELSET=PART,MATERIAL=PART_MATERIAL\n*BOUNDARY\n")
        for node in fixed:
            output.write(f"{node + 1},1,3,0\n")
        output.write("*STEP\n*STATIC\n*CLOAD\n")
        for node, axis in zip(*np.nonzero(np.abs(loads) > 1e-12)):
            output.write(f"{node + 1},{axis + 1},{loads[node, axis]:.12g}\n")
        output.write("*NODE FILE\nU\n*EL FILE\nS,E\n")
        if options.meshMode == "adaptive":
            output.write("*EL PRINT,ELSET=PART\nS\n")
        output.write("*END STEP\n")


def read_frd(path, node_count):
    # CalculiX writes adjacent signed fields without whitespace. Parse by column and node ID.
    components = {"DISP": 3, "STRESS": 6, "TOSTRAIN": 6}
    results = {}
    active = None
    complete = False
    with path.open(encoding="ascii") as stream:
        for line in stream:
            record = line[:3].strip()
            if record == "-4":
                field = line[3:].split()[0]
                active = field if field in components else None
                if active:
                    results[active] = np.full((node_count, components[active]), np.nan)
            elif record == "-3":
                active = None
            elif record == "-1" and active:
                node = int(line[3:13]) - 1
                if not 0 <= node < node_count:
                    raise ValueError("CalculiX results contain an unexpected node")
                count = components[active]
                results[active][node] = [float(line[13 + 12*i:25 + 12*i]) for i in range(count)]
            elif line.strip() == "9999":
                complete = True
    if not complete or any(field not in results or not np.isfinite(results[field]).all() for field in components):
        raise ValueError("CalculiX did not produce complete nodal results")
    return results["DISP"], results["STRESS"], results["TOSTRAIN"]


def write_array(output, name, data, data_type="Float64"):
    components = data.shape[1] if data.ndim == 2 else 1
    output.write(f'<DataArray type="{data_type}" Name="{name}" NumberOfComponents="{components}" format="ascii">\n')
    np.savetxt(output, data, fmt="%.9g" if data_type == "Float64" else "%d")
    output.write("</DataArray>\n")


def preview_surface(points, triangles, field):
    node_ids, indices = np.unique(triangles, return_inverse=True)
    indices = indices.reshape(-1, 3)
    vertices = points[node_ids]
    samples = field[node_ids]
    if len(indices) <= MAX_PREVIEW_TRIANGLES:
        return np.column_stack((vertices, samples)), indices

    import fast_simplification
    import trimesh

    simplified, faces = fast_simplification.simplify(vertices, indices, target_count=MAX_PREVIEW_TRIANGLES)
    if not 0 < len(faces) <= MAX_PREVIEW_TRIANGLES:
        raise InvalidModel("Could not simplify the FEM surface for the phone viewer")
    mesh = trimesh.Trimesh(vertices=vertices, faces=indices, process=False)
    # Transfer fields from the original exterior triangles without changing the VTU or summary metrics.
    values = []
    for batch in np.array_split(simplified, 24):
        nearest, _, triangle_ids = trimesh.proximity.closest_point(mesh, batch)
        weights = trimesh.triangles.points_to_barycentric(mesh.triangles[triangle_ids], nearest)
        weights = np.clip(weights, 0, 1)
        weights /= weights.sum(axis=1, keepdims=True)
        values.append(np.einsum("ij,ijk->ik", weights, samples[indices[triangle_ids]]))
    compact, remap = np.unique(faces, return_inverse=True)
    return np.column_stack((simplified, np.concatenate(values)))[compact], remap.reshape(-1, 3)


def write_mobile_result(folder, points, exterior, mises, displacement):
    # Split each quadratic face at its mid-edge nodes to retain the solved surface values.
    triangles = exterior[:, [[0, 3, 5], [3, 1, 4], [5, 4, 2], [3, 4, 5]]].reshape(-1, 3)
    values, indices = preview_surface(points, triangles, np.column_stack((mises, displacement)))
    values = values.astype("<f4")
    if not np.isfinite(values).all():
        raise InvalidModel("FEM values exceed the range supported by the phone viewer")
    with ZipFile(folder / "mobile.zip", "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
        archive.write(folder / "result.vtu", "result.vtu")
        archive.writestr("surface.bin", struct.pack("<4sII", b"XRF1", len(values), len(indices))
                         + values.tobytes() + indices.astype("<i4").tobytes())
    return len(triangles) > len(indices)


def convert(folder, mobile=False):
    with np.load(folder / "mesh.npz") as mesh:
        points, tetrahedra = mesh["points"], mesh["tetrahedra"]
        exterior = mesh["exterior"] if mobile else None
        loads = mesh["loads"]
    displacement, stress, strain = read_frd(folder / "analysis.frd", len(points))
    xx, yy, zz, xy, yz, zx = stress.T
    mises = np.sqrt(((xx-yy)**2 + (yy-zz)**2 + (zz-xx)**2) / 2 + 3 * (xy**2 + yz**2 + zx**2))
    with (folder / "result.vtu").open("w", encoding="ascii", newline="\n") as output:
        output.write('<?xml version="1.0"?>\n<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">\n')
        output.write(f'<UnstructuredGrid><Piece NumberOfPoints="{len(points)}" NumberOfCells="{len(tetrahedra)}">\n')
        output.write('<PointData Scalars="Stress" Vectors="Displacement">\n')
        # Keep the upstream Strecs3D scalar name and Pa units for its VTU importer.
        write_array(output, "Stress", mises * 1e6)
        write_array(output, "StressTensor", stress * 1e6)
        write_array(output, "Displacement", displacement)
        write_array(output, "Strain", strain)
        output.write("</PointData><Points>\n")
        write_array(output, "Coordinates", points)
        output.write("</Points><Cells>\n")
        write_array(output, "connectivity", tetrahedra, "Int32")
        write_array(output, "offsets", np.arange(1, len(tetrahedra) + 1) * 10, "Int32")
        write_array(output, "types", np.full(len(tetrahedra), 24), "UInt8")
        output.write("</Cells></Piece></UnstructuredGrid></VTKFile>\n")
    displacement_magnitude = np.linalg.norm(displacement, axis=1)
    simplified = exterior is not None and write_mobile_result(folder, points, exterior, mises, displacement_magnitude)
    summary = {
        "nodes": len(points), "elements": len(tetrahedra),
        "maxStressMpa": float(mises.max()), "maxDisplacementMm": float(displacement_magnitude.max()),
        "previewSimplified": simplified,
        **json.loads((folder / "mesh-report.json").read_text()),
    }
    options = FemOptions.model_validate_json((folder / "request.json").read_text())
    if options.meshMode == "adaptive":
        try:
            integration = read_integration_stress(folder / "analysis.dat", len(tetrahedra))
            errors, estimate = element_errors(points, tetrahedra, integration, options.poissonsRatio)
            compliance = float(np.sum(loads * displacement))
            if not np.isfinite(compliance) or compliance <= 0:
                raise ValueError("The solution did not provide positive load work")
            sizes = target_sizes(points, tetrahedra, errors, options.elementSizeMm)
            np.savez(folder / "sizing.npz", points=points, tetrahedra=tetrahedra[:, :4], sizes=sizes)
            summary.update(energyError=estimate, complianceNmm=compliance)
        except (ValueError, OSError) as error:
            print(f"Adaptive FEM estimate unavailable: {error}", file=sys.stderr, flush=True)
    (folder / "summary.json").write_text(json.dumps(summary, allow_nan=False))


if __name__ == "__main__":
    stage, directory, source_name, *previous = sys.argv[1:]
    folder = Path(directory)
    try:
        if stage in ("prepare", "prepare-mobile"):
            prepare(folder, folder / source_name, mobile=stage == "prepare-mobile",
                    previous=Path(previous[0]) if previous else None)
        elif stage in ("convert", "convert-mobile"):
            convert(folder, mobile=stage == "convert-mobile")
        else:
            raise ValueError("Unknown FEM stage")
    except InvalidModel as error:
        (folder / "invalid-model.txt").write_text(str(error), encoding="utf-8")
        sys.exit(2)
