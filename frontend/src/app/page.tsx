"use client";

import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Film,
  Flame,
  Layers,
  Loader2,
  Maximize2,
  Search,
  Sparkles,
  TrendingUp,
  Upload,
  UserCheck,
  Youtube,
  Zap,
} from "lucide-react";
import { HeatmapChart } from "@/components/HeatmapChart";
import { ShortCard } from "@/components/ShortCard";
import {
  CropMode,
  JobStage,
  JobStatusResponse,
  ShortClipCandidate,
} from "@/types/shorts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const STAGES: { key: JobStage; label: string }[] = [
  { key: "fetching_video", label: "Fetch Video & Heatmap" },
  { key: "transcribing", label: "Transcript & Audio" },
  { key: "researching_trends", label: "Trend Research" },
  { key: "scoring_clips", label: "Viral Scoring" },
  { key: "rendering_shorts", label: "Render 9:16 MP4s" },
];

const FRAMING_PRESETS: {
  id: CropMode;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
}[] = [
  {
    id: "blur_fill",
    title: "Cinema Full-Frame",
    subtitle: "No zoom • full widescreen + blurred backdrop",
    icon: <Maximize2 className="h-4 w-4 text-rose-400" />,
  },
  {
    id: "hybrid_fit",
    title: "Balanced 4:5",
    subtitle: "Gentle punch-in • preserves context",
    icon: <Layers className="h-4 w-4 text-amber-400" />,
  },
  {
    id: "smart_face",
    title: "Close-Up Face Track",
    subtitle: "Full 9:16 portrait • best for solo vlogs",
    icon: <UserCheck className="h-4 w-4 text-sky-400" />,
  },
  {
    id: "center",
    title: "Center 9:16",
    subtitle: "Tight center vertical crop",
    icon: <Film className="h-4 w-4 text-emerald-400" />,
  },
];

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rem = s % 60;
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${rem.toString().padStart(2, "0")}`
    : `${m}:${rem.toString().padStart(2, "0")}`;
}

export default function HomePage() {
  const [inputMode, setInputMode] = useState<"youtube" | "upload">("youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [maxClips, setMaxClips] = useState(4);
  const [minDuration, setMinDuration] = useState(20);
  const [maxDuration, setMaxDuration] = useState(55);
  const [cropMode, setCropMode] = useState<CropMode>("blur_fill");
  const [burnCaptions, setBurnCaptions] = useState(true);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let active = true;

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
        if (res.status === 404) {
          if (!active) return;
          setError(
            "Job not found (backend may have restarted). Please submit the link again."
          );
          setJobId(null);
          return;
        }
        if (res.ok) {
          const data: JobStatusResponse = await res.json();
          if (!active) return;
          setJob(data);
          if (data.stage === "failed" && data.error) {
            setError(data.error);
          }
          if (data.stage === "completed" || data.stage === "failed") {
            return;
          }
        }
      } catch {
        // Keep polling gently if backend is busy
      }
      if (active) {
        setTimeout(poll, 1500);
      }
    };

    poll();
    return () => {
      active = false;
    };
  }, [jobId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (inputMode === "youtube" && !youtubeUrl.trim()) {
      setError("Please paste a YouTube video link.");
      return;
    }
    if (inputMode === "upload" && !videoFile) {
      setError("Please select an MP4/MOV/WEBM video file to upload.");
      return;
    }

    setSubmitting(true);
    setJob(null);
    setJobId(null);

    try {
      let res: Response;
      if (inputMode === "upload" && videoFile) {
        const form = new FormData();
        form.append("file", videoFile);
        form.append("max_clips", String(maxClips));
        form.append("min_duration", String(minDuration));
        form.append("max_duration", String(maxDuration));
        form.append("crop_mode", cropMode);
        form.append("burn_captions", String(burnCaptions));
        res = await fetch(`${API_BASE}/api/jobs/upload`, {
          method: "POST",
          body: form,
        });
      } else {
        res = await fetch(`${API_BASE}/api/jobs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            youtube_url: youtubeUrl.trim(),
            max_clips: maxClips,
            min_duration: minDuration,
            max_duration: maxDuration,
            crop_mode: cropMode,
            burn_captions: burnCaptions,
            auto_render: true,
          }),
        });
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start job" }));
        throw new Error(err.detail || "Failed to start job");
      }
      const created: JobStatusResponse = await res.json();
      setJob(created);
      setJobId(created.job_id);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to reach the FastAPI backend"
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleClipUpdated = (updated: ShortClipCandidate) => {
    setJob((prev) =>
      prev
        ? {
            ...prev,
            clips: prev.clips.map((c) =>
              c.clip_id === updated.clip_id ? updated : c
            ),
          }
        : prev
    );
  };

  const isRunning =
    job !== null && job.stage !== "completed" && job.stage !== "failed";

  return (
    <div className="studio-grid relative min-h-screen overflow-hidden">
      {/* Animated Ambient Glows */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="animate-float-slow absolute -left-32 -top-32 h-[460px] w-[460px] rounded-full bg-rose-600/20 blur-[130px]" />
        <div className="animate-float-reverse absolute -right-24 top-24 h-[420px] w-[420px] rounded-full bg-orange-500/15 blur-[130px]" />
        <div className="animate-float-slow absolute bottom-0 left-1/3 h-[380px] w-[380px] rounded-full bg-indigo-600/15 blur-[130px]" />
      </div>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Top Navbar */}
        <header className="animate-fade-up mb-8 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-900/50 px-5 py-3.5 backdrop-blur-xl">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 via-pink-500 to-orange-500 shadow-lg shadow-rose-500/30">
              <Film className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white sm:text-xl">
                VidPro Shorts Studio
              </h1>
              <p className="text-[11px] text-slate-400">
                Open-Source Viral Research &bull; Zero API Keys &bull; 9:16 Cinema Export
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
              Local AI + FFmpeg Ready
            </span>
          </div>
        </header>

        {/* Hero Input Panel */}
        <section className="animate-fade-up mb-8 rounded-3xl border border-white/10 bg-slate-900/65 p-6 shadow-2xl shadow-black/50 backdrop-blur-2xl sm:p-8">
          <div className="mb-6 max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-rose-500/25 bg-rose-500/10 px-3 py-1 text-xs font-medium text-rose-300">
              <Zap className="h-3.5 w-3.5" />
              Automated Trend Research + Retention Clipping
            </div>
            <h2 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
              Turn long YouTube videos into{" "}
              <span className="bg-gradient-to-r from-rose-400 via-pink-300 to-amber-300 bg-clip-text text-transparent">
                viral-ready 9:16 Shorts
              </span>
            </h2>
            <p className="mt-2.5 text-sm leading-relaxed text-slate-400">
              Paste any YouTube link. We analyze Most Replayed heatmaps, transcript
              hooks, vocal energy, and live YouTube search trends—then render crisp
              1080&times;1920 Shorts without cropping out your video.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="inline-flex rounded-xl border border-white/10 bg-slate-950/80 p-1 text-xs">
              <button
                type="button"
                onClick={() => setInputMode("youtube")}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition ${
                  inputMode === "youtube"
                    ? "bg-rose-500/20 text-rose-200"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <Youtube className="h-3.5 w-3.5" />
                YouTube Link
              </button>
              <button
                type="button"
                onClick={() => setInputMode("upload")}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition ${
                  inputMode === "upload"
                    ? "bg-rose-500/20 text-rose-200"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <Upload className="h-3.5 w-3.5" />
                Upload Video File
              </button>
            </div>

            <div className="group relative flex flex-col gap-3 rounded-2xl border border-white/10 bg-slate-950/80 p-2 transition focus-within:border-rose-500/60 focus-within:shadow-[0_0_30px_rgba(244,63,94,0.18)] sm:flex-row">
              {inputMode === "youtube" ? (
                <div className="relative flex-1">
                  <Youtube className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-rose-400 transition group-focus-within:scale-110" />
                  <input
                    type="url"
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    placeholder="Paste any YouTube video URL (e.g. https://www.youtube.com/watch?v=...)"
                    className="w-full bg-transparent py-3.5 pl-12 pr-4 text-sm text-white placeholder:text-slate-500 focus:outline-none"
                  />
                </div>
              ) : (
                <label className="flex flex-1 cursor-pointer items-center gap-3 px-4 py-3 text-sm text-slate-300">
                  <Upload className="h-5 w-5 shrink-0 text-rose-400" />
                  <span className="truncate">
                    {videoFile ? videoFile.name : "Choose an MP4, MOV, or WEBM video file..."}
                  </span>
                  <input
                    type="file"
                    accept="video/mp4,video/quicktime,video/webm,video/*"
                    onChange={(e) => setVideoFile(e.target.files?.[0] || null)}
                    className="hidden"
                  />
                </label>
              )}

              <button
                type="submit"
                disabled={submitting || isRunning}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 via-pink-500 to-orange-500 px-6 py-3.5 text-sm font-semibold text-white shadow-lg shadow-rose-500/30 transition-all duration-200 hover:scale-[1.01] hover:brightness-110 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting || isRunning ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Researching &amp; Rendering...
                  </>
                ) : (
                  <>
                    <Flame className="h-4 w-4" />
                    Generate Shorts
                  </>
                )}
              </button>
            </div>

            {/* Visual Framing Mode Selector */}
            <div>
              <div className="mb-2 text-xs font-medium text-slate-400">
                Aspect Ratio &amp; Framing Style
              </div>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {FRAMING_PRESETS.map((preset) => {
                  const selected = cropMode === preset.id;
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => setCropMode(preset.id)}
                      className={`flex items-start gap-3 rounded-2xl border p-3 text-left transition-all duration-200 ${
                        selected
                          ? "border-rose-500/60 bg-rose-500/10 shadow-lg shadow-rose-500/10"
                          : "border-white/10 bg-slate-950/60 hover:border-white/20 hover:bg-slate-900/80"
                      }`}
                    >
                      <div className="mt-0.5 rounded-xl border border-white/10 bg-slate-900 p-2">
                        {preset.icon}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 text-xs font-semibold text-white">
                          {preset.title}
                          {preset.id === "blur_fill" && (
                            <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-emerald-300">
                              Best
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 text-[11px] leading-snug text-slate-400">
                          {preset.subtitle}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Secondary Options Row */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Number of Shorts
                <select
                  value={maxClips}
                  onChange={(e) => setMaxClips(Number(e.target.value))}
                  className="rounded-xl border border-white/10 bg-slate-950/90 px-3 py-2.5 text-xs text-slate-200 focus:border-rose-500 focus:outline-none"
                >
                  {[2, 3, 4, 5, 6, 8].map((n) => (
                    <option key={n} value={n}>
                      Top {n} viral clips
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Min Clip Length
                <select
                  value={minDuration}
                  onChange={(e) => setMinDuration(Number(e.target.value))}
                  className="rounded-xl border border-white/10 bg-slate-950/90 px-3 py-2.5 text-xs text-slate-200 focus:border-rose-500 focus:outline-none"
                >
                  <option value={15}>15 seconds</option>
                  <option value={20}>20 seconds</option>
                  <option value={30}>30 seconds</option>
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Max Clip Length
                <select
                  value={maxDuration}
                  onChange={(e) => setMaxDuration(Number(e.target.value))}
                  className="rounded-xl border border-white/10 bg-slate-950/90 px-3 py-2.5 text-xs text-slate-200 focus:border-rose-500 focus:outline-none"
                >
                  <option value={30}>30 seconds</option>
                  <option value={45}>45 seconds</option>
                  <option value={55}>55 seconds</option>
                  <option value={60}>60 seconds</option>
                </select>
              </label>

              <label className="flex cursor-pointer items-center gap-2.5 self-end rounded-xl border border-white/10 bg-slate-950/90 px-3.5 py-2.5 text-xs text-slate-200 transition hover:border-white/20">
                <input
                  type="checkbox"
                  checked={burnCaptions}
                  onChange={(e) => setBurnCaptions(e.target.checked)}
                  className="h-4 w-4 rounded accent-rose-500"
                />
                Burn-in bold Shorts captions
              </label>
            </div>
          </form>

          {error && (
            <div className="animate-fade-up mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
              <div className="flex items-center gap-2.5">
                <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
                <span>{error}</span>
              </div>
              {error.toLowerCase().includes("upload video file") && (
                <button
                  type="button"
                  onClick={() => {
                    setInputMode("upload");
                    setError(null);
                  }}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20"
                >
                  <Upload className="h-3.5 w-3.5" />
                  Switch to Upload Video
                </button>
              )}
            </div>
          )}
        </section>

        {/* Animated Progress & Stage Stepper */}
        {job && (
          <section className="animate-fade-up mb-8 rounded-3xl border border-white/10 bg-slate-900/70 p-6 backdrop-blur-xl">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5 text-sm font-semibold text-white">
                {job.stage === "completed" ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                ) : job.stage === "failed" ? (
                  <AlertCircle className="h-5 w-5 text-rose-400" />
                ) : (
                  <Loader2 className="h-5 w-5 animate-spin text-rose-400" />
                )}
                <span>{job.message}</span>
              </div>
              <span className="font-mono text-xs font-semibold text-slate-300">
                {job.progress}%
              </span>
            </div>

            <div className="relative mb-5 h-2.5 overflow-hidden rounded-full bg-slate-800/90">
              <div
                className={`relative h-full overflow-hidden rounded-full transition-all duration-500 ease-out ${
                  job.stage === "failed"
                    ? "bg-rose-500"
                    : "bg-gradient-to-r from-rose-500 via-amber-400 to-emerald-400"
                }`}
                style={{ width: `${job.progress}%` }}
              >
                {isRunning && (
                  <div className="animate-shimmer absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-white/40 to-transparent" />
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
              {STAGES.map((st, idx) => {
                const currentIdx = STAGES.findIndex((s) => s.key === job.stage);
                const done =
                  job.stage === "completed" ||
                  (currentIdx !== -1 && idx < currentIdx);
                const active = st.key === job.stage;
                return (
                  <div
                    key={st.key}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition-all duration-300 ${
                      done
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                        : active
                          ? "border-rose-500/50 bg-rose-500/15 text-rose-200 shadow-lg shadow-rose-500/10"
                          : "border-white/5 bg-slate-950/60 text-slate-500"
                    }`}
                  >
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        done
                          ? "bg-emerald-400"
                          : active
                            ? "animate-ping bg-rose-400"
                            : "bg-slate-700"
                      }`}
                    />
                    <span className="truncate font-medium">{st.label}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Video Metadata + Trend Research Insights */}
        {job?.metadata && (
          <section className="animate-fade-up mb-8 grid gap-6 lg:grid-cols-12">
            <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-5 backdrop-blur-xl lg:col-span-5">
              <div className="flex gap-4">
                {job.metadata.thumbnail && (
                  <img
                    src={job.metadata.thumbnail}
                    alt={job.metadata.title}
                    className="h-24 w-40 shrink-0 rounded-2xl border border-white/10 object-cover shadow-lg"
                  />
                )}
                <div className="min-w-0">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                    Source Video
                  </span>
                  <h3 className="mt-0.5 line-clamp-2 text-base font-semibold text-white">
                    {job.metadata.title}
                  </h3>
                  <p className="mt-1 text-xs text-slate-400">{job.metadata.channel}</p>
                  <div className="mt-2 flex flex-wrap gap-3 font-mono text-xs text-slate-300">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5 text-slate-400" />
                      {formatDuration(job.metadata.duration)}
                    </span>
                    {job.metadata.view_count !== null && (
                      <span>{job.metadata.view_count.toLocaleString()} views</span>
                    )}
                  </div>
                </div>
              </div>

              {job.heatmap.length > 0 && (
                <div className="mt-4">
                  <HeatmapChart
                    heatmap={job.heatmap}
                    duration={job.metadata.duration}
                    clips={job.clips}
                  />
                </div>
              )}
            </div>

            {job.research && (
              <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-5 backdrop-blur-xl lg:col-span-7">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-base font-semibold text-white">
                    <TrendingUp className="h-4 w-4 text-emerald-400" />
                    Open-Source Trend &amp; Audience Research
                  </h3>
                  <span className="rounded-full border border-white/10 bg-white/5 px-3 py-0.5 text-[11px] text-slate-300">
                    Transcript: {job.research.transcript_source.replace(/_/g, " ")}
                  </span>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-400">
                      <Activity className="h-3.5 w-3.5 text-amber-400" />
                      Extracted High-Signal Topics
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {job.research.extracted_topics.map((topic) => (
                        <span
                          key={topic}
                          className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200"
                        >
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>

                  {job.research.youtube_trending_queries.length > 0 && (
                    <div>
                      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-400">
                        <Search className="h-3.5 w-3.5 text-sky-400" />
                        Live YouTube Search Demand
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {job.research.youtube_trending_queries.map((q) => (
                          <span
                            key={q}
                            className="rounded-xl border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-200"
                          >
                            {q}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <ul className="space-y-1.5 text-xs text-slate-300">
                    {job.research.summary_notes.map((note, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
                        <span>{note}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Generated Shorts Grid */}
        {job && job.clips.length > 0 && (
          <section className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-xl font-bold text-white">
                Generated Shorts Clips ({job.clips.length})
              </h2>
              <span className="text-xs text-slate-400">
                Ranked by Viral Potential Score (0&ndash;100)
              </span>
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              {job.clips.map((clip, index) => (
                <ShortCard
                  key={clip.clip_id}
                  jobId={job.job_id}
                  clip={clip}
                  apiBase={API_BASE}
                  videoDuration={job.metadata?.duration || 600}
                  index={index}
                  onClipUpdated={handleClipUpdated}
                />
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
