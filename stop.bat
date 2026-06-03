@echo off
echo Stopping VoiceDub...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8770') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8771') do taskkill /F /PID %%a 2>nul

echo VoiceDub stopped
pause
