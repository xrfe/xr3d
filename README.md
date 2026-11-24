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
| Phone AR | Place a model or a solved FEM heatmap on a tracked table or floor at its saved scale on an ARCore-compatible phone. Pan, tilt, rotate, reset placement, and show an adjustable clearance envelope. |
| FDM slicing | Slice offline on Android with the bundled OrcaPhone core for the FLASHFORGE Adventurer 5M series with its stock 0.4 mm nozzle. Advanced Slicer shows the toolpath and print estimates. A calibrated PrusaSlicer backend covers other supported FDM workflows. |
| Printer Hub | Scan the LAN or add a printer manually. Connect directly to FLASHFORGE Adventurer 5M/5M Pro, OctoPrint, Moonraker, and PrusaLink. Use the private server for eligible connection fallbacks, Duet, and Bambu LAN. Upload compatible files, confirm a print start, and use the status and job controls supported by the selected printer. |
| Flashforge Print Monitor | Follow reported print phase, layer progress, elapsed and remaining time, nozzle and bed temperatures, and up to 30 minutes of temperature history. The monitor also shows a job thumbnail when the firmware supplies one. |
| Backend services | Run authenticated reconstruction jobs with status, cancellation, and recovery. The server validates model downloads and supports GLB, OBJ, STL, and ASCII PLY output. It also provides server-side FDM slicing, LAN discovery, advanced STL checks, and printer fallbacks. The local XR3D Studio MCP service exposes printer discovery, STL inspection, and printer status. |
| Structural analysis | Run a static solid solve from Android through the backend's Strecs3D-based Gmsh and CalculiX pipeline. View stress and displacement on the model, or export the full VTU. The API also accepts STEP. Mock mode provides a labelled demonstration. |

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

### Prepare your first filament print

Open **Home → First Print** to load a small built-in cube, import a model, or make one from photos. Select a printer and confirm the loaded filament, then slice and use **View layers** to inspect the toolpath before starting the print. **Practice without a printer** uses the phone's slicer and keeps the result in preview mode. For server-assisted workflows, use **Find XR3D Server** in Settings, then tap the discovered server and enter its setup code.

### Capture and reconstruct with Meshy

1. In **Settings**, choose **Meshy Single Image** for one photo or **Meshy Multi Image** for 2–4 photos of the same object.
2. Select **My Meshy key** and enter a personal API key, or select **Server key** after configuring the backend with `MESHY_API_KEY`.
3. In multi-view capture, open **Scan angles**, choose the angle you plan to shoot, then take the photo. Tap a gallery or older photo's thumbnail to set its angle manually. Use a front view first for Meshy.
4. Tap **Reconstruct**, choose the provider settings, and generate the model. Open the result, inspect its geometry, and calibrate a known dimension before printing.

A personal Meshy key is stored in Android Keystore-backed preferences. Paid generation requires internet and credits. Stopping tracking can leave the provider task running, so check task history before retrying an uncertain submission. [Meshy setup, formats, and recovery](docs/meshy.md)

### Preview a part in AR

Open a saved model and tap **View in AR**. Complete the AR setup, allow camera access, and move the phone until it finds a table or floor. Tap that surface to place the model, then use **Pan**, **Tilt**, **Rotate**, or **Reset**. The AR preview supports meshes up to 400,000 triangles.

After a backend FEM solve, tap **View result in AR** below the result viewport. Tap a tracked surface beside the physical object to compare it with the solved model at its saved scale. Switch between **Stress** (MPa) and **Displacement** (mm) while it stays placed. Use the placement controls to align the view manually. The colors represent the simulated load case, with displacement shown as a magnitude on the original shape.

Turn on **Fit guides** to see cyan part bounds and an amber clearance envelope. Tap **Edit** beside the clearance value to set the margin from 0 to 250 mm. The margin extends around the sides and above the part. The envelope updates when you tilt the part and provides a visual estimate of fit.

### Inspect metal SLM layers

