export type WarningRiskLevel = "critical" | "high" | "medium" | "low";

export interface Warning {
  warning_id?: string;
  track_id: number | null;
  class_name: string;
  direction?: string;
  risk_level: WarningRiskLevel;
  priority: number;
  message: string;
  short_text?: string;
  speak: boolean;
  interrupt: boolean;
  rule?: string;
}

export interface Utterance {
  text: string;
  priority: number;
  interrupt?: boolean;
  source: "warning" | "guardian" | "system" | "answer";
  timestamp?: number;
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

interface QueuedUtterance {
  utterance: Utterance;
  order: number;
}

interface WarningState {
  riskLevel: WarningRiskLevel;
  lastSpokenAt: number | null;
}

const MAX_QUEUE_LENGTH = 2;
const MAX_UTTERANCE_AGE_MS = 2_000;
const DUPLICATE_WINDOW_MS = 3_000;

const WARNING_COOLDOWNS_MS: Record<Exclude<WarningRiskLevel, "low">, number> = {
  critical: 1_500,
  high: 3_000,
  medium: 6_000,
};

const RISK_RANK: Record<WarningRiskLevel, number> = {
  critical: 3,
  high: 2,
  medium: 1,
  low: 0,
};

function isRiskLevel(value: unknown): value is WarningRiskLevel {
  return value === "critical" || value === "high" || value === "medium" || value === "low";
}

function warningCooldownKey(warning: Warning): string {
  if (
    typeof warning.track_id === "number" &&
    Number.isFinite(warning.track_id)
  ) {
    return `track:${warning.track_id}`;
  }
  const shortTextDirection =
    typeof warning.short_text === "string"
      ? warning.short_text.split("·")[1]?.trim()
      : undefined;
  const direction =
    (typeof warning.direction === "string" && warning.direction.trim()) ||
    shortTextDirection ||
    "unknown";
  const className =
    typeof warning.class_name === "string" ? warning.class_name : "unknown";
  return `class:${className}:${direction}`;
}

export class WebSpeechService implements SpeechService {
  private queue: QueuedUtterance[] = [];
  private current: SpeechSynthesisUtterance | null = null;
  private currentAudio: HTMLAudioElement | null = null;
  private currentAudioUrl: string | null = null;
  private fallbackPending = false;
  private fallbackGeneration = 0;
  private fallbackAbort: AbortController | null = null;
  private lastSpoken: Utterance | null = null;
  private sequence = 0;
  private readonly recentMessages = new Map<string, number>();
  private readonly warningStates = new Map<string, WarningState>();
  private voiceOptions: Required<Pick<SpeechSynthesisVoice, "lang">> & {
    rate: number;
    pitch: number;
  } = {
    lang: "en-IN",
    rate: 1.05,
    pitch: 1,
  };

  private get synthesis(): SpeechSynthesis | null {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return null;
    }
    return window.speechSynthesis;
  }

  unlock(): void {
    const synthesis = this.synthesis;
    if (!synthesis || typeof SpeechSynthesisUtterance === "undefined") {
      return;
    }

    try {
      const silentUtterance = new SpeechSynthesisUtterance("");
      silentUtterance.lang = this.voiceOptions.lang;
      silentUtterance.rate = this.voiceOptions.rate;
      silentUtterance.pitch = this.voiceOptions.pitch;
      silentUtterance.volume = 0;
      synthesis.speak(silentUtterance);
    } catch {
      // Some browsers expose speechSynthesis but reject calls before user activation.
    }
  }

  speak(utterance: Utterance): void {
    this.enqueue(utterance);
  }

