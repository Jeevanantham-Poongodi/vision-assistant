import type { Warning } from "@/types/contracts";
import type { ListenResult, SpeechInput, SpeechService, Utterance } from "@/types/speech";

type RecognitionAlternative = { transcript: string; confidence: number };
type RecognitionResult = ArrayLike<RecognitionAlternative>;
type RecognitionEvent = { results: ArrayLike<RecognitionResult> };
type RecognitionError = { error: string };

interface BrowserRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionError) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type BrowserRecognitionConstructor = new () => BrowserRecognition;

declare global {
  interface Window {
    SpeechRecognition?: BrowserRecognitionConstructor;
    webkitSpeechRecognition?: BrowserRecognitionConstructor;
  }
}

const getRecognition = () => {
  if (typeof window === "undefined") return undefined;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition;
};

const getSynth = () => (typeof window === "undefined" ? null : window.speechSynthesis);

let voiceOptions = { lang: "en-IN", rate: 1.05, pitch: 1 };
let activeUtterance: SpeechSynthesisUtterance | null = null;
let lastUtterance: Utterance | null = null;
let utteranceQueue: Utterance[] = [];
let activeRecognition: BrowserRecognition | null = null;
let generation = 0;
const recentWarnings = new Map<string, number>();

const playNext = () => {
  const synth = getSynth();
  if (!synth || activeUtterance || utteranceQueue.length === 0) return;
  const item = utteranceQueue.shift();
  if (!item) return;

  const token = ++generation;
  const utterance = new SpeechSynthesisUtterance(item.text);
  utterance.lang = voiceOptions.lang;
  utterance.rate = voiceOptions.rate;
  utterance.pitch = voiceOptions.pitch;
  utterance.onend = utterance.onerror = () => {
    if (generation !== token) return;
    activeUtterance = null;
    playNext();
  };
  activeUtterance = utterance;
  synth.speak(utterance);
};

export const speech: SpeechService = {
  unlock() {
    getSynth()?.resume();
  },
  speak(item) {
    const synth = getSynth();
    if (!synth || !item.text.trim()) return;
    lastUtterance = item;
    if (item.interrupt) {
      utteranceQueue = [];
      generation += 1;
      activeUtterance = null;
      synth.cancel();
    } else if (
      activeUtterance?.text === item.text ||
      utteranceQueue.some((queued) => queued.text === item.text)
    ) {
      return;
    }
    utteranceQueue.push(item);
    playNext();
  },
  speakWarnings(warnings: Warning[]) {
    const now = Date.now();
    const warning = warnings
      .filter((item) => item.speak && now - (recentWarnings.get(item.warning_id) ?? 0) >= 900)
      .sort((left, right) => right.priority - left.priority)[0];
    if (!warning) return;
    recentWarnings.set(warning.warning_id, now);
    speech.speak({
      text: warning.message,
      priority: warning.priority,
      interrupt: warning.interrupt,
      source: "warning",
    });
  },
  stop() {
    utteranceQueue = [];
    generation += 1;
    activeUtterance = null;
    getSynth()?.cancel();
  },
  repeatLast() {
    if (lastUtterance) speech.speak({ ...lastUtterance, interrupt: true });
  },
  isSpeaking: () => getSynth()?.speaking ?? false,
  setVoice(options) {
    voiceOptions = { ...voiceOptions, ...options };
  },
};

const parseIntent = (transcript: string): ListenResult["intent"] => {
  const text = transcript.toLowerCase();
  if (/\b(help|emergency|sos)\b/.test(text)) return "emergency";
  if (/\b(read|reading)\s+(this|the|text|sign)|read text\b/.test(text)) return "read_text";
  if (/\b(path|way)\s+(clear|safe)|any obstacles?\b/.test(text)) return "path_check";
  if (/\b(describe|what is|what's|tell me)\b/.test(text)) return "describe";
  if (/\b(stop speaking|stop talking|be quiet)\b/.test(text)) return "stop_speaking";
  if (/\b(repeat|say that again)\b/.test(text)) return "repeat";
  return "ask";
};

export const speechInput: SpeechInput = {
  isSupported: () => Boolean(getRecognition()),
  parseIntent,
  listenOnce({ lang = voiceOptions.lang, timeoutMs = 7000 } = {}) {
    const Recognition = getRecognition();
    if (!Recognition) return Promise.reject(new Error("Speech recognition is not supported."));
    activeRecognition?.abort();

    return new Promise((resolve, reject) => {
      const recognition = new Recognition();
      let settled = false;
      const timeout = setTimeout(() => fail("Speech recognition timed out."), timeoutMs);
      const finish = () => {
        if (settled) return false;
        settled = true;
        clearTimeout(timeout);
        if (activeRecognition === recognition) activeRecognition = null;
        return true;
      };
      const fail = (message: string) => {
        if (!finish()) return;
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        recognition.abort();
        reject(new Error(message));
      };

      recognition.lang = lang;
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event) => {
        const result = event.results[0]?.[0];
        if (!result?.transcript.trim() || !finish()) return;
        recognition.onerror = null;
        recognition.onend = null;
        recognition.stop();
        resolve({
          transcript: result.transcript.trim(),
          confidence: result.confidence,
          intent: parseIntent(result.transcript),
        });
      };
      recognition.onerror = (event) => fail(event.error || "Speech recognition failed.");
      recognition.onend = () => {
        if (!settled) fail("No speech was detected.");
      };
      activeRecognition = recognition;
      try {
        recognition.start();
      } catch (error) {
        fail(error instanceof Error ? error.message : "Speech recognition could not start.");
      }
    });
  },
};
