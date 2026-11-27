from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CropMode(str, Enum):
    BLUR_FILL = "blur_fill"
    HYBRID_FIT = "hybrid_fit"
    SMART_FACE = "smart_face"
    CENTER = "center"


class JobStage(str, Enum):
    QUEUED = "queued"
    FETCHING_VIDEO = "fetching_video"
    TRANSCRIBING = "transcribing"
    RESEARCHING_TRENDS = "researching_trends"
    SCORING_CLIPS = "scoring_clips"
    RENDERING_SHORTS = "rendering_shorts"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalyzeRequest(BaseModel):
    youtube_url: str = Field(..., description="YouTube watch, live, or youtu.be URL")
    max_clips: int = Field(default=5, ge=1, le=10)
    min_duration: int = Field(default=20, ge=10, le=50)
    max_duration: int = Field(default=55, ge=15, le=60)
    crop_mode: CropMode = Field(default=CropMode.BLUR_FILL)
    burn_captions: bool = Field(default=True)
    auto_render: bool = Field(default=True)


class RenderClipRequest(BaseModel):
    start_time: Optional[float] = Field(default=None, ge=0)
    end_time: Optional[float] = Field(default=None, gt=0)
    crop_mode: Optional[CropMode] = None
    burn_captions: Optional[bool] = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class HeatmapPoint(BaseModel):
    start_time: float
    end_time: float
    value: float


class ScoreBreakdown(BaseModel):
    hook_strength: int = Field(ge=0, le=100)
    trend_alignment: int = Field(ge=0, le=100)
    retention_heatmap: int = Field(ge=0, le=100)
    audio_energy: int = Field(ge=0, le=100)
    pacing_completeness: int = Field(ge=0, le=100)


class ShortClipCandidate(BaseModel):
    clip_id: str
    rank: int
    start_time: float
    end_time: float
    duration: float
    viral_score: int = Field(ge=0, le=100)
    breakdown: ScoreBreakdown
    suggested_title: str
    hook_line: str
    why_trending: List[str]
    matched_trends: List[str]
    hashtags: List[str]
    transcript_excerpt: str
    crop_mode: CropMode
    burn_captions: bool
    status: str = "pending"  # pending | rendering | ready | error
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    error: Optional[str] = None


class TrendResearchReport(BaseModel):
    extracted_topics: List[str]
    youtube_trending_queries: List[str]
    google_rising_topics: List[str]
    has_youtube_heatmap: bool
    transcript_source: str  # youtube_subtitles | youtube_auto_captions | faster_whisper
    summary_notes: List[str]


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: float
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    thumbnail: Optional[str] = None
    webpage_url: str
    categories: List[str] = []
    tags: List[str] = []


class JobStatusResponse(BaseModel):
    job_id: str
    stage: JobStage
    progress: int = Field(ge=0, le=100)
    message: str
    error: Optional[str] = None
    metadata: Optional[VideoMetadata] = None
    heatmap: List[HeatmapPoint] = []
    research: Optional[TrendResearchReport] = None
    clips: List[ShortClipCandidate] = []
