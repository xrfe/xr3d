# XR3D / AI 3D Studio

XR3D is an Android app for creating and preparing 3D models from photographs. Use a personal Meshy API key to generate models online directly from your phone, or connect the app to a private XR3D server for self-hosted or hosted inference. You can inspect the result, adjust its dimensions, export it, and prepare it for 3D printing.

## Features

- **Image to 3D:** capture or import a photo for Meshy Single Image or TRELLIS.2; Meshy Multi Image accepts 2–4 views of the same object.
- **Online or local AI:** use Meshy directly from Android, a server-managed Meshy key, hosted TRELLIS.2 through fal, or a separately installed local TRELLIS.2 GPU runtime.
- **Model library and viewer:** save projects, reopen generated models, inspect geometry, calibrate dimensions, simplify or repair meshes, and run printability checks.
- **Export and printing:** export STL for an external slicer, or use an optional server-side FDM slicer with a calibrated profile. Printer Hub supports OctoPrint, Moonraker, PrusaLink, and server-bridged Bambu LAN and FLASHFORGE Adventurer 5M/5M Pro connections.
- **Demonstrations:** procedural demo models and FEM demo results are demonstrations, not AI reconstructions or validated engineering analysis.

AI-generated geometry may need repair and dimensional adjustment before printing. The viewer uses geometry shading rather than a full textured PBR preview. A successful printability check does not guarantee a successful print.

## Which setup do I need?

| Task | XR3D server required? | Other requirements |
| --- | --- | --- |
| Meshy with **My Meshy key** | No | Internet, personal Meshy API key and credits |
| Meshy with **Server key** | Yes | Server configured with a Meshy key and internet |
| Local TRELLIS.2 | Yes | Separate compatible GPU environment, model dependencies and weights |
| Hosted TRELLIS.2 | Yes | fal account, API key, credits and internet |
| View, adjust and export a downloaded model | No | Model already available in the app |
| In-app FDM slicing | Yes | PrusaSlicer and a calibrated printer profile on the server |
| FLASHFORGE 5M or Bambu LAN via Printer Hub | Yes | Server and printer reachable on a trusted network; printer-specific setup |

**XR3D server** is the optional Python application in this repository that runs on your computer or another machine. It connects Android to configured AI runtimes, performs server-side slicing, and bridges certain printer protocols. It is separate from the Android app. The supported release model is a private, single-owner server, not a public multi-user service.

## Get the Android app

Open the project in Android Studio and build a debug version, or build on Windows with a configured JDK and Android SDK:

```powershell
.\gradlew.bat :app:testLiteDebugUnitTest :app:assembleLiteDebug
```

The debug APK is created at `app/build/outputs/apk/lite/debug/app-lite-debug.apk`. Install it on your Android device using Android Studio or your usual APK installation method. A debug APK is not a signed production release.

## Generate online with Meshy — no server

