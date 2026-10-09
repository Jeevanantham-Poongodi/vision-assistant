/**
 * FE-06 detection overlay. Pure display of backend-provided FrameResult data —
 * no risk or distance calculation happens here. SVG viewBox = frame_size, so bboxes scale
 * automatically to the displayed media (which must use object-contain).
 */
import type { FrameResult, RiskLevel } from "@/types/contracts";
import { detectionLabel, pathBadgeText } from "./detection-text";

const RISK_MARK: Record<RiskLevel, string> = {
  critical: "‼ CRITICAL",
  high: "! HIGH",
  medium: "▲ MED",
  low: "· LOW",
};
const RISK_DASH: Record<RiskLevel, string | undefined> = {
  critical: undefined,
  high: undefined,
  medium: "10 6",
  low: "3 5",
};

export function DetectionOverlay({ frame }: { frame: FrameResult | null }) {
  if (!frame) return null;
  const { width: w, height: h } = frame.frame_size;
  const fs = Math.max(12, Math.round(w / 34));
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      {/* walking corridor (slight_left + center + slight_right) */}
      <rect x={w * 0.2} y={0} width={w * 0.6} height={h} className="fill-corridor" />
      {[0.2, 0.4, 0.6, 0.8].map((z) => (
        <line
          key={z}
          x1={w * z}
          x2={w * z}
          y1={0}
          y2={h}
          className="stroke-zone"
          strokeWidth={1}
          strokeDasharray="4 6"
        />
      ))}
      {frame.detections.map((d, i) => {
        const { x1, y1, x2, y2 } = d.bbox;
        const label = `${RISK_MARK[d.risk_level]}  ${detectionLabel(d)}`;
        const labelWidth = Math.min(w, label.length * fs * 0.65 + 10);
        const labelX = Math.max(0, Math.min(x1, w - labelWidth));
        const labelFontSize = Math.min(fs, (labelWidth - 10) / (label.length * 0.65));
        const ly = y1 > fs + 8 ? y1 - 6 : y2 + fs + 4;
        return (
          <g key={`${d.track_id ?? "n"}-${i}`} className={`risk-${d.risk_level}`}>
            <rect
              x={x1}
              y={y1}
              width={x2 - x1}
              height={y2 - y1}
              fill="none"
              className="risk-stroke"
              strokeWidth={d.risk_level === "critical" ? 5 : 3}
              strokeDasharray={RISK_DASH[d.risk_level]}
              rx={4}
            />
            <rect
              x={labelX}
              y={ly - fs - 2}
              width={labelWidth}
              height={fs + 8}
              className="risk-fill"
              rx={3}
            />
            <text
              x={labelX + 5}
              y={ly}
              fontSize={labelFontSize}
              className="fill-overlay-ink font-mono"
              fontWeight={700}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function PathBadge({ frame }: { frame: FrameResult | null }) {
  if (!frame) return null;
  const clear = frame.path_clear;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 font-bold ${clear ? "bg-success text-success-foreground" : "bg-risk-high text-overlay-ink"}`}
    >
      <span aria-hidden="true">{clear ? "✓" : "⚠"}</span>
      {pathBadgeText(frame)}
    </span>
  );
}
