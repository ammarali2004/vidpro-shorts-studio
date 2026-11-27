from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Sequence

import cv2
import numpy as np

from app.models import CropMode, TranscriptSegment
from app.services.youtube_service import find_ffmpeg_executable


def _detect_speaker_center_x_ratio(
    video_path: Path,
    start_time: float,
    end_time: float,
    samples: int = 10,
) -> float:
    """
    Use OpenCV Haar cascades (frontal + profile) to estimate the speaker's
    normalized horizontal position [0.15..0.85] across the clip without heavy TF imports.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.5

    xs: List[float] = []
    timestamps = np.linspace(
        start_time + 0.3, max(start_time + 0.5, end_time - 0.3), samples
    )

    frontal = None
    profile = None
    try:
        frontal = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        profile = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_profileface.xml"
        )
    except Exception:
        pass

    try:
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(ts) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            if w <= 0 or h <= 0:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = []
            if frontal is not None and not frontal.empty():
                faces = frontal.detectMultiScale(gray, 1.15, 4, minSize=(40, 40))
            if len(faces) == 0 and profile is not None and not profile.empty():
                faces = profile.detectMultiScale(gray, 1.15, 4, minSize=(40, 40))

            if len(faces) > 0:
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                cx = (fx + fw / 2.0) / float(w)
                xs.append(float(np.clip(cx, 0.15, 0.85)))
    finally:
        cap.release()

    if not xs:
        return 0.5
    return float(np.median(xs))


def _format_ass_time(seconds: float) -> str:
    s = max(0.0, seconds)
    hrs = int(s // 3600)
    mins = int((s % 3600) // 60)
    secs = int(s % 60)
    cs = int(round((s - int(s)) * 100)) % 100
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


def _write_shorts_ass_subtitles(
    segments: Sequence[TranscriptSegment],
    start_time: float,
    end_time: float,
    ass_path: Path,
    margin_v: int = 300,
) -> bool:
    """Create bold Shorts-style ASS subtitles synchronized to [0, clip_duration]."""
    clip_events: List[str] = []
    for seg in segments:
        if seg.end <= start_time or seg.start >= end_time:
            continue
        rel_start = max(0.0, seg.start - start_time)
        rel_end = min(end_time - start_time, seg.end - start_time)
        if rel_end - rel_start < 0.25:
            continue

        words = seg.text.strip().split()
        if not words:
            continue

        chunk_size = 4
        chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_dur = (rel_end - rel_start) / len(chunks)
        for idx, chunk in enumerate(chunks):
            c_start = rel_start + idx * chunk_dur
            c_end = rel_start + (idx + 1) * chunk_dur
            line = " ".join(chunk).upper().replace("{", "").replace("}", "")
            clip_events.append(
                f"Dialogue: 0,{_format_ass_time(c_start)},{_format_ass_time(c_end)},Shorts,,0,0,0,,{line}"
            )

    if not clip_events:
        return False

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Shorts,Arial,62,&H00FFFFFF,&H0000FFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_path.write_text(header + "\n".join(clip_events) + "\n", encoding="utf-8")
    return True


def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape Windows path for FFmpeg libass filter argument."""
    posix = path.resolve().as_posix()
    return posix.replace(":", "\\:")


