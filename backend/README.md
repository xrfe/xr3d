# XR3D Studio server

The Android app sends a **real source image** to this API, runs local or hosted inference, downloads a validated model, and stores it in the project. It never substitutes a procedural sample when inference fails.

## Start on Windows (from the project root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.install_print_engine
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m backend.serve
```

The launcher generates a random `XR3D_API_TOKEN` in `.env` if it is empty. Enter it in the existing **Settings → XR3D server access token** field. Do not enter a fal credential in the phone: the phone uses the private server token, while hosted credentials stay in `.env` on the server.

The default XR3D Print Engine runs in an isolated `.venv-print` environment. Android connects directly to supported printers and asks the server for discovery if its local scan found nothing. OctoPrint, Moonraker, and PrusaLink use the server when their direct connection fails. Duet runs through the server. The Adventurer 5M and 5M Pro retain their own direct LAN protocol and authenticated fallback. Bambu uses the certificate-pinned LAN bridge. Direct LAN printing and on-device Flashforge slicing can run with the server offline. See [third-party source and notices](PRINT-ENGINE-NOTICE.md).

### Server model checks and MCP

Authenticated `GET /api/v1/print-engine` reports engine health, `GET /api/v1/print-engine/discover` finds printer advertisements from the server's LAN, and `POST /api/v1/print-engine/inspect` accepts a multipart `model` field containing an STL up to 24 MB. Its optional `config` JSON accepts `nozzleMm` and `buildVolumeMm`. Results include dimensions, triangle count, printability, and recommendations.

Configure your local MCP client to run the studio's Python interpreter with `-m backend.studio_mcp` from the project root while the XR3D server is running. The MCP server is named **XR3D Studio** and offers `discover_printers`, `inspect_stl`, and `printer_status`. `--model-dir` sets the directory the model tool can access. `--printers` points to a local JSON map of printer names to the same profiles accepted by `/printers/vendor/status`. Keep that file private because it can contain LAN access codes. `--api` selects a loopback HTTP or HTTPS studio API URL. Print starts go through the app's confirmation and one-use upload receipt.

In the app select **TRELLIS.2**, set the endpoint to:

- Android emulator: `http://10.0.2.2:8000/api/v1/reconstruct`
- Physical phone: `http://YOUR_COMPUTER_LAN_IP:8000/api/v1/reconstruct`; start with `python -m backend.serve --host 0.0.0.0` and allow the chosen port through the local firewall. The phone and server must share a trusted LAN.
- Remote server: `https://YOUR_HOST/api/v1/reconstruct` behind a TLS reverse proxy. Public HTTP inference URLs are rejected by Android.

Start with **Single View** capture, take a photograph or import one, then reconstruct. The bundled TRELLIS.2 adapters accept one conditioning image. Multiple views and text prompts fail explicitly rather than being silently ignored.

## Choose an inference runtime

### Meshy online (single or multiple images)

Select **Meshy Single Image** or **Meshy Multi Image** in Android. **My Meshy key** now contacts Meshy directly from Android and does not require this backend. Alternatively, set `MESHY_API_KEY` on the server and select **Server key** in Android. Existing personal-key server jobs retain their original route. See [complete Meshy workflow, restart handling and cost/cancellation limits](../docs/meshy.md). Meshy requires API credits and internet, not a local GPU.

### Hosted TRELLIS.2

Set `FAL_KEY` in `.env`, restart the API, and select TRELLIS.2 in the app. The adapter submits to `fal-ai/trellis-2`, polls the returned queue URL, propagates cancellation, downloads the real GLB, and validates its geometry. Hosted execution requires a funded provider account and can incur provider charges. No paid inference has been run during development.

Provider reference: <https://fal.ai/models/fal-ai/trellis-2/api>.

### Local TRELLIS.2 (GPU computer, not Android inference)

Install the official CUDA runtime, model dependencies, and weights using <https://github.com/microsoft/TRELLIS.2>. Run the API and worker on the same filesystem, usually Linux/WSL with a supported NVIDIA GPU. The mobile app does not bundle the multi-billion-parameter model.

In `.env`, point the command to the upstream environment's Python and this project's worker:

