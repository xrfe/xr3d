"""Mesh size fields and recovery-based error estimates for linear elasticity."""

from pathlib import Path

import numpy as np

from backend.services.fem import Face, InvalidModel

TET_EDGES = np.array([[0, 1], [1, 2], [2, 0], [0, 3], [1, 3], [2, 3]])
# C3D10 uses four equal-weight Gauss points, one nearest each corner in node order.
GAUSS = np.full((4, 4), (5 - np.sqrt(5)) / 20) + np.eye(4) / np.sqrt(5)


def mesh_fields(gmsh, options, regions, sizing):
    size = options.elementSizeMm
    fields = gmsh.model.mesh.field
    gmsh.option.setNumber("Mesh.MeshSizeMin", max(0.05, size * (0.15 if sizing is not None else 0.45)))
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    local_fields = []
    for region in [*options.fixed, *(load.region for load in options.loads)]:
        if isinstance(region, Face):
            distance = fields.add("Distance")
            fields.setNumbers(distance, "SurfacesList", [region.faceId])
            field = fields.add("Threshold")
            for name, value in {"InField": distance, "SizeMin": size * 0.65, "SizeMax": size,
                                "DistMin": size * 0.2, "DistMax": size * 1.5}.items():
                fields.setNumber(field, name, value)
        else:
            field = fields.add("Box")
            for axis, lower, upper in zip("XYZ", region.minMm, region.maxMm):
                fields.setNumber(field, axis + "Min", lower - size * 0.2)
                fields.setNumber(field, axis + "Max", upper + size * 0.2)
            fields.setNumber(field, "VIn", size * 0.65)
            fields.setNumber(field, "VOut", size)
            fields.setNumber(field, "Thickness", size * 1.3)
        local_fields.append(field)

    for center, local_size in regions:
        field = fields.add("Ball")
        for name, value in {"XCenter": center[0], "YCenter": center[1], "ZCenter": center[2],
                            "Radius": size, "Thickness": size, "VIn": local_size, "VOut": size}.items():
            fields.setNumber(field, name, value)
        local_fields.append(field)

    if sizing is not None:
        points, tets, sizes = sizing
        tag = gmsh.view.add("Estimated local element size")
        values = np.column_stack((points[tets].transpose(0, 2, 1).reshape(-1, 12), sizes[tets]))
        gmsh.view.addListData(tag, "SS", len(tets), values.ravel())
        field = fields.add("PostView")
        fields.setNumber(field, "ViewTag", tag)
        local_fields.append(field)

    minimum = fields.add("Min")
    fields.setNumbers(minimum, "FieldsList", local_fields)
    fields.setAsBackgroundMesh(minimum)


def read_integration_stress(path: Path, elements, orientation=None):
    stress = np.full((elements, 4, 6), np.nan)
    with path.open(encoding="ascii") as result:
        for line in result:
            parts = line.split()
            # CalculiX may append the name of the local material frame.
            has_stresses = len(parts) == 8 or (len(parts) == 9 and parts[8] == orientation)
            if has_stresses and parts[0].isdigit() and parts[1].isdigit():
                element, point = map(int, parts[:2])
                if not 1 <= element <= elements or not 1 <= point <= 4 or np.isfinite(stress[element-1, point-1]).any():
                    raise ValueError("Invalid CalculiX integration point output")
                stress[element-1, point-1] = parts[2:8]
    if not np.isfinite(stress).all():
        raise ValueError("Incomplete CalculiX integration point stresses")
    return stress


