@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Install Python 3.12 from python.org, then run Install XR3D Server again.
        pause
        popd
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m backend.install %*
set "XR3D_INSTALL_RESULT=%ERRORLEVEL%"
pause
popd
exit /b %XR3D_INSTALL_RESULT%
