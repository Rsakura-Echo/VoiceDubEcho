# VoiceDub — 本地 TTS 语音台词配音工具

上传音频 → 自动识别说话人并切分台词 → 逐段编辑 → 调用 IndexTTS2 生成配音 → 导出成品。

**零 Python 环境依赖**：项目捆绑 Python 3.11.9 嵌入便携版，clone 后双击脚本即可运行，无需安装任何 Python。

## 功能概览

- 上传音频文件（mp3/wav/m4a/flac），自动语音识别 + 说话人分离
- 台词逐段编辑，支持切割/合并/插入/修剪
- 情绪参数调节（happy/angry/sad/fear/hate/low/surprise/neutral）
- 单段配音 / 批量配音 / 克隆配音
- 音色库管理（上传参考音频作为克隆音色）
- 导出配音音频 + SRT/ASS 字幕
- 模型管理面板（一键下载所需模型，含 HuggingFace 授权指引）
- 本地 IndexTTS2 模式（~5.5GB 显存）或云端 RunningHub API 模式

## 环境要求

### 操作系统
- **Windows 10/11 64-bit**（捆绑的 Python 为 Windows 版本）

### 必须
无。`setup.bat` 会自动下载 Python 嵌入版、FFmpeg 和所有依赖。clone 后双击 `setup.bat` 即可。

### 可选（强烈推荐）
| 依赖 | 说明 |
|------|------|
| **NVIDIA GPU + CUDA 12.x** | 8GB+ 显存，RTX 30/40/50 系列。CPU 模式可运行但极慢 |
| **HuggingFace 账号** | 说话人分离模型需要授权。注册 https://huggingface.co/join ，然后在模型管理面板按指引操作 |
| **ComfyUI** | 使用云端 API 模式时不需要；本地模式需自行安装 ComfyUI + IndexTTS2 工作流 |

## 快速开始

```batch
# 1. 克隆仓库
git clone <repo-url> VoiceDub
cd VoiceDub

# 2. 首次安装（下载依赖、创建虚拟环境）
setup.bat

# 3. 启动服务
start.bat
```

浏览器自动打开 http://localhost:8765

详细步骤：

1. 创建项目 → 上传音频文件
2. 等待自动处理（语音识别 → 说话人分离 → 标点恢复）
3. 编辑台词文本，调节情绪参数
4. 点击「开始配音」或「克隆配音」
5. 导出音频 / 字幕

## 项目结构

