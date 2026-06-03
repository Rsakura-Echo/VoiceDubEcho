@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   VoiceDub 环境安装
echo ========================================
echo.

set "PYTHON_DIR=%~dp0python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "TOOLS_DIR=%~dp0tools"
set "FFMPEG_DIR=%TOOLS_DIR%\ffmpeg"

:: Step 0: Ensure FFmpeg is available (bundled, no system install needed)
if not exist "%FFMPEG_DIR%\ffmpeg.exe" (
    echo [0/5] 下载 FFmpeg（音频处理必需）...
    mkdir "%TOOLS_DIR%" 2>nul

    :: 按优先级尝试多个源（国内优先）
    set "FFZIP=%TEMP%\ffmpeg.zip"
    set "FF_DOWNLOADED=0"

    :: 源1: GitHub Releases 通过 ghproxy 加速（国内快）
    if "!FF_DOWNLOADED!"=="0" (
        echo   尝试 ghproxy 加速...
        curl.exe -L -o "!FFZIP!" "https://ghproxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" 2>nul
        if exist "!FFZIP!" set "FF_DOWNLOADED=1"
    )

    :: 源2: GitHub Releases 直连
    if "!FF_DOWNLOADED!"=="0" (
        echo   尝试 GitHub 直连...
        curl.exe -L -o "!FFZIP!" "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" 2>nul
        if exist "!FFZIP!" set "FF_DOWNLOADED=1"
    )

    :: 源3: gyan.dev
    if "!FF_DOWNLOADED!"=="0" (
        echo   尝试 gyan.dev...
        curl.exe -L -o "!FFZIP!" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" 2>nul
        if exist "!FFZIP!" set "FF_DOWNLOADED=1"
    )

    if "!FF_DOWNLOADED!"=="1" (
        echo   解压 FFmpeg...
        mkdir "%FFMPEG_DIR%" 2>nul
        powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; try { $z = [System.IO.Compression.ZipFile]::OpenRead('!FFZIP!'); foreach ($e in $z.Entries) { $n = $e.Name; if ($n -eq 'ffmpeg.exe' -or $n -eq 'ffprobe.exe') { $out = Join-Path '%FFMPEG_DIR%' $n; [System.IO.Compression.FileSystem]::ExtractToFile($e, $out, $true) } }; $z.Dispose() } catch {}" 2>nul
        del "!FFZIP!" 2>nul
    )

    if not exist "%FFMPEG_DIR%\ffmpeg.exe" (
        echo [警告] FFmpeg 自动下载失败
        echo.
        echo 请手动将 ffmpeg.exe 和 ffprobe.exe 放到:
        echo   %FFMPEG_DIR%\
        echo.
        echo 下载地址: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
        pause
    ) else (
        echo [0/5] FFmpeg 就绪
    )
) else (
    echo [0/5] FFmpeg 已就绪
)

:: Step 1: Ensure local Python exists (should already be in git)
if not exist "%PYTHON_EXE%" (
    echo [1/5] 本地 Python 不存在，正在下载...
    set "DL=%TEMP%\python-embed.zip"
    curl.exe -L -o "!DL!" "https://repo.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip" 2>nul
    if not exist "!DL!" (
        curl.exe -L -o "!DL!" "https://registry.npmmirror.com/-/binary/python/3.11.9/python-3.11.9-embed-amd64.zip" 2>nul
    )
    if not exist "!DL!" (
        curl.exe -L -o "!DL!" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" 2>nul
    )
    if not exist "!DL!" (
        echo [错误] 下载 Python 失败，请检查网络
        pause
        exit /b 1
    )
    mkdir "%PYTHON_DIR%" 2>nul
    powershell -Command "Expand-Archive -Path '!DL!' -DestinationPath '%PYTHON_DIR%' -Force"
    del "!DL!" 2>nul
    :: Enable site-packages
    powershell -Command "(Get-Content '%PYTHON_DIR%\python311._pth') -replace '#import site', 'import site' | Set-Content '%PYTHON_DIR%\python311._pth'"
    :: Install pip
    curl.exe -L -o "%PYTHON_DIR%\get-pip.py" "https://bootstrap.pypa.io/get-pip.py" 2>nul
    "%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location
    del "%PYTHON_DIR%\get-pip.py" 2>nul
    echo [1/5] Python 便携版就绪
) else (
    echo [1/5] 本地 Python 3.11 已就绪
)

:: Step 1: Ensure virtualenv is available (embed Python lacks venv module)
echo [2/5] 准备虚拟环境工具...
"%PYTHON_EXE%" -m pip install virtualenv --quiet 2>nul

:: Step 2: Create venv using local Python
if exist "%~dp0venv\Scripts\python.exe" (
    echo [3/5] 虚拟环境已存在
) else (
    echo [3/5] 正在创建虚拟环境...
    "%PYTHON_EXE%" -m virtualenv "%~dp0venv"
    if !errorlevel! neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

:: Step 3: Install dependencies via venv pip (based on local Python)
echo [4/5] 安装项目依赖（清华镜像加速）...
call "%~dp0venv\Scripts\activate.bat"
pip install fastapi uvicorn python-multipart aiofiles pydantic ffmpeg-python pydub httpx uv -i https://pypi.tuna.tsinghua.edu.cn/simple
if !errorlevel! neq 0 (
    echo 清华镜像失败，重试默认源...
    pip install fastapi uvicorn python-multipart aiofiles pydantic ffmpeg-python pydub httpx uv
    if !errorlevel! neq 0 (
        echo [错误] 核心依赖安装失败
        pause
        exit /b 1
    )
)

echo.
echo 正在安装 WhisperX（可能需要几分钟）...
pip install whisperx==3.8.5 -i https://pypi.tuna.tsinghua.edu.cn/simple
if !errorlevel! neq 0 (
    pip install whisperx==3.8.5
    if !errorlevel! neq 0 (
        echo [警告] WhisperX 安装失败，语音切分功能将不可用
    )
)

:: Check for local CUDA torch wheel, upgrade if found
set "TORCH_WHEEL=%~dp0model\torch-2.8.0+cu128-cp311-cp311-win_amd64.whl"
if exist "!TORCH_WHEEL!" (
    echo.
    echo 检测到本地 CUDA Torch，正在安装...
    pip install "!TORCH_WHEEL!" --force-reinstall --no-deps
    if !errorlevel! equ 0 (
        echo CUDA Torch 安装完成
    ) else (
        echo [警告] CUDA Torch 安装失败，当前使用 CPU 版本
    )
)

echo.
echo ========================================
echo   安装完成！双击 start.bat 启动
echo ========================================
pause