def render_vertical_short(
    source_video: Path,
    output_mp4: Path,
    thumbnail_jpg: Path,
    start_time: float,
    end_time: float,
    crop_mode: CropMode,
    burn_captions: bool,
    segments: Sequence[TranscriptSegment],
    work_dir: Path,
    clip_id: str,
) -> None:
    """Render a 1080x1920 9:16 H.264 MP4 Short clip + thumbnail using FFmpeg."""
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(
            "FFmpeg executable not found. Please ensure FFmpeg is installed and accessible."
        )

    duration = max(1.0, end_time - start_time)
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(source_video))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    cap.release()
    if src_w <= 0 or src_h <= 0:
        src_w, src_h = 1920, 1080

    # Position captions cleanly below the video frame for cinema/hybrid modes
    margin_v = 320 if crop_mode in (CropMode.BLUR_FILL, CropMode.HYBRID_FIT) else 230
    ass_path = work_dir / f"{clip_id}.ass"
    has_ass = False
    if burn_captions and segments:
        has_ass = _write_shorts_ass_subtitles(
            segments, start_time, end_time, ass_path, margin_v=margin_v
        )

    if crop_mode == CropMode.BLUR_FILL:
        # Full-frame 16:9 preserved cleanly (zero zoom/cut-off) over cinematic blurred 9:16 canvas
        fg = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=30:8,eq=brightness=-0.16:saturation=1.15[bgblur];"
            "[fg]scale=1080:-2:force_original_aspect_ratio=decrease[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:max(140\\,(H-h)/2-70)[v]"
        )
        if has_ass:
            fg = fg.replace(
                "[v]",
                "[vpre];[vpre]ass='" + _escape_ffmpeg_filter_path(ass_path) + "'[v]",
            )
        filter_args = ["-filter_complex", fg, "-map", "[v]", "-map", "0:a?"]

    elif crop_mode == CropMode.HYBRID_FIT:
        # Balanced 1:1 / 4:5 portrait crop centered on speaker + ambient blurred 9:16 backdrop
        center_ratio = _detect_speaker_center_x_ratio(source_video, start_time, end_time)
        target_aspect = 0.85  # ~4:5 vertical-friendly without extreme 9:16 zoom
        if src_w / src_h > target_aspect:
            crop_h = src_h - (src_h % 2)
            crop_w = int(round(crop_h * target_aspect))
            crop_w -= crop_w % 2
            cx_px = int(round(center_ratio * src_w))
            crop_x = max(0, min(src_w - crop_w, cx_px - crop_w // 2))
            crop_y = 0
        else:
            crop_w = src_w - (src_w % 2)
            crop_h = int(round(crop_w / target_aspect))
            crop_h = min(src_h, crop_h - (crop_h % 2))
            crop_x = 0
            crop_y = max(0, (src_h - crop_h) // 2)

        fg = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=30:8,eq=brightness=-0.18:saturation=1.12[bgblur];"
            f"[fg]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
            "scale=1080:-2:flags=lanczos[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:max(80\\,(H-h)/2-50)[v]"
        )
        if has_ass:
            fg = fg.replace(
                "[v]",
                "[vpre];[vpre]ass='" + _escape_ffmpeg_filter_path(ass_path) + "'[v]",
            )
        filter_args = ["-filter_complex", fg, "-map", "[v]", "-map", "0:a?"]

    else:
        center_ratio = 0.5
        if crop_mode == CropMode.SMART_FACE:
            center_ratio = _detect_speaker_center_x_ratio(
                source_video, start_time, end_time
            )

        target_aspect = 9.0 / 16.0
        if src_w / src_h > target_aspect:
            crop_h = src_h
            crop_w = int(round(src_h * target_aspect))
            crop_w -= crop_w % 2
            cx_px = int(round(center_ratio * src_w))
            crop_x = max(0, min(src_w - crop_w, cx_px - crop_w // 2))
            crop_y = 0
        else:
            crop_w = src_w - (src_w % 2)
            crop_h = int(round(crop_w / target_aspect))
            crop_h = min(src_h, crop_h - (crop_h % 2))
            crop_x = 0
            crop_y = max(0, (src_h - crop_h) // 2)

        vf_parts = [
            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
            "scale=1080:1920:flags=lanczos",
        ]
        if has_ass:
            vf_parts.append(f"ass='{_escape_ffmpeg_filter_path(ass_path)}'")
        filter_args = ["-vf", ",".join(vf_parts)]

    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss",
        f"{start_time:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source_video),
        *filter_args,
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_mp4),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    if proc.returncode != 0 or not output_mp4.exists():
        if has_ass:
            return render_vertical_short(
                source_video=source_video,
                output_mp4=output_mp4,
                thumbnail_jpg=thumbnail_jpg,
                start_time=start_time,
                end_time=end_time,
                crop_mode=crop_mode,
                burn_captions=False,
                segments=segments,
                work_dir=work_dir,
                clip_id=clip_id,
            )
        raise RuntimeError(f"FFmpeg failed ({proc.returncode}): {proc.stderr[-500:]}")

    thumb_cmd = [
        ffmpeg_exe,
        "-y",
        "-ss",
        f"{min(1.5, duration * 0.25):.2f}",
        "-i",
        str(output_mp4),
        "-vframes",
        "1",
        "-q:v",
        "3",
        str(thumbnail_jpg),
    ]
    subprocess.run(thumb_cmd, capture_output=True, check=False, timeout=30)
