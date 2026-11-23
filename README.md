# XR3D Studio

XR3D is a mobile-first Android app for capturing, inspecting, and preparing 3D models for printing. Import an existing model or reconstruct one from photos, check its fit in the camera view, then slice and send it to a supported printer. An optional private backend adds AI runtimes, printer fallbacks, server-side slicing, model checks, and structural analysis.

**Version 1.1.0** (build 10) runs on Android 10 or later. Lite includes ads and Pro is ad-free. The editions install under separate application IDs.

## Features

| Area | What you can do |
| --- | --- |
| Capture and scan guidance | Take photos with CameraX or import them from the gallery. In multi-view mode, select a target angle, see completed and missing views, and label older or imported photos. Angle assignments stay with their photos when you reopen a project. |
| Image-to-3D | Generate from one photo with Meshy Single Image or 2–4 views with Meshy Multi Image. Use a personal Meshy key directly on Android, or use the backend for a shared Meshy key, hosted or local TRELLIS.2, configured Hunyuan3D, or a compatible Custom REST service. The offline mock engine generates demo models. |
| Model workspace | Browse and reopen projects, import OBJ, binary or ASCII STL, ASCII PLY, and supported uncompressed GLB/glTF geometry. Inspect meshes at saved dimensions with camera presets, shading modes, a grid, and a bounding box. |
| Geometry and export | Inspect mesh health and printability, apply basic repair, simplify or smooth a mesh, calibrate dimensions and units, and export or share binary or ASCII STL. |
| Phone AR | Place a model on a tracked table or floor at its saved scale on an ARCore-compatible phone. Pan in 10 mm steps, rotate in 30° steps, tilt in 15° steps, reset placement, and show an adjustable clearance envelope. |
| FDM slicing | Slice offline on Android with the bundled OrcaPhone core for the FLASHFORGE Adventurer 5M series with its stock 0.4 mm nozzle. Advanced Slicer shows the toolpath and print estimates. A calibrated PrusaSlicer backend covers other supported FDM workflows. |
| Printer Hub | Scan the LAN or add a printer manually. Connect directly to FLASHFORGE Adventurer 5M/5M Pro, OctoPrint, Moonraker, and PrusaLink. Use the private server for eligible connection fallbacks, Duet, and Bambu LAN. Upload compatible files, confirm a print start, and use the status and job controls supported by the selected printer. |
| Flashforge Print Monitor | Follow reported print phase, layer progress, elapsed and remaining time, nozzle and bed temperatures, and up to 30 minutes of temperature history. The monitor also shows a job thumbnail when the firmware supplies one. |
| Backend services | Run authenticated reconstruction jobs with status, cancellation, and recovery. The server validates model downloads and supports GLB, OBJ, STL, and ASCII PLY output. It also provides server-side FDM slicing, LAN discovery, advanced STL checks, and printer fallbacks. The local XR3D Studio MCP service exposes printer discovery, STL inspection, and printer status. |
| Structural analysis | Submit a closed STL or STEP solid to the backend's Strecs3D-based Gmsh and CalculiX pipeline and download stress, strain, and displacement as VTU. Android's **FEM Demo** provides illustrative results in mock mode. |

### Which setup do I need?

| Workflow | Setup |
| --- | --- |
| Import, edit, share, or preview a model in AR | Android app. AR also requires a supported phone, Google Play Services for AR, and camera permission. |
| Meshy with **My Meshy key** | Android app, internet, a personal Meshy API key, and credits. |
| Meshy with **Server key**, TRELLIS.2, Hunyuan3D, or Custom REST | Private server with the selected provider configured. Hosted providers require internet and credentials. Local TRELLIS.2 requires its own CUDA environment and weights. |
| Offline Flashforge slicing and direct LAN printing | Android app and the intended printer on the same LAN. On-device slicing targets the Adventurer 5M series with its stock 0.4 mm nozzle. |
| Direct OctoPrint, Moonraker, or PrusaLink | Android app and the reachable printer or printer host. Use a suitable pre-sliced file or set up server slicing. |
| Printer fallback, Duet, Bambu LAN, or MCP | Private server. Install the XR3D Print Engine for discovery, model checks, Duet, and its supported fallbacks. Bambu LAN also requires a trusted printer certificate. |
| Server-side slicing or FEM | Private server with the relevant optional runtime installed. |

## Install the Android app

Download it from android play store:
## 🖨️ [XR3D: 3D Printing Any Images](https://play.google.com/store/apps/details?id=com.feaxr.xr3d)
## Use the phone workflows

### Capture and reconstruct with Meshy

1. In **Settings**, choose **Meshy Single Image** for one photo or **Meshy Multi Image** for 2–4 photos of the same object.
2. Select **My Meshy key** and enter a personal API key, or select **Server key** after configuring the backend with `MESHY_API_KEY`.
3. In multi-view capture, open **Scan angles**, choose the angle you plan to shoot, then take the photo. Tap a gallery or older photo's thumbnail to set its angle manually. Use a front view first for Meshy.
4. Tap **Reconstruct**, choose the provider settings, and generate the model. Open the result, inspect its geometry, and calibrate a known dimension before printing.

