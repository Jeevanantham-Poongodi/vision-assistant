/**
 * Type mirror of API_CONTRACTS.md section 9.1 (services/speech.ts, owned by Coder 4).
 * Coder 1 only consumes these interfaces; the implementation lives in src/services/speech.ts.
 */
import type { VoiceIntent, Warning } from "./contracts";

export interface Utterance {
  text: string;
  priority: number;
  interrupt?: boolean;
  source: "warning" | "guardian" | "system" | "answer";
}
export interface SpeechService {
  unlock(): void;
  speak(u: Utterance): void;
  speakWarnings(ws: Warning[]): void;
  stop(): void;
  repeatLast(): void;
  isSpeaking(): boolean;
  setVoice(opts: { lang?: string; rate?: number; pitch?: number }): void;
}
export interface ListenResult {
  transcript: string;
  confidence: number;
  intent: VoiceIntent;
}
export interface SpeechInput {
  isSupported(): boolean;
  listenOnce(opts?: { lang?: string; timeoutMs?: number }): Promise<ListenResult>;
  parseIntent(transcript: string): VoiceIntent;
}

/** Utterance priorities from contract 9.1. */
export const PRIORITY = { guardian: 70, system: 60, answer: 40 } as const;