def element_errors(points, tetrahedra, stress, poisson, transverse=None):
    corners = tetrahedra[:, :4]
    barycentric_derivative = np.vstack((-np.ones(3), np.eye(3)))
    derivative = (4 * GAUSS - 1)[:, :, None] * barycentric_derivative
    left, right = TET_EDGES.T
    edge_derivative = 4 * (GAUSS[:, left, None] * barycentric_derivative[right]
                           + GAUSS[:, right, None] * barycentric_derivative[left])
    derivative = np.concatenate((derivative, edge_derivative), axis=1)
    jacobian = np.einsum("eni,qnj->eqij", points[tetrahedra], derivative)
    weights = np.linalg.det(jacobian) / 24
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("Invalid quadratic geometry for stress recovery")

    # Extrapolate each element's integration-point field, then recover a continuous nodal field.
    stress_at_corners = np.einsum("ij,ejk->eik", np.linalg.inv(GAUSS), stress)
    volumes = weights.sum(axis=1)
    corner_weights = np.zeros(len(points))
    recovered = np.zeros((len(points), 6))
    np.add.at(corner_weights, corners.ravel(), volumes.repeat(4))
    np.add.at(recovered, corners.ravel(), (stress_at_corners * volumes[:, None, None]).reshape(-1, 6))
    nodal = recovered[corners] / corner_weights[corners, None]
    difference = np.einsum("ij,ejk->eik", GAUSS, nodal) - stress

    def energy(stress_tensor):
        if transverse is None:
            normal, shear = stress_tensor[..., :3], stress_tensor[..., 3:]
            # The common 1/E term cancels in the relative energy error.
            return (1 + poisson) * ((normal**2).sum(axis=2) + 2 * (shear**2).sum(axis=2)) - poisson * normal.sum(axis=2)**2
        # CalculiX prints local stresses as S11, S22, S33, S12, S13, S23.
        # Contract with the engineering compliance, scaled by the in-plane modulus.
        s1, s2, s3, s12, s13, s23 = np.moveaxis(stress_tensor, -1, 0)
        plane_e = transverse.inPlaneYoungsModulusMpa
        return (s1**2 + s2**2 + (plane_e / transverse.throughLayerYoungsModulusMpa) * s3**2
                - 2 * transverse.inPlanePoissonsRatio * s1 * s2
                - 2 * transverse.crossPlanePoissonsRatio * (s1 + s2) * s3
                + (plane_e / transverse.in_plane_shear) * s12**2
                + (plane_e / transverse.crossPlaneShearModulusMpa) * (s13**2 + s23**2))

    squared_errors = np.maximum((energy(difference) * weights).sum(axis=1), 0)
    reference = float((energy(stress) * weights).sum())
    if not np.isfinite(reference) or reference <= 0 or not np.isfinite(squared_errors).all():
        raise ValueError("Could not estimate the FEM discretization error")
    return squared_errors, float(np.sqrt(squared_errors.sum() / reference))


def target_sizes(points, tetrahedra, errors, size):
    corners = tetrahedra[:, :4]
    left, right = corners[:, TET_EDGES].transpose(2, 0, 1)
    edge_lengths = np.linalg.norm(points[left] - points[right], axis=2)
    element_size = np.median(edge_lengths, axis=1)
    order = np.argsort(-errors, kind="stable")
    # Mark the smallest set contributing at least half of the squared error.
    marked = order[:np.searchsorted(np.cumsum(errors[order]), errors.sum() * 0.5) + 1]
    targets = np.full(len(points), size)
    np.minimum.at(targets, corners.ravel(), np.minimum(element_size * 1.25, size).repeat(4))
    np.minimum.at(targets, corners[marked].ravel(), (element_size[marked] * 0.7).repeat(4))
    targets = np.clip(targets, max(0.05, size * 0.15), size)
    # Spread small sizes to neighboring vertices to limit abrupt jumps in density.
    for _ in range(3):
        previous = targets.copy()
        np.minimum.at(targets, left.ravel(), (previous[right] + 0.55 * edge_lengths).ravel())
        np.minimum.at(targets, right.ravel(), (previous[left] + 0.55 * edge_lengths).ravel())
    return targets


def bisect_volume(sizing, max_elements, max_nodes):
    """Refine a discrete-boundary mesh by bisecting whole stars around selected edges."""
    points, tetrahedra, targets = sizing
    edges, occurrence = np.unique(np.sort(tetrahedra[:, TET_EDGES], axis=2).reshape(-1, 2),
                                  axis=0, return_inverse=True)
    occurrence = occurrence.reshape(-1)
    length = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    per_element = occurrence.reshape(-1, 6)
    longest = np.unique(per_element[np.arange(len(tetrahedra)), length[per_element].argmax(axis=1)])
    ratio = length[longest] / targets[edges[longest]].mean(axis=1)
    order = np.argsort(-ratio, kind="stable")
    edge_groups = np.argsort(occurrence, kind="stable") // 6
    offsets = np.r_[0, np.cumsum(np.bincount(occurrence, minlength=len(edges)))]

    result = tetrahedra.copy()
    split = np.zeros(len(tetrahedra), dtype=bool)
    new_points, appended = [], []
    new_elements = 0
    quadratic_nodes = len(points)
    element_budget = min(max(8, int(len(tetrahedra) * 0.45)), max_elements - len(tetrahedra))
    for index in order[ratio[order] > 1.15]:
        edge = longest[index]
        incident = edge_groups[offsets[edge]:offsets[edge + 1]]
        nodes_required = 2 + len(incident) * 2
        if (split[incident].any() or new_elements + len(incident) > element_budget
                or quadratic_nodes + nodes_required > max_nodes):
            continue
        left, right = edges[edge]
        node = len(points) + len(new_points)
        new_points.append((points[left] + points[right]) / 2)
        original = tetrahedra[incident]
        result[incident] = np.where(original == right, node, original)
        appended.append(np.where(original == left, node, original))
        split[incident] = True
        new_elements += len(incident)
        quadratic_nodes += nodes_required
    if not appended:
        raise InvalidModel("No further local refinement fits the element size and node budget")
    return np.vstack((points, new_points)), np.concatenate([result, *appended])
