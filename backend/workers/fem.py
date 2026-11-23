"""Headless adaptation of Strecs3D's mesh, CalculiX, and VTU workflow."""
import json
import sys
from pathlib import Path

import numpy as np

from backend.services.fem import Face, FemOptions

MAX_NODES = 100_000
MAX_TETRAHEDRA = 80_000
GMSH_TETRA10 = 11
GMSH_TRIANGLE6 = 9
# Gmsh orders the last two mid-edge nodes differently from CalculiX and VTK.
TETRA_ORDER = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


class InvalidModel(ValueError):
    pass


def is_connected(mesh):
    neighbours = [[] for _ in mesh.faces]
    for left, right in mesh.face_adjacency:
        neighbours[left].append(right)
        neighbours[right].append(left)
    visited = {0}
    pending = [0]
    while pending:
        for face in neighbours[pending.pop()]:
            if face not in visited:
                visited.add(face)
                pending.append(face)
    return len(visited) == len(mesh.faces)


def check_mesh_budget(volume, area, element_size):
    if volume / element_size**3 > MAX_TETRAHEDRA / 3 or area / element_size**2 > MAX_NODES / 2:
        raise InvalidModel("Increase elementSizeMm to keep the FEM mesh within its size budget")


def import_solid(gmsh, source, element_size):
    if source.suffix == ".stl":
        import trimesh

        try:
            mesh = trimesh.load_mesh(source, file_type="stl")
        except (ValueError, TypeError, IndexError) as error:
            raise InvalidModel("Provide a readable STL model") from error
        if (not len(mesh.faces) or len(mesh.faces) > 80_000 or not np.isfinite(mesh.vertices).all()
                or not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0
                or not is_connected(mesh)):
            raise InvalidModel("Provide one closed, consistently wound STL solid with up to 80,000 triangles")
        check_mesh_budget(mesh.volume, mesh.area, element_size)
        gmsh.merge(str(source))
        gmsh.model.mesh.classifySurfaces(np.pi / 4, True, True)
        gmsh.model.mesh.createGeometry()
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
        check_mesh_budget(volume, area, element_size)


def mesh_solid(source, options):
    import gmsh

    gmsh.initialize(readConfigFiles=False, interruptible=False)
    try:
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMin", options.elementSizeMm)
        gmsh.option.setNumber("Mesh.MeshSizeMax", options.elementSizeMm)
        gmsh.model.add("xr3d-fem")
        try:
            import_solid(gmsh, source, options.elementSizeMm)
            gmsh.model.mesh.generate(3)
            gmsh.model.mesh.setOrder(2)
        except InvalidModel:
            raise
        except Exception as error:
            raise InvalidModel("Gmsh could not generate a volume mesh. Check the solid or increase the element size") from error

        tags, coordinates, _ = gmsh.model.mesh.getNodes()
        types, _, connectivities = gmsh.model.mesh.getElements(3)
        if list(types) != [GMSH_TETRA10] or not len(connectivities[0]):
            raise InvalidModel("The model did not produce a quadratic tetrahedral mesh")
        tetrahedra = connectivities[0].reshape(-1, 10)
        if len(tags) > MAX_NODES or len(tetrahedra) > MAX_TETRAHEDRA:
            raise InvalidModel("Increase elementSizeMm to keep the FEM mesh within its size budget")
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
        return coordinates, connectivity, surfaces
    finally:
        gmsh.finalize()


def select_triangles(region, points, surfaces, exterior):
    if isinstance(region, Face):
        triangles = surfaces.get(region.faceId)
    else:
        corners = points[exterior[:, :3]]
        selection = np.all((corners >= np.asarray(region.minMm) - 1e-7)
                           & (corners <= np.asarray(region.maxMm) + 1e-7), axis=(1, 2))
        triangles = exterior[selection]
    if triangles is None or not len(triangles):
        raise InvalidModel("A fixed or load region did not select any complete exterior triangles")
    return triangles


def boundary_conditions(options, points, surfaces):
    exterior = np.concatenate(list(surfaces.values()))
    fixed = np.unique(np.concatenate([
        select_triangles(region, points, surfaces, exterior).ravel() for region in options.fixed
    ]))
    loads = np.zeros_like(points)
    for load in options.loads:
        triangles = select_triangles(load.region, points, surfaces, exterior)
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


def prepare(folder, source):
    options = FemOptions.model_validate_json((folder / "request.json").read_text())
    if source.suffix == ".stl" and any(isinstance(region, Face) for region in [*options.fixed, *(load.region for load in options.loads)]):
        raise InvalidModel("Use coordinate regions for STL; face IDs are only supported for STEP")
    points, tetrahedra, surfaces = mesh_solid(source, options)
    fixed, loads = boundary_conditions(options, points, surfaces)
    np.savez(folder / "mesh.npz", points=points, tetrahedra=tetrahedra)
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
        output.write("*NODE FILE\nU\n*EL FILE\nS,E\n*END STEP\n")


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


def convert(folder):
    with np.load(folder / "mesh.npz") as mesh:
        points, tetrahedra = mesh["points"], mesh["tetrahedra"]
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
    (folder / "summary.json").write_text(json.dumps({
        "nodes": len(points), "elements": len(tetrahedra),
        "maxStressMpa": float(mises.max()), "maxDisplacementMm": float(np.linalg.norm(displacement, axis=1).max()),
    }, allow_nan=False))


if __name__ == "__main__":
    stage, directory, source_name = sys.argv[1:]
    folder = Path(directory)
    try:
        if stage == "prepare":
            prepare(folder, folder / source_name)
        elif stage == "convert":
            convert(folder)
        else:
            raise ValueError("Unknown FEM stage")
    except InvalidModel as error:
        (folder / "invalid-model.txt").write_text(str(error), encoding="utf-8")
        sys.exit(2)
