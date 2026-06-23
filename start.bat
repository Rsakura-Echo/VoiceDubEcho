@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Add bundled FFmpeg to PATH
if exist "%~dp0tools\ffmpeg\ffmpeg.exe" set "PATH=%~dp0tools\ffmpeg;%PATH%"

if not exist "%~dp0python\python.exe" (
    echo [ERROR] python\python.exe not found
    pause
    exit /b 1
)

echo =====================================
echo   VoiceDub  http://localhost:8765
echo =====================================
echo.

start "" /B "%~dp0python\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

timeout /t 4 /nobreak >nul
start http://localhost:8765

echo Server starting...
echo.
echo Press any key or close this window to stop VoiceDub.
pause >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765') do taskkill /F /PID %%a 2>nul
