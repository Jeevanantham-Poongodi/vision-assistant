import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WebSpeechInput } from "../voiceInput";

class MockRecognition {
  static instances: MockRecognition[] = [];

  lang = "";
  continuous = true;
  interimResults = true;
  maxAlternatives = 10;
  onresult: ((event: never) => void) | null = null;
  onerror: ((event: never) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();

  constructor() {
    MockRecognition.instances.push(this);
  }

  result(transcript: string, confidence = 0.9): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ 0: { transcript, confidence }, length: 1, isFinal: true }],
    } as never);
  }

  fail(error = "no-speech"): void {
    this.onerror?.({ error } as never);
  }
}

class MockMediaRecorder {
  static instance: MockMediaRecorder | null = null;
  static isTypeSupported = vi.fn(() => true);
  state = "inactive";
  mimeType = "audio/webm;codecs=opus";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onstop: (() => void) | null = null;

  constructor() {
    MockMediaRecorder.instance = this;
  }

  start(): void {
    this.state = "recording";
    this.ondataavailable?.({ data: new Blob(["audio"]), } as BlobEvent);
  }

  stop(): void {
    this.state = "inactive";
    this.onstop?.();
  }
}

describe("WebSpeechInput", () => {
  let service: WebSpeechInput;

  beforeEach(() => {
    MockRecognition.instances = [];
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: MockRecognition,
    });
    service = new WebSpeechInput();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
  });

  it("reports support when a native recognition constructor exists", () => {
    expect(service.isSupported()).toBe(true);
  });

  it("supports the WebKit-prefixed recognition constructor", () => {
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    Object.defineProperty(window, "webkitSpeechRecognition", {
      configurable: true,
      value: MockRecognition,
    });

    expect(service.isSupported()).toBe(true);
  });

  it("uses en-IN and returns parsed intent, transcript, and confidence", async () => {
    const listening = service.listenOnce();
    const recognition = MockRecognition.instances[0];

    expect(recognition.lang).toBe("en-IN");
    expect(recognition.continuous).toBe(false);
    expect(recognition.interimResults).toBe(false);
    expect(recognition.maxAlternatives).toBe(1);

    recognition.result("Help me, please", 0.84);

    await expect(listening).resolves.toEqual({
      intent: "EMERGENCY",
      rawTranscript: "Help me, please",
      confidence: 0.84,
    });
  });

  it("applies supplied language and timeout settings", () => {
    vi.useFakeTimers();
    service.listenOnce({ lang: "en-US", timeoutMs: 750 });
    expect(MockRecognition.instances[0].lang).toBe("en-US");
    expect(vi.getTimerCount()).toBe(1);
  });

  it.each([
    ["emergency", "EMERGENCY"],
    ["Please help me now", "EMERGENCY"],
    ["SOS!", "EMERGENCY"],
    ["stop speaking", "STOP"],
    ["Quiet, please.", "STOP"],
    ["silence", "STOP"],
    ["repeat", "REPEAT"],
    ["say again", "REPEAT"],
    ["read this", "READ_TEXT"],
    ["read the sign", "READ_TEXT"],
    ["what does it say?", "READ_TEXT"],
    ["navigate to the station", "NAVIGATE"],
    ["take me home", "NAVIGATE"],
    ["describe my surroundings", "DESCRIBE_SCENE"],
    ["what is around me?", "DESCRIBE_SCENE"],
    ["is the path clear?", "QUERY_ENVIRONMENT"],
    ["can I walk?", "QUERY_ENVIRONMENT"],
    ["where is the nearest bus stop", "UNKNOWN"],
    ["", "UNKNOWN"],
  ] as const)("parses %s as %s", (transcript, expected) => {
    const intent = service.parseIntent(transcript);

    expect(intent.intent).toBe(expected);
    expect(intent.rawTranscript).toBe(transcript);
    expect(intent.confidence).toBe(0);
  });

  it("returns UNKNOWN when recognition is unsupported", async () => {
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    const unsupported = new WebSpeechInput();

    expect(unsupported.isSupported()).toBe(false);
    await expect(unsupported.listenOnce()).resolves.toEqual({
      intent: "UNKNOWN",
      rawTranscript: "",
      confidence: 0,
    });
  });

  it("returns UNKNOWN if the browser recognition constructor throws", async () => {
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: class {
        constructor() {
          throw new Error("recognition unavailable");
        }
      },
    });

    await expect(service.listenOnce()).resolves.toEqual({
      intent: "UNKNOWN",
      rawTranscript: "",
      confidence: 0,
    });
  });

  it("returns UNKNOWN when recognition errors without a transcript", async () => {
    const listening = service.listenOnce();
    MockRecognition.instances[0].fail("not-allowed");

    await expect(listening).resolves.toEqual({
      intent: "UNKNOWN",
      rawTranscript: "",
      confidence: 0,
    });
  });

  it("returns UNKNOWN and aborts when listening times out", async () => {
    vi.useFakeTimers();
    const listening = service.listenOnce({ timeoutMs: 500 });
    const recognition = MockRecognition.instances[0];

    await vi.advanceTimersByTimeAsync(500);
    await expect(listening).resolves.toMatchObject({
      intent: "UNKNOWN",
      rawTranscript: "",
      confidence: 0,
    });
    expect(recognition.abort).toHaveBeenCalledOnce();
  });

  it("stops an active listening session and resolves it safely", async () => {
    const listening = service.listenOnce();
    const recognition = MockRecognition.instances[0];

    service.stopListening();

    expect(recognition.abort).toHaveBeenCalledOnce();
    await expect(listening).resolves.toMatchObject({
      intent: "UNKNOWN",
      rawTranscript: "",
      confidence: 0,
    });
  });

  it("settles an active promise before starting a new listen session", async () => {
    const firstListening = service.listenOnce();
    const firstRecognition = MockRecognition.instances[0];
    const secondListening = service.listenOnce();

    expect(firstRecognition.abort).toHaveBeenCalledOnce();
    await expect(firstListening).resolves.toMatchObject({ intent: "UNKNOWN" });

    MockRecognition.instances[1].result("Read this", 0.72);
    await expect(secondListening).resolves.toEqual({
      intent: "READ_TEXT",
      rawTranscript: "Read this",
      confidence: 0.72,
    });
  });

  it("ignores repeated browser events after the first result settles", async () => {
    const listening = service.listenOnce();
    const recognition = MockRecognition.instances[0];

    recognition.result("repeat", 0.7);
    recognition.onend?.();

    await expect(listening).resolves.toMatchObject({
      intent: "REPEAT",
      rawTranscript: "repeat",
      confidence: 0.7,
    });
  });

  it("records and posts audio when browser speech recognition is unavailable", async () => {
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ text: "Take me to the library", confidence: 0.91 }),
      }),
    );

    expect(service.isSupported()).toBe(true);
    const listening = service.listenOnce({ lang: "en-IN" });
    MockMediaRecorder.instance?.stop();

    await expect(listening).resolves.toMatchObject({
      rawTranscript: "Take me to the library",
      confidence: 0.91,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/stt",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("cancels fallback recording without posting or returning a transcript", async () => {
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const listening = service.listenOnce();
    service.stopListening();

    await expect(listening).resolves.toMatchObject({ rawTranscript: "", intent: "UNKNOWN" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