```dotenv
XR3D_LOCAL_COMMAND=["/absolute/path/to/trellis-env/bin/python", "/absolute/path/to/xr3d/backend/workers/trellis2.py"]
XR3D_LOCAL_PROVIDER=TRELLIS_2
```

The adapter passes one absolute request JSON path as the final argument. That file contains `images`, `output`, `max_poly_count`, `texture_resolution`, and the other request settings. A worker must create a valid **uncompressed GLB** at `output`, then exit zero. Logs are retained in `backend-data/JOB_ID/worker.log`. GPU/model errors become failed jobs, never invented geometry.

The included worker follows the upstream `Trellis2ImageTo3DPipeline` and `o_voxel.postprocess.to_glb` APIs. Its default local pipeline resolution follows upstream defaults; hosted quality presets map to 512/1024/1536. Actual local GPU execution still needs verification on the intended CUDA environment.

### Other models

Hunyuan can use a custom local worker through the same file contract with `XR3D_LOCAL_PROVIDER=HUNYUAN_3D`, or a compatible fal endpoint configured with `FAL_HUNYUAN_MODEL`. The generic hosted adapter expects an `image_url` input and `model_glb` or `model_mesh` output; verify the exact model schema before enabling it. There is no bundled Hunyuan worker.

The bundled app hides Tripo and Pixal because the server reports them as unconfigured. A new provider needs a verified server adapter that follows the existing `/jobs` contract. Custom REST can target another compatible XR3D server.

## Geometry and export

The API validates real GLB geometry, enforces the requested triangle budget, preserves textures in GLB when enabled, and converts to OBJ, STL, or ASCII PLY. glTF uses metres/Y-up; the Android reader and non-GLB conversion consistently convert to millimetres/Z-up. Image generation does not recover reliable physical dimensions: calibrate dimensions in the app before printing.

Android supports uncompressed GLB scene transforms, triangle lists/strips/fans, OBJ, STL, and ASCII PLY. Draco/meshopt compression, sparse glTF accessors, external texture preview, USDZ and STEP are not implemented. Unsupported geometry is rejected. The current viewer displays geometry shading; it is not a full PBR renderer.

## Optional real FDM slicing

Install PrusaSlicer 2.9.2+ and set `XR3D_SLICER_EXECUTABLE` to its CLI executable. Windows requires `prusa-slicer-console.exe`. Set `XR3D_SLICER_PROFILE` to the exported, calibrated `.ini` configuration for the intended printer. Missing profiles fail explicitly. The `/api/v1/slicer/slice` endpoint validates the actual STL and printer volume, then invokes PrusaSlicer with the profile and selected settings. Triangle infill and Normal/Organic support styles are explicit; unsupported Tree settings fail instead of being substituted. No bounding-box toolpaths are generated.

Verify printer profiles and generated toolpaths on the intended FDM printer. [PrusaSlicer CLI documentation](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface)

## Optional SLM preparation with PySLM

Install the supplied PySLM source in a separate Python 3.12 environment. The commands assume the PySLM folder is present under `external/`.

```powershell
py -3.12 -m venv .venv-slm
.\.venv-slm\Scripts\python.exe -m pip install .\external\pyslm-master
```

```bash
python3.12 -m venv .venv-slm
.venv-slm/bin/python -m pip install ./external/pyslm-master
```

