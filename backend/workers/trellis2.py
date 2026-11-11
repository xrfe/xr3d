"""Run in upstream TRELLIS.2 CUDA environment: python trellis2.py request.json.
Reference: https://github.com/microsoft/TRELLIS.2/blob/main/example.py
"""
import json
import os
import sys
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

def main():
    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    import o_voxel
    with open(sys.argv[1], encoding="utf-8") as stream:
        request = json.load(stream)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    pipeline.cuda()
    with Image.open(request["images"][0]) as image:
        mesh = pipeline.run(image.convert("RGBA"))[0]
    mesh.simplify(16777216)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=request["max_poly_count"], texture_size=request["texture_resolution"],
        remesh=True, remesh_band=1, remesh_project=0, verbose=True)
    glb.export(request["output"], extension_webp=False)

if __name__ == "__main__":
    main()
