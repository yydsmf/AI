@echo off
setlocal

cd /d "%~dp0"
set "APP_NAME=GPTLocalToolbox.exe"
set "UPDATER_NAME=GPTToolboxUpdater.exe"
set "SETUP_NAME=GPTLocalToolbox_Setup.exe"
set "PYTHON_CMD="
set "ISCC_EXE="
set "BUILD_ROOT=%LOCALAPPDATA%\GPTLocalToolboxBuild"
set "VENV_DIR=%BUILD_ROOT%\venv"
set "WORK_DIR=%BUILD_ROOT%\pyinstaller-work"
set "DIST_DIR=%BUILD_ROOT%\dist"
set "PIP_CACHE_DIR=%BUILD_ROOT%\pip-cache"
set "WHEELHOUSE_DIR=%CD%\wheelhouse"
set "TMP=%BUILD_ROOT%\tmp"
set "TEMP=%BUILD_ROOT%\tmp"
set "PYINSTALLER_CONFIG_DIR=%BUILD_ROOT%\pyinstaller-config"
set "PYTHON_VERSION=3.11.9"
if not defined PYTHON_INSTALLER_URL set "PYTHON_INSTALLER_URL=https://mirrors.tuna.tsinghua.edu.cn/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if not defined PIP_DEFAULT_TIMEOUT set "PIP_DEFAULT_TIMEOUT=120"
if not defined PIP_RETRIES set "PIP_RETRIES=10"

echo Preparing Windows build environment...
echo Project: %CD%
echo Build cache: %BUILD_ROOT%
echo Pip index: %PIP_INDEX_URL%
if exist "%WHEELHOUSE_DIR%\*.whl" (
    if /I "%USE_LOCAL_WHEELS_ONLY%"=="1" (
        set "PIP_NO_INDEX=1"
        set "PIP_FIND_LINKS=%WHEELHOUSE_DIR%"
        echo Local wheelhouse only: %WHEELHOUSE_DIR%
    ) else (
        set "PIP_FIND_LINKS=%WHEELHOUSE_DIR%"
        echo Local wheelhouse: %WHEELHOUSE_DIR%
    )
)
echo.

if not defined LOCALAPPDATA (
    echo LOCALAPPDATA was not found. Please run this script from a normal Windows user account.
    goto fail
)

if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"
if errorlevel 1 goto fail
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
if errorlevel 1 goto fail
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if errorlevel 1 goto fail
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if errorlevel 1 goto fail
if not exist "%TMP%" mkdir "%TMP%"
if errorlevel 1 goto fail
if not exist "%PYINSTALLER_CONFIG_DIR%" mkdir "%PYINSTALLER_CONFIG_DIR%"
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
        echo build_windows_exe.bat
        goto fail
    )
    call :find_python
    if not defined PYTHON_CMD (
        echo.
        echo Python was installed, but this script still cannot find python.exe.
        echo Please reopen Command Prompt and run build_windows_exe.bat again.
        goto fail
    )
)

echo Using Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment in short path...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 goto fail
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 goto fail

if /I "%USE_LOCAL_WHEELS_ONLY%"=="1" (
    echo Skipping pip upgrade because USE_LOCAL_WHEELS_ONLY=1.
) else (
    python -m pip install --upgrade pip --cache-dir "%PIP_CACHE_DIR%"
    if errorlevel 1 goto fail
)

python -m pip install --upgrade --prefer-binary --cache-dir "%PIP_CACHE_DIR%" -r requirements-windows.txt
if errorlevel 1 goto pip_fail

if exist "%APP_NAME%" del "%APP_NAME%"
if exist "%UPDATER_NAME%" del "%UPDATER_NAME%"
if exist "%SETUP_NAME%" del "%SETUP_NAME%"
if exist "%DIST_DIR%\%APP_NAME%" del "%DIST_DIR%\%APP_NAME%"
if exist "%DIST_DIR%\%UPDATER_NAME%" del "%DIST_DIR%\%UPDATER_NAME%"

python -m PyInstaller --clean --noconfirm --distpath "%DIST_DIR%" --workpath "%WORK_DIR%" GPTLocalToolbox_windows.spec
if errorlevel 1 goto fail

if not exist "%DIST_DIR%\%APP_NAME%" (
    echo Build finished, but %DIST_DIR%\%APP_NAME% was not found.
    goto fail
)

python -m PyInstaller --clean --noconfirm --distpath "%DIST_DIR%" --workpath "%WORK_DIR%-updater" GPTToolboxUpdater_windows.spec
if errorlevel 1 goto fail

if not exist "%DIST_DIR%\%UPDATER_NAME%" (
    echo Build finished, but %DIST_DIR%\%UPDATER_NAME% was not found.
    goto fail
)

copy /Y "%DIST_DIR%\%APP_NAME%" "%CD%\%APP_NAME%" >nul
if errorlevel 1 goto fail
copy /Y "%DIST_DIR%\%UPDATER_NAME%" "%CD%\%UPDATER_NAME%" >nul
if errorlevel 1 goto fail

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE (
    for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do (
        if not defined ISCC_EXE set "ISCC_EXE=%%i"
    )
)

if defined ISCC_EXE (
    echo.
    echo Building Windows installer...
    "%ISCC_EXE%" /O"%CD%" /F"GPTLocalToolbox_Setup" "installer\GPTLocalToolbox.iss"
    if errorlevel 1 goto fail
) else (
    echo.
    echo Inno Setup was not found, so the installer package was skipped.
    echo You can still use %APP_NAME% directly.
)

echo.
echo Build finished:
echo %CD%\%APP_NAME%
if exist "%SETUP_NAME%" echo %CD%\%SETUP_NAME%
echo.
if exist "%SETUP_NAME%" (
    explorer.exe /select,"%CD%\%SETUP_NAME%"
) else (
    explorer.exe /select,"%CD%\%APP_NAME%"
)
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

:pip_fail
echo.
echo Python dependency installation failed.
echo.
echo If the error mentions "No such file or directory" under PySide6 or "Long Path support",
echo it is a Windows path-length problem. This script already uses a short venv path:
echo %VENV_DIR%
echo.
echo Please try one of these fixes on the Windows build computer:
echo 1. Move this project to a short folder, for example C:\GPTLocalToolbox
echo 2. Open Command Prompt as Administrator and run:
echo    reg add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled /t REG_DWORD /d 1 /f
echo    Then restart Windows and run this script again.
echo.
goto fail

:fail
echo.
echo Build failed. Please keep this window open and check the message above.
echo.
pause
exit /b 1
