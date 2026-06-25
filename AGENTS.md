# VoiceDub — 本地 TTS 语音台词配音工具

## 核心原则

### 修改代码前的依赖检查（铁律）
每次修改任意函数/组件/API 前，必须先搜索所有引用点（调用方和被调用方），评估修改影响范围。
如果一个修改会影响到其他模块，必须同步调整所有关联项，确保整个链路完整可用。
例如：修改克隆配音的 API 调用逻辑 → 检查前端调用、后端路由、rh_client 函数签名、`_do_clone_dub` 传参、`_showVoicePicker` 回调等全链路。

### 零手动命令
- 所有安装、配置、启动操作必须通过脚本自动化完成
- 用户不需要手动执行任何命令（`pip install`、`python`、`venv` 等）
- 启动脚本需自动处理：虚拟环境创建、依赖安装、服务启动
- **所有需要额外下载的组件（模型、NLTK 数据等）必须列入模型管理面板，用户点击按钮即可下载**
- 严禁让用户手动下载文件、手动执行命令

### 本地 Python 隔离（最高优先级）
- 项目捆绑 Python 3.11.9 嵌入便携版（`python/` 目录，已提交 Git）
- **目标机器不需要安装任何 Python**，clone 后直接可用
- **项目中所有 Python 命令、pip、脚本必须基于 `python/python.exe`**
- 严禁调用系统的 `python`、`py`、`python3` 命令
- 严禁假设用户电脑上有任何 Python 环境
- 脚本中 Python 路径统一使用 `%~dp0python\python.exe`（Windows batch）
- venv 基于本地 Python 创建，使用 `virtualenv`（嵌入版不含 `venv` 模块）
- pip 安装通过 `venv\Scripts\pip`（间接使用本地 Python）
- 零系统侵入：不写注册表、不需要管理员权限、删除目录即彻底清除

### 语言
- 所有面向用户的文字使用中文
- 代码、命令、技术术语保持原文

## 技术栈
- 前端：纯 HTML/CSS/JS（极简 SPA，无框架）
- 数据：SQLite（~/VoiceDub/voicedub.db）
- 后端：Python + FastAPI
- 语音识别/切分：WhisperX 3.8.5
- TTS：IndexTTS2（通过 ComfyUI API 调用）
- Python：3.11.9 嵌入便携版（捆绑在 `python/` 目录，无需系统安装）
