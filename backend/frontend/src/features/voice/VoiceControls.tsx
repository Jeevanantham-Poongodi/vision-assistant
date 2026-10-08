import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties, FormEvent, ReactElement } from "react";

import {
  webSpeechInput,
  type SpeechInput,
  type VoiceIntent,
  type VoiceIntentType,
} from "../../services/voiceInput";
import {
  speechService,
  type SpeechService,
} from "../../services/speech";

type AskMode = "question" | "describe" | "path_check";

interface SpokenResponse {
  spoken_text?: string;
}

export interface VoiceControlsProps {
  speechInput?: SpeechInput;
  speechOutput?: SpeechService;
  startAreaRef?: { current: HTMLElement | null };
  onAsk?: (question: string, mode: AskMode) => Promise<SpokenResponse> | SpokenResponse;
  onReadText?: () => Promise<SpokenResponse> | SpokenResponse;
  onIntent?: (intent: VoiceIntent) => void;
}

const BUTTON_STYLE: CSSProperties = {
  minHeight: 64,
  minWidth: 140,
  padding: "12px 20px",
  borderRadius: 16,
  border: "2px solid currentColor",
  fontSize: 20,
  fontWeight: 700,
  cursor: "pointer",
};

function playStartBeep(): void {
  if (typeof window === "undefined") {
    return;
  }
  const AudioContextConstructor =
    window.AudioContext ??
    (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextConstructor) {
    return;
  }

  try {
    const context = new AudioContextConstructor();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.08, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.12);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.12);
    oscillator.onended = (): void => {
      void context.close();
    };
  } catch {
    // Audio feedback is optional; listening should still start.
  }
}

function getAskRoute(intent: VoiceIntent): { question: string; mode: AskMode } | null {
  switch (intent.intent) {
    case "QUERY_ENVIRONMENT":
      return { question: intent.rawTranscript || "Is the path clear?", mode: "path_check" };
    case "DESCRIBE_SCENE":
      return { question: intent.rawTranscript || "Describe my surroundings.", mode: "describe" };
    case "UNKNOWN":
      return { question: intent.rawTranscript, mode: "question" };
    default:
      return null;
  }
}

