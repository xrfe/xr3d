"""Surface validation and a tolerance-limited tetrahedral fallback for STL."""

from contextlib import closing

import numpy as np
import trimesh

from backend.services.fem import InvalidModel


def read_stl(source):
    try:
        mesh = trimesh.load_mesh(source, file_type="stl")
    except (ValueError, TypeError, IndexError) as error:
        raise InvalidModel("Provide a readable STL model") from error
    if (not isinstance(mesh, trimesh.Trimesh) or not 0 < len(mesh.faces) <= 80_000
            or not np.isfinite(mesh.vertices).all() or not mesh.is_watertight
            or not mesh.is_winding_consistent or not np.isfinite(mesh.volume) or mesh.volume <= 0
            or mesh.body_count != 1 or not mesh.nondegenerate_faces(height=0).all()):
        raise InvalidModel("Provide one closed, consistently wound STL solid with up to 80,000 triangles")
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
    if (labels != labels[0]).any():
        raise InvalidModel("Provide one closed STL solid connected along its edges")
    return mesh


def overlapping_triangles(left, right):
    """Separating-axis test, including in-plane axes for coplanar triangles."""
    left_edges = np.roll(left, -1, axis=1) - left
    right_edges = np.roll(right, -1, axis=1) - right
    left_normal = np.cross(left_edges[:, 0], left_edges[:, 1])
    right_normal = np.cross(right_edges[:, 0], right_edges[:, 1])
    axes = np.concatenate((left_normal[:, None], right_normal[:, None],
                           np.cross(left_edges[:, :, None], right_edges[:, None]).reshape(-1, 9, 3),
                           np.cross(left_normal[:, None], left_edges),
                           np.cross(right_normal[:, None], right_edges)), axis=1)
    axis_length = np.linalg.norm(axes, axis=2)
    projection_left = np.einsum("nij,nkj->nik", axes, left)
    projection_right = np.einsum("nij,nkj->nik", axes, right)
    gap = np.maximum(projection_left.min(axis=2) - projection_right.max(axis=2),
                     projection_right.min(axis=2) - projection_left.max(axis=2))
    return ~(gap > 1e-12 * axis_length).any(axis=1)


def has_surface_overlap(mesh):
    """Find overlaps beyond shared topology using AABBs and triangle intersections."""
    from rtree.index import Index, Property

    faces = mesh.faces
    triangles = (mesh.triangles - mesh.bounds[0]) / mesh.scale
    bounds = np.concatenate((triangles.min(axis=1), triangles.max(axis=1)), axis=1)
    tested = 0
    entries = ((index, extent, None) for index, extent in enumerate(bounds))
    with closing(Index(entries, properties=Property(dimension=3))) as tree:
        for start in range(0, len(bounds), 128):
            pairs = []
            for index in range(start, min(start + 128, len(bounds))):
                pairs.extend((index, other) for other in tree.intersection(bounds[index]) if other > index)
                if len(pairs) > 100_000:
                    raise InvalidModel("The STL has too many overlapping triangle bounds to validate automatically")
            if not pairs:
                continue
            tested += len(pairs)
            if tested > 4_000_000:
                raise InvalidModel("The STL has too many overlapping triangle bounds to validate automatically")
            first, second = np.asarray(pairs).T
            left, right = triangles[first], triangles[second]
            shared = (faces[first, :, None] == faces[second, None, :]).any(axis=(1, 2))
            # A shared edge or vertex is expected. Test the interiors of adjacent faces.
            for triangle in (left, right):
                triangle[shared] += 1e-6 * (triangle[shared].mean(axis=1, keepdims=True) - triangle[shared])
            if overlapping_triangles(left, right).any():
                return True
    return False


def thin_regions(mesh, base_size):
    """Sample opposing faces through the solid to find narrow regions for local sizing."""
    origins = mesh.triangles_center
    sample = np.linspace(0, len(origins) - 1, min(len(origins), 256), dtype=int)
    normals = mesh.face_normals[sample]
    offset = mesh.scale * 1e-7
    starts = origins[sample] - offset * normals
    hits, rays, faces = mesh.ray.intersects_location(starts, -normals, multiple_hits=False)
    distances = np.linalg.norm(hits - starts[rays], axis=1)
    facing = np.einsum("ij,ij->i", normals[rays], mesh.face_normals[faces]) < -0.8
    valid = np.flatnonzero(facing & (distances > offset) & (distances < 2 * base_size))
    regions = []
    for index in valid[np.argsort(distances[valid])]:
        center = (starts[rays[index]] + hits[index]) / 2
        if all(np.linalg.norm(center - previous) > base_size for previous, _ in regions):
            regions.append((center, distances[index] / 3))
        if len(regions) == 8:
            break
    return regions


def boundary_faces(tets):
    # Outward winding for positively oriented linear tetrahedra.
    faces = tets[:, [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]].reshape(-1, 3)
    _, indices, counts = np.unique(np.sort(faces, axis=1), axis=0, return_index=True, return_counts=True)
    if (counts > 2).any():
        raise InvalidModel("The fallback produced a non-manifold volume mesh")
    return faces[indices[counts == 1]]


