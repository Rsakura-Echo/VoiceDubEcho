@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   VoiceDub Yun Pan Bao
echo ========================================
echo.

set "ROOT=%~dp0"
set "STAGING=%ROOT%_cloud_package"
set "BASE=%STAGING%\VoiceDub_base"
set "TTS=%STAGING%\VoiceDub_local_tts"

if exist "%STAGING%" (
    echo Clean old dir...
    rmdir /s /q "%STAGING%" 2>nul
)

mkdir "%BASE%\tools\ffmpeg" 2>nul
mkdir "%BASE%\model" 2>nul
mkdir "%BASE%\python\nltk_data" 2>nul
mkdir "%TTS%\model\indextts_repo" 2>nul

echo.
echo ========================================
echo [1/6] FFmpeg
echo ========================================
if not exist "%ROOT%tools\ffmpeg\ffmpeg.exe" (
    echo Downloading ffmpeg...
    curl.exe -L -o "%TEMP%\ffmpeg.zip" "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" 2>nul
    if exist "%TEMP%\ffmpeg.zip" (
        powershell -Command "Expand-Archive -Path '%TEMP%\ffmpeg.zip' -DestinationPath '%TEMP%\ffmpeg_tmp' -Force" 2>nul
        for /r "%TEMP%\ffmpeg_tmp" %%f in (ffmpeg.exe) do copy "%%f" "%ROOT%tools\ffmpeg\" >nul 2>nul
        for /r "%TEMP%\ffmpeg_tmp" %%f in (ffprobe.exe) do copy "%%f" "%ROOT%tools\ffmpeg\" >nul 2>nul
        rmdir /s /q "%TEMP%\ffmpeg_tmp" 2>nul
        del "%TEMP%\ffmpeg.zip" 2>nul
    )
)
if exist "%ROOT%tools\ffmpeg\ffmpeg.exe" (
    echo Copy ffmpeg...
    xcopy "%ROOT%tools\ffmpeg\*" "%BASE%\tools\ffmpeg\" /E /Q /Y >nul
    echo   OK
) else (
    echo   SKIP: ffmpeg download failed
)

echo.
echo ========================================
echo [2/6] Models
echo ========================================
echo Copy model/huggingface/ ...
xcopy "%ROOT%model\huggingface\*" "%BASE%\model\huggingface\" /E /Q /Y >nul 2>nul
if exist "%BASE%\model\huggingface" (echo   OK) else (echo   SKIP: dir not found)

echo Copy model/speaker/ ...
xcopy "%ROOT%model\speaker\*" "%BASE%\model\speaker\" /E /Q /Y >nul 2>nul
if exist "%BASE%\model\speaker" (echo   OK) else (echo   SKIP: dir not found)

echo Copy model/punctuation_funasr/ ...
xcopy "%ROOT%model\punctuation_funasr\*" "%BASE%\model\punctuation_funasr\" /E /Q /Y >nul 2>nul
if exist "%BASE%\model\punctuation_funasr" (echo   OK) else (echo   SKIP: dir not found)

echo.
echo ========================================
echo [3/6] NLTK data
echo ========================================
xcopy "%ROOT%python\nltk_data\*" "%BASE%\python\nltk_data\" /E /Q /Y >nul 2>nul
if exist "%BASE%\python\nltk_data\tokenizers" (echo   OK) else (echo   SKIP: dir not found)

echo.
echo ========================================
echo [4/6] PyTorch CUDA wheel
echo ========================================
for %%f in ("%ROOT%model\torch-*.whl") do (
    copy "%%f" "%BASE%\model\" >nul
    echo   %%f - OK
)
if not exist "%BASE%\model\torch-*.whl" (
    echo   SKIP: torch wheel not found
)

echo.
echo ========================================
echo [5/6] IndexTTS2 (local TTS only)
echo ========================================
echo Copy model/indextts_repo/ ...
xcopy "%ROOT%model\indextts_repo\*" "%TTS%\model\indextts_repo\" /E /Q /Y >nul 2>nul
if exist "%TTS%\model\indextts_repo" (echo   OK) else (echo   SKIP: dir not found)

echo.
echo ========================================
echo [6/6] README
echo ========================================
(
echo VoiceDub Pre-install Package
echo ============================
echo.
echo Extract to VoiceDub project root, overwrite existing folders.
echo Then run setup.bat to complete installation.
echo.
echo Base package (VoiceDub_base):
echo   FFmpeg, HF models, speaker diarization, punctuation, NLTK, PyTorch
echo.
echo Local TTS package (VoiceDub_local_tts):
echo   IndexTTS2 model and inference code
) > "%STAGING%\README.txt"
echo   OK

echo.
echo ========================================
echo   Done!
echo ========================================
echo.
echo Base:  %BASE%
echo TTS:   %TTS%
echo.
echo Zip each folder and upload to cloud storage.
echo.
pause
