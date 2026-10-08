export type VoiceIntentType =
  | "EMERGENCY"
  | "QUERY_ENVIRONMENT"
  | "READ_TEXT"
  | "DESCRIBE_SCENE"
  | "NAVIGATE"
  | "STOP"
  | "REPEAT"
  | "UNKNOWN";

export interface VoiceIntent {
  intent: VoiceIntentType;
  rawTranscript: string;
  confidence: number;
  parameters?: Record<string, string>;
}

export interface SpeechInputOptions {
  lang?: string;
  timeoutMs?: number;
}

export interface SpeechInput {
  isSupported(): boolean;
  listenOnce(opts?: SpeechInputOptions): Promise<VoiceIntent>;
  stopListening(): void;
}

interface RecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface RecognitionResult {
  readonly length: number;
  readonly isFinal: boolean;
  [index: number]: RecognitionAlternative;
}

interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<RecognitionResult>;
}

interface RecognitionErrorEvent {
  readonly error: string;
}

interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface RecognitionConstructor {
  new (): Recognition;
}

type RecognitionWindow = Window & {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
};

interface ActiveListen {
  recognition: Recognition;
  resolve: (intent: VoiceIntent) => void;
  timeout: ReturnType<typeof setTimeout>;
  settled: boolean;
}

interface ActiveRecording {
  resolve: (intent: VoiceIntent) => void;
  language: string;
  recorder: MediaRecorder | null;
  stream: MediaStream | null;
  chunks: BlobPart[];
  timeout: ReturnType<typeof setTimeout>;
  uploadAbort: AbortController | null;
  settled: boolean;
  canceled: boolean;
}

const DEFAULT_LANGUAGE = "en-IN";
const DEFAULT_TIMEOUT_MS = 6_000;
const MAX_TIMEOUT_MS = 60_000;
const STT_ENDPOINT = "/api/v1/stt";

function normalizeTranscript(transcript: string): string {
  return transcript
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}\s']/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function containsPhrase(transcript: string, phrase: string): boolean {
  return ` ${transcript} `.includes(` ${phrase} `);
}

export class WebSpeechInput implements SpeechInput {
  private activeListen: ActiveListen | null = null;
  private activeRecording: ActiveRecording | null = null;

  isSupported(): boolean {
    if (this.getRecognitionConstructor()) {
      return true;
    }
    return (
      typeof navigator !== "undefined" &&
      typeof MediaRecorder !== "undefined" &&
      typeof navigator.mediaDevices?.getUserMedia === "function"
    );
  }

  listenOnce(options: SpeechInputOptions = {}): Promise<VoiceIntent> {
    this.stopListening();

    const RecognitionClass = this.getRecognitionConstructor();
    if (!RecognitionClass) {
      return this.listenWithServer(options);
    }

    let recognition: Recognition;
    try {
      recognition = new RecognitionClass();
    } catch {
      return Promise.resolve(this.createIntent("", 0));
    }
    recognition.lang =
      typeof options.lang === "string" && options.lang.trim()
        ? options.lang.trim()
        : DEFAULT_LANGUAGE;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    return new Promise<VoiceIntent>((resolve) => {
      const timeoutMs =
        typeof options.timeoutMs === "number" && Number.isFinite(options.timeoutMs)
          ? Math.min(MAX_TIMEOUT_MS, Math.max(1, options.timeoutMs))
          : DEFAULT_TIMEOUT_MS;
      const active: ActiveListen = {
        recognition,
        resolve,
        timeout: setTimeout(() => {
          this.finishListen(active, "", 0, true);
        }, timeoutMs),
        settled: false,
      };
      this.activeListen = active;

      recognition.onresult = (event): void => {
        const result = event.results[event.resultIndex];
        const alternative = result?.[0];
        const transcript =
          typeof alternative?.transcript === "string" ? alternative.transcript.trim() : "";
        const confidence =
          typeof alternative?.confidence === "number" &&
          Number.isFinite(alternative.confidence)
            ? Math.min(1, Math.max(0, alternative.confidence))
            : 0;
        this.finishListen(active, transcript, confidence);
      };

      recognition.onerror = (): void => {
        this.finishListen(active, "", 0);
      };
      recognition.onend = (): void => {
        this.finishListen(active, "", 0);
      };

      try {
        recognition.start();
      } catch {
        this.finishListen(active, "", 0);
      }
    });
  }

