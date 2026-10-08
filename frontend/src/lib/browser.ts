/** Small browser helpers (wake lock, battery, beep). All feature-detected; safe when unsupported. */

interface WakeLockSentinelLike {
  release(): Promise<void>;
}
interface NavigatorExtras {
  wakeLock?: { request(type: "screen"): Promise<WakeLockSentinelLike> };
  getBattery?: () => Promise<{ level: number }>;
}
const nav = () => (typeof navigator === "undefined" ? undefined : (navigator as Navigator & NavigatorExtras));

export async function requestWakeLock(): Promise<WakeLockSentinelLike | null> {
  try {
    return (await nav()?.wakeLock?.request("screen")) ?? null;
  } catch {
    return null;
  }
}

export async function batteryPct(): Promise<number | null> {
  try {
    const b = await nav()?.getBattery?.();
    return b ? Math.round(b.level * 100) : null;
  } catch {
    return null;
  }
}

export function vibrate(p: number | number[]) {
  try {
    nav()?.vibrate?.(p);
  } catch {
    /* unsupported */
  }
}

let ctx: AudioContext | null = null;
export function audioCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

/** Short tone (push-to-talk cue, emergency siren). Not speech. */
export function beep(freq = 880, ms = 120, gain = 0.15) {
  const c = audioCtx();
  if (!c) return;
  const o = c.createOscillator();
  const g = c.createGain();
  o.frequency.value = freq;
  g.gain.value = gain;
  o.connect(g).connect(c.destination);
  o.start();
  o.stop(c.currentTime + ms / 1000);
}

/** Approximate meters between two lat/lng points (used only for the 10 m location-send threshold). */
export function metersBetween(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
