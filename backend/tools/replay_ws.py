# backend/tools/replay_ws.py
"""Stream a recorded clip into /ws/user as if it were the phone (BE-05). Owner: Coder 3.

Run from backend/:
    python -m tools.replay_ws --clip clips/vehicle.mp4 --duration 300 --loop --out results.jsonl

Sends JPEG frames (max 640 px wide, quality 65) at --fps with one frame in flight, like the
phone (contract 5.2), then prints round-trip latency and exits non-zero if p95 > --max-p95 or
any error came back. --out saves every FrameResult as JSON lines for regression diffs."""
import argparse
import asyncio
import base64
import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import websockets

from db.repo import DEMO_USER_ID
from live.stats import percentile

MAX_WIDTH = 640
JPEG_QUALITY = 65
REPLY_TIMEOUT_S = 1.0  # contract 5.2: send the next frame after 1000 ms with no reply


def resize_for_phone(frame: np.ndarray, max_width: int = MAX_WIDTH) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    return cv2.resize(frame, (max_width, round(h * max_width / w)), interpolation=cv2.INTER_AREA)


def encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("could not encode frame as JPEG")
    return base64.b64encode(buf.tobytes()).decode()


@dataclass
class Report:
    sent: int = 0
    results: int = 0
    errors: int = 0
    timeouts: int = 0
    round_trip_ms: list[float] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def lines(self) -> list[str]:
        elapsed = time.perf_counter() - self.started
        rt = self.round_trip_ms
        return [
            f"frames sent {self.sent}, results {self.results}, errors {self.errors}, timeouts {self.timeouts}",
            f"round trip p50 {percentile(rt, 50):.0f} ms, p95 {percentile(rt, 95):.0f} ms, "
            f"max {max(rt, default=0):.0f} ms",
            f"effective {self.results / max(elapsed, 1e-9):.2f} results/s over {elapsed:.1f} s",
        ]


def _post_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _envelope(type_: str, payload: dict) -> str:
    return json.dumps({"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload})


async def _await_reply(ws, frame_id: int, deadline: float) -> dict | None:
    """Waits for the frame_result or error for frame_id; other messages are skipped."""
    while (remaining := deadline - time.perf_counter()) > 0:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        except TimeoutError:
            return None
        payload = msg.get("payload", {})
        if msg.get("type") in ("frame_result", "error") and payload.get("frame_id") == frame_id:
            return msg
    return None


async def replay(args: argparse.Namespace) -> Report:
    cap = cv2.VideoCapture(str(args.clip))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open clip: {args.clip}")
    base = args.base.rstrip("/")
    session = _post_json(f"{base}/api/v1/sessions", {"user_id": args.user_id, "device_info": {"platform": "replay"}})
    sid = session["session_id"]
    ws_url = base.replace("http", "ws", 1) + session["ws_url"]
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    report = Report()
    interval = 1 / args.fps
    stop_at = time.perf_counter() + args.duration if args.duration else None
    try:
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.send(_envelope("hello", {"user_id": args.user_id, "device_info": {"platform": "replay"}}))
            welcome = json.loads(await ws.recv())
            if welcome.get("type") != "welcome":
                raise SystemExit(f"Expected welcome, got {welcome}")
            frame_id = 0
            while stop_at is None or time.perf_counter() < stop_at:
                tick = time.perf_counter()
                ok, frame = cap.read()
                if not ok:
                    if not args.loop:
                        break
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                frame = resize_for_phone(frame)
                frame_id += 1
                h, w = frame.shape[:2]
                await ws.send(_envelope("frame", {"frame_id": frame_id, "image": encode_jpeg(frame),
                                                  "width": w, "height": h}))
                report.sent += 1
                reply = await _await_reply(ws, frame_id, tick + REPLY_TIMEOUT_S)
                if reply is None:
                    report.timeouts += 1
                elif reply["type"] == "error":
                    report.errors += 1
                    print(f"frame {frame_id}: {reply['payload']}", file=sys.stderr)
                else:
                    report.results += 1
                    report.round_trip_ms.append((time.perf_counter() - tick) * 1000)
                    if out:
                        out.write(json.dumps(reply["payload"]) + "\n")
                await asyncio.sleep(max(0.0, interval - (time.perf_counter() - tick)))
    finally:
        cap.release()
        if out:
            out.close()
        _post_json(f"{base}/api/v1/sessions/{sid}/end")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay a video clip into /ws/user like the phone does.")
    p.add_argument("--clip", type=Path, required=True, help="video file readable by OpenCV")
    p.add_argument("--base", default="http://localhost:8000", help="backend base URL")
    p.add_argument("--user-id", default=str(DEMO_USER_ID))
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--duration", type=float, default=0, help="seconds; 0 = until the clip ends")
    p.add_argument("--loop", action="store_true", help="restart the clip when it ends")
    p.add_argument("--max-p95", type=float, default=250.0, help="fail if round-trip p95 is above this (ms)")
    p.add_argument("--out", type=Path, help="write each FrameResult as a JSON line")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(replay(args))
    for line in report.lines():
        print(line)
    p95 = percentile(report.round_trip_ms, 95)
    failed = report.errors > 0 or report.results == 0 or p95 > args.max_p95
    print("FAIL" if failed else "PASS", f"(p95 limit {args.max_p95:.0f} ms)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
