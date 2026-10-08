import { useState } from "react";
import type { CSSProperties, ReactElement } from "react";

import {
  webSpeechInput,
  type SpeechInput,
} from "../../services/voiceInput";

export interface GuardianMicButtonProps {
  onTranscript: (transcript: string) => void;
  speechInput?: SpeechInput;
  disabled?: boolean;
}

const BUTTON_STYLE: CSSProperties = {
  minHeight: 44,
  minWidth: 44,
  borderRadius: 12,
  border: "1px solid currentColor",
  fontSize: 20,
  cursor: "pointer",
};

export function GuardianMicButton({
  onTranscript,
  speechInput = webSpeechInput,
  disabled = false,
}: GuardianMicButtonProps): ReactElement {
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("");
  const supported = speechInput.isSupported();

  const startListening = async (): Promise<void> => {
    if (!supported || disabled || listening) {
      return;
    }

    setListening(true);
    setStatus("Listening.");
    try {
      const result = await speechInput.listenOnce();
      const transcript =
        "transcript" in result
          ? result.transcript
          : result.rawTranscript;
      if (typeof transcript !== "string" || !transcript.trim()) {
        setStatus("No transcript was recognized. Your message is unchanged.");
        return;
      }

      onTranscript(transcript);
      setStatus("Transcript added. Review it before sending.");
    } catch {
      setStatus("Could not recognize speech. Your message is unchanged.");
    } finally {
      setListening(false);
    }
  };

  const stopListening = (): void => {
    speechInput.stopListening();
    setListening(false);
    setStatus("Listening canceled. Your message is unchanged.");
  };

  if (!supported) {
    return (
      <span role="status" aria-live="polite">
        Voice input is not supported in this browser.
      </span>
    );
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {listening ? (
        <button
          type="button"
          onClick={stopListening}
          disabled={disabled}
          aria-label="Cancel voice input"
          style={BUTTON_STYLE}
        >
          Cancel
        </button>
      ) : (
        <button
          type="button"
          onClick={() => void startListening()}
          disabled={disabled}
          aria-label="Use voice to enter a guardian message"
          title="Speak a message"
          style={BUTTON_STYLE}
        >
          🎙
        </button>
      )}
      <span role="status" aria-live="polite">
        {status}
      </span>
    </span>
  );
}

export default GuardianMicButton;
