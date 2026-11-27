"use client";

import React, { useEffect, useState } from "react";
import {
  Check,
  Copy,
  Download,
  Loader2,
  RefreshCw,
  Scissors,
  SlidersHorizontal,
  TrendingUp,
} from "lucide-react";
import { CropMode, ShortClipCandidate } from "@/types/shorts";

interface ShortCardProps {
  jobId: string;
  clip: ShortClipCandidate;
  apiBase: string;
  videoDuration: number;
  index: number;
  onClipUpdated: (updated: ShortClipCandidate) => void;
}

function formatTime(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

function ViralScoreRing({ score }: { score: number }) {
  const radius = 19;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(100, Math.max(0, score)) / 100) * circumference;

  const strokeColor =
    score >= 80 ? "#34d399" : score >= 65 ? "#fbbf24" : "#38bdf8";

  return (
    <div className="relative flex h-12 w-12 shrink-0 items-center justify-center">
      <svg className="h-12 w-12 -rotate-90" viewBox="0 0 48 48">
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="4"
        />
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="font-mono text-xs font-bold text-white">{score}</span>
      </div>
    </div>
  );
}

export function ShortCard({
  jobId,
  clip,
  apiBase,
  videoDuration,
  index,
  onClipUpdated,
}: ShortCardProps) {
  const [startTime, setStartTime] = useState<number>(clip.start_time);
  const [endTime, setEndTime] = useState<number>(clip.end_time);
  const [cropMode, setCropMode] = useState<CropMode>(clip.crop_mode);
  const [burnCaptions, setBurnCaptions] = useState<boolean>(clip.burn_captions);
  const [rendering, setRendering] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [cacheBust, setCacheBust] = useState<number>(0);

  useEffect(() => {
    setStartTime(clip.start_time);
    setEndTime(clip.end_time);
    setCropMode(clip.crop_mode);
    setBurnCaptions(clip.burn_captions);
  }, [clip.start_time, clip.end_time, clip.crop_mode, clip.burn_captions]);

  const handleRerender = async () => {
    if (endTime <= startTime + 2) {
      setRenderError("End time must be at least 2 seconds after start time.");
      return;
    }
    setRendering(true);
    setRenderError(null);
    try {
      const res = await fetch(
        `${apiBase}/api/jobs/${jobId}/clips/${clip.clip_id}/render`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            start_time: startTime,
            end_time: endTime,
            crop_mode: cropMode,
            burn_captions: burnCaptions,
          }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Render failed" }));
        throw new Error(err.detail || "Render failed");
      }
      const updated: ShortClipCandidate = await res.json();
      setCacheBust(Date.now());
      onClipUpdated(updated);
    } catch (e) {
      setRenderError(e instanceof Error ? e.message : "Failed to re-render clip");
    } finally {
      setRendering(false);
    }
  };

  const handleCopyMeta = async () => {
    const payload = `${clip.suggested_title}\n\n${clip.hashtags.join(" ")}`;
    await navigator.clipboard.writeText(payload);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const videoSrc = clip.video_url
    ? `${apiBase}${clip.video_url}${cacheBust ? `?v=${cacheBust}` : ""}`
    : null;
  const downloadHref = clip.video_url
    ? `${apiBase}${clip.video_url}?download=true`
    : null;

  return (
    <article
      style={{ animationDelay: `${index * 90}ms` }}
      className="animate-fade-up group flex flex-col overflow-hidden rounded-3xl border border-white/10 bg-slate-900/75 shadow-2xl shadow-black/40 backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:border-rose-500/30"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-white/[0.02] px-5 py-4">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/15 px-2.5 py-0.5 font-semibold text-rose-300">
              Short #{clip.rank}
            </span>
            <span className="font-mono text-[11px] text-slate-300">
              {formatTime(clip.start_time)} – {formatTime(clip.end_time)} ({clip.duration.toFixed(0)}s)
            </span>
            {clip.status === "ready" && !rendering && (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                1080×1920 Ready
              </span>
            )}
          </div>
          <h3
            className="truncate text-base font-semibold text-white"
            title={clip.suggested_title}
          >
            {clip.suggested_title}
          </h3>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden text-right sm:block">
            <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
              Viral Score
            </div>
            <div className="text-xs font-semibold text-slate-200">
              {clip.viral_score >= 80
                ? "High Potential"
                : clip.viral_score >= 65
                  ? "Strong Hook"
                  : "Good Clip"}
            </div>
          </div>
          <ViralScoreRing score={clip.viral_score} />
        </div>
      </div>

      {/* Main Content */}
      <div className="grid flex-1 gap-5 p-5 lg:grid-cols-[240px_1fr]">
        {/* Vertical 9:16 Device Frame Preview (object-contain prevents any browser zoom/crop) */}
        <div className="flex flex-col gap-3">
          <div className="relative aspect-[9/16] w-full overflow-hidden rounded-[22px] border border-white/15 bg-black p-1 shadow-xl shadow-black/60">
            <div className="relative h-full w-full overflow-hidden rounded-[18px] bg-black">
              {clip.status === "ready" && videoSrc ? (
                <video
                  key={videoSrc}
                  src={videoSrc}
                  controls
                  playsInline
                  preload="metadata"
                  poster={
                    clip.thumbnail_url ? `${apiBase}${clip.thumbnail_url}` : undefined
                  }
                  className="h-full w-full object-contain"
                />
              ) : clip.status === "rendering" || rendering ? (
                <div className="flex h-full flex-col items-center justify-center gap-2.5 p-4 text-center text-xs text-slate-300">
                  <Loader2 className="h-7 w-7 animate-spin text-rose-400" />
                  <span>Rendering 9:16 Short...</span>
                </div>
              ) : clip.status === "error" ? (
                <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-xs text-rose-300">
                  <span>Render error: {clip.error || "Unknown error"}</span>
                </div>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-xs text-slate-400">
                  <Scissors className="h-6 w-6 text-slate-500" />
                  <span>Ready to render</span>
                </div>
              )}
            </div>
          </div>

          {downloadHref && clip.status === "ready" && (
            <a
              href={downloadHref}
              download={`short_${clip.rank}.mp4`}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 via-pink-500 to-orange-500 px-3 py-2.5 text-xs font-semibold text-white shadow-lg shadow-rose-500/25 transition-all duration-200 hover:scale-[1.01] hover:brightness-110 active:scale-[0.99]"
            >
              <Download className="h-4 w-4" />
              Download 9:16 MP4
            </a>
          )}
        </div>

        {/* Research & Trim Controls */}
        <div className="flex min-w-0 flex-col justify-between gap-4">
          <div className="space-y-3.5">
            {/* Why it could trend */}
            <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-3.5">
              <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                <TrendingUp className="h-3.5 w-3.5" />
                Why This Could Trend
              </div>
              <ul className="space-y-1.5 text-xs text-slate-300">
                {clip.why_trending.map((reason, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Score Breakdown Bars */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
              {[
                { label: "Hook Strength", val: clip.breakdown.hook_strength },
                { label: "Trend Match", val: clip.breakdown.trend_alignment },
                { label: "Retention Heatmap", val: clip.breakdown.retention_heatmap },
                { label: "Vocal Energy", val: clip.breakdown.audio_energy },
              ].map((metric) => (
                <div key={metric.label}>
                  <div className="mb-1 flex justify-between text-[11px] text-slate-400">
                    <span>{metric.label}</span>
                    <span className="font-mono font-semibold text-slate-200">
                      {metric.val}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-800/90">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-rose-500 to-amber-400 transition-all duration-700 ease-out"
                      style={{ width: `${metric.val}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Transcript excerpt */}
            <div className="rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2.5 text-xs leading-relaxed text-slate-400">
              <span className="font-semibold text-slate-200">Opening Hook: </span>
              &ldquo;{clip.transcript_excerpt}&rdquo;
            </div>

            {/* Hashtags & Copy */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1.5">
                {clip.hashtags.slice(0, 6).map((tag) => (
                  <span
                    key={tag}
                    className="rounded-lg border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <button
                type="button"
                onClick={handleCopyMeta}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:bg-white/10"
              >
                {copied ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-400" /> Copied!
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" /> Copy Title &amp; Tags
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Fine-Tune Trim & Aspect Framing Re-Render */}
          <div className="rounded-2xl border border-white/10 bg-slate-950/65 p-3.5">
            <div className="mb-2.5 flex items-center justify-between text-xs font-medium text-slate-300">
              <span className="flex items-center gap-1.5">
                <SlidersHorizontal className="h-3.5 w-3.5 text-amber-400" />
                Framing &amp; Trim Studio
              </span>
              <span className="font-mono text-[11px] text-slate-400">
                {Math.max(0, endTime - startTime).toFixed(1)}s
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="flex flex-col gap-1 text-[11px] text-slate-400">
                Start (sec)
                <input
                  type="number"
                  step="0.5"
                  min={0}
                  max={Math.max(0, videoDuration - 3)}
                  value={startTime}
                  onChange={(e) => setStartTime(Number(e.target.value))}
                  className="rounded-lg border border-white/10 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white transition focus:border-rose-500 focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1 text-[11px] text-slate-400">
                End (sec)
                <input
                  type="number"
                  step="0.5"
                  min={startTime + 2}
                  max={videoDuration}
                  value={endTime}
                  onChange={(e) => setEndTime(Number(e.target.value))}
                  className="rounded-lg border border-white/10 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white transition focus:border-rose-500 focus:outline-none"
                />
              </label>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
              <select
                value={cropMode}
                onChange={(e) => setCropMode(e.target.value as CropMode)}
                className="rounded-lg border border-white/10 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 focus:border-rose-500 focus:outline-none"
              >
                <option value="blur_fill">Cinema Full-Frame (No Zoom)</option>
                <option value="hybrid_fit">Balanced 4:5 Portrait</option>
                <option value="smart_face">Close-Up Face Track</option>
                <option value="center">Center 9:16 Crop</option>
              </select>

              <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={burnCaptions}
                  onChange={(e) => setBurnCaptions(e.target.checked)}
                  className="h-3.5 w-3.5 rounded accent-rose-500"
                />
                Captions
              </label>

              <button
                type="button"
                disabled={rendering}
                onClick={handleRerender}
                className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20 disabled:opacity-50"
              >
                {rendering ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Re-Render
              </button>
            </div>

            {renderError && (
              <p className="mt-2 text-xs text-rose-400">{renderError}</p>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
