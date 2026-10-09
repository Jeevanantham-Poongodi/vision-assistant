import type { Envelope } from "@/types/contracts";
import type { RealtimeClient } from "./ws";

export type WebRtcSignalType = "webrtc_offer" | "webrtc_answer" | "webrtc_ice";

export interface WebRtcSignalHandlers {
  webrtc_offer?: (payload: unknown, envelope: Envelope<unknown>) => void;
  webrtc_answer?: (payload: unknown, envelope: Envelope<unknown>) => void;
  webrtc_ice?: (payload: unknown, envelope: Envelope<unknown>) => void;
}

/** Contract 6 exposes opaque SDP/ICE payloads; this adapter forwards them without reshaping. */
export function subscribeWebRtcSignals(
  client: RealtimeClient,
  handlers: WebRtcSignalHandlers,
): () => void {
  const types: WebRtcSignalType[] = ["webrtc_offer", "webrtc_answer", "webrtc_ice"];
  const unsubscribe = types.map((type) =>
    client.on<unknown>(type, (payload, envelope) => {
      handlers[type]?.(payload, envelope);
    }),
  );
  return () => unsubscribe.forEach((off) => off());
}

export function sendWebRtcSignal(
  client: RealtimeClient,
  type: WebRtcSignalType,
  payload: unknown,
): void {
  client.send(type, payload);
}
