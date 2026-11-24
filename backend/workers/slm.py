"""Generate SLM scan paths and resin layer masks in a bounded worker process."""
from io import BytesIO
import json
import math
from pathlib import Path
import struct
import sys
from zipfile import ZIP_DEFLATED, ZipFile

MAX_LAYERS = 2_000
MAX_FACES = 250_000
MAX_FACE_LAYER_PRODUCT = 80_000_000
MAX_SEGMENTS = 500_000
MAX_MASK_PIXELS = 2_000_000
MAX_STACK_PIXELS = 250_000_000


class PreviewInputError(ValueError):
    pass


def load_part(source):
    try:
        with source.open("rb") as stream:
            mesh = trimesh.load_mesh(stream, file_type="stl", process=False)
    except (ValueError, IndexError, OverflowError, struct.error) as error:
        raise PreviewInputError("The uploaded file is not a valid STL") from error
    if mesh.is_empty or not np.isfinite(mesh.vertices).all():
        raise PreviewInputError("STL must contain finite mesh geometry")
    if len(mesh.faces) > MAX_FACES:
        raise PreviewInputError("Simplify the STL to 250,000 triangles or fewer")
    mesh.merge_vertices()
    if not mesh.is_volume:
        raise PreviewInputError("STL must be watertight with consistently outward-facing triangles")
    if np.any(np.abs(mesh.bounds) > 100_000) or np.any(mesh.extents > 500):
        raise PreviewInputError("Use model dimensions up to 500 mm and coordinates within 100,000 mm of the origin")

    part = pyslm.Part("XR3D preview")
    part.setGeometryByMesh(mesh)
    part.dropToPlatform()
    return part, len(mesh.faces), float(-mesh.bounds[0, 2])


def layer_paths(layer):
    paths = []
    length = 0.0
    count = 0
    for geometry in layer.geometry:
        coords = geometry.coords
        if isinstance(geometry, ContourGeometry):
            segments = np.diff(coords, axis=0)
            kind = "contour"
        elif isinstance(geometry, HatchGeometry):
            segments = coords[1::2] - coords[::2]
            kind = "hatch"
        else:
            raise RuntimeError("Unexpected geometry in a PySLM hatch layer")
        count += len(segments)
        length += float(np.linalg.norm(segments, axis=1).sum())
        paths.append({"kind": kind, "xyMm": coords.tolist()})
    return paths, length, count