A personal Meshy key is stored in Android Keystore-backed preferences. Paid generation requires internet and credits. Stopping tracking can leave the provider task running, so check task history before retrying an uncertain submission. [Meshy setup, formats, and recovery](docs/meshy.md)

### Preview a part in AR

Open a saved model and tap **View in AR**. Complete the AR setup, allow camera access, and move the phone until it finds a table or floor. Tap that surface to place the model, then use **Pan**, **Tilt**, **Rotate**, or **Reset**. The AR preview supports meshes up to 400,000 triangles.

Turn on **Fit guides** to see cyan part bounds and an amber clearance envelope. Tap **Edit** beside the clearance value to set the margin from 0 to 250 mm. The margin extends around the sides and above the part. The envelope updates when you tilt the part and provides a visual estimate of fit.

### Slice, print, and monitor

1. Open **Printer Hub** from **Connect Printer** and use **Scan LAN** or add the printer manually. Allow local network access if Android asks. Verify that the profile matches the printer, nozzle, material, and build volume.
2. In the viewer, inspect and calibrate the model. Use **Advanced Slicer** for supported FDM profiles, or export STL and slice it in your printer's slicer.
3. Review the toolpath. Choose **Send to Printer** or upload an existing file through **Print G-code** or **Print sliced 3MF**, as appropriate. Verify the destination and confirm the start.
4. For Flashforge, open the printer's **Print Monitor** to follow progress, temperatures, and the thumbnail when supplied.

| Printer | Connection and file setup |
| --- | --- |
| FLASHFORGE Adventurer 5M / 5M Pro | Enable **LAN Only** and enter the IPv4 address, serial number, and LAN check code. The direct connection and optional server fallback use TCP 8898. Print plain `.gcode` generated for the intended machine. |
| OctoPrint, Moonraker/Klipper, PrusaLink | Connect to the local host with its credentials. The app prefers the direct route. The XR3D Print Engine can provide a fallback using a private IPv4 target. |
| Duet | Add it manually in Printer Hub with the LAN address and board password if configured. The XR3D server runs the adapter. |
| Bambu LAN | Enable LAN Only and any firmware-required Developer Mode. Configure the private server with the verified printer certificate. Upload an externally sliced, single-plate, single-filament `.gcode.3mf` for the intended model and external spool. |

Use **Express Print** for a supported saved model and printer after confirming the loaded material. Use **Advanced Slicer** when you want to inspect the toolpath first. If a start request times out, check the printer before trying again. [Printer setup, monitoring, and certificate pairing](docs/printer-adapters.md)

## Install the private backend

Use Python **3.12** with `venv` support, the version used by the backend image. Run these commands from the project root. The examples preserve an existing `.env`.

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
.\.venv\Scripts\python.exe -m backend.install_print_engine
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m backend.serve
```

### Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock.txt
.venv/bin/python -m backend.install_print_engine
test -e .env || cp .env.example .env
.venv/bin/python -m backend.serve
```

The launcher generates `XR3D_API_TOKEN` in `.env` if needed. Keep that file private. In Android **Settings**, set **XR3D server access token** to this token and **XR3D server URL** to the reconstruction endpoint below. Provider keys stay separate from the XR3D access token.

| Client | XR3D server URL |
| --- | --- |
| Android emulator on the server computer | `http://10.0.2.2:8000/api/v1/reconstruct` |
| Physical phone on the same trusted LAN | `http://SERVER_LAN_IP:8000/api/v1/reconstruct`. Start with `--host 0.0.0.0` and allow the chosen port through the local firewall. |
| Remote client | `https://YOUR_HOST/api/v1/reconstruct` behind a TLS reverse proxy. |

Use `/health` for basic liveness and `/api/v1/docs` for the interactive API. The authenticated `/ready` endpoint reports inference and slicing configuration. Run one backend worker for one trusted owner and keep `XR3D_DATA_DIR` persistent. [Backend setup, operations, and recovery](backend/README.md)

### Docker

Copy `.env.example` to `.env` if needed and set a private `XR3D_API_TOKEN` before starting the container. The container runs Uvicorn directly. This example publishes the server on the host's loopback interface. For a trusted LAN, publish on the host's LAN address and restrict access to that network.

```bash
docker build -f backend/Dockerfile -t xr3d .
docker run --rm --env-file .env -e XR3D_DATA_DIR=/data -p 127.0.0.1:8000:8000 --mount type=volume,source=xr3d-data,target=/data xr3d
```

The image includes the API and XR3D Print Engine. Add the optional FEM or PrusaSlicer dependencies to the runtime on which you want to use them. Local AI inference also needs its own model runtime, CUDA setup, and weights.

### Optional backend capabilities

