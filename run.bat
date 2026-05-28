@echo off
setlocal enabledelayedexpansion

echo Checking for Python 3.11.0...

:: Detect installed Python version
set PY_VER=

for /f "tokens=2 delims= " %%i in ('python --version 2^>nul') do (
set PY_VER=%%i
)

if "!PY_VER!"=="3.11.0" (
echo Python 3.11.0 already installed.
goto setup
)

echo Python 3.11.0 not found.
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

:: Install for all users and add to PATH
start /wait "" "%INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

echo Installation finished.

:: Typical install path
set PYTHON_EXE=C:\Program Files\Python311\python.exe

if not exist "%PYTHON_EXE%" (
echo Python installation failed or path changed.
pause
exit /b 1
)

:setup

echo.
echo Creating virtual environment...

"%PYTHON_EXE%" -m venv venv

if errorlevel 1 (
echo Failed to create virtual environment.
pause
exit /b 1
)

echo Activating virtual environment...

call venv\Scripts\activate.bat

echo.
echo Installing dependencies...

python -m pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
echo Failed to install requirements.
pause
exit /b 1
)

echo.
echo Running application...

python app.py

pause