  stopListening(): void {
    const active = this.activeListen;
    if (active) {
      this.finishListen(active, "", 0, true);
    }
    if (this.activeRecording) {
      this.cancelRecording(this.activeRecording);
    }
  }

  parseIntent(transcript: string): VoiceIntent {
    const rawTranscript = typeof transcript === "string" ? transcript : "";
    const normalized = normalizeTranscript(rawTranscript);

    if (this.matchesAny(normalized, ["emergency", "help me", "sos"])) {
      return this.createIntent(rawTranscript, 0, "EMERGENCY");
    }
    if (this.matchesAny(normalized, ["stop", "stop speaking", "quiet", "silence"])) {
      return this.createIntent(rawTranscript, 0, "STOP");
    }
    if (this.matchesAny(normalized, ["repeat", "say again"])) {
      return this.createIntent(rawTranscript, 0, "REPEAT");
    }
    if (
      this.matchesAny(normalized, [
        "read this",
        "read the sign",
        "what does it say",
        "read text",
      ])
    ) {
      return this.createIntent(rawTranscript, 0, "READ_TEXT");
    }
    if (this.matchesAny(normalized, ["navigate", "navigation", "take me", "go to"])) {
      return this.createIntent(rawTranscript, 0, "NAVIGATE");
    }
    if (
      this.matchesAny(normalized, [
        "describe",
        "describe my surroundings",
        "what is around me",
        "what's around me",
      ])
    ) {
      return this.createIntent(rawTranscript, 0, "DESCRIBE_SCENE");
    }
    if (
      this.matchesAny(normalized, [
        "is the path clear",
        "can i walk",
        "is it safe to walk",
        "path check",
      ])
    ) {
      return this.createIntent(rawTranscript, 0, "QUERY_ENVIRONMENT");
    }

    return this.createIntent(rawTranscript, 0, "UNKNOWN");
  }

  private getRecognitionConstructor(): RecognitionConstructor | null {
    if (typeof window === "undefined") {
      return null;
    }
    const speechWindow = window as RecognitionWindow;
    return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
  }

  private listenWithServer(options: SpeechInputOptions): Promise<VoiceIntent> {
    if (
      typeof navigator === "undefined" ||
      typeof MediaRecorder === "undefined" ||
      typeof navigator.mediaDevices?.getUserMedia !== "function"
    ) {
      return Promise.resolve(this.createIntent("", 0));
    }

    return new Promise<VoiceIntent>((resolve) => {
      const timeoutMs =
        typeof options.timeoutMs === "number" && Number.isFinite(options.timeoutMs)
          ? Math.min(MAX_TIMEOUT_MS, Math.max(1, options.timeoutMs))
          : DEFAULT_TIMEOUT_MS;
      const active: ActiveRecording = {
        resolve,
        language:
          typeof options.lang === "string" && options.lang.trim()
            ? options.lang.trim()
            : DEFAULT_LANGUAGE,
        recorder: null,
        stream: null,
        chunks: [],
        timeout: setTimeout(() => this.stopRecording(active), timeoutMs),
        uploadAbort: null,
        settled: false,
        canceled: false,
      };
      this.activeRecording = active;
      void this.startRecording(active);
    });
  }

