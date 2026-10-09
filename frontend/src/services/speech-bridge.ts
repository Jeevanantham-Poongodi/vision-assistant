/**
 * Integration point for Coder 4's speech service (contract 9.1).
 * Coder 1 does NOT implement speech. When `src/services/speech.ts` exists and exports
 * `speech` and `speechInput`, they are used directly. Until then a silent placeholder is used
 * (it logs, never speaks, and reports recognition as unsupported).
 *
 * The bridge also emits every utterance text so the UI can mirror it into an aria-live region.
 */
import type { Warning } from "@/types/contracts";
import type { SpeechInput, SpeechService, Utterance } from "@/types/speech";

interface SpeechModule {
  speech?: SpeechService;
  speechInput?: SpeechInput;
  default?: SpeechService;
}

const mods = import.meta.glob<SpeechModule>("./speech.ts", { eager: true });
const mod: SpeechModule | undefined = Object.values(mods)[0];

const placeholder: SpeechService = {
  unlock() {},
  speak(u) {
    console.info("[speech] (Coder 4 speech.ts not installed)", u.source, u.text);
  },
  speakWarnings(ws) {
    console.info(
      "[speech] (Coder 4 speech.ts not installed) warnings",
      ws.map((w) => w.message),
    );
  },
  stop() {},
  repeatLast() {},
  isSpeaking: () => false,
  setVoice() {},
};
const placeholderInput: SpeechInput = {
  isSupported: () => false,
  listenOnce: () => Promise.reject(new Error("speechInput not installed")),
  parseIntent: () => "ask",
};

const svc: SpeechService = mod?.speech ?? mod?.default ?? placeholder;
export const speechInput: SpeechInput = mod?.speechInput ?? placeholderInput;
export const speechInstalled = Boolean(mod?.speech ?? mod?.default);

type Listener = (text: string, kind: Utterance["source"]) => void;
const listeners = new Set<Listener>();
export function onSpoken(l: Listener) {
  listeners.add(l);
  return () => listeners.delete(l);
}
const emit = (t: string, k: Utterance["source"]) => listeners.forEach((l) => l(t, k));

/** Thin pass-through: all queue, priority, dedupe and interrupt rules stay inside Coder 4's service. */
export const speech: SpeechService = {
  unlock: () => svc.unlock(),
  speak: (u) => {
    emit(u.text, u.source);
    svc.speak(u);
  },
  speakWarnings: (ws: Warning[]) => {
    for (const w of ws) if (w.speak) emit(w.message, "warning");
    svc.speakWarnings(ws);
  },
  stop: () => svc.stop(),
  repeatLast: () => svc.repeatLast(),
  isSpeaking: () => svc.isSpeaking(),
  setVoice: (o) => svc.setVoice(o),
};