export function VoiceControls({
  speechInput = webSpeechInput,
  speechOutput = speechService,
  startAreaRef,
  onAsk,
  onReadText,
  onIntent,
}: VoiceControlsProps): ReactElement {
  const supported = useMemo(() => speechInput.isSupported(), [speechInput]);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState(
    supported ? "Voice controls ready." : "Speech recognition is unavailable.",
  );

  const readText = useCallback(async (): Promise<void> => {
    if (!onReadText || busy) {
      setStatus("Read text is unavailable right now.");
      return;
    }
    setBusy(true);
    setStatus("Reading text.");
    speechOutput.speak({
      text: "Let me look.",
      priority: 40,
      source: "answer",
    });
    try {
      const response = await onReadText();
      const spokenText = response.spoken_text?.trim();
      if (spokenText) {
        speechOutput.speak({ text: spokenText, priority: 40, source: "answer" });
        setStatus(spokenText);
      } else {
        setStatus("No spoken text was returned.");
      }
    } catch {
      setStatus("Could not read text. Please try again.");
    } finally {
      setBusy(false);
    }
  }, [busy, onReadText, speechOutput]);

  const askQuestion = useCallback(
    async (text: string, mode: AskMode = "question"): Promise<void> => {
      const trimmedQuestion = text.trim();
      if (!trimmedQuestion || !onAsk || busy) {
        if (!onAsk) {
          setStatus("Ask AI is unavailable right now.");
        } else if (!trimmedQuestion) {
          setStatus("Enter a question first.");
        }
        return;
      }

      setBusy(true);
      setStatus("Let me look.");
      speechOutput.speak({
        text: "Let me look.",
        priority: 40,
        source: "answer",
      });
      try {
        const response = await onAsk(trimmedQuestion, mode);
        const spokenText = response.spoken_text?.trim();
        if (spokenText) {
          speechOutput.speak({ text: spokenText, priority: 40, source: "answer" });
          setStatus(spokenText);
        } else {
          setStatus("No answer was returned.");
        }
      } catch {
        setStatus("Could not get an answer. Please try again.");
      } finally {
        setBusy(false);
      }
    },
    [busy, onAsk, speechOutput],
  );

  const routeIntent = useCallback(
    async (intent: VoiceIntent): Promise<void> => {
      onIntent?.(intent);
      if (intent.intent === "STOP") {
        speechOutput.stop();
        setStatus("Speech stopped.");
        return;
      }
      if (intent.intent === "REPEAT") {
        speechOutput.repeatLast();
        setStatus("Repeating the last message.");
        return;
      }
      if (intent.intent === "READ_TEXT") {
        await readText();
        return;
      }

      const askRoute = getAskRoute(intent);
      if (askRoute) {
        await askQuestion(askRoute.question, askRoute.mode);
      } else {
        setStatus(intent.rawTranscript || "Voice command received.");
      }
    },
    [askQuestion, onIntent, readText, speechOutput],
  );

  const listen = useCallback(async (): Promise<void> => {
    if (!supported || listening || busy) {
      return;
    }
    setListening(true);
    setStatus("Listening.");
    playStartBeep();
    try {
      const intent = await speechInput.listenOnce({ lang: "en-IN", timeoutMs: 6_000 });
      setStatus(intent.rawTranscript || "I did not hear anything.");
      if (!intent.rawTranscript) {
        return;
      }
      await routeIntent(intent);
    } finally {
      setListening(false);
    }
  }, [busy, listening, routeIntent, speechInput, supported]);

  useEffect(() => {
    const startArea = startAreaRef?.current;
    if (!startArea || !supported) {
      return;
    }
    const onDoubleClick = (): void => {
      void listen();
    };
    startArea.addEventListener("dblclick", onDoubleClick);
    return () => startArea.removeEventListener("dblclick", onDoubleClick);
  }, [listen, startAreaRef, supported]);

  const handleIntent = (intent: VoiceIntentType, rawTranscript: string): VoiceIntent => ({
    intent,
    rawTranscript,
    confidence: 1,
  });

  const submitQuestion = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    await askQuestion(question);
  };

  return (
    <section
      aria-label="Voice controls"
      style={{ display: "grid", gap: 16, justifyItems: "center", padding: 16 }}
    >
      <div role="status" aria-live="polite" style={{ minHeight: 24, textAlign: "center" }}>
        {status}
      </div>

      {supported ? (
        <button
          type="button"
          onClick={() => void listen()}
          disabled={listening || busy}
          aria-pressed={listening}
          style={BUTTON_STYLE}
        >
          {listening ? "Listening…" : "Push to talk"}
        </button>
      ) : null}

      {askOpen ? (
        <form onSubmit={(event) => void submitQuestion(event)} style={{ display: "grid", gap: 12 }}>
          <label htmlFor="voice-question">Ask a question</label>
          <input
            id="voice-question"
            value={question}
            onChange={(event) => setQuestion(event.currentTarget.value)}
            disabled={busy}
            style={{ minHeight: 48, minWidth: 260, fontSize: 18 }}
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            style={BUTTON_STYLE}
          >
            Ask
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setAskOpen(true)}
          disabled={busy}
          style={BUTTON_STYLE}
        >
          Ask
        </button>
      )}

      <button
        type="button"
        onClick={() => void readText()}
        disabled={busy}
        style={BUTTON_STYLE}
      >
        Read text
      </button>

      {supported ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "center" }}>
          <button
            type="button"
            onClick={() => void routeIntent(handleIntent("STOP", "stop"))}
            style={BUTTON_STYLE}
          >
            Stop speaking
          </button>
          <button
            type="button"
            onClick={() => void routeIntent(handleIntent("REPEAT", "repeat"))}
            style={BUTTON_STYLE}
          >
            Repeat
          </button>
        </div>
      ) : null}
    </section>
  );
}

export default VoiceControls;
