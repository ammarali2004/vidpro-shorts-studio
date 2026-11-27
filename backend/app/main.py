from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import cv2
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.models import (
    AnalyzeRequest,
    CropMode,
    HeatmapPoint,
    JobStage,
    JobStatusResponse,
    RenderClipRequest,
    ShortClipCandidate,
    TranscriptSegment,
    TrendResearchReport,
    VideoMetadata,
)
from app.services.trend_researcher import run_trend_research, select_viral_clips
from app.services.video_processor import render_vertical_short
from app.services.youtube_service import (
    compute_audio_energy_profile,
    download_source_video,
    extract_transcript,
    extract_video_metadata_and_heatmap,
    find_ffmpeg_executable,
    normalize_youtube_url,
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / "workspace"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


@dataclass
class JobState:
    job_id: str
    request: AnalyzeRequest
    work_dir: Path
    stage: JobStage = JobStage.QUEUED
    progress: int = 0
    message: str = "Job queued..."
    error: Optional[str] = None
    metadata: Optional[VideoMetadata] = None
    heatmap: List[HeatmapPoint] = field(default_factory=list)
    transcript: List[TranscriptSegment] = field(default_factory=list)
    source_video: Optional[Path] = None
    research: Optional[TrendResearchReport] = None
    clips: List[ShortClipCandidate] = field(default_factory=list)


JOBS: Dict[str, JobState] = {}
JOBS_LOCK = threading.Lock()

app = FastAPI(
    title="VidPro Open-Source YouTube Shorts Studio",
    description="Zero-API-key YouTube research & 9:16 Shorts generator using yt-dlp, FFmpeg, MediaPipe, and scikit-learn.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_status_response(job: JobState) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        stage=job.stage,
        progress=job.progress,
        message=job.message,
        error=job.error,
        metadata=job.metadata,
        heatmap=job.heatmap,
        research=job.research,
        clips=job.clips,
    )


def _render_single_clip(job: JobState, clip: ShortClipCandidate) -> None:
    if not job.source_video or not job.source_video.exists():
        raise RuntimeError("Source video is not available on disk.")
    clip.status = "rendering"
    clip.error = None
    out_mp4 = job.work_dir / "clips" / f"{clip.clip_id}.mp4"
    out_thumb = job.work_dir / "clips" / f"{clip.clip_id}.jpg"
    try:
        render_vertical_short(
            source_video=job.source_video,
            output_mp4=out_mp4,
            thumbnail_jpg=out_thumb,
            start_time=clip.start_time,
            end_time=clip.end_time,
            crop_mode=clip.crop_mode,
            burn_captions=clip.burn_captions,
            segments=job.transcript,
            work_dir=job.work_dir,
            clip_id=clip.clip_id,
        )
        clip.status = "ready"
        clip.video_url = f"/api/jobs/{job.job_id}/clips/{clip.clip_id}/video"
        if out_thumb.exists():
            clip.thumbnail_url = f"/api/jobs/{job.job_id}/clips/{clip.clip_id}/thumbnail"
    except Exception as exc:
        clip.status = "error"
        clip.error = str(exc)


def _run_pipeline(job_id: str) -> None:
    job = JOBS[job_id]
    req = job.request
    try:
        url = normalize_youtube_url(req.youtube_url)

        # Stage 1: Metadata, Heatmap & Video Download
        job.stage = JobStage.FETCHING_VIDEO
        job.progress = 10
        job.message = "Fetching YouTube metadata and audience retention heatmap..."
        metadata, heatmap, _ = extract_video_metadata_and_heatmap(url)
        job.metadata = metadata
        job.heatmap = heatmap

        job.progress = 22
        job.message = f"Downloading '{metadata.title[:48]}...' via yt-dlp..."
        source_video = download_source_video(url, job.work_dir)
        job.source_video = source_video

        # Stage 2: Transcript & Audio Energy Extraction
        job.stage = JobStage.TRANSCRIBING
        job.progress = 42
        job.message = "Extracting timestamped transcript & vocal energy profile..."
        segments, transcript_source = extract_transcript(
            url=url,
            video_id=metadata.video_id,
            source_video=source_video,
            work_dir=job.work_dir,
        )
        job.transcript = segments
        audio_energy = compute_audio_energy_profile(source_video, metadata.duration)

        # Stage 3: Open-Source Trend Research
        job.stage = JobStage.RESEARCHING_TRENDS
        job.progress = 60
        job.message = "Researching live YouTube search trends & topic keywords..."
        research = run_trend_research(
            metadata=metadata,
            segments=segments,
            heatmap=heatmap,
            transcript_source=transcript_source,
        )
        job.research = research

        # Stage 4: Viral Moment Scoring
        job.stage = JobStage.SCORING_CLIPS
        job.progress = 74
        job.message = "Scoring hooks, retention spikes, and trend alignment..."
        clips = select_viral_clips(
            metadata=metadata,
            segments=segments,
            heatmap=heatmap,
            audio_energy=audio_energy,
            research=research,
            max_clips=req.max_clips,
            min_duration=req.min_duration,
            max_duration=req.max_duration,
            crop_mode=req.crop_mode,
            burn_captions=req.burn_captions,
        )
        job.clips = clips

        # Stage 5: Render 9:16 Vertical Shorts MP4s
        if req.auto_render and clips:
            job.stage = JobStage.RENDERING_SHORTS
            total_clips = len(clips)
            for idx, clip in enumerate(clips):
                job.progress = 76 + int((idx / total_clips) * 22)
                job.message = f"Rendering 9:16 Short {idx + 1}/{total_clips} with FFmpeg..."
                _render_single_clip(job, clip)

        job.stage = JobStage.COMPLETED
        job.progress = 100
        ready_count = sum(1 for c in job.clips if c.status == "ready")
        job.message = f"Done! Generated {ready_count} ready-to-post 9:16 Shorts."
    except Exception as exc:
        job.stage = JobStage.FAILED
        job.error = str(exc)
        job.message = f"Pipeline failed: {exc}"


@app.get("/api/health")
def health_check() -> dict:
    ffmpeg = find_ffmpeg_executable()
    return {
        "status": "ok",
        "ffmpeg_available": ffmpeg is not None,
        "ffmpeg_path": ffmpeg,
        "api_keys_required": False,
    }


@app.post("/api/jobs", response_model=JobStatusResponse)
def create_job(req: AnalyzeRequest, background_tasks: BackgroundTasks) -> JobStatusResponse:
    normalize_youtube_url(req.youtube_url)
    job_id = uuid.uuid4().hex[:10]
    work_dir = WORKSPACE_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    job = JobState(job_id=job_id, request=req, work_dir=work_dir)
    with JOBS_LOCK:
        JOBS[job_id] = job
    background_tasks.add_task(_run_pipeline, job_id)
    return _to_status_response(job)


def _run_upload_pipeline(job_id: str, source_path: Path, display_title: str) -> None:
    job = JOBS[job_id]
    req = job.request
    try:
        job.stage = JobStage.FETCHING_VIDEO
        job.progress = 20
        job.message = f"Inspecting uploaded video '{display_title}'..."

        cap = cv2.VideoCapture(str(source_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        cap.release()
        duration = max(1.0, frames / max(1.0, fps))

        metadata = VideoMetadata(
            video_id=job_id,
            title=display_title,
            channel="Uploaded Video",
            duration=round(duration, 2),
            webpage_url="",
        )
        job.metadata = metadata
        job.source_video = source_path

        job.stage = JobStage.TRANSCRIBING
        job.progress = 42
        job.message = "Transcribing audio with local Whisper & analyzing vocal energy..."
        segments, transcript_source = extract_transcript(
            url="",
            video_id=job_id,
            source_video=source_path,
            work_dir=job.work_dir,
        )
        job.transcript = segments
        audio_energy = compute_audio_energy_profile(source_path, metadata.duration)

        job.stage = JobStage.RESEARCHING_TRENDS
        job.progress = 62
        job.message = "Researching live YouTube search trends & topic keywords..."
        research = run_trend_research(
            metadata=metadata,
            segments=segments,
            heatmap=[],
            transcript_source=transcript_source,
        )
        job.research = research

        job.stage = JobStage.SCORING_CLIPS
        job.progress = 75
        job.message = "Scoring hooks, pacing, and trend alignment..."
        clips = select_viral_clips(
            metadata=metadata,
            segments=segments,
            heatmap=[],
            audio_energy=audio_energy,
            research=research,
            max_clips=req.max_clips,
            min_duration=req.min_duration,
            max_duration=req.max_duration,
            crop_mode=req.crop_mode,
            burn_captions=req.burn_captions,
        )
        job.clips = clips

        if req.auto_render and clips:
            job.stage = JobStage.RENDERING_SHORTS
            total_clips = len(clips)
            for idx, clip in enumerate(clips):
                job.progress = 77 + int((idx / total_clips) * 21)
                job.message = f"Rendering 9:16 Short {idx + 1}/{total_clips} with FFmpeg..."
                _render_single_clip(job, clip)

        job.stage = JobStage.COMPLETED
        job.progress = 100
        ready_count = sum(1 for c in job.clips if c.status == "ready")
        job.message = f"Done! Generated {ready_count} ready-to-post 9:16 Shorts."
    except Exception as exc:
        job.stage = JobStage.FAILED
        job.error = str(exc)
        job.message = f"Pipeline failed: {exc}"


@app.post("/api/jobs/upload", response_model=JobStatusResponse)
async def create_upload_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    max_clips: int = Form(4),
    min_duration: int = Form(20),
    max_duration: int = Form(55),
    crop_mode: CropMode = Form(CropMode.BLUR_FILL),
    burn_captions: bool = Form(True),
) -> JobStatusResponse:
    job_id = uuid.uuid4().hex[:10]
    work_dir = WORKSPACE_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        suffix = ".mp4"
    source_path = work_dir / f"source{suffix}"
    with source_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    req = AnalyzeRequest(
        youtube_url="https://youtube.com/watch?v=uploaded",
        max_clips=max(1, min(10, max_clips)),
        min_duration=max(10, min(50, min_duration)),
        max_duration=max(15, min(60, max_duration)),
        crop_mode=crop_mode,
        burn_captions=burn_captions,
        auto_render=True,
    )
    job = JobState(job_id=job_id, request=req, work_dir=work_dir)
    with JOBS_LOCK:
        JOBS[job_id] = job
    display_title = Path(file.filename or "Uploaded Video").stem
    background_tasks.add_task(_run_upload_pipeline, job_id, source_path, display_title)
    return _to_status_response(job)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_status_response(job)


@app.post("/api/jobs/{job_id}/clips/{clip_id}/render", response_model=ShortClipCandidate)
def rerender_clip(job_id: str, clip_id: str, req: RenderClipRequest) -> ShortClipCandidate:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clip = next((c for c in job.clips if c.clip_id == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if req.start_time is not None:
        clip.start_time = round(req.start_time, 2)
    if req.end_time is not None:
        clip.end_time = round(req.end_time, 2)
    if clip.end_time <= clip.start_time + 2.0:
        raise HTTPException(status_code=400, detail="Clip end_time must be at least 2s after start_time.")
    clip.duration = round(clip.end_time - clip.start_time, 2)
    if req.crop_mode is not None:
        clip.crop_mode = req.crop_mode
    if req.burn_captions is not None:
        clip.burn_captions = req.burn_captions

    _render_single_clip(job, clip)
    return clip


@app.get("/api/jobs/{job_id}/clips/{clip_id}/video")
def stream_or_download_clip(job_id: str, clip_id: str, download: bool = False):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clip_path = job.work_dir / "clips" / f"{clip_id}.mp4"
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Rendered clip video not found")

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="short_{clip_id}.mp4"'
    return FileResponse(path=str(clip_path), media_type="video/mp4", headers=headers)


@app.get("/api/jobs/{job_id}/clips/{clip_id}/thumbnail")
def get_clip_thumbnail(job_id: str, clip_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    thumb_path = job.work_dir / "clips" / f"{clip_id}.jpg"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path=str(thumb_path), media_type="image/jpeg")
