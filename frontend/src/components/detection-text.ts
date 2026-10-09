/** Spoken/visible text for detections, shared by the overlay and the user screen. */
import type { Detection, FrameResult, Motion } from "@/types/contracts";

const MOTION_ICON: Record<Motion, string> = {
  approaching: "↗",
  receding: "↙",
  stationary: "•",
  unknown: "?",
};

export function detectionLabel(d: Detection): string {
  const dist = d.distance_m === null ? "? m" : `${d.distance_m.toFixed(1)} m`;
  return `${d.spoken_name} · ${d.direction.replace("_", " ")} · ${dist} · ${MOTION_ICON[d.motion]} ${d.motion}`;
}

export function pathBadgeText(fr: FrameResult): string {
  if (fr.path_clear) return "Path clear";
  if (fr.clear_distance_m !== null) return `Nearest obstacle ${fr.clear_distance_m.toFixed(1)} m`;
  return "Path not clear";
}