  speakWarnings(warnings: Warning[]): void {
    if (!Array.isArray(warnings)) {
      return;
    }

    const now = Date.now();
    const sortedWarnings = warnings
      .filter(
        (warning): warning is Warning =>
          Boolean(warning) &&
          typeof warning === "object" &&
          warning.speak === true &&
          typeof warning.message === "string" &&
          warning.message.trim().length > 0 &&
          typeof warning.priority === "number" &&
          Number.isFinite(warning.priority) &&
          isRiskLevel(warning.risk_level),
      )
      .map((warning, index) => ({ warning, index }))
      .sort(
        (first, second) =>
          second.warning.priority - first.warning.priority || first.index - second.index,
      );

    for (const { warning } of sortedWarnings) {
      if (warning.risk_level === "low") {
        continue;
      }

      const key = warningCooldownKey(warning);
      const previous = this.warningStates.get(key);
      const escalated =
        previous !== undefined &&
        RISK_RANK[warning.risk_level] > RISK_RANK[previous.riskLevel];

      if (
        previous?.lastSpokenAt !== null &&
        previous?.lastSpokenAt !== undefined &&
        !escalated &&
        now - previous.lastSpokenAt < WARNING_COOLDOWNS_MS[warning.risk_level]
      ) {
        previous.riskLevel = warning.risk_level;
        continue;
      }

      const accepted = this.enqueue(
        {
          text: warning.message,
          priority: warning.priority,
          interrupt: warning.interrupt,
          source: "warning",
          timestamp: now,
        },
        now,
      );

      if (accepted) {
        this.warningStates.set(key, {
          riskLevel: warning.risk_level,
          lastSpokenAt: now,
        });
      } else if (previous) {
        previous.riskLevel = warning.risk_level;
      }
    }
  }

  stop(): void {
    this.queue = [];
    this.current = null;
    this.recentMessages.clear();
    this.warningStates.clear();
    this.cancelFallbackAudio();
    try {
      this.synthesis?.cancel();
    } catch {
      // Keep the service reset even if the browser rejects cancellation.
    }
  }

  repeatLast(): void {
    if (!this.lastSpoken) {
      return;
    }
    this.enqueue(
      {
        ...this.lastSpoken,
        timestamp: Date.now(),
      },
      Date.now(),
      true,
    );
  }

  isSpeaking(): boolean {
    return this.current !== null || this.currentAudio !== null || this.fallbackPending;
  }

  setVoice(options: { lang?: string; rate?: number; pitch?: number }): void {
    if (!options || typeof options !== "object") {
      return;
    }
    if (typeof options.lang === "string" && options.lang.trim()) {
      this.voiceOptions.lang = options.lang.trim();
    }
    if (typeof options.rate === "number" && Number.isFinite(options.rate)) {
      this.voiceOptions.rate = Math.min(10, Math.max(0.1, options.rate));
    }
    if (typeof options.pitch === "number" && Number.isFinite(options.pitch)) {
      this.voiceOptions.pitch = Math.min(2, Math.max(0, options.pitch));
    }
  }

  setLanguage(language: "en-IN" | "ta-IN"): void {
    this.setVoice({ lang: language });
  }

  private enqueue(
    utterance: Utterance,
    now = Date.now(),
    bypassAgeAndDuplicateChecks = false,
  ): boolean {
    if (
      typeof window === "undefined" ||
      (!this.synthesis && typeof window.fetch !== "function") ||
      !utterance ||
      typeof utterance.text !== "string" ||
      !utterance.text.trim() ||
      typeof utterance.priority !== "number" ||
      !Number.isFinite(utterance.priority)
    ) {
      return false;
    }

    const timestamp =
      typeof utterance.timestamp === "number" && Number.isFinite(utterance.timestamp)
        ? utterance.timestamp
        : now;
    if (!bypassAgeAndDuplicateChecks && now - timestamp > MAX_UTTERANCE_AGE_MS) {
      return false;
    }

    this.pruneRecentMessages(now);
    const previousMessageTime = this.recentMessages.get(utterance.text);
    if (
      !bypassAgeAndDuplicateChecks &&
      previousMessageTime !== undefined &&
      now - previousMessageTime < DUPLICATE_WINDOW_MS
    ) {
      return false;
    }

    const entry: QueuedUtterance = {
      utterance: { ...utterance, timestamp },
      order: this.sequence++,
    };

    if (this.queue.length >= MAX_QUEUE_LENGTH) {
      const lowestPriorityEntry = this.queue[this.queue.length - 1];
      if (entry.utterance.priority <= lowestPriorityEntry.utterance.priority) {
        return false;
      }
      this.queue.pop();
    }

    this.queue.push(entry);
    this.queue.sort(
      (first, second) =>
        second.utterance.priority - first.utterance.priority || first.order - second.order,
    );
    this.recentMessages.set(utterance.text, now);

    if (utterance.interrupt && (this.current || this.currentAudio || this.fallbackPending)) {
      this.current = null;
      this.cancelFallbackAudio();
      try {
        this.synthesis?.cancel();
      } catch {
        // Continue with the newly queued utterance if cancellation is unavailable.
      }
    }

    this.processQueue();
    return true;
  }

