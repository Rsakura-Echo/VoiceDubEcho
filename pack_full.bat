@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   VoiceDub Full Package Builder
echo ========================================
echo.

set "ROOT=%~dp0"
set "OUT=%ROOT%VoiceDub_Full"

:: Clean
if exist "%OUT%" (
    echo Cleaning old build...
    rmdir /s /q "%OUT%" 2>nul
)

echo Creating package structure...
mkdir "%OUT%" 2>nul

echo.
echo ========================================
echo [1/5] Source code
echo ========================================
for %%d in (backend frontend) do (
    echo   %%d/
    xcopy "%ROOT%%%d\*" "%OUT%\%%d\" /E /Q /Y >nul
)
for %%f in (setup.bat start.bat stop.bat requirements.txt VERSION README.md CLAUDE.md) do (
    if exist "%ROOT%%%f" copy "%ROOT%%%f" "%OUT%\" >nul
)
echo   OK

echo.
echo ========================================
echo [2/5] Python runtime
echo ========================================
echo   Copying python/ (without site-packages)...
robocopy "%ROOT%python" "%OUT%\python" /E /NFL /NDL /NJH /NJS /XD "Lib\site-packages" "__pycache__" 2>nul
echo   OK

echo.
echo ========================================
echo [3/5] FFmpeg
echo ========================================
if not exist "%ROOT%tools\ffmpeg\ffmpeg.exe" (
    echo   Seeking system ffmpeg...
    for /f "delims=" %%i in ('where ffmpeg 2^>nul') do (
        if not exist "%OUT%\tools\ffmpeg\ffmpeg.exe" (
            mkdir "%OUT%\tools\ffmpeg" 2>nul
            for %%j in ("%%i") do set "FFD=%%~dpj"
            copy "%%i" "%OUT%\tools\ffmpeg\" >nul
            if exist "!FFD!ffprobe.exe" copy "!FFD!ffprobe.exe" "%OUT%\tools\ffmpeg\" >nul
            echo   Copied from %%i
        )
    )
    if not exist "%OUT%\tools\ffmpeg\ffmpeg.exe" (
        if exist "C:\Program Files\ffmpeg\bin\ffmpeg.exe" (
            mkdir "%OUT%\tools\ffmpeg" 2>nul
            copy "C:\Program Files\ffmpeg\bin\ffmpeg.exe" "%OUT%\tools\ffmpeg\" >nul
            copy "C:\Program Files\ffmpeg\bin\ffprobe.exe" "%OUT%\tools\ffmpeg\" >nul 2>nul
            echo   Copied from Program Files
        )
    )
)
if exist "%ROOT%tools\ffmpeg\ffmpeg.exe" (
    mkdir "%OUT%\tools\ffmpeg" 2>nul
    copy "%ROOT%tools\ffmpeg\*" "%OUT%\tools\ffmpeg\" >nul
    echo   OK
)
if not exist "%OUT%\tools\ffmpeg\ffmpeg.exe" (
    echo   WARNING: ffmpeg not found - package will be incomplete
)

echo.
echo ========================================
echo [4/5] Models (this may take several minutes)
echo ========================================
for %%d in (huggingface speaker punctuation_funasr) do (
    if exist "%ROOT%model\%%d" (
        echo   model/%%d/ ...
        robocopy "%ROOT%model\%%d" "%OUT%\model\%%d" /E /NFL /NDL /NJH /NJS 2>nul
    )
)
if exist "%ROOT%model\indextts" (
    echo   model/indextts/ ...
    robocopy "%ROOT%model\indextts" "%OUT%\model\indextts" /E /NFL /NDL /NJH /NJS 2>nul
)
if exist "%ROOT%model\indextts_repo" (
    echo   model/indextts_repo/ ...
    robocopy "%ROOT%model\indextts_repo" "%OUT%\model\indextts_repo" /E /NFL /NDL /NJH /NJS 2>nul
)
for %%f in ("%ROOT%model\torch-*.whl") do (
    copy "%%f" "%OUT%\model\" >nul
    echo   %%f
)
echo   OK

echo.
echo ========================================
echo [5/5] NLTK data
echo ========================================
if exist "%ROOT%python\nltk_data" (
    robocopy "%ROOT%python\nltk_data" "%OUT%\python\nltk_data" /E /NFL /NDL /NJH /NJS 2>nul
    echo   OK
)

echo.
echo ========================================
echo   BUILD COMPLETE
echo ========================================
echo.
echo Package: %OUT%
echo.
echo User instructions:
echo   1. Download and extract VoiceDub_Full.zip
echo   2. Double-click setup.bat
echo   3. Double-click start.bat
echo.
echo To create the zip: right-click VoiceDub_Full folder
echo and use 7-Zip or WinRAR to compress.
echo.
echo Recommended: split into 4GB parts for cloud storage compatibility.
echo   7-Zip: right-click -^> 7-Zip -^> Add to archive -^> Split to volumes: 4G
echo.
pause