```
VoiceDub/
├── python/                 # Python 3.11.9 嵌入便携版（8.0G，已提交 Git）
├── venv/                   # 后端虚拟环境（13G，setup.bat 创建，含 PyTorch 等）
├── backend/                # FastAPI 后端
│   ├── main.py             # API 路由入口（57K，含所有 API + WebSocket）
│   ├── database.py         # SQLite 数据层
│   ├── config.py           # 配置管理
│   ├── models.py           # Pydantic 数据模型
│   ├── whisperx_worker.py  # WhisperX 后台处理流程
│   ├── whisperx_cli.py     # WhisperX 命令行封装
│   ├── indextts_client.py  # IndexTTS2 本地 HTTP 调用
│   ├── rh_client.py        # RunningHub 云端 API
│   ├── audio_utils.py      # 音频处理工具
│   ├── punctuation.py      # 中文标点恢复
│   └── model_cache.py      # 模型下载/缓存状态管理
├── frontend/               # 前端 SPA（纯 HTML/CSS/JS，无框架）
│   ├── index.html          # 主页面入口
│   ├── css/style.css       # 全局样式
│   └── js/
│       ├── app.js          # 主应用逻辑 + 事件绑定
│       ├── api.js          # API 调用封装
│       ├── components.js   # UI 组件（模型管理面板等）
│       └── audio-editor.js # 音频编辑器
├── model/                  # AI 模型文件（31G，从云盘下载，不提交 Git）
│   ├── huggingface/        # HuggingFace 模型（~10.6G）
│   │   ├── models--Systran--faster-whisper-large-v3/    # 5.8G
│   │   ├── models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/  # 4.8G
│   │   ├── models--pyannote--speaker-diarization-3.1/    # 21M
│   │   ├── models--pyannote--segmentation-3.0/           # 12M
│   │   └── models--pyannote--speaker-diarization-community-1/  # 1K
│   ├── indextts/           # IndexTTS2 模型权重（5.5G）
│   │   ├── gpt.pth         # GPT 声学模型（3.3G）
│   │   ├── s2mel.pth       # 语义→梅尔频谱模型（1.2G）
│   │   ├── qwen0.6bemo4-merge/  # Qwen 0.6B 语言模型（1.14G）
│   │   ├── bpe.model       # BPE 分词器
│   │   ├── feat1.pt / feat2.pt  # 特征提取器
│   │   └── config.yaml     # IndexTTS2 配置
│   ├── indextts_repo/      # IndexTTS2 完整仓库（11G）
│   │   ├── .venv/          # IndexTTS2 独立虚拟环境（8.2G）
│   │   ├── checkpoints/    # 额外检查点，含 w2v-bert-2.0（2.8G）
│   │   ├── indextts/       # IndexTTS2 Python 源码
│   │   ├── tts_server.py   # TTS 服务进程入口
│   │   └── tts_worker.py   # TTS Worker 进程
│   ├── punctuation_funasr/ # 中文标点恢复模型（283M）
│   │   ├── model.pt        # CT-Transformer 标点模型（278M）
│   │   └── tokens.json     # Token 映射表
│   ├── speaker/            # 说话人识别模型（33M）
│   │   ├── embedding/      # 声纹特征提取
│   │   ├── segmentation/   # 语音分段
│   │   └── plda/           # PLDA 打分模型
│   ├── voices/             # 用户音色库（6.7M，已注册的克隆声音）
│   └── torch-2.8.0+cu128-cp311-cp311-win_amd64.whl  # PyTorch 离线包（3.2G）
├── data/                   # 运行时数据（不提交 Git）
│   ├── voicedub.db         # SQLite 数据库
│   ├── projects/           # 项目音频文件 + 配音结果
│   └── settings.json       # 用户设置
├── memory/                 # 会话记忆（项目状态、市场分析等）
├── docs/                   # 文档（技术规格、实现计划）
├── setup.bat               # 一键安装脚本
├── start.bat               # 启动服务脚本
├── stop.bat                # 停止服务脚本
├── pack_cloud.bat          # 云盘版打包脚本
├── pack_full.bat           # 完整版打包脚本
└── requirements.txt        # Python 依赖列表
```

## 首次部署（新电脑，零依赖）

GitHub 仓库只含代码（包括 Python 嵌入版），大文件需从云盘下载后放入对应目录。

### 第一步：clone 代码
```batch
git clone <repo-url> VoiceDub
cd VoiceDub
```

### 第二步：下载预置包（从云盘）

将以下文件夹放入对应位置。**没有这些模型，语音识别/配音功能将无法使用。**

| 预下载内容 | 大小 | 放到哪个目录 | 用途 |
|-----------|------|-------------|------|
| `python/` 目录 | ~4.0GB | `python/`（仓库已自带，含 nltk_data） | Python 3.11.9 + nltk 数据 |
| PyTorch CUDA wheel | ~3.2GB | `model/` | GPU 深度学习运行时（`torch-2.8.0+cu128-cp311-cp311-win_amd64.whl`） |
| faster-whisper-large-v3 | ~5.8GB | `model/huggingface/models--Systran--faster-whisper-large-v3/` | 语音转文字（Whisper Large V3） |
| wav2vec2 中文对齐模型 | ~4.8GB | `model/huggingface/models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/` | 字级别时间轴对齐 |
| 说话人分离模型 | ~21MB | `model/huggingface/models--pyannote--speaker-diarization-3.1/` | 区分不同说话人 |
| 人声分割模型 | ~12MB | `model/huggingface/models--pyannote--segmentation-3.0/` | 语音活动检测 (VAD) |
| 说话人声纹模型 | ~33MB | `model/speaker/` | 声纹特征提取 + PLDA 打分 |
| 中文标点模型 | ~283MB | `model/punctuation_funasr/` | 恢复中文标点（CT-Transformer） |
| IndexTTS2 模型权重 | ~5.5GB | `model/indextts/` | GPT + S2Mel + Qwen 0.6B（本地配音核心） |
| IndexTTS2 完整仓库 | ~11GB | `model/indextts_repo/` | TTS 服务 + 独立 venv + w2v-bert-2.0（本地模式需要） |
| FFmpeg | ~80MB | `tools/ffmpeg/`（setup.bat 自动下载） | 音频编解码 |

