@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo Checking for Python 3.11...

set PYTHON_EXE=
set PY_VER=

:: First try Python Launcher
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_EXE=py -3.11
    for /f "tokens=2 delims= " %%i in ('py -3.11 --version 2^>nul') do set PY_VER=%%i
    echo Python !PY_VER! found using Python Launcher.
    goto setup
)

:: Then try normal python command, but ignore Microsoft Store alias failure
for /f "tokens=2 delims= " %%i in ('python --version 2^>nul') do set PY_VER=%%i

echo !PY_VER! | findstr /b "3.11." >nul
if not errorlevel 1 (
    set PYTHON_EXE=python
    echo Python !PY_VER! already installed.
    goto setup
)

echo Python 3.11 not found.
echo Downloading Python 3.11 installer...

set PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
set INSTALLER=%TEMP%\python-3.11.9-amd64.exe

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER%'"

if not exist "%INSTALLER%" (
    echo Failed to download installer.
    pause
    exit /b 1
)

echo Installing Python silently...
"%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0

if errorlevel 1 (
    echo Python installer failed.
    pause
    exit /b 1
)

echo Installation finished.

:: Directly use the per-user install path. This avoids Microsoft Store alias problems.
set PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe

if not exist "%PYTHON_EXE%" (
    echo Could not find Python at: %PYTHON_EXE%
    echo Trying Python Launcher again...

    py -3.11 --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_EXE=py -3.11
        goto setup
    )

    echo Python installation failed or PATH was not updated.
    echo Please disable Python app execution aliases in Windows Settings.
    pause
    exit /b 1
)

:setup

echo.
echo Using Python:
%PYTHON_EXE% --version

echo.
echo Creating virtual environment...

%PYTHON_EXE% -m venv venv

if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
)

echo.
echo Activating virtual environment...

call venv\Scripts\activate.bat

if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

echo.
echo Upgrading pip...

python -m pip install --upgrade pip

if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo Installing dependencies...

if exist requirements.txt (
    python -m pip install -r requirements.txt

    if errorlevel 1 (
        echo Failed to install requirements.
        pause
        exit /b 1
    )
) else (
    echo requirements.txt not found. Skipping dependency installation.
)

echo.
echo Running application...

if exist app.py (
    python app.py
) else (
    echo app.py not found.
)

pause