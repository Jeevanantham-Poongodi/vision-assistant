import { describe, expect, it, vi } from "vitest";

import { WebSpeechService } from "../speech";

class MockUtterance {
  lang = "";
  rate = 1;
  pitch = 1;
  voice: SpeechSynthesisVoice | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly text: string) {}
}

function configureSynthesis(voices: SpeechSynthesisVoice[]): {
  speak: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
} {
  const synthesis = {
    getVoices: () => voices,
    speak: vi.fn(),
    cancel: vi.fn(),
  };
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: synthesis,
  });
  vi.stubGlobal("SpeechSynthesisUtterance", MockUtterance);
  return synthesis;
}

describe("WebSpeechService language support", () => {
  it("selects an exact Tamil voice when ta-IN is chosen", () => {
    const tamilVoice = { lang: "ta-IN" } as SpeechSynthesisVoice;
    configureSynthesis([{ lang: "en-IN" } as SpeechSynthesisVoice, tamilVoice]);
    const service = new WebSpeechService();
    service.setLanguage("ta-IN");

    service.speak({ text: "வணக்கம்", priority: 50, source: "warning" });

    const utterance = (
      window.speechSynthesis.speak as unknown as ReturnType<typeof vi.fn>
    ).mock.calls[0][0] as MockUtterance;
    expect(utterance.lang).toBe("ta-IN");
    expect(utterance.voice).toBe(tamilVoice);
  });

  it("uses a regional Tamil voice if there is no exact ta-IN voice", () => {
    const tamilVoice = { lang: "ta-LK" } as SpeechSynthesisVoice;
    configureSynthesis([tamilVoice]);
    const service = new WebSpeechService();
    service.setVoice({ lang: "ta-IN" });

    service.speak({ text: "வணக்கம்", priority: 50, source: "warning" });

    const utterance = (
      window.speechSynthesis.speak as unknown as ReturnType<typeof vi.fn>
    ).mock.calls[0][0] as MockUtterance;
    expect(utterance.voice).toBe(tamilVoice);
  });

  it("does not fail if no Tamil voice is installed", () => {
    configureSynthesis([{ lang: "en-IN" } as SpeechSynthesisVoice]);
    const service = new WebSpeechService();
    service.setLanguage("ta-IN");

    expect(() =>
      service.speak({ text: "வணக்கம்", priority: 50, source: "warning" }),
    ).not.toThrow();
  });

  it("uses the server MP3 fallback when browser speech synthesis is absent", async () => {
    const mockAudio = {
      onended: null as (() => void) | null,
      onerror: null as (() => void) | null,
      play: vi.fn().mockResolvedValue(undefined),
      pause: vi.fn(),
      currentTime: 0,
    };
    vi.stubGlobal(
      "Audio",
      vi.fn(function MockAudio(this: typeof mockAudio) {
        Object.assign(this, mockAudio);
        return this;
      }),
    );
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["mp3"]),
    });
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(window, "fetch", {
      configurable: true,
      value: fetchMock,
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:tts");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const service = new WebSpeechService();
    service.setLanguage("ta-IN");

    service.speak({ text: "வணக்கம்", priority: 50, source: "warning" });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/tts",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "வணக்கம்", lang: "ta-IN" }),
      }),
    );
    expect(mockAudio.play).toHaveBeenCalledOnce();
    mockAudio.onended?.();
    expect(service.isSpeaking()).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:tts");
  });
});