  private processQueue(): void {
    if (this.current || this.currentAudio || this.fallbackPending || this.queue.length === 0) {
      return;
    }

    const entry = this.queue.shift();
    if (!entry) {
      return;
    }

    const now = Date.now();
    if (now - (entry.utterance.timestamp ?? now) > MAX_UTTERANCE_AGE_MS) {
      this.processQueue();
      return;
    }

    const synthesis = this.synthesis;
    if (synthesis && typeof SpeechSynthesisUtterance !== "undefined") {
      this.speakWithBrowser(synthesis, entry.utterance);
    } else {
      void this.speakWithServer(entry.utterance);
    }
  }

  private speakWithBrowser(
    synthesis: SpeechSynthesis,
    utterance: Utterance,
  ): void {
    const nativeUtterance = new SpeechSynthesisUtterance(utterance.text);
    nativeUtterance.lang = this.voiceOptions.lang;
    nativeUtterance.rate = this.voiceOptions.rate;
    nativeUtterance.pitch = this.voiceOptions.pitch;
    const voices =
      typeof synthesis.getVoices === "function" ? synthesis.getVoices() : [];
    const language = this.voiceOptions.lang.toLowerCase();
    const selectedVoice =
      voices.find((voice) => voice.lang.toLowerCase() === language) ??
      (language === "ta-in"
        ? voices.find((voice) => voice.lang.toLowerCase().startsWith("ta-"))
        : undefined);
    if (selectedVoice) {
      nativeUtterance.voice = selectedVoice;
    }

    this.current = nativeUtterance;
    this.lastSpoken = utterance;

    const finish = (): void => {
      if (this.current !== nativeUtterance) {
        return;
      }
      this.current = null;
      this.processQueue();
    };
    nativeUtterance.onend = finish;
    nativeUtterance.onerror = finish;

    try {
      synthesis.speak(nativeUtterance);
    } catch {
      finish();
    }
  }

  private async speakWithServer(utterance: Utterance): Promise<void> {
    if (typeof window === "undefined" || typeof window.fetch !== "function") {
      this.processQueue();
      return;
    }
    if (typeof Audio === "undefined" || typeof URL.createObjectURL !== "function") {
      this.processQueue();
      return;
    }

    const generation = ++this.fallbackGeneration;
    const controller = new AbortController();
    this.fallbackAbort = controller;
    this.fallbackPending = true;
    this.lastSpoken = utterance;

    try {
      const response = await window.fetch("/api/v1/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: utterance.text,
          lang: this.voiceOptions.lang,
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`TTS request failed with status ${response.status}`);
      }
      const audioBlob = await response.blob();
      if (generation !== this.fallbackGeneration) {
        return;
      }

      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      this.currentAudioUrl = audioUrl;
      this.currentAudio = audio;
      audio.onended = () => this.finishServerAudio(generation);
      audio.onerror = () => this.finishServerAudio(generation);
      await audio.play();
    } catch {
      this.finishServerAudio(generation);
    } finally {
      if (this.fallbackAbort === controller) {
        this.fallbackAbort = null;
      }
    }
  }

  private finishServerAudio(generation: number): void {
    if (generation !== this.fallbackGeneration) {
      return;
    }
    this.currentAudio = null;
    this.fallbackPending = false;
    this.revokeCurrentAudioUrl();
    this.processQueue();
  }

  private cancelFallbackAudio(): void {
    this.fallbackGeneration += 1;
    this.fallbackAbort?.abort();
    this.fallbackAbort = null;
    this.fallbackPending = false;
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
      this.currentAudio = null;
    }
    this.revokeCurrentAudioUrl();
  }

  private revokeCurrentAudioUrl(): void {
    if (this.currentAudioUrl) {
      URL.revokeObjectURL(this.currentAudioUrl);
      this.currentAudioUrl = null;
    }
  }

  private pruneRecentMessages(now: number): void {
    for (const [text, timestamp] of this.recentMessages) {
      if (now - timestamp >= DUPLICATE_WINDOW_MS) {
        this.recentMessages.delete(text);
      }
    }
  }
}

export const speechService: SpeechService = new WebSpeechService();
export default speechService;
