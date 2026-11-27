from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yt_dlp

from app.models import HeatmapPoint, TranscriptSegment, VideoMetadata


def find_ffmpeg_executable() -> Optional[str]:
    """Locate ffmpeg from PATH, WinGet packages, or imageio-ffmpeg fallback."""
    direct = shutil.which("ffmpeg")
    if direct:
        return direct

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidate_globs = [
        os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "ffmpeg.exe"),
        os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for pattern in candidate_globs:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]

    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    return None


def find_node_executable() -> Optional[str]:
    """Locate Node.js so yt-dlp can solve YouTube JS/n-challenges reliably."""
    direct = shutil.which("node")
    if direct:
        return direct

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.join(local_app_data, "Programs", "nodejs", "node.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _get_cookie_file() -> Optional[str]:
    """Write optional YOUTUBE_COOKIES_B64 or YOUTUBE_COOKIES env var to a temp Netscape cookie file."""
    b64_val = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
    raw_val = os.environ.get("YOUTUBE_COOKIES", "").strip()
    content = ""
    if b64_val:
        try:
            content = base64.b64decode(b64_val).decode("utf-8", errors="ignore")
        except Exception:
            content = ""
    elif raw_val:
        content = raw_val

    if not content:
        return None

    cookie_path = Path(tempfile.gettempdir()) / "vidpro_yt_cookies.txt"
    cookie_path.write_text(content, encoding="utf-8")
    return str(cookie_path)


def _base_ydl_opts() -> Dict[str, Any]:
    """Build hardened yt-dlp base options with Node JS runtime + EJS challenge solver + optional cookies."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "remote_components": ["ejs:github"],
    }
    node_exe = find_node_executable()
    if node_exe:
        opts["js_runtimes"] = {"node": {"path": node_exe}}
    ffmpeg_exe = find_ffmpeg_executable()
    if ffmpeg_exe:
        opts["ffmpeg_location"] = str(Path(ffmpeg_exe).parent)
    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


def _format_yt_error(exc: Optional[Exception], context: str) -> RuntimeError:
    msg = str(exc or "Unknown YouTube extraction error")
    lower = msg.lower()
    if "confirm you" in lower and "not a bot" in lower:
        return RuntimeError(
            "YouTube temporarily blocked this cloud server's IP ('Sign in to confirm you're not a bot'). "
            "Use 'Upload Video File' or 'Try Instant Demo' below, or set YOUTUBE_COOKIES_B64 in backend env vars."
        )
    return RuntimeError(f"{context}: {msg}")


def normalize_youtube_url(url: str) -> str:
    """Validate and normalize common YouTube URL formats."""
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Please provide a YouTube URL.")
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        cleaned = f"https://{cleaned}"
    if not re.search(r"(youtube\.com|youtu\.be|youtube-nocookie\.com)", cleaned, re.IGNORECASE):
        raise ValueError("URL must be a valid youtube.com or youtu.be link.")
    return cleaned


def extract_video_metadata_and_heatmap(
    url: str,
) -> Tuple[VideoMetadata, List[HeatmapPoint], dict]:
    """Fetch video metadata, chapters, tags, and YouTube Most Replayed heatmap with client fallbacks."""
    client_strategies: List[Optional[List[str]]] = [
        None,
        ["tv_simply", "android_vr", "ios"],
        ["android_vr", "tv"],
        ["mweb", "web_safari", "tv"],
    ]

    info = None
    last_error: Optional[Exception] = None
    for clients in client_strategies:
        ydl_opts: Dict[str, Any] = {
            **_base_ydl_opts(),
            "skip_download": True,
            "extract_flat": False,
        }
        if clients:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                break
        except Exception as exc:
            last_error = exc
            continue

    if not info:
        raise _format_yt_error(last_error, "Could not extract metadata from this YouTube URL")

    video_id = info.get("id") or "unknown"
    duration = float(info.get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError("Live streams without fixed duration or empty videos are not supported.")

    metadata = VideoMetadata(
        video_id=video_id,
        title=info.get("title") or "Untitled YouTube Video",
        channel=info.get("uploader") or info.get("channel") or "Unknown Channel",
        duration=duration,
        view_count=info.get("view_count"),
        upload_date=info.get("upload_date"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or url,
        categories=list(info.get("categories") or []),
        tags=list(info.get("tags") or [])[:25],
    )

    heatmap_raw = info.get("heatmap") or []
    heatmap: List[HeatmapPoint] = []
    for pt in heatmap_raw:
        try:
            heatmap.append(
                HeatmapPoint(
                    start_time=float(pt["start_time"]),
                    end_time=float(pt["end_time"]),
                    value=float(pt["value"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return metadata, heatmap, info


def _cleanup_partial_downloads(output_dir: Path) -> None:
    for item in output_dir.glob("source.*"):
        try:
            item.unlink()
        except OSError:
            pass


def download_source_video(url: str, output_dir: Path) -> Path:
    """
    Download best compatible H.264 MP4 (<=1080p) into output_dir with multi-client fallbacks
    to avoid YouTube HTTP 403 / bot-check errors.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target_template = str(output_dir / "source.%(ext)s")

    strategies: List[Dict[str, Any]] = [
        {
            "format": (
                "bestvideo[height<=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080]+bestaudio/"
                "best[height<=1080][ext=mp4]/best[height<=1080]/best"
            ),
        },
        {
            "format": (
                "bestvideo[height<=1080][vcodec^=avc1]+bestaudio/"
                "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            ),
            "extractor_args": {"youtube": {"player_client": ["tv_simply", "android_vr", "ios"]}},
        },
        {
            "format": "best[height<=1080]/best",
            "extractor_args": {"youtube": {"player_client": ["tv", "web_safari", "mweb"]}},
        },
    ]

    last_error: Optional[Exception] = None
    for extra in strategies:
        _cleanup_partial_downloads(output_dir)
        ydl_opts: Dict[str, Any] = {
            **_base_ydl_opts(),
            "outtmpl": target_template,
            "merge_output_format": "mp4",
            **extra,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            for candidate in sorted(output_dir.glob("source.*")):
                if (
                    candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
                    and not candidate.name.endswith(".part")
                    and candidate.stat().st_size > 0
                ):
                    return candidate
        except Exception as exc:
            last_error = exc
            continue

    raise _format_yt_error(last_error, "Failed to download YouTube video")


def _parse_json3_subtitles(json3_path: Path) -> List[TranscriptSegment]:
    data = json.loads(json3_path.read_text(encoding="utf-8", errors="ignore"))
    events = data.get("events") or []
    segments: List[TranscriptSegment] = []
    for ev in events:
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        start_ms = float(ev.get("tStartMs", 0))
        dur_ms = float(ev.get("dDurationMs", 2500))
        start = max(0.0, start_ms / 1000.0)
        end = max(start + 0.3, (start_ms + dur_ms) / 1000.0)
        segments.append(TranscriptSegment(start=start, end=end, text=text))
    return _merge_tiny_segments(segments)


def _merge_tiny_segments(segments: List[TranscriptSegment]) -> List[TranscriptSegment]:
    """Merge overly fragmented auto-caption lines into clean 2-6s phrase chunks."""
    if not segments:
        return []
    merged: List[TranscriptSegment] = []
    cur = segments[0].model_copy()

    for nxt in segments[1:]:
        combined_len = len(cur.text) + 1 + len(nxt.text)
        gap = nxt.start - cur.end
        ends_sentence = cur.text.endswith((".", "!", "?"))
        if not ends_sentence and gap < 0.8 and (nxt.end - cur.start) < 6.0 and combined_len < 110:
            cur.text = f"{cur.text} {nxt.text}".strip()
            cur.end = max(cur.end, nxt.end)
        else:
            if cur.end <= cur.start:
                cur.end = cur.start + 0.5
            merged.append(cur)
            cur = nxt.model_copy()

    if cur.end <= cur.start:
        cur.end = cur.start + 0.5
    merged.append(cur)
    return merged


def extract_transcript(
    url: str,
    video_id: str,
    source_video: Optional[Path],
    work_dir: Path,
) -> Tuple[List[TranscriptSegment], str]:
    """
    Extract timestamped transcript using open-source methods in priority order:
    1. youtube-transcript-api (fast, clean manual or auto captions)
    2. yt-dlp json3 subtitles download
    3. Local faster-whisper transcription fallback (when installed)
    """
    if url:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            chosen = None
            source_label = "youtube_subtitles"
            try:
                chosen = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
                source_label = "youtube_subtitles"
            except Exception:
                try:
                    chosen = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
                    source_label = "youtube_auto_captions"
                except Exception:
                    for tr in transcript_list:
                        chosen = tr
                        source_label = "youtube_auto_captions" if tr.is_generated else "youtube_subtitles"
                        break

            if chosen is not None:
                fetched = chosen.fetch()
                segments = []
                for item in fetched:
                    text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else "")
                    start = getattr(item, "start", None)
                    if start is None and isinstance(item, dict):
                        start = item.get("start", 0.0)
                    duration = getattr(item, "duration", None)
                    if duration is None and isinstance(item, dict):
                        duration = item.get("duration", 2.5)
                    cleaned = re.sub(r"\s+", " ", str(text).replace("\n", " ")).strip()
                    if cleaned:
                        s = float(start or 0.0)
                        d = float(duration or 2.0)
                        segments.append(TranscriptSegment(start=s, end=s + max(0.4, d), text=cleaned))
                if segments:
                    return _merge_tiny_segments(segments), source_label
        except Exception:
            pass

        try:
            sub_dir = work_dir / "subs"
            sub_dir.mkdir(parents=True, exist_ok=True)
            ydl_opts = {
                **_base_ydl_opts(),
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "en-US", "en-GB", "en.*"],
                "subtitlesformat": "json3",
                "outtmpl": str(sub_dir / "cap.%(ext)s"),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            json3_files = sorted(sub_dir.glob("*.json3"))
            if json3_files:
                segments = _parse_json3_subtitles(json3_files[0])
                if segments:
                    return segments, "youtube_auto_captions"
        except Exception:
            pass

    if source_video and source_video.exists():
        try:
            from faster_whisper import WhisperModel  # type: ignore

            device = "cpu"
            compute_type = "int8"
            try:
                import torch  # type: ignore

                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
            except Exception:
                pass

            model = WhisperModel("tiny", device=device, compute_type=compute_type)
            raw_segments, _ = model.transcribe(str(source_video), vad_filter=True)
            segments = []
            for seg in raw_segments:
                txt = re.sub(r"\s+", " ", seg.text).strip()
                if txt:
                    segments.append(
                        TranscriptSegment(start=float(seg.start), end=float(seg.end), text=txt)
                    )
            if segments:
                return _merge_tiny_segments(segments), "faster_whisper"
        except Exception:
            pass

    return [], "unavailable"


def compute_audio_energy_profile(source_video: Path, duration: float) -> np.ndarray:
    """
    Extract a 1-second resolution normalized RMS audio energy profile [0.0..1.0]
    using ffmpeg + numpy (no extra audio libraries required).
    """
    n_bins = max(1, int(np.ceil(duration)))
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe or not source_video.exists():
        return np.full(n_bins, 0.5, dtype=np.float32)

    sample_rate = 4000
    cmd = [
        ffmpeg_exe,
        "-v",
        "error",
        "-i",
        str(source_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=240)
        if proc.returncode != 0 or not proc.stdout:
            return np.full(n_bins, 0.5, dtype=np.float32)
        samples = np.frombuffer(proc.stdout, dtype=np.float32)
        if samples.size < sample_rate:
            return np.full(n_bins, 0.5, dtype=np.float32)

        total_secs = samples.size // sample_rate
        trimmed = samples[: total_secs * sample_rate].reshape(total_secs, sample_rate)
        rms = np.sqrt(np.mean(trimmed * trimmed, axis=1) + 1e-10)
        p95 = float(np.percentile(rms, 95)) or 1.0
        norm = np.clip(rms / p95, 0.0, 1.0)
        if norm.size < n_bins:
            norm = np.pad(norm, (0, n_bins - norm.size), mode="edge")
        return norm[:n_bins].astype(np.float32)
    except Exception:
        return np.full(n_bins, 0.5, dtype=np.float32)
