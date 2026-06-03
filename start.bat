@echo off
cd /d "%~dp0"

:: Add bundled FFmpeg to PATH (no system install needed)
if exist "%~dp0tools\ffmpeg\ffmpeg.exe" set "PATH=%~dp0tools\ffmpeg;%PATH%"

if not exist "venv\Scripts\python.exe" (
    echo Installing environment, please wait...
    call setup.bat
    if errorlevel 1 (echo Setup failed! & pause & exit /b 1)
)

echo =====================================
echo   VoiceDub  http://localhost:8765
echo =====================================
echo.

start "" /B venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

timeout /t 4 /nobreak >nul
start http://localhost:8765

echo Server starting... Model progress is shown in the browser.
echo.
echo Press any key or close this window to stop VoiceDub.
pause >nul
:: Only kill our uvicorn process, not all Python on the system
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765') do taskkill /F /PID %%a 2>nul