def prepare(folder):
    options = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    part, face_count, z_shift = load_part(folder / "model.stl")
    height = float(part.boundingBox[5])
    thickness = options["layerThicknessMm"]
    layer_count = math.ceil(height / thickness - 1e-9)
    if layer_count < 1:
        raise PreviewInputError("The STL has no usable height")
    if layer_count > MAX_LAYERS or face_count * layer_count > MAX_FACE_LAYER_PRODUCT:
        raise PreviewInputError("Use thicker layers or simplify the STL to fit the preview complexity limit")

    hatcher = {"parallel": Hatcher, "stripe": StripeHatcher, "island": IslandHatcher}[options["strategy"]]()
    hatcher.hatchDistance = options["hatchSpacingMm"]
    hatcher.spotCompensation = 0.0
    hatcher.contourOffset = 0.0
    hatcher.volumeOffsetHatch = 0.0
    hatcher.numOuterContours = 1
    hatcher.numInnerContours = 0
    if options["strategy"] == "parallel":
        hatcher.hatchSortMethod = AlternateSort()

    total_length = 0.0
    total_segments = 0
    with ZipFile(folder / "preview.zip", "w", compression=ZIP_DEFLATED) as archive:
        with archive.open("layers.jsonl", "w") as layers:
            for index in range(layer_count):
                bottom = index * thickness
                top = min(height, bottom + thickness)
                z = (bottom + top) / 2
                angle = (options["hatchAngleDeg"] + index * options["layerRotationDeg"]) % 180
                hatcher.hatchAngle = angle
                boundaries = part.getVectorSlice(z)
                try:
                    layer = hatcher.hatch(boundaries) if boundaries else None
                except ValueError as error:
                    raise PreviewInputError("PySLM could not hatch a layer. Check the mesh or choose a different strategy") from error
                paths, length, count = layer_paths(layer) if layer is not None else ([], 0.0, 0)
                total_length += length
                total_segments += count
                if total_segments > MAX_SEGMENTS:
                    raise PreviewInputError("Use thicker layers or wider hatch spacing to fit the scan segment limit")
                record = {"index": index, "zMm": z, "thicknessMm": top - bottom,
                          "hatchAngleDeg": angle, "scanLengthMm": length, "paths": paths}
                layers.write(json.dumps(record, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n")
        if not total_segments:
            raise PreviewInputError("No scan paths were generated at the requested layer thickness")
        manifest = {"schemaVersion": 1, "engine": "PySLM", "engineVersion": pyslm.__version__,
                    "machineReady": False, "settings": options, "boundsMm": part.geometry.bounds.tolist(),
                    "translationMm": [0, 0, z_shift], "layerCount": layer_count,
                    "scanSegmentCount": total_segments, "scanLengthMm": total_length}
        archive.writestr("manifest.json", json.dumps(manifest, allow_nan=False))


def prepare_resin(folder):
    options = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    part, face_count, _ = load_part(folder / "model.stl")
    part.origin = [0.0, 0.0, 0.0]
    part.rotation = [*options["rotationDeg"], 0.0]
    part.dropToPlatform()
    # Express the printer's +Z in the original model frame, before tilting for the preview.
    build_direction = part.getTransform()[2, :3].tolist()
    bounds = part.geometry.bounds
    extents = bounds[1] - bounds[0]
    if np.any(extents > np.array(options["buildVolumeMm"]) + 1e-6):
        dimensions = " × ".join(f"{dimension:.2f}" for dimension in extents)
        raise PreviewInputError(f"The oriented model measures {dimensions} mm and exceeds the build volume")

    pitch = options["pixelSizeMm"]
    thickness = options["layerThicknessMm"]
    height = float(extents[2])
    layer_count = max(1, math.ceil(height / thickness - 1e-9))
    if layer_count > MAX_LAYERS or face_count * layer_count > MAX_FACE_LAYER_PRODUCT:
        raise PreviewInputError("Use thicker layers or simplify the STL to fit the resin preview complexity limit")
    width_px, height_px = (max(1, math.ceil(length / pitch)) for length in extents[:2])
    plane_pixels = width_px * height_px
    if plane_pixels > MAX_MASK_PIXELS or plane_pixels * layer_count > MAX_STACK_PIXELS:
        raise PreviewInputError("Use larger preview pixels or thicker layers to fit the resin preview pixel limit")

    # Sample a fixed XY grid at pixel centres so area and motion compare across layers.
    center_x, center_y = bounds[:, :2].mean(axis=0)
    columns = center_x + (np.arange(width_px) + 0.5 - width_px / 2) * pitch
    rows = center_y - (np.arange(height_px) + 0.5 - height_px / 2) * pitch
    layers = []
    volume = 0.0
    with ZipFile(folder / "preview.zip", "w") as archive:
        for index in range(layer_count):
            bottom = index * thickness
            top = min(height, bottom + thickness)
            z = (bottom + top) / 2
            polygons = part.getVectorSlice(z, returnCoordPaths=False, fixPolygons=False)
            if len(polygons):
                region = shapely.union_all(polygons)
                mask = shapely.intersects_xy(region, columns[None, :], rows[:, None])
            else:
                mask = np.zeros((height_px, width_px), dtype=bool)
            area = float(np.count_nonzero(mask) * pitch**2)
            volume += area * (top - bottom)
            layers.append({"zMm": z, "thicknessMm": top - bottom, "exposedAreaMm2": area})
            with BytesIO() as png:
                Image.fromarray(mask).save(png, format="PNG")
                archive.writestr(f"layers/{index}.png", png.getvalue())
        if not volume:
            raise PreviewInputError("No solid pixels were sampled. Use finer pixels or thinner layers")
        manifest = {"schemaVersion": 1, "kind": "resinPreview", "machineReady": False, "engine": "PySLM",
                    "pixelSizeMm": pitch, "widthPx": width_px, "heightPx": height_px,
                    "modelSizeMm": extents.tolist(), "buildVolumeMm": options["buildVolumeMm"],
                    "rotationDeg": options["rotationDeg"], "buildDirectionInModel": build_direction,
                    "estimatedCuredVolumeMm3": volume, "layers": layers}
        archive.writestr("manifest.json", json.dumps(manifest, allow_nan=False), compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    operation = sys.argv[1]
    try:
        import numpy as np
        import pyslm
        from pyslm.geometry import ContourGeometry, HatchGeometry
        from pyslm.hatching import AlternateSort, Hatcher, IslandHatcher, StripeHatcher
        import trimesh
        if operation in ("resin", "check-resin"):
            from PIL import Image
            import shapely
    except (ImportError, OSError):
        sys.exit(3)

    if operation in ("preview", "resin"):
        preview_folder = Path(sys.argv[2])
        try:
            (prepare_resin if operation == "resin" else prepare)(preview_folder)
        except PreviewInputError as error:
            (preview_folder / "input-error.txt").write_text(str(error), encoding="utf-8")
            sys.exit(2)
