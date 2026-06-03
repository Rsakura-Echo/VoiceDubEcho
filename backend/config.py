"""Global configuration and settings management."""
import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "voicedub.db"
WORKFLOW_TEMPLATE_PATH = Path(__file__).parent.parent / "indexTTS2 最强语音克隆支持多人 10人对话_api.json"


def ensure_directories():
    """Create ~/VoiceDub/ and subdirectories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    """Load settings from settings.json, return defaults if missing."""
    ensure_directories()
    defaults = {
        "rh_api_url": "http://localhost:8188",
        "rh_api_key": "",
        "rh_workflow_id": "",
        "rh_clone_workflow_id": "",
        "hf_token": "",
        "whisperx_model": "large-v3",
        "use_local_tts": False,
        "rh_concurrency": 3,
    }
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
            defaults.update(stored)
    return defaults


def save_settings(data: dict):
    """Save settings to settings.json."""
    ensure_directories()
    current = load_settings()
    current.update(data)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


def get_project_dir(project_id: str) -> Path:
    """Return the project-specific subdirectory, creating if needed."""
    path = PROJECTS_DIR / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path
