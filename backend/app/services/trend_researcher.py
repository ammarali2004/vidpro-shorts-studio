from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Sequence, Tuple

import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.models import (
    CropMode,
    HeatmapPoint,
    ScoreBreakdown,
    ShortClipCandidate,
    TranscriptSegment,
    TrendResearchReport,
    VideoMetadata,
)

FILLER_WORDS = {
    "yeah",
    "like",
    "just",
    "know",
    "right",
    "actually",
    "basically",
    "literally",
    "really",
    "going",
    "gonna",
    "wanna",
    "thing",
    "things",
    "stuff",
    "kind",
    "sort",
    "guys",
    "people",
    "video",
    "subscribe",
    "channel",
    "watch",
    "today",
    "make",
    "sure",
    "want",
    "need",
    "look",
    "said",
    "says",
    "okay",
    "well",
    "also",
    "even",
    "much",
    "very",
    "still",
    "back",
    "time",
    "way",
    "one",
    "two",
    "three",
}

HOOK_PATTERNS: List[Tuple[str, float, str]] = [
    (r"^(why|how|what if|did you know|have you ever)\b", 22.0, "Opens with a curiosity-gap question"),
    (r"\b(secret|nobody tells you|truth about|mistake|stop doing|never do|don't ever)\b", 24.0, "Contrarian or insider hook"),
    (r"\b(\d+\s+(ways|reasons|tips|mistakes|things|steps|rules|secrets))\b", 20.0, "Listicle/numbered promise"),
    (r"\b(insane|crazy|unbelievable|shocking|massive|game.?changer|blown away|wild)\b", 16.0, "High-arousal emotional framing"),
    (r"\b(here'?s the thing|listen carefully|watch this|wait until|the real reason)\b", 18.0, "Direct retention pattern interrupt"),
    (r"\b(fastest|easiest|best|worst|biggest|biggest problem|hidden)\b", 15.0, "Superlative hook that drives clicks"),
]

PAYOFF_PATTERNS = [
    r"\b(that'?s why|so remember|the takeaway|at the end of the day|which means|in short|that changed everything)\b",
    r"[!?]$",
]


def extract_top_keywords(
    metadata: VideoMetadata,
    segments: Sequence[TranscriptSegment],
    top_k: int = 10,
) -> List[str]:
    """Extract representative topic keywords & 2-word phrases using scikit-learn TF-IDF."""
    docs: List[str] = []
    if segments:
        # Group transcript into ~30s chunks so TF-IDF highlights topical peaks
        chunk_text: List[str] = []
        chunk_start = segments[0].start
        for seg in segments:
            chunk_text.append(seg.text)
            if seg.end - chunk_start >= 30.0:
                docs.append(" ".join(chunk_text))
                chunk_text = []
                chunk_start = seg.end
        if chunk_text:
            docs.append(" ".join(chunk_text))

    title_and_tags = f"{metadata.title} {' '.join(metadata.tags[:15])}".strip()
    if title_and_tags:
        docs.insert(0, title_and_tags)

    if not docs:
        return [w for w in re.findall(r"[A-Za-z0-9]{3,}", metadata.title.lower())][:top_k]

    try:
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            max_features=120,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-]{2,}\b",
        )
        matrix = vectorizer.fit_transform(docs)
        terms = vectorizer.get_feature_names_out()
        scores = np.asarray(matrix.mean(axis=0)).ravel()
        # Boost terms that also appear in the title
        title_lower = metadata.title.lower()
        ranked: List[Tuple[str, float]] = []
        for term, score in zip(terms, scores):
            parts = term.split()
            if any(p in FILLER_WORDS for p in parts):
                continue
            boost = 1.45 if term in title_lower else 1.0
            ranked.append((term, float(score) * boost))
        ranked.sort(key=lambda x: x[1], reverse=True)

        selected: List[str] = []
        for term, _ in ranked:
            if not any(term in existing and len(existing) > len(term) for existing in selected):
                selected.append(term)
            if len(selected) >= top_k:
                break
        return selected
    except Exception:
        words = [
            w
            for w in re.findall(r"[a-zA-Z0-9]{4,}", metadata.title.lower())
            if w not in FILLER_WORDS
        ]
        return list(dict.fromkeys(words))[:top_k]


