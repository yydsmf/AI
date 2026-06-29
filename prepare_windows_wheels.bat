@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_CMD="
set "FAIL_REASON="
set "BUILD_ROOT=%LOCALAPPDATA%\GPTLocalToolboxBuild"
set "WHEELHOUSE_DIR=%CD%\wheelhouse"
set "PIP_CACHE_DIR=%BUILD_ROOT%\pip-cache"
set "TMP=%BUILD_ROOT%\tmp"
set "TEMP=%BUILD_ROOT%\tmp"
set "PYTHON_VERSION=3.11.9"
if not defined PYTHON_INSTALLER_URL set "PYTHON_INSTALLER_URL=https://mirrors.tuna.tsinghua.edu.cn/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if not defined PIP_DEFAULT_TIMEOUT set "PIP_DEFAULT_TIMEOUT=120"
if not defined PIP_RETRIES set "PIP_RETRIES=10"

echo Preparing Windows Python wheels...
echo Wheelhouse: %WHEELHOUSE_DIR%
echo Pip index: %PIP_INDEX_URL%
echo.

if not defined LOCALAPPDATA (
    echo LOCALAPPDATA was not found. Please run this script from a normal Windows user account.
    goto fail
)

if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"
if errorlevel 1 goto fail
if not exist "%WHEELHOUSE_DIR%" mkdir "%WHEELHOUSE_DIR%"
if errorlevel 1 goto fail
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if errorlevel 1 goto fail
if not exist "%TMP%" mkdir "%TMP%"
if errorlevel 1 goto fail

call :find_python

if not defined PYTHON_CMD (
    echo Could not find Python on this Windows computer.
    echo Trying to install Windows x64 Python %PYTHON_VERSION% from China mirror:
    echo %PYTHON_INSTALLER_URL%
    echo.
    call :install_python_from_cn_mirror
    if errorlevel 1 (
        echo.
        echo Automatic Python installation failed.
        echo If Python is already installed but not on PATH, run this before this script:
        echo set PYTHON_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe
        echo prepare_windows_wheels.bat
        set "FAIL_REASON=python"
        goto fail
    )
    call :find_python
    if not defined PYTHON_CMD (
        echo.
        echo Python was installed, but this script still cannot find python.exe.
        echo Please reopen Command Prompt and run prepare_windows_wheels.bat again.
        set "FAIL_REASON=python"
        goto fail
    )
)

echo Using Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

%PYTHON_CMD% -m pip download --prefer-binary --dest "%WHEELHOUSE_DIR%" --cache-dir "%PIP_CACHE_DIR%" -r requirements-windows.txt
if errorlevel 1 goto fail

echo.
echo Wheel download finished. You can now run build_windows_exe.bat.
echo To force offline installation from wheelhouse, run:
echo set USE_LOCAL_WHEELS_ONLY=1
echo build_windows_exe.bat
echo.
pause
exit /b 0

:find_python
set "PYTHON_CMD="
if defined PYTHON_EXE (
    if exist "%PYTHON_EXE%" (
        "%PYTHON_EXE%" --version >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD="%PYTHON_EXE%""
    ) else (
        echo PYTHON_EXE was set, but the file does not exist:
        echo %PYTHON_EXE%
    )
)
if not defined PYTHON_CMD (
    py -3.11 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)
if not defined PYTHON_CMD (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    python3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python3"
)
if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe""
)
if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
)
if not defined PYTHON_CMD (
    if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON_CMD="%ProgramFiles%\Python311\python.exe""
)
if not defined PYTHON_CMD (
    if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON_CMD="%ProgramFiles%\Python312\python.exe""
)
exit /b 0

:install_python_from_cn_mirror
set "PYTHON_INSTALLER=%BUILD_ROOT%\python-%PYTHON_VERSION%-amd64.exe"
if exist "%PYTHON_INSTALLER%" del "%PYTHON_INSTALLER%"
echo Downloading Python installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_INSTALLER_URL%' -OutFile '%PYTHON_INSTALLER%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 exit /b 1
if not exist "%PYTHON_INSTALLER%" exit /b 1
echo Installing Python silently...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0 SimpleInstall=1
if errorlevel 1 exit /b 1
exit /b 0

:fail
echo.
if /I "%FAIL_REASON%"=="python" (
    echo Wheel download did not start because Python was not found.
) else (
    echo Wheel download failed. If the mirror is slow, try another mirror:
    echo set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
    echo prepare_windows_wheels.bat
)
echo.
pause
exit /b 1