- **AI providers** — Set `MESHY_API_KEY` for shared Meshy access or `FAL_KEY` for hosted TRELLIS.2. For local TRELLIS.2, install the upstream GPU runtime and set `XR3D_LOCAL_COMMAND` to the worker command as a JSON argument list. Hunyuan3D requires a compatible local worker or a configured fal endpoint. [Provider configuration and worker contract](backend/README.md#choose-an-inference-runtime)
- **Printer fallback, STL checks, and MCP** — The installer creates a separate `.venv-print` for the Kiln-based XR3D Print Engine. Check it at `GET /api/v1/print-engine`. With the backend running, configure a local MCP client to launch the backend's Python with `-m backend.studio_mcp` from the project root. This exposes `discover_printers`, `inspect_stl`, and `printer_status`. [Print Engine and MCP setup](backend/README.md#server-model-checks-and-mcp)
- **Server-side FDM slicing** — Install PrusaSlicer 2.9.2 or later, export the intended printer's calibrated `.ini` profile, and set `XR3D_SLICER_EXECUTABLE` and `XR3D_SLICER_PROFILE` in `.env`. Use `prusa-slicer-console.exe` on Windows or `prusa-slicer` on Linux. [Server slicing setup](backend/README.md#optional-real-fdm-slicing)

### Enable Strecs3D FEM

On Windows, install the CalculiX solver and set `XR3D_CCX_EXECUTABLE` in `.env` to its executable path. The Windows verification used `ccx_i4_static.exe`. [CalculiX downloads](https://www.dhondt.de/)

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.fem.txt
```

On Debian-based Linux, install the solver and the system GLU library, then install Gmsh into the backend virtual environment. The backend finds `ccx` on `PATH` when `XR3D_CCX_EXECUTABLE` is unset.

```bash
sudo apt install calculix-ccx libglu1-mesa
.venv/bin/python -m pip install -r backend/requirements.fem.txt
```

Restart the backend and check the authenticated `GET /api/v1/fem`. Submit the solid and load settings to `POST /api/v1/fem/solve` for the VTU download. [Request format and cantilever example](backend/README.md#strecs3d-fem)

## Scope and verification

- **Android and AR** — The viewer renders geometry shading. AR placement, controls, and fit guides were tested on an LG V35. The emulator verified that scan angles survive an app restart and that saved photos reach the reconstruction screen.
- **Geometry and AI** — Inspect reconstructed geometry and calibrate its scale before printing. The current importer supports uncompressed geometry with compatible glTF data. Tripo, Pixal, compressed glTF geometry, and machine-specific resin and metal slicing are outside the available workflows. Live Meshy generation and local CUDA inference still need acceptance testing.
- **Printing** — An Adventurer 5M with a stock 0.4 mm nozzle completed a 10-layer PLA test using G-code sliced offline on Android and sent through the backend bridge. Direct LAN paths have protocol coverage. Physical direct-route printing, 5M Pro, Bambu LAN, and Duet still need hardware print validation.
- **Structural analysis** — The backend solves static loads on one solid with isotropic linear elastic properties. STEP and STL benchmarks and an HTTP solve of the bundled Strecs3D cantilever ran with real Gmsh and CalculiX on Windows. Linux FEM still needs an end-to-end solve. Directional printed material properties, stress-based region segmentation, variable-density infill, and Strecs3D's slicer-specific 3MF export are outside the current FEM integration.

### Run the checks

Run these Gradle checks from the project root. On Linux or macOS, use `./gradlew` as the wrapper.

```powershell
.\gradlew.bat :app:testLiteDebugUnitTest :app:testProDebugUnitTest :app:lintLiteRelease
```

Install `pytest` in the backend virtual environment, then run `python -m pytest backend/tests -q -p no:cacheprovider` with that environment's Python. Configure Gmsh and CalculiX to include the native FEM tests. [Verification history](docs/verification.md) · [Release acceptance checklist](docs/release-readiness.md)

### Troubleshooting

- **Phone cannot reach the backend** — Check the URL, token, server bind address, and firewall. Use the server's LAN IP on a physical phone and `10.0.2.2` on the local Android emulator.
- **Meshy fails** — Check the key source, credits, internet access, and image count. If submission status is uncertain, check the provider's task history before retrying.
- **AR cannot start** — Check ARCore compatibility, Google Play Services for AR, and camera permission. Move slowly over a well-lit table or floor to find a placement surface.
- **Slicing or printing fails** — Confirm the mesh is closed and fits the print volume, the selected profile matches the loaded material and hardware, and the printer is reachable in its supported LAN mode.
- **FEM solve is unavailable** — Check the backend's active Python environment, Gmsh native dependencies, and CalculiX path. If the model or a region is rejected, verify it is one closed solid and the fixed and load regions cover actual exterior faces.

## Project components and notices

- [Android app](app/) and [architecture](docs/architecture.md)
- [XR3D backend](backend/README.md) and [API documentation notes](backend/README.md#api-and-deployment)
- [Bundled OrcaPhone slicer core and license](external/orcaphone/README.md)
- [Kiln-based XR3D Print Engine source and notices](backend/PRINT-ENGINE-NOTICE.md)
- [Strecs3D license](backend/STRECS3D-LICENSE)