def fetch_youtube_autocomplete_trends(topics: Sequence[str], max_queries: int = 15) -> List[str]:
    """Query public YouTube Search Autocomplete endpoint (no API key required)."""
    suggestions: List[str] = []
    seen = set()
    seeds = list(topics[:4])
    if len(topics) >= 2:
        seeds.append(f"{topics[0]} {topics[1]}")

    with httpx.Client(timeout=4.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for seed in seeds:
            for query in (seed, f"{seed} shorts"):
                try:
                    resp = client.get(
                        "https://suggestqueries.google.com/complete/search",
                        params={"client": "youtube", "ds": "yt", "q": query},
                    )
                    if resp.status_code != 200:
                        continue
                    # Response is JSONP: window.google.ac.h([...])
                    raw = resp.text
                    match = re.search(r"\[.*\]", raw)
                    if not match:
                        continue
                    import json

                    payload = json.loads(match.group(0))
                    if len(payload) >= 2 and isinstance(payload[1], list):
                        for entry in payload[1]:
                            term = entry[0] if isinstance(entry, list) and entry else str(entry)
                            norm = term.strip()
                            if norm and norm.lower() not in seen:
                                seen.add(norm.lower())
                                suggestions.append(norm)
                            if len(suggestions) >= max_queries:
                                return suggestions
                except Exception:
                    continue
    return suggestions


def fetch_google_rising_topics(limit: int = 20) -> List[str]:
    """Fetch public Google Trends daily RSS topics (zero API key)."""
    try:
        with httpx.Client(timeout=4.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get("https://trends.google.com/trending/rss?geo=US")
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            titles: List[str] = []
            for item in root.findall(".//item/title"):
                if item.text:
                    titles.append(item.text.strip())
                if len(titles) >= limit:
                    break
            return titles
    except Exception:
        return []


def run_trend_research(
    metadata: VideoMetadata,
    segments: Sequence[TranscriptSegment],
    heatmap: Sequence[HeatmapPoint],
    transcript_source: str,
) -> TrendResearchReport:
    """Gather open-source trend intelligence from transcript, YouTube Suggest, and Google Trends."""
    topics = extract_top_keywords(metadata, segments, top_k=10)
    yt_queries = fetch_youtube_autocomplete_trends(topics, max_queries=14)
    google_rising = fetch_google_rising_topics(limit=15)

    notes: List[str] = []
    if heatmap:
        peak = max(heatmap, key=lambda h: h.value)
        notes.append(
            f"YouTube Most Replayed retention data available ({len(heatmap)} buckets; peak rewatch spike at {_fmt_ts(peak.start_time)})."
        )
    else:
        notes.append(
            "YouTube Most Replayed heatmap not exposed for this video; scoring uses transcript hooks, search trend alignment, and vocal energy."
        )

    if yt_queries:
        notes.append(
            f"Discovered {len(yt_queries)} live YouTube search autocomplete queries around '{topics[0] if topics else metadata.title}'."
        )
    if google_rising:
        overlap = [
            g for g in google_rising if any(t in g.lower() for t in topics[:5])
        ]
        if overlap:
            notes.append(f"Rising Google Trends overlap detected: {', '.join(overlap[:3])}.")

    return TrendResearchReport(
        extracted_topics=topics,
        youtube_trending_queries=yt_queries,
        google_rising_topics=google_rising[:10],
        has_youtube_heatmap=len(heatmap) > 0,
        transcript_source=transcript_source,
        summary_notes=notes,
    )


def _fmt_ts(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _build_windows_from_transcript(
    segments: Sequence[TranscriptSegment],
    duration: float,
    min_duration: int,
    max_duration: int,
) -> List[Tuple[float, float, str]]:
    """Build candidate time windows aligned to transcript segment boundaries."""
    if not segments:
        # Uniform fallback windows when no speech/captions exist
        step = max(20, (min_duration + max_duration) // 2)
        windows: List[Tuple[float, float, str]] = []
        t = 0.0
        while t + min_duration <= duration:
            end = min(duration, t + step)
            windows.append((t, end, ""))
            t += max(15.0, step * 0.65)
        return windows or [(0.0, min(duration, float(max_duration)), "")]

    windows = []
    n = len(segments)
    i = 0
    while i < n:
        start_t = segments[i].start
        j = i
        texts: List[str] = []
        while j < n:
            texts.append(segments[j].text)
            cur_dur = segments[j].end - start_t
            if cur_dur >= min_duration:
                # Prefer stopping on a sentence boundary once we reach comfortable length
                if cur_dur >= max_duration - 6 or segments[j].text.endswith((".", "!", "?")):
                    if cur_dur <= max_duration:
                        windows.append((start_t, segments[j].end, " ".join(texts)))
                if cur_dur >= max_duration:
                    break
            j += 1

        if j == n and (segments[-1].end - start_t) >= min_duration:
            end_t = min(segments[-1].end, start_t + max_duration)
            windows.append((start_t, end_t, " ".join(texts)))

        # Advance start by ~8-12 seconds for dense candidate coverage
        next_target = start_t + 10.0
        while i < n and segments[i].start < next_target:
            i += 1
        if i == 0:
            i = 1

    return windows


def _score_window(
    start_t: float,
    end_t: float,
    text: str,
    heatmap: Sequence[HeatmapPoint],
    audio_energy: np.ndarray,
    research: TrendResearchReport,
    duration: float,
) -> Tuple[int, ScoreBreakdown, List[str], List[str], str]:
    lower = text.lower()
    words = re.findall(r"[a-zA-Z0-9']+", lower)
    clip_dur = max(1.0, end_t - start_t)

    # 1. Hook strength (opening 140 chars / first sentence)
    opening = text[:160].strip()
    opening_lower = opening.lower()
    hook_score = 44.0
    hook_reasons: List[str] = []
    for pattern, boost, reason in HOOK_PATTERNS:
        if re.search(pattern, opening_lower):
            hook_score += boost
            hook_reasons.append(reason)
    if "?" in opening:
        hook_score += 10.0
    if len(words) >= 15:
        hook_score += 6.0
    hook_score = float(np.clip(hook_score, 20.0, 99.0))

    # 2. Trend & search alignment
    trend_terms = list(research.extracted_topics) + [
        q.lower() for q in research.youtube_trending_queries
    ]
    matched_trends: List[str] = []
    for term in trend_terms:
        tokens = [t for t in term.lower().split() if len(t) >= 3 and t not in FILLER_WORDS]
        if not tokens:
            continue
        if term.lower() in lower or (len(tokens) >= 2 and all(tok in lower for tok in tokens)):
            if term not in matched_trends:
                matched_trends.append(term)
    trend_score = float(np.clip(42.0 + len(matched_trends) * 14.0, 25.0, 98.0))

    # 3. Retention / YouTube Most Replayed heatmap
    if heatmap:
        overlapping = [
            h.value for h in heatmap if h.end_time >= start_t and h.start_time <= end_t
        ]
        if overlapping:
            peak_h = max(overlapping)
            mean_h = sum(overlapping) / len(overlapping)
            heatmap_score = float(np.clip((0.65 * peak_h + 0.35 * mean_h) * 100.0, 18.0, 99.0))
        else:
            heatmap_score = 45.0
    else:
        heatmap_score = 55.0

    # 4. Audio energy & speech pacing
    s_idx = max(0, int(start_t))
    e_idx = min(len(audio_energy), max(s_idx + 1, int(np.ceil(end_t))))
    seg_energy = audio_energy[s_idx:e_idx]
    if seg_energy.size > 0:
        peak_e = float(np.percentile(seg_energy, 85))
        mean_e = float(np.mean(seg_energy))
        dyn_e = float(np.std(seg_energy))
        energy_score = (0.5 * peak_e + 0.35 * mean_e + 0.35 * dyn_e) * 100.0
    else:
        energy_score = 55.0

    wps = len(words) / clip_dur
    if 2.0 <= wps <= 3.9:
        energy_score += 10.0
    elif wps < 1.2:
        energy_score -= 12.0
    energy_score = float(np.clip(energy_score, 20.0, 98.0))

    # 5. Pacing & standalone completeness
    completeness = 60.0
    if 24.0 <= clip_dur <= 52.0:
        completeness += 16.0
    if any(re.search(p, lower[-120:]) for p in PAYOFF_PATTERNS):
        completeness += 14.0
    if start_t > 5.0 and start_t < duration - 10.0:
        completeness += 5.0
    completeness = float(np.clip(completeness, 25.0, 97.0))

    # Weighted viral score
    if heatmap:
        total = (
            0.27 * hook_score
            + 0.23 * trend_score
            + 0.25 * heatmap_score
            + 0.15 * energy_score
            + 0.10 * completeness
        )
    else:
        total = (
            0.34 * hook_score
            + 0.28 * trend_score
            + 0.23 * energy_score
            + 0.15 * completeness
        )

    why_trending: List[str] = []
    if heatmap and heatmap_score >= 68:
        why_trending.append(f"High YouTube 'Most Replayed' rewatch intensity ({int(heatmap_score)}/100).")
    if hook_reasons:
        why_trending.append(f"Strong opening hook: {hook_reasons[0]}.")
    if matched_trends:
        why_trending.append(
            f"Matches trending YouTube searches: {', '.join(matched_trends[:3])}."
        )
    if energy_score >= 70:
        why_trending.append("High vocal energy and fast conversational pacing ideal for retention.")
    if not why_trending:
        why_trending.append("Self-contained high-clarity segment sized cleanly for vertical Shorts.")

    hook_line = _extract_hook_line(text)
    breakdown = ScoreBreakdown(
        hook_strength=int(round(hook_score)),
        trend_alignment=int(round(trend_score)),
        retention_heatmap=int(round(heatmap_score)),
        audio_energy=int(round(energy_score)),
        pacing_completeness=int(round(completeness)),
    )
    return int(round(np.clip(total, 1, 99))), breakdown, why_trending, matched_trends[:5], hook_line


def _extract_hook_line(text: str) -> str:
    if not text:
        return "Watch how this unfolds..."
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    if len(sentence) > 105:
        sentence = sentence[:102].rstrip() + "..."
    return sentence


def _generate_short_title(
    hook_line: str,
    matched_trends: Sequence[str],
    metadata: VideoMetadata,
    rank: int,
) -> str:
    if matched_trends:
        topic = matched_trends[0].title()
        clean_hook = re.sub(r"^(so|and|but|well|okay)[,\s]+", "", hook_line, flags=re.I).strip()
        if len(clean_hook) >= 16 and len(clean_hook) <= 58:
            return clean_hook.rstrip(".")
        return f"{topic}: {clean_hook[:42].rstrip('., ')}..."
    if hook_line and len(hook_line) > 12:
        return hook_line[:62].rstrip("., ")
    return f"{metadata.title[:48]} (Highlight #{rank})"


def _build_hashtags(
    matched_trends: Sequence[str],
    research: TrendResearchReport,
    metadata: VideoMetadata,
) -> List[str]:
    raw_tags = ["shorts", "youtubeshorts", "trending"]
    for item in list(matched_trends) + list(research.extracted_topics[:4]) + list(metadata.categories[:2]):
        slug = re.sub(r"[^a-zA-Z0-9]", "", item.title())
        if slug and len(slug) >= 3 and slug.lower() not in {t.lower() for t in raw_tags}:
            raw_tags.append(slug)
        if len(raw_tags) >= 8:
            break
    return [f"#{t}" for t in raw_tags]


def select_viral_clips(
    metadata: VideoMetadata,
    segments: Sequence[TranscriptSegment],
    heatmap: Sequence[HeatmapPoint],
    audio_energy: np.ndarray,
    research: TrendResearchReport,
    max_clips: int,
    min_duration: int,
    max_duration: int,
    crop_mode: CropMode,
    burn_captions: bool,
) -> List[ShortClipCandidate]:
    """Score candidate windows and pick non-overlapping highest-viral-potential Shorts."""
    windows = _build_windows_from_transcript(
        segments=segments,
        duration=metadata.duration,
        min_duration=min_duration,
        max_duration=max_duration,
    )

    scored = []
    for start_t, end_t, text in windows:
        score, breakdown, why_trending, matched_trends, hook_line = _score_window(
            start_t=start_t,
            end_t=end_t,
            text=text,
            heatmap=heatmap,
            audio_energy=audio_energy,
            research=research,
            duration=metadata.duration,
        )
        scored.append(
            {
                "start": round(start_t, 2),
                "end": round(min(metadata.duration, end_t), 2),
                "text": text,
                "score": score,
                "breakdown": breakdown,
                "why_trending": why_trending,
                "matched_trends": matched_trends,
                "hook_line": hook_line,
            }
        )

    # Sort descending by score and greedily pick non-overlapping clips
    scored.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for cand in scored:
        overlaps = any(
            not (cand["end"] <= prev["start"] + 4.0 or cand["start"] >= prev["end"] - 4.0)
            for prev in chosen
        )
        if overlaps:
            continue
        chosen.append(cand)
        if len(chosen) >= max_clips:
            break

    # Sort final presentation by rank (viral score desc)
    clips: List[ShortClipCandidate] = []
    for idx, cand in enumerate(chosen, start=1):
        title = _generate_short_title(cand["hook_line"], cand["matched_trends"], metadata, idx)
        hashtags = _build_hashtags(cand["matched_trends"], research, metadata)
        excerpt = cand["text"][:320].strip() + ("..." if len(cand["text"]) > 320 else "")
        clips.append(
            ShortClipCandidate(
                clip_id=f"clip_{idx}_{uuid.uuid4().hex[:6]}",
                rank=idx,
                start_time=cand["start"],
                end_time=cand["end"],
                duration=round(cand["end"] - cand["start"], 2),
                viral_score=cand["score"],
                breakdown=cand["breakdown"],
                suggested_title=title,
                hook_line=cand["hook_line"],
                why_trending=cand["why_trending"],
                matched_trends=cand["matched_trends"],
                hashtags=hashtags,
                transcript_excerpt=excerpt or "Visual highlight segment.",
                crop_mode=crop_mode,
                burn_captions=burn_captions,
                status="pending",
            )
        )

    return clips