Set `XR3D_SLM_PYTHON` in `.env` to use a different Python executable. The standard Docker image requires a separate PySLM install to enable this feature. PySLM is distributed under the LGPL 2.1 license included with the supplied source. [PySLM documentation](https://pyslm.readthedocs.io/en/latest/)

- `GET /api/v1/slm` checks the optional runtime.
- `POST /api/v1/slm/preview` accepts multipart `model` (a closed STL in millimetres) and `config` (JSON). Both endpoints use the XR3D server token. Try them in `/api/v1/docs`.
- The response is `xr3d-slm-preview.zip`. `manifest.json` records the engine version, settings, XYZ limits, source-to-preview translation, layer count, and total contour and hatch length. `layers.jsonl` has one JSON object per layer, including the slicing plane at `zMm`, layer thickness, and ordered `paths`. Each `contour` stores a connected XY polyline. Each `hatch` stores consecutive pairs of XY points, with a separate line segment for each pair. Coordinates are in millimetres, with the bottom of the model aligned to Z = 0.
- Preview requests are limited to 24 MiB, 250,000 triangles, 2,000 layers, and 500,000 scan segments. Additional limits on model dimensions, combined complexity, and runtime keep large previews bounded. One preview runs at a time.

For a small geometry test, paste this into the `config` field.

```json
{"layerThicknessMm":0.5,"hatchSpacingMm":0.4,"strategy":"stripe","hatchAngleDeg":5,"layerRotationDeg":67}
```

`strategy` accepts `parallel`, `stripe`, or `island`. Hatch spacing and thickness are geometry inputs for preview. In Android, open a model and select **Advanced Slicer → SLM Layer Preview** to generate or import the ZIP. Automatic metal supports, material profiles, and machine-specific output require separate integration.

## Resin layer previews

Resin layer previews use the same isolated PySLM environment as SLM. `GET /api/v1/resin` checks whether the runtime is configured. `POST /api/v1/resin/preview` accepts multipart `model` (closed STL in millimetres) and `config` (JSON). Both require the XR3D server token. For a small preview test, use this configuration in `/api/v1/docs`.

```json
{"layerThicknessMm":0.1,"pixelSizeMm":0.1,"buildVolumeMm":[120,68,150],"rotationDeg":[0,0]}
```

The backend applies X and Y tilt, aligns the lowest point with Z = 0, and checks the part’s dimensions against the supplied build volume. The preview ZIP contains `manifest.json` and one binary PNG per layer. The masks share a fixed XY grid cropped to the oriented model. Per-layer exposed area is computed from the number of white pixels. Estimated cured volume integrates that area over layer thickness and describes the model geometry. The preview omits supports, resin use outside the model, exposure timing, and printer-specific export. SLM and resin share one preview slot.

## API and deployment

Open the XR3D API Explorer at `/api/v1/docs` or the API Reference at `/redoc`. In the API Explorer, choose **Authorize** and enter the server token to test protected endpoints. The health endpoint is `/health`. All model, provider, and slicer endpoints require `Authorization: Bearer XR3D_API_TOKEN`. This is a **single-owner private studio server**, not a multi-tenant service. Use separate instances/tokens per owner; per-user accounts, quotas, billing and tenant isolation are not implemented.

### Strecs3D FEM

Install `backend/requirements.fem.txt` in the backend Python environment. Install [CalculiX CrunchiX](https://www.dhondt.de/) and set `XR3D_CCX_EXECUTABLE` in `.env` to the path to its solver executable, or put `ccx` on the server's PATH. On a minimal Linux host the Gmsh wheel also needs the system GLU library (for Debian, `libglu1-mesa`). Use the Windows `ccx_i4_static.exe` on a Windows server.

- `GET /api/v1/fem` reports whether the optional runtime is configured.
- `POST /api/v1/fem/solve` accepts multipart `model` (one closed STL or STEP solid up to 24 MB) and `config` (JSON). It returns `xr3d-fem.vtu` and summary headers for peak nodal von Mises stress in MPa, maximum displacement in mm, and mesh counts.
- Android sends the optional multipart field `output_format=mobile` to get a ZIP with the full VTU and a compact exterior mesh. The exterior uses the same solve's nodal von Mises stress in MPa and displacement magnitude in mm. Requests without this field receive the VTU directly.
- XYZ coordinates and element size are in millimetres. `forceN` is the total XYZ force in newtons, distributed over the selected triangles. A coordinate box must contain all three corners of each selected triangle. Give flat faces a small tolerance. STEP requests can also select a Gmsh surface tag with `{"faceId": 1}`. Each fixed region constrains all three translations.
- `meshMode` defaults to `adaptive`, which starts with local sizing near curvature, sampled thin STL regions, and fixed and loaded faces. CalculiX supplies integration-point stresses for a stress-recovery error estimate. The backend performs up to three solves and checks for at most 7.5% estimated relative energy error and 2% change in load work between passes. `automatic` runs the initial locally sized mesh only. `uniform` requests a single global size. The backend returns the last valid solve if later refinement exceeds the job budget or changes the selected boundary regions substantially. On repaired meshes, each refined surface triangle inherits the original support and load selection from its parent.
- For closed STL models, the worker checks for overlapping triangles and tries CGAL surface repair before Gmsh meshing. fTetWild is a fallback when Gmsh cannot build a valid volume mesh. The default repair tolerance is the smallest of 1 mm, 0.05% of the bounding box diagonal, and 5% of the requested size. `repairToleranceMm` overrides it. Repairs can simplify dense triangulations and are checked against the original for topology, volume change, and sampled surface deviation in both directions. Subsequent refinement bisects shared tetrahedral edges while preserving the accepted repaired surface. Open and disconnected models are rejected. Use the original STEP for parts with critical tolerances when it is available.
- The `X-XR3D-FEM-Mesh-Status`, `X-XR3D-FEM-Mesh-Passes`, and `X-XR3D-FEM-Mesh-History` response headers report the refinement outcome and the error and load work for each completed pass when available. `X-XR3D-FEM-Surface-Deviation-Mm` reports the sampled deviation when the STL fallback was used. The mobile ZIP contains the full VTU and a heatmap preview capped at 12,000 triangles. The preview cap does not reduce the solver resolution.

```json
{
  "elementSizeMm": 4,
  "youngsModulusMpa": 200000,
  "poissonsRatio": 0.3,
  "fixed": [{"minMm": [-0.01, -5.01, -5.01], "maxMm": [0.01, 5.01, 5.01]}],
  "loads": [{
    "region": {"minMm": [99.99, -5.01, -5.01], "maxMm": [100.01, 5.01, 5.01]},
    "forceN": [0, 0, -100]
  }]
}
```

This example fixes the end at X = 0 and loads the X = 100 end of a 100 × 10 × 10 mm beam centred on Y and Z. Save the JSON as `fem-config.json`, set `XR3D_API_TOKEN` in your shell, and submit from PowerShell with `curl.exe -H "Authorization: Bearer $env:XR3D_API_TOKEN" -F "model=@beam.stl" -F "config=<fem-config.json" -o beam.vtu http://127.0.0.1:8000/api/v1/fem/solve`.

The worker adapts [Strecs3D's mesh, solver and export workflow](../external/Strecs3D-2.1.0/FEM/fem_pipeline.cpp) for the backend. Results use quadratic tetrahedra, an isotropic linear elastic solid, and a static load case. `Stress` is the scalar von Mises field in Pa used by the Strecs3D VTU importer. `StressTensor` is in Pa, `Displacement` is in mm, and `Strain` is dimensionless. The calculation describes the solid and material properties provided. Printed-part layer bonding, infill, nonlinear failure and infill generation require separate models. See the [Strecs3D license](STRECS3D-LICENSE).

Authenticated `/ready` returns inference/slicer configuration status, not live provider or GPU validation. The pending-job queue defaults to 8 (`XR3D_MAX_PENDING_JOBS`). Waiting uploads expire after 900 seconds by default (`XR3D_UPLOAD_TTL_SECONDS`, minimum 60). Expiry releases the slot and removes partial input files. You can also cancel an abandoned job. Offline backups and dry-run retention are provided by `python -m backend.maintenance`; stop the API first. See [release operations and acceptance](../docs/release-readiness.md).

The private server also bridges Bambu MQTT/FTPS and FLASHFORGE Adventurer 5M HTTP under authenticated `/api/v1/printers/vendor` routes. These adapters work independently of AI inference configuration. See [printer adapter setup and limitations](../docs/printer-adapters.md), including trusted Bambu certificate installation and the separate printer LAN access/check code.

Run exactly **one Uvicorn worker**. SQLite records survive restarts; interrupted inference jobs become failed/retryable. The GPU queue runs one inference at a time. Keep the data volume persistent. Jobs are not automatically retried after restart to avoid duplicate hosted charges. Configure storage retention/backups before a public deployment.

Docker (hosted inference): `docker build -f backend/Dockerfile -t xr3d .`, then run with a private environment file and a persistent `/data` volume. The slim image contains the API, not CUDA or model weights.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
```

Tests cover the Android JSON contract, auth, invalid images, durable jobs, cancellation, conversion, real subprocess transport, and provider failure. Fixture geometry verifies transport; it does not measure AI output quality. Live hosted inference, local CUDA inference, and physical printer operation require their respective configured environments.