### 第三步：一键安装
```batch
setup.bat
```
脚本自动完成：检测已有文件 → 缺失的从国内镜像下载 → 创建虚拟环境 → 安装 Python 依赖。

所有自动下载均使用国内源（清华 pip 镜像、hf-mirror、ModelScope、NJU 镜像），无需 VPN。

### 第四步：启动
```batch
start.bat
```
浏览器打开 http://localhost:8765 → 在模型管理面板确认所有模型显示 ✓ 已安装 → 开始使用。

## 配音模式

### 云端模式（默认）
通过 RunningHub API 调用远程 ComfyUI 工作流。需在设置中配置：
- API 地址
- API Token
- 配音 / 克隆配音 Workflow ID

### 本地模式
在设置中切换到「本地」，启动本地 IndexTTS2 模型。需要：
- NVIDIA GPU ≥8GB 显存
- ComfyUI 本地运行
- IndexTTS2 模型已下载

## 完整模型清单

以下列出所有 AI 模型文件及其用途，按功能模块分组。

### 语音识别管线（WhisperX）— 合计 ~10.6G

| 模型 | HuggingFace ID | 大小 | 用途 |
|------|---------------|------|------|
| Whisper Large V3 | `Systran/faster-whisper-large-v3` | 5.8G | ASR 语音转文字，输出带时间戳的文本 |
| Wav2Vec2 中文对齐 | `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn` | 4.8G | 字级别强制对齐，精确到每个汉字的时间戳 |
| 说话人分离 3.1 | `pyannote/speaker-diarization-3.1` | 21M | 区分录音中的不同说话人 |
| 语音分段 3.0 | `pyannote/segmentation-3.0` | 12M | 语音活动检测 (VAD)，分离语音/静音段 |
| 说话人分离（社区版） | `pyannote/speaker-diarization-community-1` | 1K | 社区版备选 |

### 说话人声纹模型 — 合计 33M

| 组件 | 目录 | 用途 |
|------|------|------|
| 声纹 Embedding | `model/speaker/embedding/` | 提取说话人声纹特征向量 |
| 语音分段 | `model/speaker/segmentation/` | 语音段分割 |
| PLDA 打分 | `model/speaker/plda/` | 声纹相似度打分，确认两段音频是否同一人 |

### 中文标点恢复 — 合计 283M

| 文件 | 大小 | 用途 |
|------|------|------|
| `model/punctuation_funasr/model.pt` | 278M | CT-Transformer 标点恢复模型，给无标点文本自动加标点 |
| `model/punctuation_funasr/tokens.json` | 4M | 标点 Token 映射表 |

### IndexTTS2 语音合成 — 合计 16.5G

| 文件/目录 | 大小 | 用途 |
|-----------|------|------|
| `model/indextts/gpt.pth` | **3.3G** | GPT 声学模型，根据文本 + 音色参考生成声学特征 |
| `model/indextts/s2mel.pth` | **1.2G** | 语义 Token → 梅尔频谱转换 |
| `model/indextts/qwen0.6bemo4-merge/model.safetensors` | **1.14G** | Qwen 0.6B 基础语言模型，理解+生成语音语义 Token |
| `model/indextts/bpe.model` | 465K | BPE 分词器 |
| `model/indextts/feat1.pt` + `feat2.pt` | 423K | 音频特征提取器权重 |
| `model/indextts/config.yaml` | 3K | IndexTTS2 配置 |
| `model/indextts_repo/.venv/` | **8.2G** | IndexTTS2 独立 Python 虚拟环境（含 PyTorch ~3G） |
| `model/indextts_repo/checkpoints/` | **2.8G** | w2v-bert-2.0 预训练模型等检查点 |

