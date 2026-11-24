# XR3D Studio server

XR3D Server is the optional backend for the mobile-first Android app. It provides local or hosted image-to-3D inference, server-side FDM slicing, printer discovery and connection fallbacks, STL checks, FEM, and resin and metal layer previews. The phone can connect directly to supported printers, slice for the FLASHFORGE Adventurer 5M series on-device, and practice with offline demos. [Android workflows](../README.md#use-the-phone-workflows)

## Install and start

On Windows, install Python 3.12, then double-click **Install XR3D Server.bat** and **Start XR3D Server.bat** from the project folder. On Debian-based Linux, use Python 3.12 with `venv` and its development headers, then install `calculix-ccx`, `libglu1-mesa`, `build-essential`, and `cmake` using your package manager. Run `bash install-xr3d-server.sh` and `bash start-xr3d-server.sh`. Pyclipr builds from its source release on Linux. Both installers create `.venv` when needed and reuse an existing `.venv` and `.env`. To create the environment yourself, run `py -3.12 -m venv .venv` on Windows or `python3.12 -m venv .venv` on Linux before using the install launcher.

The server defaults to port `8000`. When LAN pairing is available, the launcher prints its LAN address and setup code. On startup it generates `XR3D_API_TOKEN` in `.env` if a token is missing. Use [.env.example](../.env.example) for optional settings.

### Connect one or more phones

1. On the same trusted LAN, open **Settings → Find XR3D Server**, tap the discovered server, enter the setup code from the launcher, and tap **Connect**. If discovery finds no server, enter the displayed LAN address in that dialog and use the same code. Discovery uses mDNS (UDP 5353). Pairing and API requests use the server's configured HTTP port.
2. To add another phone while the server is running, fill in **XR3D server URL** and **XR3D server access token** in Android Settings using the server endpoint and `XR3D_API_TOKEN` from `.env`. For example, use `http://192.168.1.20:8000/api/v1/reconstruct` on the LAN, `http://10.0.2.2:8000/api/v1/reconstruct` on the Android Studio emulator, or `https://xr3d.example.com/api/v1/reconstruct` for a private server behind an HTTPS reverse proxy. Use the actual address and port of your server.

Each setup code expires after ten minutes or one successful connection. Restart the server when it is idle to generate a fresh code for discovery-based pairing. Several trusted phones can use the same server concurrently. They share the server token and its permissions, and Android project libraries stay on their respective phones. Use HTTPS for connections outside the local network.

The API, print engine, MCP, SLM, resin, and FEM workers use the same `.venv`. Workers still run in separate bounded processes. Existing `.venv-print` and `.venv-slm` directories and their old interpreter overrides are ignored by the backend. Android connects directly to supported printers and uses the backend for eligible fallbacks and advanced workflows. Direct LAN printing, on-device Flashforge slicing, and direct personal-key Meshy generation can run with the XR3D server offline. See [third-party source and notices](PRINT-ENGINE-NOTICE.md).

### Upstream dependencies

The installer reads [requirements.lock.txt](requirements.lock.txt) and [requirements.upstream.txt](requirements.upstream.txt). The latter pins public releases from [Kiln](https://github.com/codeofaxel/Kiln), [PySLM](https://github.com/drlukeparry/pyslm), and [Pyclipr](https://github.com/drlukeparry/pyclipr). For a fork, replace its entry with the fork's release wheel URL or a direct archive pinned to a full Git commit. A Kiln source archive needs `#subdirectory=kiln`. PySLM's package is at its repository root. For a Pyclipr fork, publish a wheel or a source release that includes its build submodules. Update the lock when a fork changes dependencies, then rerun the installer. The backend and Docker build use these sources directly. The Android build packages its native OrcaPhone slicer separately to keep Flashforge slicing on the phone.

### Server model checks and MCP

Authenticated `GET /api/v1/print-engine` reports engine health, `GET /api/v1/print-engine/discover` finds printer advertisements from the server's LAN, and `POST /api/v1/print-engine/inspect` accepts a multipart `model` field containing an STL up to 24 MiB. Its optional `config` JSON accepts `nozzleMm` and `buildVolumeMm`. Results include dimensions, triangle count, printability, and recommendations.

Configure your local MCP client to run the studio's Python interpreter with `-m backend.studio_mcp` from the project root while the XR3D server is running. The MCP server is named **XR3D Studio** and offers `discover_printers`, `inspect_stl`, and `printer_status`. `--model-dir` sets the directory the model tool can access. `--printers` points to a local JSON map of printer names to the same profiles accepted by `/printers/vendor/status`. Keep that file private because it can contain LAN access codes. `--api` selects a loopback HTTP or HTTPS studio API URL. Print starts go through the app's confirmation and one-use upload receipt.

## Choose an inference runtime

Edit the server's `.env` and restart XR3D Server to apply provider settings. Choose the provider in Android Settings or Reconstruction. **Offline Demo** creates a sample mesh on the phone. Connected reconstruction reports provider failures in the app.

### Meshy online (single or multiple images)

Select **Meshy Single Image** or **Meshy Multi Image** in Android. **My Meshy key** now contacts Meshy directly from Android and does not require this backend. Alternatively, set `MESHY_API_KEY` on the server and select **Server key** in Android. Existing personal-key server jobs retain their original route. See [complete Meshy workflow, restart handling and cost/cancellation limits](../docs/meshy.md). Meshy requires API credits and internet, not a local GPU.

### Hosted TRELLIS.2

Set `FAL_KEY` in `.env`, restart the API, and select **TRELLIS.2** in the app. The default `FAL_TRELLIS_MODEL` is `fal-ai/trellis-2`. The adapter polls the returned queue URL, propagates cancellation, and downloads and validates the GLB. Hosted execution requires a funded provider account and can incur provider charges. Live paid inference is unverified.

Provider reference: <https://fal.ai/models/fal-ai/trellis-2/api>.

### Local TRELLIS.2 (GPU computer, not Android inference)

Install the official CUDA runtime, model dependencies, and weights using <https://github.com/microsoft/TRELLIS.2>. Run the API and worker on the same filesystem, usually Linux/WSL with a supported NVIDIA GPU. The mobile app does not bundle the multi-billion-parameter model.

In `.env`, point the command to the upstream environment's Python and this project's worker:

```dotenv
XR3D_LOCAL_COMMAND=["/absolute/path/to/trellis-env/bin/python", "/absolute/path/to/xr3d/backend/workers/trellis2.py"]
XR3D_LOCAL_PROVIDER=TRELLIS_2
```

The adapter passes one absolute request JSON path as the final argument. That file contains `images`, `output`, `max_poly_count`, `texture_resolution`, and the other request settings. A worker must create a valid **uncompressed GLB** at `output`, then exit zero. Logs are retained in `backend-data/JOB_ID/worker.log`. GPU/model errors become failed jobs, never invented geometry.

The included worker follows the upstream `Trellis2ImageTo3DPipeline` and `o_voxel.postprocess.to_glb` APIs. Its local pipeline resolution follows upstream defaults. Hosted quality presets map to 512, 1024, or 1536. For either TRELLIS.2 adapter, use **Single View** in Android and supply one photo. Actual local GPU execution still needs verification on the intended CUDA environment.

### Other models

Hunyuan can use a custom local worker through the same file contract with `XR3D_LOCAL_PROVIDER=HUNYUAN_3D`, or a compatible fal endpoint configured with `FAL_HUNYUAN_MODEL`. The generic hosted adapter expects an `image_url` input and `model_glb` or `model_mesh` output; verify the exact model schema before enabling it. There is no bundled Hunyuan worker.

The bundled app hides Tripo and Pixal because the server reports them as unconfigured. A new provider needs a verified server adapter that follows the existing `/jobs` contract. Custom REST can target another compatible XR3D server.

## Geometry and export

The API validates real GLB geometry, enforces the requested triangle budget, preserves textures in GLB when enabled, and converts to OBJ, STL, or ASCII PLY. glTF uses metres/Y-up; the Android reader and non-GLB conversion consistently convert to millimetres/Z-up. Image generation does not recover reliable physical dimensions: calibrate dimensions in the app before printing.

Android supports uncompressed GLB scene transforms, triangle lists/strips/fans, OBJ, STL, and ASCII PLY. Draco/meshopt compression, sparse glTF accessors, external texture preview, USDZ and STEP are not implemented. Unsupported geometry is rejected. The current viewer displays geometry shading; it is not a full PBR renderer.

## Optional real FDM slicing

Install PrusaSlicer 2.9.2+ and set `XR3D_SLICER_EXECUTABLE` in `.env` to its CLI executable. Use `prusa-slicer-console.exe` on Windows or `prusa-slicer` on Linux. Set `XR3D_SLICER_PROFILE` to one exported, calibrated `.ini` profile for the intended printer, then restart the server. `POST /api/v1/slicer/slice` accepts multipart `model` (watertight STL in millimetres) and `config` (JSON), validates the model and build volume, then returns G-code generated by PrusaSlicer. Supported support styles are None, Normal, and Organic.

On the phone, open **Home → First Print** for a guided filament workflow, or **Viewer → Prepare Print** for the slicer. Choose the saved printer profile and loaded filament, tap **Slice Model**, then use **View layers** to inspect the G-code before confirming **Start print**. Supported Flashforge profiles slice on the phone. **Practice without a printer** also runs on the phone and stops at the layer preview. Use the manufacturer's slicer when the printer requires a vendor-specific file, such as Bambu's sliced `.gcode.3mf`.

Verify printer profiles and generated toolpaths on the intended FDM printer. [PrusaSlicer CLI documentation](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface)

## Optional SLM preparation with PySLM

The standard installer and Docker image include the pinned PySLM package in the backend environment. [PySLM documentation](https://pyslm.readthedocs.io/en/latest/) · [PySLM license](https://github.com/drlukeparry/pyslm/blob/master/LICENSE)

- `GET /api/v1/slm` checks the optional runtime.
- `POST /api/v1/slm/preview` accepts multipart `model` (a closed STL in millimetres) and `config` (JSON). Both endpoints use the XR3D server token. Try them in `/api/v1/docs`.
- The response is `xr3d-slm-preview.zip`. `manifest.json` records the engine version, settings, XYZ limits, source-to-preview translation, layer count, and total contour and hatch length. `layers.jsonl` has one JSON object per layer, including the slicing plane at `zMm`, layer thickness, and ordered `paths`. Each `contour` stores a connected XY polyline. Each `hatch` stores consecutive pairs of XY points, with a separate line segment for each pair. Coordinates are in millimetres, with the bottom of the model aligned to Z = 0.
- Preview requests are limited to 24 MiB, 250,000 triangles, 2,000 layers, and 500,000 scan segments. Additional limits on model dimensions, combined complexity, and runtime keep large previews bounded. One preview runs at a time.

For a small geometry test, paste this into the `config` field.

```json
{"layerThicknessMm":0.5,"hatchSpacingMm":0.4,"strategy":"stripe","hatchAngleDeg":5,"layerRotationDeg":67}
```

`strategy` accepts `parallel`, `stripe`, or `island`. Hatch spacing and thickness are geometry inputs for preview. In Android, select **SLM Metal**, then open **Viewer → Preview or simulate**. Use **Generate preview** to compute layers on the server or **Open ZIP** to inspect an existing archive. The offline simulator runs on the phone with a sample or a loaded model. Use the machine manufacturer's software to prepare files for a physical metal print.

## Resin layer previews

Resin layer previews use PySLM in the shared backend Python environment. `GET /api/v1/resin` checks whether the runtime is configured. `POST /api/v1/resin/preview` accepts multipart `model` (closed STL in millimetres) and `config` (JSON). Both require the XR3D server token. For a small preview test, use this configuration in `/api/v1/docs`.

```json
{"layerThicknessMm":0.1,"pixelSizeMm":0.1,"buildVolumeMm":[120,68,150],"rotationDeg":[0,0]}
```

The backend applies X and Y tilt, aligns the lowest point with Z = 0, and checks the part’s dimensions against the supplied build volume. The preview ZIP contains `manifest.json` and one binary PNG per layer. The masks share a fixed XY grid cropped to the oriented model. Per-layer exposed area is computed from the number of white pixels. Estimated cured volume integrates that area over layer thickness and describes the model geometry. The preview omits supports, resin use outside the model, exposure timing, and printer-specific export. SLM and resin share one preview slot.

In Android, select **SLA Resin**, then open **Viewer → Preview or simulate** to generate a preview on the server, open a saved preview ZIP, or practice with the offline print simulator. Physical resin print preparation uses the manufacturer's software.

## Strecs3D FEM

The standard installer includes the Python FEM libraries. On x86-64 Windows it installs a checksum-verified CalculiX 2.24 executable when needed. Linux uses the system `ccx` command and GLU library. `XR3D_CCX_EXECUTABLE` in `.env` can select a different solver installation. [CalculiX project](https://www.dhondt.de/)

Connect the server in Android Settings, open a saved model, then choose **Viewer → FEA XR**. Select **Use backend** if the demo is active. Pick the fixed and loaded regions, set the material, force, and mesh size, then tap **Run FEM on Server**. Inspect stress and displacement, open **View result in AR**, or export the full VTU. The Android app sends STL. The API also accepts STEP directly.

- `GET /api/v1/fem` reports runtime availability, supported material models, and planned analyses.
- `POST /api/v1/fem/solve` accepts multipart `model` (one closed STL or STEP solid up to 24 MiB) and `config` (JSON). It returns `xr3d-fem.vtu` and summary headers for peak nodal von Mises stress in MPa, maximum displacement in mm, and mesh counts.
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

This example fixes the end at X = 0 and loads the X = 100 end of a 100 × 10 × 10 mm beam centred on Y and Z. Save the JSON as `fem-config.json` and set `XR3D_API_TOKEN` in your terminal before running the request. In Windows Command Prompt, run:

```bat
curl.exe -H "Authorization: Bearer %XR3D_API_TOKEN%" -F "model=@beam.stl" -F "config=<fem-config.json" -o beam.vtu http://127.0.0.1:8000/api/v1/fem/solve
```

In Linux or WSL, use `curl` and `$XR3D_API_TOKEN` in the same command.

The backend worker adapts the mesh, solver, and export workflow from Strecs3D. It uses quadratic tetrahedra and linear static elasticity. `Stress` is the scalar von Mises field in Pa used by the Strecs3D VTU importer. `StressTensor` is in Pa, `Displacement` is in mm, and `Strain` is dimensionless. The solve describes the effective solid under external load. Predicting failure or the strength of layer bonds requires separate directional strength data and a failure model. [Strecs3D upstream](https://github.com/tomohiron907/Strecs3D) · [Strecs3D license](STRECS3D-LICENSE)

For FDM, SLM, or SLA, choose **Transversely isotropic** in FEM when stiffness is approximately uniform within the layer plane. The phone accepts GPa and the API uses MPa. Specify the layer normal in the model's XYZ coordinates. The **Analyze in FEM** link in an XR3D layer preview transfers the SLM build axis or the SLA build axis after the preview tilt. For an imported model, confirm the build axis before solving. Supply measured constants for the intended print settings, heat treatment, or resin post-cure. **Isotropic** remains available and uses the original request fields.

API clients can send `transverseIsotropy` in place of both `youngsModulusMpa` and `poissonsRatio`. Its five elastic constants are `inPlaneYoungsModulusMpa`, `throughLayerYoungsModulusMpa`, `inPlanePoissonsRatio` (ν₁₂), `crossPlanePoissonsRatio` (ν₁₃ under in-plane load), and `crossPlaneShearModulusMpa` (G₁₃ = G₂₃). `buildDirection` is a nonzero XYZ vector normal to the layers. Adaptive mesh refinement uses the material's local elastic compliance. The `X-XR3D-FEM-Material-Model` response header identifies the solved material model.

Residual stress, print warping, and thermo-mechanical coupling appear as planned analyses. They require separate process models and have no solve action.

## API and deployment

On the server computer, open the [XR3D API Explorer](http://127.0.0.1:8000/api/v1/docs) to submit requests and inspect responses, or the [API Reference](http://127.0.0.1:8000/redoc) to browse the operations. Use **Authorize** in the Explorer and enter the server token for protected endpoints. The Explorer is a developer tool. Change persistent server settings in `.env`, edit calibrated printer profiles in PrusaSlicer, and use Android for visual print preparation and FEM.

The interactive pages load their browser libraries from a CDN. The [OpenAPI JSON](http://127.0.0.1:8000/api/v1/openapi.json) is served locally and is available offline.

`GET /health` checks liveness without a token. Authenticated `GET /ready` reports configured inference and slicing. Its HTTP status reflects inference readiness, so inspect `slicingConfigured` separately. `GET /api/v1/providers` lists provider capabilities, and `GET /api/v1/fem`, `/api/v1/slm`, and `/api/v1/resin` report runtime availability. Live provider and hardware checks require running their corresponding workflows.

The private server bridges Bambu MQTT/FTPS and FLASHFORGE Adventurer 5M-series HTTP under authenticated `/api/v1/printers/vendor` routes. The XR3D Print Engine handles Duet and eligible fallbacks for OctoPrint, Moonraker, and PrusaLink. These adapters work independently of AI inference configuration. See [printer adapter setup and limitations](../docs/printer-adapters.md), including trusted Bambu certificates and the separate printer LAN access or check code.

### Concurrent jobs and storage

Run exactly **one Uvicorn worker** for this private, single-owner server. Multiple connected phones share access to server jobs. Use separate instances and tokens for separate owners who need isolated data.

| Workload | Server behavior |
| --- | --- |
| Reconstruction | Runs one inference at a time. The pending-job limit defaults to 8 (`XR3D_MAX_PENDING_JOBS`). |
| Server-side FDM slicing | Runs one PrusaSlicer process at a time. Other slicing requests wait for it. |
| FEM | Runs one solve at a time. Additional solves receive HTTP `429`. |
| Resin and SLM previews | Share one slot. Additional preview requests receive HTTP `429`. |

Keep `XR3D_DATA_DIR` persistent to retain SQLite job records and files. Waiting uploads expire after 900 seconds by default (`XR3D_UPLOAD_TTL_SECONDS`, minimum 60). Expiry releases the slot and removes partial input files. Restart recovery makes interrupted work eligible for an explicit retry or supported Meshy task resumption. Stop the API before using `python -m backend.maintenance` for offline backups or retention. [Release operations](../docs/release-readiness.md)

For Docker, build `docker build -f backend/Dockerfile -t xr3d .` from the repository root, then run with a private environment file and a persistent `/data` volume. The image includes the API, print engine, FEM and layer-preview dependencies. Provide a PrusaSlicer executable and profile separately for FDM slicing, or an external GPU runtime and weights for local inference. [Docker setup](../README.md#docker)

## Verification

```bat
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
```

On Linux, run:

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest backend/tests -q -p no:cacheprovider
```

Tests cover the Android JSON contract, auth, invalid images, durable jobs, cancellation, conversion, real subprocess transport, and provider failure. Fixture geometry verifies transport; it does not measure AI output quality. Live hosted inference, local CUDA inference, and physical printer operation require their respective configured environments.
