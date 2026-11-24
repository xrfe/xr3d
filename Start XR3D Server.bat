@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Run Install XR3D Server first.
    pause
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -m backend.serve --host 0.0.0.0 %*
set "XR3D_START_RESULT=%ERRORLEVEL%"
if not "%XR3D_START_RESULT%" == "0" pause
popd
exit /b %XR3D_START_RESULT%