### 音色库 — 合计 6.7M

`model/voices/` 存放用户注册的克隆声音，每个声音一个子目录，含声纹 embedding + 参考音频片段。当前已注册 4 个声音。

### 离线安装包

| 文件 | 大小 | 用途 |
|------|------|------|
| `model/torch-2.8.0+cu128-cp311-cp311-win_amd64.whl` | **3.2G** | PyTorch 2.8.0 CUDA 12.8，GPU 深度学习运行时（离线安装用） |

## 大于 1G 的文件清单

| # | 文件 | 大小 | 所属模块 |
|---|------|------|----------|
| 1 | `model/huggingface/models--Systran--faster-whisper-large-v3/blobs/...` | 5.8G | Whisper Large V3 模型权重 |
| 2 | `model/huggingface/models--Systran--faster-whisper-large-v3/snapshots/.../model.bin` | 5.8G | 同上（snapshot 副本） |
| 3 | `model/huggingface/models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/blobs/...` (×2) | 2.4G + 2.4G | Wav2Vec2 中文对齐模型（原始 blob） |
| 4 | `model/huggingface/models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/snapshots/.../pytorch_model.bin` | 2.4G | Wav2Vec2 中文对齐（snapshot） |
| 5 | `model/huggingface/models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/snapshots/.../model.safetensors` | 2.4G | Wav2Vec2 safetensors 版本 |
| 6 | `model/indextts/gpt.pth` | **3.3G** | IndexTTS2 GPT 声学模型 |
| 7 | `model/indextts/s2mel.pth` | **1.2G** | IndexTTS2 语义→频谱模型 |
| 8 | `model/indextts/qwen0.6bemo4-merge/model.safetensors` | **1.14G** | Qwen 0.6B 语言模型 |
| 9 | `model/torch-2.8.0+cu128-cp311-cp311-win_amd64.whl` | **3.2G** | PyTorch 离线安装包 |
| 10 | `model/indextts_repo/checkpoints/hf_cache/.../w2v-bert-2.0/blobs/...` | 1.4G | w2v-bert-2.0 预训练模型 |
| 11 | `model/indextts_repo/.venv/Lib/site-packages/torch/lib/dnnl.lib` | 1.1G | PyTorch oneDNN 加速库 |
| 12 | `venv/Lib/site-packages/torch/lib/dnnl.lib` | 1.1G | 同上（后端 venv 副本） |

## 常见问题

**Q: 启动报错 "Python not found"？**
A: 确保 `python/` 目录完整（包含在 Git 仓库中），不要删除该目录。

**Q: 语音识别失败？**
A: 打开模型管理面板，确认所有模型已下载。说话人分离模型需要 HuggingFace Token 授权。

**Q: 配音按钮灰色？**
A: 检查设置中是否正确配置了 RunningHub API 地址和 Token，或确认本地模型已启动。

**Q: 端口被占用？**
A: 运行 `stop.bat` 释放端口，或手动关闭占用 8765 端口的进程。

**Q: 支持 macOS/Linux 吗？**
A: 目前仅支持 Windows。捆绑的 Python 为 Windows 版本。如需其他平台，可替换 `python/` 目录为对应平台的 Python 嵌入版，并调整 `.bat` 脚本为 shell 脚本。

## 技术栈

- 前端：纯 HTML/CSS/JS（无框架 SPA）
- 后端：Python FastAPI + Uvicorn
- 数据库：SQLite
- 语音识别：WhisperX 3.8.5
- 说话人分离：PyAnnote (speaker-diarization-3.1)
- TTS：IndexTTS2（ComfyUI / RunningHub）
- Python：3.11.9 嵌入版
