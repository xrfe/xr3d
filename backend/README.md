# XR3D inference server

The Android app sends a **real source image** to this API, runs local or hosted inference, downloads a validated model, and stores it in the project. It never substitutes a procedural sample when inference fails.

## Start on Windows (from the project root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m backend.serve
```

The launcher generates a random `XR3D_API_TOKEN` in `.env` if it is empty. Enter it in the existing **Settings → XR3D server access token** field. Do not enter a fal credential in the phone: the phone uses the private server token, while hosted credentials stay in `.env` on the server.

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

The app's existing Tripo/Pixal entries remain in the layout for compatibility, but the bundled server reports them as unconfigured. Their original adapters were fictitious. Adding a model means adding a verified server adapter, not changing the app's `/jobs` contract. Custom REST can target another compatible XR3D server.

## Geometry and export

The API validates real GLB geometry, enforces the requested triangle budget, preserves textures in GLB when enabled, and converts to OBJ, STL, or ASCII PLY. glTF uses metres/Y-up; the Android reader and non-GLB conversion consistently convert to millimetres/Z-up. Image generation does not recover reliable physical dimensions: calibrate dimensions in the app before printing.

Android supports uncompressed GLB scene transforms, triangle lists/strips/fans, OBJ, STL, and ASCII PLY. Draco/meshopt compression, sparse glTF accessors, external texture preview, USDZ and STEP are not implemented. Unsupported geometry is rejected. The current viewer displays geometry shading; it is not a full PBR renderer.

## Optional real FDM slicing

Install PrusaSlicer 2.9.2+ and set `XR3D_SLICER_EXECUTABLE` to its CLI executable. Windows requires `prusa-slicer-console.exe`. Set `XR3D_SLICER_PROFILE` to the exported, calibrated `.ini` configuration for the intended printer. Missing profiles fail explicitly. The `/api/v1/slicer/slice` endpoint validates the actual STL and printer volume, then invokes PrusaSlicer with the profile and selected settings. Triangle infill and Normal/Organic support styles are explicit; unsupported Tree settings fail instead of being substituted. No bounding-box toolpaths are generated.

Resin and SLM require machine-specific slicers and are unavailable in this build. Verify printer profiles and generated toolpaths on the intended printer; defaults cannot replace a calibrated machine profile. See <https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface>.

## API and deployment

Interactive docs: `/api/v1/docs`; health: `/health`. All model, provider, and slicer endpoints require `Authorization: Bearer XR3D_API_TOKEN`. This is a **single-owner private studio server**, not a multi-tenant service. Use separate instances/tokens per owner; per-user accounts, quotas, billing and tenant isolation are not implemented.

Authenticated `/ready` returns inference/slicer configuration status, not live provider or GPU validation. The pending-job queue defaults to 8 (`XR3D_MAX_PENDING_JOBS`); cancel abandoned jobs when full. Offline backups and dry-run retention are provided by `python -m backend.maintenance`; stop the API first. See [release operations and acceptance](../docs/release-readiness.md).

The private server also bridges Bambu MQTT/FTPS and FLASHFORGE Adventurer 5M HTTP under authenticated `/api/v1/printers/vendor` routes. These adapters work independently of AI inference configuration. See [printer adapter setup and limitations](../docs/printer-adapters.md), including trusted Bambu certificate installation and the separate printer LAN access/check code.

Run exactly **one Uvicorn worker**. SQLite records survive restarts; interrupted inference jobs become failed/retryable. The GPU queue runs one inference at a time. Keep the data volume persistent. Jobs are not automatically retried after restart to avoid duplicate hosted charges. Configure storage retention/backups before a public deployment.

Docker (hosted inference): `docker build -f backend/Dockerfile -t xr3d .`, then run with a private environment file and a persistent `/data` volume. The slim image contains the API, not CUDA or model weights.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
```

Tests cover the Android JSON contract, auth, invalid images, durable jobs, cancellation, conversion, real subprocess transport, and provider failure. Fixture geometry verifies transport; it does not measure AI output quality. Live hosted inference, local CUDA inference, and physical printer operation require their respective configured environments.
