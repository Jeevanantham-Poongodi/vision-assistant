# backend/tools/wss_check.py
"""Checks the backend end to end through a tunnel: HTTPS REST + wss:// WebSocket (BE-07). Owner: Coder 3.

    python -m tools.wss_check --base https://<backend>.trycloudflare.com

Creates a session, opens the user socket, sends hello, one real JPEG frame and a ping, prints
the timings, ends the session. Exit code 0 = the path works; run it from a machine on mobile
data (e.g. a laptop on a phone hotspot) to test the venue-independent path."""
import argparse
import asyncio
import base64
import json
import sys
import time
import urllib.request

import cv2
import numpy as np
import websockets

from db.repo import DEMO_USER_ID


def ws_base(http_base: str) -> str:
    """https://host -> wss://host, http://host -> ws://host."""
    base = http_base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base.removeprefix("https://")
    if base.startswith("http://"):
        return "ws://" + base.removeprefix("http://")
    raise ValueError(f"--base must start with http:// or https://, got {http_base!r}")


def _post(url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _expect(reply: dict, type_: str) -> None:
    if reply.get("type") != type_:
        raise RuntimeError(f"expected {type_}, got {reply}")


def _env(type_: str, payload: dict) -> str:
    return json.dumps({"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload})


async def check(base: str, user_id: str) -> None:
    base = base.rstrip("/")
    t0 = time.perf_counter()
    with urllib.request.urlopen(f"{base}/api/v1/health", timeout=15) as resp:
        print(f"health     {json.load(resp)['status']:<10} {(time.perf_counter() - t0) * 1000:6.0f} ms")
    session = _post(f"{base}/api/v1/sessions", {"user_id": user_id, "device_info": {"platform": "wss_check"}})
    sid = session["session_id"]
    try:
        jpeg = base64.b64encode(cv2.imencode(".jpg", np.full((480, 640, 3), 90, np.uint8))[1].tobytes()).decode()
        t0 = time.perf_counter()
        async with websockets.connect(f"{ws_base(base)}/ws/user/{sid}", open_timeout=15) as ws:
            await ws.send(_env("hello", {"user_id": user_id}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
            _expect(reply, "welcome")
            print(f"welcome    ok         {(time.perf_counter() - t0) * 1000:6.0f} ms  (connect + hello)")
            for type_, payload, expected in (
                ("frame", {"frame_id": 1, "image": jpeg, "width": 640, "height": 480}, "frame_result"),
                ("ping", {}, "pong"),
            ):
                t0 = time.perf_counter()
                await ws.send(_env(type_, payload))
                reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
                _expect(reply, expected)
                print(f"{type_:<10} ok         {(time.perf_counter() - t0) * 1000:6.0f} ms")
    finally:
        _post(f"{base}/api/v1/sessions/{sid}/end")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check REST + WebSocket through a tunnel URL.")
    p.add_argument("--base", required=True, help="e.g. https://abc-def.trycloudflare.com")
    p.add_argument("--user-id", default=str(DEMO_USER_ID))
    args = p.parse_args(argv)
    try:
        ws_base(args.base)
        asyncio.run(check(args.base, args.user_id))
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        if "getaddrinfo" in str(exc):
            print("Hint: a new tunnel name can take a minute to reach your DNS. Wait, run "
                  "`ipconfig /flushdns`, and try again.", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
