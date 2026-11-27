export type CropMode = "blur_fill" | "hybrid_fit" | "smart_face" | "center";

export type JobStage =
  | "queued"
  | "fetching_video"
  | "transcribing"
  | "researching_trends"
  | "scoring_clips"
  | "rendering_shorts"
  | "completed"
  | "failed";

export interface HeatmapPoint {
  start_time: number;
  end_time: number;
  value: number;
}

export interface ScoreBreakdown {
  hook_strength: number;
  trend_alignment: number;
  retention_heatmap: number;
  audio_energy: number;
  pacing_completeness: number;
}

export interface ShortClipCandidate {
  clip_id: string;
  rank: number;
  start_time: number;
  end_time: number;
  duration: number;
  viral_score: number;
  breakdown: ScoreBreakdown;
  suggested_title: string;
  hook_line: string;
  why_trending: string[];
  matched_trends: string[];
  hashtags: string[];
  transcript_excerpt: string;
  crop_mode: CropMode;
  burn_captions: boolean;
  status: "pending" | "rendering" | "ready" | "error";
  video_url: string | null;
  thumbnail_url: string | null;
  error: string | null;
}

export interface TrendResearchReport {
  extracted_topics: string[];
  youtube_trending_queries: string[];
  google_rising_topics: string[];
  has_youtube_heatmap: boolean;
  transcript_source: string;
  summary_notes: string[];
}

export interface VideoMetadata {
  video_id: string;
  title: string;
  channel: string;
  duration: number;
  view_count: number | null;
  upload_date: string | null;
  thumbnail: string | null;
  webpage_url: string;
  categories: string[];
  tags: string[];
}

export interface JobStatusResponse {
  job_id: string;
  stage: JobStage;
  progress: number;
  message: string;
  error: string | null;
  metadata: VideoMetadata | null;
  heatmap: HeatmapPoint[];
  research: TrendResearchReport | null;
  clips: ShortClipCandidate[];
}
