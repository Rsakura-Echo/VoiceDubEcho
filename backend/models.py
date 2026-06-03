"""Pydantic data models for API request/response schemas."""
from pydantic import BaseModel
from typing import Optional


class SettingsModel(BaseModel):
    """Global settings stored in ~/VoiceDub/settings.json."""
    rh_api_url: str = "http://localhost:8188"
    rh_api_key: str = ""
    hf_token: str = ""
    whisperx_model: str = "large-v3"


class ProjectCreate(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    audio_path: Optional[str] = None
    status: str
    created_at: str


class SegmentResponse(BaseModel):
    id: str
    project_id: str
    speaker: str
    start_time: float
    end_time: float
    original_text: str
    edited_text: str
    seg_audio_path: Optional[str] = None
    dubbed_audio_path: Optional[str] = None
    dub_status: str


class SegmentUpdate(BaseModel):
    edited_text: Optional[str] = None
    emotion: Optional[str] = None


class ProjectDetailResponse(BaseModel):
    id: str
    name: str
    audio_path: Optional[str] = None
    status: str
    created_at: str
    segments: list[SegmentResponse]


class WhisperXStatusResponse(BaseModel):
    model_name: str
    is_downloaded: bool
    is_processing: bool
