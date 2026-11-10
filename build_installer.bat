@echo off
setlocal
cd /d "%~dp0"

set "APP_VERSION=%~1"
if not defined APP_VERSION set "APP_VERSION=0.1.0"

python -m PyInstaller --clean --noconfirm lanq.spec
if errorlevel 1 exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    where ISCC.exe >nul 2>nul
    if errorlevel 1 (
        echo Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php
        exit /b 1
    )
    set "ISCC=ISCC.exe"
)

"%ISCC%" "/DAppVersion=%APP_VERSION%" "installer\LANQ.iss"
exit /b %ERRORLEVEL%