def sampled_deviation(source, target):
    samples = []
    for data in (source.vertices, source.triangles_center):
        samples.append(data[np.linspace(0, len(data) - 1, min(len(data), 3072), dtype=int)])
    distances = [trimesh.proximity.closest_point(target, batch)[1].max()
                 for batch in np.array_split(np.concatenate(samples), 24)]
    return float(max(distances))


def verify_fallback_surface(original, surface, tolerance):
    if (not surface.is_volume or surface.body_count != 1 or surface.euler_number != original.euler_number
            or abs(surface.volume - original.volume) > min(original.area * tolerance, original.volume * 0.05)):
        raise InvalidModel("The STL fallback changed the solid's topology or volume beyond the repair tolerance")
    deviation = max(sampled_deviation(original, surface), sampled_deviation(surface, original))
    if not np.isfinite(deviation) or deviation > tolerance:
        raise InvalidModel("The STL fallback changed the surface beyond the repair tolerance")
    return deviation


def repair_intersections(mesh, tolerance):
    from igl.copyleft import cgal
    from scipy.sparse import coo_array
    from scipy.sparse.csgraph import connected_components

    vertices, faces, _ = cgal.mesh_boolean(np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.int64), type_str="union")
    if not len(faces):
        raise InvalidModel("Surface intersection repair could not recover a closed solid")
    surface = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    # A resolved point contact can still join two separate local fans at the same vertex.
    adjacent = surface.face_adjacency
    shared = surface.face_adjacency_edges
    position = (faces[adjacent][:, :, :, None] == shared[:, None, None, :]).argmax(axis=2)
    corners = adjacent[:, :, None] * 3 + position
    links = coo_array((np.ones(len(corners) * 2), (corners[:, 0].ravel(), corners[:, 1].ravel())),
                      shape=(faces.size, faces.size))
    _, fans = connected_components(links, directed=False)
    _, first = np.unique(fans, return_index=True)
    isolated_fans = trimesh.Trimesh(vertices=vertices[faces.ravel()[first]], faces=fans.reshape(-1, 3), process=False)

    for count in dict.fromkeys([min(12_000, len(faces)), min(24_000, len(faces)), len(faces)]):
        candidate = isolated_fans.simplify_quadric_decimation(face_count=count) if count < len(faces) else isolated_fans
        try:
            deviation = verify_fallback_surface(mesh, candidate, tolerance)
            if not has_surface_overlap(candidate):
                return candidate, deviation
        except InvalidModel:
            continue
    raise InvalidModel("Surface intersection repair did not preserve the solid within its repair tolerance")


def tetrahedral_fallback(mesh, size, tolerance, max_tetrahedra):
    try:
        import pytetwild
    except ImportError as error:
        raise InvalidModel("Install the updated FEM requirements to use the STL meshing fallback") from error

    source, remaining = mesh, tolerance
    if len(mesh.faces) > 16_000:
        # An oversampled scan can spend most of the meshing budget inserting almost coplanar triangles.
        reduced = mesh.simplify_quadric_decimation(face_count=12_000)
        try:
            if not has_surface_overlap(reduced):
                deviation = verify_fallback_surface(mesh, reduced, tolerance * 0.30)
                source, remaining = reduced, tolerance - deviation
        except InvalidModel:
            pass

    vertices, tets = pytetwild.tetrahedralize(np.ascontiguousarray(source.vertices),
                                              np.ascontiguousarray(source.faces, dtype=np.int32),
                                              edge_length_abs=size, epsilon=remaining / source.scale,
                                              num_threads=1, num_opt_iter=4, loglevel=4, quiet=False)
    vertices, tets, exterior = fallback_boundary(vertices, tets, max_tetrahedra)
    boundary = trimesh.Trimesh(vertices=vertices, faces=exterior, process=False)
    boundary.remove_unreferenced_vertices()
    deviation = verify_fallback_surface(mesh, boundary, tolerance)
    return vertices, tets, exterior, deviation


def fallback_boundary(vertices, tets, max_tetrahedra):
    tets = np.asarray(tets, dtype=np.int64)
    if not len(tets):
        raise InvalidModel("The STL fallback did not find a closed interior within the repair tolerance")
    if len(tets) > max_tetrahedra:
        raise InvalidModel(f"The STL fallback produced {len(tets):,} elements, above its {max_tetrahedra:,}-element budget")
    used, indices = np.unique(tets, return_inverse=True)
    vertices = np.asarray(vertices)[used]
    tets = indices.reshape(-1, 4)
    corners = vertices[tets]
    determinants = np.linalg.det(corners[:, 1:] - corners[:, :1])
    if not np.isfinite(determinants).all() or (determinants == 0).any():
        raise InvalidModel("The STL fallback produced degenerate volume elements")
    reversed_tets = determinants < 0
    tets[reversed_tets] = tets[reversed_tets][:, [0, 2, 1, 3]]
    return vertices, tets, boundary_faces(tets)
