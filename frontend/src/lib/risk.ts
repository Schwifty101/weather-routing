import type { Level, LevelKey } from "../types";

export interface LevelInfo {
  level: Level;
  key: LevelKey;
  label: string;
  color: string;
  rgb: [number, number, number];
}

/** Colour ramp: green -> yellow -> orange -> red -> deep purple. Distinguishable in greyscale. */
export const LEVELS: LevelInfo[] = [
  { level: 0, key: "low", label: "Low", color: "#2f9e62", rgb: [47, 158, 98] },
  { level: 1, key: "moderate", label: "Moderate", color: "#e6b800", rgb: [230, 184, 0] },
  { level: 2, key: "high", label: "High", color: "#f08a24", rgb: [240, 138, 36] },
  { level: 3, key: "severe", label: "Severe", color: "#d62839", rgb: [214, 40, 57] },
  { level: 4, key: "no_travel", label: "No Travel", color: "#5b1a8f", rgb: [91, 26, 143] },
];

export const levelInfo = (level: number): LevelInfo => LEVELS[Math.min(4, Math.max(0, Math.round(level)))];

/** Continuous colour for a fractional risk score (used when interpolating the heatmap in time). */
export function colorAt(score: number): [number, number, number] {
  const s = Math.min(4, Math.max(0, score));
  const lo = Math.floor(s);
  const hi = Math.min(4, lo + 1);
  const t = s - lo;
  const a = LEVELS[lo].rgb;
  const b = LEVELS[hi].rgb;
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
  ];
}

/** Heatmap blob opacity: faint for Low so the corridor reads as context, strong for Severe+. */
export const alphaAt = (score: number): number => Math.min(0.78, 0.2 + 0.15 * Math.min(4, Math.max(0, score)));

/** Linear interpolation into an hourly series at a fractional hour. */
export function valueAtHour(series: number[], hour: number): number {
  if (series.length === 0) return 0;
  const h = Math.min(series.length - 1, Math.max(0, hour));
  const i = Math.floor(h);
  const j = Math.min(series.length - 1, i + 1);
  return series[i] + (series[j] - series[i]) * (h - i);
}
