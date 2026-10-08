/**
 * The single realtime client (contract 9.2, 5.1, 5.4). Both the user app and the guardian
 * dashboard use createRealtimeClient(); with VITE_USE_MOCKS=true it returns MockRealtimeClient.
 */
import type { Envelope } from "@/types/contracts";
import { config } from "./config";
import { MockRealtimeClient } from "@/mocks/MockRealtimeClient";

export type ConnectionStatus = "connecting" | "open" | "closed";

export interface RealtimeClient {
  connect(url: string): void;
  send<T>(type: string, payload: T): void;
  on<T>(type: string, handler: (payload: T, env: Envelope<T>) => void): () => void;
  status(): "connecting" | "open" | "closed";
}

export interface StatusInfo {
  code?: number;
  /** true while the client is waiting to reconnect */
  reconnecting: boolean;
}

export interface RealtimeClientOptions {
  /** Payload for `hello`, sent after every (re)connect. */
  hello: () => unknown;
  /** Close code 4001: create a new session via REST and return its ws URL, or null to stop. */
  onSessionNotFound?: () => Promise<string | null>;
  onStatusChange?: (s: ConnectionStatus, info: StatusInfo) => void;
}

/** Extended client: same contract plus explicit close and an optional envelope `ts` (frame capture time). */
export interface ManagedRealtimeClient extends RealtimeClient {
  send<T>(type: string, payload: T, ts?: number): void;
  close(): void;
}

export const CloseCode = {
  NORMAL: 1000,
  SESSION_NOT_FOUND: 4001,
  REPLACED: 4002,
  PROTOCOL_VIOLATION: 4003,
} as const;

export const BACKOFF_MS = [500, 1000, 2000, 4000] as const;
export const STEADY_RETRY_MS = 5000;
export const PING_IDLE_MS = 15000;

type AnyHandler = (payload: unknown, env: Envelope<unknown>) => void;

export function makeEnvelope<T>(type: string, payload: T, ts = Date.now()): Envelope<T> {
  return { v: 1, type, ts, payload };
}

export function parseEnvelope(raw: string): Envelope<unknown> | null {
  try {
    const x: unknown = JSON.parse(raw);
    if (
      typeof x === "object" &&
      x !== null &&
      (x as Envelope).v === 1 &&
      typeof (x as Envelope).type === "string"
    ) {
      return x as Envelope<unknown>;
    }
  } catch {
    /* ignore malformed */
  }
  return null;
}

/** Shared listener registry for real and mock clients. */
export class HandlerRegistry {
  private handlers = new Map<string, Set<AnyHandler>>();
  on<T>(type: string, handler: (payload: T, env: Envelope<T>) => void): () => void {
    const h = handler as AnyHandler;
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(h);
    return () => set?.delete(h);
  }
  dispatch(env: Envelope<unknown>) {
    for (const key of [env.type, "*"]) {
      this.handlers.get(key)?.forEach((h) => {
        try {
          h(env.payload, env);
        } catch (e) {
          console.error("[ws] handler error", e);
        }
      });
    }
  }
}

export class WebSocketRealtimeClient implements ManagedRealtimeClient {
  private ws: WebSocket | null = null;
  private url = "";
  private st: ConnectionStatus = "closed";
  private registry = new HandlerRegistry();
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private lastSentAt = 0;
  private manualClose = false;

  constructor(private readonly opts: RealtimeClientOptions) {}

  connect(url: string) {
    this.url = url;
    this.manualClose = false;
    this.attempt = 0;
    this.clearReconnect();
    this.open();
  }

  send<T>(type: string, payload: T, ts = Date.now()) {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(makeEnvelope(type, payload, ts)));
    this.lastSentAt = Date.now();
  }

  on<T>(type: string, handler: (payload: T, env: Envelope<T>) => void) {
    return this.registry.on(type, handler);
  }

  status() {
    return this.st;
  }

  close() {
    this.manualClose = true;
    this.clearReconnect();
    this.stopPing();
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close(CloseCode.NORMAL);
    this.setStatus("closed", { reconnecting: false });
  }

  private setStatus(s: ConnectionStatus, info: StatusInfo) {
    this.st = s;
    this.opts.onStatusChange?.(s, info);
  }

  private open() {
    this.setStatus("connecting", { reconnecting: this.attempt > 0 });
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.attempt = 0;
      this.setStatus("open", { reconnecting: false });
      this.send("hello", this.opts.hello());
      this.startPing();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const env = parseEnvelope(ev.data);
      if (env) this.registry.dispatch(env);
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.stopPing();
      void this.handleClose(ev.code);
    };
  }

  private async handleClose(code: number) {
    if (this.manualClose) return this.setStatus("closed", { code, reconnecting: false });
    // 1000: session ended normally. 4002: replaced by a newer connection — do not fight it.
    if (code === CloseCode.NORMAL || code === CloseCode.REPLACED) {
      return this.setStatus("closed", { code, reconnecting: false });
    }
    if (code === CloseCode.SESSION_NOT_FOUND) {
      this.setStatus("closed", { code, reconnecting: true });
      let next: string | null = null;
      try {
        next = (await this.opts.onSessionNotFound?.()) ?? null;
      } catch {
        next = null;
      }
      if (next && !this.manualClose) {
        this.url = next;
        this.attempt = 0;
        this.open();
      } else {
        this.setStatus("closed", { code, reconnecting: false });
      }
      return;
    }
    // 4003 protocol violation and network drops: reconnect; hello is re-sent on open.
    this.setStatus("closed", { code, reconnecting: true });
    this.scheduleReconnect();
  }

  private scheduleReconnect() {
    const delay = BACKOFF_MS[this.attempt] ?? STEADY_RETRY_MS;
    this.attempt++;
    this.clearReconnect();
    this.reconnectTimer = setTimeout(() => {
      if (!this.manualClose) this.open();
    }, delay);
  }

  private clearReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private startPing() {
    this.stopPing();
    this.lastSentAt = Date.now();
    this.pingTimer = setInterval(() => {
      if (Date.now() - this.lastSentAt >= PING_IDLE_MS) this.send("ping", {});
    }, 1000);
  }

  private stopPing() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }
}

export type Channel = "user" | "guardian";

export function createRealtimeClient(channel: Channel, opts: RealtimeClientOptions): ManagedRealtimeClient {
  return config.useMocks ? new MockRealtimeClient(channel, opts) : new WebSocketRealtimeClient(opts);
}