1. Obtain a personal API key and available API credits from [Meshy](https://www.meshy.ai/). Generation requires internet and may incur charges.
2. Open XR3D **Settings**. Choose **Meshy Single Image** for one photo or **Meshy Multi Image** for 2–4 views.
3. Choose **My Meshy key** and enter your key in the separate Meshy key field. A server URL and server token are not needed for this workflow.
4. Capture or import your images. For multiple views, use photos of the same object and put the front view first. Use clear, well-lit images with the object visible.
5. Start reconstruction and wait for the result to download into the project. Open it in the viewer, inspect it, and calibrate its dimensions. Export STL when you are ready to use a slicer.

New personal-key jobs communicate directly with Meshy over HTTPS. The key is kept in Android Keystore-backed preferences and excluded from backup; clear the key field to remove it. Direct generation downloads a GLB; STL export is available in the viewer. The exact shape and physical dimensions are not guaranteed by a photograph.

Stopping a job stops XR3D tracking; Meshy processing and charges may continue. If submission has an uncertain outcome, check your Meshy task history before retrying, since a retry can create another paid job. See [Meshy setup and limitations](docs/meshy.md) for recovery, quality settings, and supported formats.

## Set up the private XR3D server

The following example starts the server on Windows from the project root. Python and access to the package dependencies are required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m backend.serve
```

The launcher generates an `XR3D_API_TOKEN` in `.env` if one is not set. Keep `.env` private and enter this token in Android **Settings → XR3D server access token**. The server token is different from your Meshy or fal API key.

Set the server reconstruction endpoint in Android Settings:

- **Android emulator on the server computer:** `http://10.0.2.2:8000/api/v1/reconstruct`.
- **Physical phone on a trusted LAN:** `http://YOUR_COMPUTER_LAN_IP:8000/api/v1/reconstruct`. Start the server with `python -m backend.serve --host 0.0.0.0` using the virtual environment Python, and allow port 8000 through the computer's firewall if needed. The phone must be able to reach that address.
- **Remote server:** use `https://YOUR_HOST/api/v1/reconstruct` behind a TLS reverse proxy. Public HTTP inference URLs are rejected by Android.

Opening `http://SERVER_ADDRESS:8000/health` checks basic server availability. API documentation is at `/api/v1/docs`. The authenticated `/ready` endpoint reports configuration, but does not prove that a live AI provider or GPU is working. Run one server worker, keep its data directory persistent, and use it only as a private single-owner service. See [server setup and operations](backend/README.md) and [release operations](docs/release-readiness.md).

### Meshy using the server's key

This option is useful if the server owner supplies the key instead of entering a personal key on the phone.

1. Set `MESHY_API_KEY` in the server's `.env`, then start or restart the server. `MESHY_MODEL` can be configured there as well.
2. Configure the server endpoint and XR3D server token in Android Settings.
3. Select **Meshy Single Image** or **Meshy Multi Image**, then select **Server key**.
4. Capture/import the required images and start reconstruction. The server submits the request to Meshy, downloads and validates the result, and sends it to the app.

Meshy credits and internet access are still required. The server key and XR3D access token serve different purposes; do not enter one in place of the other.

### Hosted TRELLIS.2 with fal

1. Create a fal account with access and credits for TRELLIS.2. Set `FAL_KEY` in the server's `.env`; the default model is `fal-ai/trellis-2`.
2. Start or restart the server, configure its endpoint and token in Android, and select **TRELLIS.2** in Settings.
3. Choose **Single View**, capture or import one image, and start reconstruction. The server sends it to fal and retrieves the generated model.

The fal key stays on the server. Hosted jobs require internet and may incur provider charges. See [fal's TRELLIS.2 API](https://fal.ai/models/fal-ai/trellis-2/api).

### Local TRELLIS.2 on your own computer

Local inference runs on the **server computer**, not on the Android phone. Install the [official TRELLIS.2 runtime](https://github.com/microsoft/TRELLIS.2), dependencies, CUDA environment, and model weights separately. A supported NVIDIA GPU is normally needed; Linux or WSL is the usual environment. Requirements depend on the upstream model and chosen setup.

In the server's `.env`, configure the upstream environment's Python and XR3D worker with absolute paths valid in the environment where the server runs. This example uses Linux/WSL paths:

```dotenv
XR3D_LOCAL_COMMAND=["/absolute/path/to/trellis-env/bin/python", "/absolute/path/to/xr3d/backend/workers/trellis2.py"]
XR3D_LOCAL_PROVIDER=TRELLIS_2
```

Start the XR3D server where it can access that runtime and the same filesystem as the worker. Configure the server endpoint and token on Android, select **TRELLIS.2**, and use **Single View** with one image. The bundled adapter does not support multi-view TRELLIS.2 input or text prompts. Worker logs are kept under `backend-data/JOB_ID/worker.log` by default. Local GPU execution still needs validation in your own CUDA environment. See [backend setup](backend/README.md) for the worker contract and configuration.

### Other AI providers

Hunyuan3D requires a separately configured compatible local worker or fal endpoint; no Hunyuan worker is bundled. Custom REST requires a compatible XR3D server. Tripo and Pixal entries are present in the interface, but the bundled server does not provide configured adapters for them. See [backend setup](backend/README.md) before choosing these options.

## Prepare a model for 3D printing

1. Open the downloaded model in the viewer and inspect its shape. Use the available repair and simplification tools if necessary.
2. Set or calibrate its dimensions. Image-to-3D output does not determine reliable real-world size.
3. Export STL and open it in a slicer with the exact printer, nozzle, filament, and firmware profile. Set orientation, layer height, supports, and other settings as needed, then inspect the generated toolpaths.
4. Send the sliced file using your slicer or a supported Printer Hub connection. You can also transfer the file using your printer's normal workflow.

Alternatively, XR3D can request **server-side FDM slicing**: install PrusaSlicer 2.9.2 or newer on the server and set `XR3D_SLICER_EXECUTABLE` and `XR3D_SLICER_PROFILE` in `.env`. On Windows use `prusa-slicer-console.exe`. The `.ini` must be a calibrated profile for the actual printer and filament; a generic profile is not enough. Resin and SLM slicing are unavailable. See [server slicing setup](backend/README.md#optional-real-fdm-slicing).

## Connect a printer

Printer Hub includes connections for OctoPrint, Moonraker and PrusaLink, as well as Bambu LAN and FLASHFORGE 5M through the private XR3D server. Compatibility depends on the printer, firmware, and service configuration; the brand name alone does not guarantee compatibility. Automatic discovery is not included for the Bambu and FLASHFORGE adapters.

### FLASHFORGE Adventurer 5M / 5M Pro

1. Connect the printer to a trusted network, enable **LAN Only**, and find its IP address, serial number and LAN check/access code.
2. Run the XR3D server on a computer that can reach the printer, and configure its URL and server token in Android Settings. The FLASHFORGE bridge uses TCP port 8898.
3. In **Printer Hub → + → FLASHFORGE 5M**, enter the printer's IP, serial and check code, save the profile, and connect. Check whether actual status and temperatures appear.
4. Slice a small model for your exact printer and filament using a compatible slicer. In Printer Controls choose **Print G-code** and select the resulting `.gcode` file. The user-initiated action uploads the file and then requests a print start.

The adapter has protocol tests, but has **not been verified on a physical Adventurer 5M**. Verify the connection and supervise a small known-good print before relying on it. XR3D currently connects through the server, not directly from Android to this printer. See [FLASHFORGE setup and troubleshooting](docs/printer-adapters.md#set-up-your-adventurer-5m).

### Bambu LAN

Enable LAN Only and any firmware-required Developer Mode, then configure the printer's IP, serial and LAN access code. The server must trust the verified printer certificate; follow the pairing steps in [Bambu LAN setup](docs/printer-adapters.md#set-up-bambu-lan). Slice externally using the correct printer profile and upload a **single-plate, single-filament `.gcode.3mf`** via Printer Hub. Generic in-app PrusaSlicer output is not used for Bambu. The adapter has not been verified on physical Bambu hardware, and firmware/model support varies.

## Troubleshooting

- **Meshy fails:** check internet, key source, API key, credits and the required image count. Check task history before retrying an uncertain submission.
- **Phone cannot reach server:** check the endpoint, token, server process, LAN address and firewall. `10.0.2.2` is for the Android emulator, not a physical phone.
- **Local inference fails:** check GPU/CUDA compatibility, upstream installation, weights, absolute worker paths and the job's worker log. A running API alone does not mean the model is installed.
- **Slicing fails:** install PrusaSlicer and configure its executable and a calibrated profile for the exact printer. A model file is not already a print-ready toolpath.
- **Printer does not connect or start:** check network reachability, printer mode, credentials, firmware and the supported file type. If a start request times out, inspect the printer before retrying: it may have received the command.
- **Model looks wrong or is not printable:** inspect, repair, calibrate, and review it in a slicer. Generated models can contain defects, and some compressed or unsupported GLB geometry is rejected.

## Current limitations and verification

Live Meshy generation, local CUDA inference, and physical FLASHFORGE/Bambu printing have not been verified in this development session. Validate each with your own accounts, hardware and profiles. Direct Meshy generation has automated tests; those do not establish model quality or successful real-world printing. Unsupported inference and slicing configurations report errors rather than silently producing sample geometry.

Further details: [Meshy](docs/meshy.md), [printer adapters](docs/printer-adapters.md), [backend](backend/README.md), [implementation status](docs/implementation-status.md), and [release readiness](docs/release-readiness.md).
