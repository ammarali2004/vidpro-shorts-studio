"use client";

import React, { useState } from "react";
import { HeatmapPoint, ShortClipCandidate } from "@/types/shorts";

interface HeatmapChartProps {
  heatmap: HeatmapPoint[];
  duration: number;
  clips: ShortClipCandidate[];
}

function formatTs(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

export function HeatmapChart({ heatmap, duration, clips }: HeatmapChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!heatmap.length || duration <= 0) {
    return null;
  }

  const width = 800;
  const height = 120;
  const maxVal = Math.max(...heatmap.map((p) => p.value), 0.01);

  const points = heatmap.map((pt) => {
    const mid = (pt.start_time + pt.end_time) / 2;
    const x = (mid / duration) * width;
    const y = height - 12 - (pt.value / maxVal) * (height - 28);
    return { x, y, pt };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");

  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${height - 12} L ${points[0].x.toFixed(1)} ${height - 12} Z`;

  const hovered = hoverIdx !== null ? points[hoverIdx] : null;

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4 shadow-inner">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
        <span className="font-medium text-slate-200">
          YouTube &ldquo;Most Replayed&rdquo; Retention Curve
        </span>
        <span className="font-mono text-[11px] text-slate-400">
          {hovered
            ? `${formatTs(hovered.pt.start_time)} • ${Math.round((hovered.pt.value / maxVal) * 100)}% intensity`
            : `0:00 — ${formatTs(duration)}`}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-28 w-full overflow-visible"
        preserveAspectRatio="none"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id="heatFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.48" />
            <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="heatStroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#fb7185" />
            <stop offset="50%" stopColor="#f97316" />
            <stop offset="100%" stopColor="#f43f5e" />
          </linearGradient>
        </defs>

        {clips.map((clip) => {
          const x1 = (clip.start_time / duration) * width;
          const x2 = (clip.end_time / duration) * width;
          return (
            <g key={clip.clip_id}>
              <rect
                x={x1}
                y={4}
                width={Math.max(5, x2 - x1)}
                height={height - 16}
                rx={4}
                fill="rgba(16, 185, 129, 0.16)"
                stroke="rgba(52, 211, 153, 0.7)"
                strokeWidth="1.2"
              />
              <text
                x={x1 + 4}
                y={16}
                fill="#6ee7b7"
                fontSize="10"
                fontWeight="700"
              >
                #{clip.rank}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill="url(#heatFill)" />
        <path
          d={linePath}
          fill="none"
          stroke="url(#heatStroke)"
          strokeWidth="2.4"
          strokeLinejoin="round"
        />

        {points.map((p, idx) => (
          <rect
            key={idx}
            x={Math.max(0, p.x - width / points.length / 2)}
            y={0}
            width={width / points.length}
            height={height}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(idx)}
          />
        ))}

        {hovered && (
          <g>
            <line
              x1={hovered.x}
              y1={4}
              x2={hovered.x}
              y2={height - 12}
              stroke="rgba(255,255,255,0.35)"
              strokeDasharray="3 3"
            />
            <circle
              cx={hovered.x}
              cy={hovered.y}
              r={4.5}
              fill="#fb7185"
              stroke="#fff"
              strokeWidth="1.5"
            />
          </g>
        )}
      </svg>
    </div>
  );
}
