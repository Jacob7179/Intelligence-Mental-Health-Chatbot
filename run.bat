@echo off
setlocal EnableDelayedExpansion

echo Checking for Python 3.11...

:: Detect installed Python version
set PY_VER=
set PYTHON_EXE=

for /f "tokens=2 delims= " %%i in ('python --version 2^>nul') do (
    set PY_VER=%%i
)

:: Accept any Python 3.11.x version
echo !PY_VER! | findstr /b "3.11." >nul
if not errorlevel 1 (
    echo Python !PY_VER! already installed.
    set PYTHON_EXE=python
    goto setup
)

echo Python 3.11 not found.
echo Downloading installer...

set PYTHON_URL=https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe
set INSTALLER=%TEMP%\python-3.11.0-amd64.exe

powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER%'"

if not exist "%INSTALLER%" (
    echo Failed to download installer.
    pause
    exit /b 1
)

echo Installing Python silently...

start /wait "" "%INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

echo Installation finished.

:: Refresh PATH lookup
timeout /t 5 >nul

for /f "delims=" %%i in ('where python 2^>nul') do (
    set PYTHON_EXE=%%i
    goto found_python
)

echo Python installation failed.
pause
exit /b 1

:found_python

:setup

echo.
echo Creating virtual environment...

"%PYTHON_EXE%" -m venv venv

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
    pip install -r requirements.txt

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