  private async startRecording(active: ActiveRecording): Promise<void> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (active.settled || active.canceled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      active.stream = stream;
      const mimeType = this.getRecordingMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      active.recorder = recorder;
      recorder.ondataavailable = (event: BlobEvent): void => {
        if (event.data.size > 0) {
          active.chunks.push(event.data);
        }
      };
      recorder.onerror = (): void => this.finishRecording(active, "");
      recorder.onstop = (): void => {
        void this.uploadRecording(active, mimeType || recorder.mimeType || "audio/webm");
      };
      recorder.start();
    } catch {
      this.finishRecording(active, "");
    }
  }

  private getRecordingMimeType(): string {
    if (typeof MediaRecorder.isTypeSupported !== "function") {
      return "";
    }
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    return candidates.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) ?? "";
  }

  private stopRecording(active: ActiveRecording): void {
    if (active.settled || active.canceled) {
      return;
    }
    if (active.recorder?.state === "recording") {
      active.recorder.stop();
    } else if (!active.recorder) {
      this.finishRecording(active, "");
    }
  }

  private async uploadRecording(active: ActiveRecording, mimeType: string): Promise<void> {
    if (active.settled || active.canceled) {
      this.stopTracks(active);
      return;
    }
    this.stopTracks(active);
    const audio = new Blob(active.chunks, { type: mimeType });
    if (!audio.size) {
      this.finishRecording(active, "");
      return;
    }

    const controller = new AbortController();
    active.uploadAbort = controller;
    const form = new FormData();
    const extension = mimeType.includes("ogg")
      ? "ogg"
      : mimeType.includes("mp4")
        ? "mp4"
        : "webm";
    form.append("audio", audio, `speech.${extension}`);
    form.append("lang", active.language);

    try {
      const response = await fetch(STT_ENDPOINT, {
        method: "POST",
        body: form,
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error("Speech recognition request failed.");
      }
      const payload: unknown = await response.json();
      if (
        typeof payload !== "object" ||
        payload === null ||
        !("text" in payload) ||
        typeof payload.text !== "string"
      ) {
        throw new Error("Speech recognition response was invalid.");
      }
      const confidence =
        "confidence" in payload &&
        typeof payload.confidence === "number" &&
        Number.isFinite(payload.confidence)
          ? Math.min(1, Math.max(0, payload.confidence))
          : 0;
      this.finishRecording(active, payload.text.trim(), confidence);
    } catch {
      this.finishRecording(active, "");
    }
  }

  private cancelRecording(active: ActiveRecording): void {
    if (active.settled) {
      return;
    }
    active.canceled = true;
    active.uploadAbort?.abort();
    clearTimeout(active.timeout);
    if (active.recorder?.state === "recording") {
      active.recorder.stop();
    }
    this.stopTracks(active);
    this.finishRecording(active, "");
  }

  private stopTracks(active: ActiveRecording): void {
    active.stream?.getTracks().forEach((track) => track.stop());
    active.stream = null;
  }

  private finishRecording(
    active: ActiveRecording,
    transcript: string,
    confidence = 0,
  ): void {
    if (active.settled) {
      return;
    }
    active.settled = true;
    clearTimeout(active.timeout);
    this.stopTracks(active);
    if (this.activeRecording === active) {
      this.activeRecording = null;
    }
    active.resolve(this.createIntent(transcript, confidence));
  }

  private matchesAny(transcript: string, phrases: string[]): boolean {
    return phrases.some((phrase) => containsPhrase(transcript, phrase));
  }

  private createIntent(
    rawTranscript: string,
    confidence: number,
    intent?: VoiceIntentType,
  ): VoiceIntent {
    const parsedIntent = intent ?? this.parseIntent(rawTranscript).intent;
    return {
      intent: parsedIntent,
      rawTranscript,
      confidence,
    };
  }

  private finishListen(
    active: ActiveListen,
    transcript: string,
    confidence: number,
    abort: boolean = false,
  ): void {
    if (active.settled) {
      return;
    }
    active.settled = true;
    clearTimeout(active.timeout);
    if (this.activeListen === active) {
      this.activeListen = null;
    }

    active.recognition.onresult = null;
    active.recognition.onerror = null;
    active.recognition.onend = null;
    if (abort) {
      try {
        active.recognition.abort();
      } catch {
        // The promise is still settled if the browser rejects abort().
      }
    }

    active.resolve(this.createIntent(transcript, confidence));
  }
}

export const webSpeechInput = new WebSpeechInput();
export default webSpeechInput;
