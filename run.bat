@echo off

echo Checking for Python 3.11.0...

:: Try to detect Python version
for /f "tokens=2 delims= " %%i in ('python --version 2^>nul') do set PY_VER=%%i

if "%PY_VER%"=="3.11.0" (
    echo Python 3.11.0 is already installed.
    goto :continue
)

echo Python 3.11.0 not found. Installing...

:: Download Python installer
set PYTHON_URL=https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe
set INSTALLER=python-3.11.0-amd64.exe

powershell -Command "Invoke-WebRequest -Uri %PYTHON_URL% -OutFile %INSTALLER%"

if not exist %INSTALLER% (
    echo Failed to download Python installer.
    pause
    exit /b
)

echo Installing Python 3.11.0 silently...

:: Silent install with PATH added
%INSTALLER% /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

echo Installation complete.

:: Refresh environment (optional workaround)
setx PATH "%PATH%"

:continue
echo Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

echo Install dependencies
pip install -r requirements.txt

echo Run the application
python app.py