Choose **SLM Metal** in Settings or the Home technology menu, then open **Viewer → Prepare Print**. You can also open the metal workspace from the FDM slicer. **Generate preview** sends the model to the XR3D backend to generate layer contours and hatching. Inspect and measure layers, save a PNG snapshot, or save a ZIP for offline viewing. [Backend setup for PySLM](backend/README.md#optional-slm-preparation-with-pyslm)

### Inspect resin exposure layers

Choose **SLA Resin** and open **Viewer → Prepare Print**, or open the resin workspace from the FDM slicer. **Generate preview** checks the oriented model against the build volume and generates exposure masks on the backend. Scrub or play through layers to inspect exposed area and estimated cured volume. Use **Save ZIP** and **Open ZIP** for offline review. [Backend setup for resin previews](backend/README.md#resin-layer-previews)

### Practice with the offline print simulator

The resin workspace offers Formlabs Form 4 and ELEGOO Saturn 4 Ultra 12K. The metal workspace offers EOS M 290 and Nikon SLM 280 2.0. Queue a simulated job from the offline sample, an imported model, or an XR3D preview. All profiles check the nominal build envelope. The simulator runs locally and supports layer progress, pause, resume, and cancellation. Imported model counts are estimates. A loaded XR3D preview supplies its actual layer count and views. Both editions include these features. For real jobs, prepare printer-specific files in the manufacturer's workflow. [Formlabs dimensions](https://formlabs.com/uk/support/What-is-the-largest-part-I-can-print-on-a-Formlabs-printer/) · [ELEGOO specifications](https://global.elegoo.com/products/saturn-4-ultra-12k-10inch-monochrome-lcd-resin-3d-printer) · [EOS M 290 specifications](https://www.eos.info/metal-solutions/metal-printers/data-sheets/sds-eos-m-290) · [Nikon SLM 280 specifications](https://nikon-slm-solutions.com/wp-content/uploads/2024/04/Nikon-SLM-System-Brochure-SLM280-2.pdf)

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

Use Python **3.12** with `venv` support. The installer creates `.venv` if needed and installs the API, print engine, SLM and resin preview workers, and Python FEM libraries into that one environment. It preserves your `.env` and projects. Kiln and PySLM come from pinned upstream releases. [Upstream sources and fork setup](backend/README.md#upstream-dependencies)

### Windows

1. Double-click **Install XR3D Server.bat**. On 64-bit x86 Windows, setup also installs the verified CalculiX solver if needed.
2. Double-click **Start XR3D Server.bat** and leave the window open. It shows a one-time phone setup code and the server's LAN addresses.

To create the environment yourself first, run `py -3.12 -m venv .venv` from the project folder before opening the installer.

### Linux

```bash
# Debian or Ubuntu system packages for FEM and the PySLM clipping library
sudo apt install calculix-ccx libglu1-mesa build-essential cmake
bash install-xr3d-server.sh
bash start-xr3d-server.sh
```

Use a Python 3.12 installation with `venv` and its development headers. Linux builds PySLM's clipping dependency, Pyclipr, from the published source using CMake and a C++17 compiler.

In Android **Settings → Find XR3D Server**, select the PC on the same Wi-Fi, enter the one-time code from the Start window, and tap **Connect**. If discovery is unavailable, enter the address displayed on the PC in the same dialog. A fresh app install has no preconfigured server. The code expires after 10 minutes or one successful connection. Restart the launcher to create a new code.

For manual setup, enter the endpoint below in **XR3D server URL** and the private `XR3D_API_TOKEN` from `.env` in **XR3D server access token**. AI provider keys stay on the server.

| Client | XR3D server URL |
| --- | --- |
| Android emulator on the server computer | `http://10.0.2.2:8000/api/v1/reconstruct` |
| Physical phone on the same trusted LAN | Use `http://SERVER_LAN_IP:8000/api/v1/reconstruct`. The Start launcher displays the PC's LAN IP. |
| Remote client | `https://YOUR_HOST/api/v1/reconstruct` behind a TLS reverse proxy. |

Use `/health` for basic liveness and `/api/v1/docs` for the interactive API. The authenticated `/ready` endpoint reports inference and slicing configuration. Run one backend worker for one trusted owner and keep `XR3D_DATA_DIR` persistent. [Backend setup, operations, and recovery](backend/README.md)

### Docker

Copy `.env.example` to `.env` if needed and set a private `XR3D_API_TOKEN` before starting the container. This example publishes the server on the host's loopback interface. For a trusted LAN, publish on the host's LAN address and restrict access to that network.

```bash
docker build -f backend/Dockerfile -t xr3d .
docker run --rm --env-file .env -e XR3D_DATA_DIR=/data -p 127.0.0.1:8000:8000 --mount type=volume,source=xr3d-data,target=/data xr3d
```

The image installs the API, print engine, PySLM previews, and FEM in one Python environment. Server-side FDM slicing uses an optional PrusaSlicer executable and printer profile. Local AI inference runs as a separate provider with its own model runtime, CUDA setup, and weights.

### Optional backend capabilities

- **AI providers** — Set `MESHY_API_KEY` for shared Meshy access or `FAL_KEY` for hosted TRELLIS.2. For local TRELLIS.2, install the upstream GPU runtime and set `XR3D_LOCAL_COMMAND` to the worker command as a JSON argument list. Hunyuan3D requires a compatible local worker or a configured fal endpoint. [Provider configuration and worker contract](backend/README.md#choose-an-inference-runtime)
- **Printer fallback, STL checks, and MCP** — Check the installed XR3D Print Engine at `GET /api/v1/print-engine`. With the backend running, configure a local MCP client to launch `.venv`'s Python with `-m backend.studio_mcp` from the project root. This exposes `discover_printers`, `inspect_stl`, and `printer_status`. [Print Engine and MCP setup](backend/README.md#server-model-checks-and-mcp)
- **Server-side FDM slicing** — Install PrusaSlicer 2.9.2 or later, export the intended printer's calibrated `.ini` profile, and set `XR3D_SLICER_EXECUTABLE` and `XR3D_SLICER_PROFILE` in `.env`. Use `prusa-slicer-console.exe` on Windows or `prusa-slicer` on Linux. [Server slicing setup](backend/README.md#optional-real-fdm-slicing)
- **Metal SLM preparation API** — PySLM generates layer contours, parallel/stripe/island hatching, and scan lengths from an STL. The endpoint returns a machine-neutral preview ZIP. [PySLM setup and API](backend/README.md#optional-slm-preparation-with-pyslm)

### Enable Strecs3D FEM

The installer includes Gmsh and discovers CalculiX from your installation or system `PATH`. Set `XR3D_CCX_EXECUTABLE` in `.env` to select a specific CalculiX binary. [CalculiX downloads](https://www.dhondt.de/)

Restart the backend and check the authenticated `GET /api/v1/fem`. In Android, enter the **XR3D server URL** and **XR3D server access token** in Settings and turn off mock mode. Open a saved, closed solid in the viewer and choose **FEM Analysis**. Select fixed and loaded faces, or edit their XYZ boxes in millimetres. Set the material, force and element size, then tap **Run FEM on Server**. Switch between **Stress**, **Displacement** and **Solid** to inspect the result. Tap **Export VTU** to keep a copy of the full result.

For FDM, SLM, or SLA parts with direction-dependent stiffness, choose **Transversely isotropic** and select a material preset. Confirm the build direction and use **Edit elastic constants** to enter measured values when available. The SLM and SLA layer previews can open FEM for the same model and carry over the build direction. The FEM screen lists residual stress, print warping, and thermo-mechanical coupling under **Planned analyses**. [Material presets and sources](docs/fem-material-presets.md)

The phone submits the saved mesh as an STL in millimetres. The backend checks the solid, sizes the first mesh locally around geometric features and boundary conditions, and then refines regions with higher estimated FEM error. The results card shows whether the refinement targets were met. Dense heatmaps are simplified for the phone and the VTU includes the full solver mesh. The desktop API also accepts STEP directly. [Request format and cantilever example](backend/README.md#strecs3d-fem)

## Scope and verification

Both Lite and Pro debug APKs build successfully. The Android unit suites pass 107 tests per edition, and the backend suite passes 80 tests with the native FEM runtime configured.

- **Android and AR** — The viewer renders geometry shading. AR placement, controls, and fit guides were tested on an LG V35. The emulator verified that scan angles survive an app restart and that saved photos reach the reconstruction screen.
- **Geometry and AI** — Inspect reconstructed geometry and calibrate its scale before printing. The current importer supports uncompressed geometry with compatible glTF data. Tripo, Pixal, compressed glTF geometry, and machine-specific resin and metal slicing are outside the available workflows. Live Meshy generation and local CUDA inference still need acceptance testing.
- **Printing** — An Adventurer 5M with a stock 0.4 mm nozzle completed a 10-layer PLA test using G-code sliced offline on Android and sent through the backend bridge. Direct LAN paths have protocol coverage. Physical direct-route printing, 5M Pro, Bambu LAN, and Duet still need hardware print validation.
- **Structural analysis** — The backend solves static loads on one solid with isotropic or transversely isotropic linear elastic properties. STEP and STL benchmarks and an HTTP solve of the bundled Strecs3D cantilever ran with real Gmsh and CalculiX on Windows. Linux FEM still needs an end-to-end solve. Stress-based region segmentation, variable-density infill, and Strecs3D's slicer-specific 3MF export are outside the current FEM integration.

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
