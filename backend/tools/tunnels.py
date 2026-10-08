# backend/tools/tunnels.py
"""One command for the phone demo over HTTPS (BE-07). Owner: Coder 3. Guide: docs/07_HTTPS_DEMO.md

Run from backend/ while the backend (8000) and Vite (5173) are running:
    python -m tools.tunnels                 # print the URLs and the frontend .env lines
    python -m tools.tunnels --write-env     # also write them into frontend/.env
    python -m tools.tunnels --backend-only  # only the API tunnel (Postman, tools.wss_check)

Starts Cloudflare quick tunnels (no account needed). The URLs change on every start, so set
ALLOWED_ORIGIN_REGEX in backend/.env once instead of editing ALLOWED_ORIGINS each time."""
import argparse
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

URL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")  # api.* is cloudflared's own API
URL_TIMEOUT_S = 30
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
WINDOWS_PATHS = [Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
                 Path(r"C:\Program Files\cloudflared\cloudflared.exe")]
INSTALL_HINT = ("cloudflared is not installed. Install it with:\n"
                "  Windows: winget install --id Cloudflare.cloudflared   (then open a new terminal)\n"
                "  macOS:   brew install cloudflared\n"
                "  Linux:   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")


class TunnelError(Exception):
    pass


def find_cloudflared(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    found = shutil.which("cloudflared") or next((str(p) for p in WINDOWS_PATHS if p.exists()), None)
    if not found:
        raise TunnelError(INSTALL_HINT)
    return found


def find_url(line: str) -> str | None:
    match = URL_RE.search(line)
    return match.group(0) if match else None


def wait_for_url(lines: "queue.Queue[str | None]", timeout_s: float = URL_TIMEOUT_S) -> str:
    """Reads cloudflared's log lines until the public URL shows up. None in the queue = process ended."""
    deadline = time.monotonic() + timeout_s
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            raise TunnelError("cloudflared exited before printing a tunnel URL (no internet, or blocked network?)")
        if url := find_url(line):
            return url
    raise TunnelError(f"No tunnel URL from cloudflared within {timeout_s:.0f} s (network blocks tunnels? "
                      "use the hotspot + mkcert fallback in docs/07_HTTPS_DEMO.md)")


@dataclass
class Tunnel:
    name: str
    local_url: str
    process: subprocess.Popen
    lines: "queue.Queue[str | None]" = field(default_factory=queue.Queue)
    public_url: str = ""

    @classmethod
    def start(cls, exe: str, name: str, local_url: str) -> "Tunnel":
        proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", local_url],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        tunnel = cls(name, local_url, proc)
        # Keep draining the log for the whole run, or cloudflared blocks on a full pipe.
        threading.Thread(target=tunnel._pump, daemon=True).start()
        return tunnel

    def _pump(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def env_values(backend_url: str) -> dict[str, str]:
    host = backend_url.removeprefix("https://")
    return {"VITE_API_BASE": f"https://{host}/api/v1", "VITE_WS_BASE": f"wss://{host}/ws"}


def update_env_lines(text: str, values: dict[str, str]) -> str:
    """Replaces KEY=... lines for the given keys (appending missing ones); keeps everything else."""
    lines = text.splitlines()
    remaining = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    return "\n".join(lines) + "\n"


def write_frontend_env(values: dict[str, str], frontend_dir: Path = FRONTEND_DIR) -> Path:
    env, example = frontend_dir / ".env", frontend_dir / ".env.example"
    current = env.read_text(encoding="utf-8") if env.exists() else (
        example.read_text(encoding="utf-8") if example.exists() else "")
    env.write_text(update_env_lines(current, values), encoding="utf-8")
    return env


def check_health(backend_url: str, timeout_s: float = 20) -> str:
    """The quick-tunnel DNS can take a few seconds; retry until /health answers."""
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{backend_url}/api/v1/health", timeout=5) as resp:
                return resp.read().decode()
        except Exception as exc:  # DNS not ready yet, backend down, ...
            last = str(exc)
            time.sleep(1)
    return f"not reachable yet ({last}). Is the backend running on port 8000?"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Start Cloudflare quick tunnels for the phone demo.")
    p.add_argument("--backend-port", type=int, default=8000)
    p.add_argument("--frontend-port", type=int, default=5173)
    p.add_argument("--backend-only", action="store_true", help="skip the Vite tunnel")
    p.add_argument("--write-env", action="store_true", help="write VITE_API_BASE/VITE_WS_BASE into frontend/.env")
    p.add_argument("--cloudflared", help="path to cloudflared if it is not on PATH")
    args = p.parse_args(argv)

    try:
        exe = find_cloudflared(args.cloudflared)
    except TunnelError as exc:
        print(exc, file=sys.stderr)
        return 2
    tunnels = [Tunnel.start(exe, "backend", f"http://localhost:{args.backend_port}")]
    if not args.backend_only:
        tunnels.append(Tunnel.start(exe, "frontend", f"http://localhost:{args.frontend_port}"))
    try:
        for t in tunnels:
            t.public_url = wait_for_url(t.lines)
        backend = tunnels[0].public_url
        values = env_values(backend)
        bar = "=" * 72
        print(f"\n{bar}\n Backend  {backend}   (-> {tunnels[0].local_url})")
        if not args.backend_only:
            print(f" Frontend {tunnels[1].public_url}   (-> {tunnels[1].local_url})")
            print(f"\n Open on the phone (Wi-Fi off to test mobile data): {tunnels[1].public_url}")
        print("\n frontend/.env:")
        for k, v in values.items():
            print(f"   {k}={v}")
        if args.write_env:
            print(f"   written to {write_frontend_env(values)}  (restart Vite to pick it up)")
        print("\n backend/.env needs once: ALLOWED_ORIGIN_REGEX=^https://[a-z0-9-]+\\.trycloudflare\\.com$")
        print(f"\n Health through the tunnel: {check_health(backend)}")
        print(f" wss check: python -m tools.wss_check --base {backend}\n{bar}\n Ctrl+C to stop the tunnels.")
        while all(t.process.poll() is None for t in tunnels):
            time.sleep(1)
        print("A tunnel stopped unexpectedly; rerun this command (the URLs will change).", file=sys.stderr)
        return 1
    except TunnelError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for t in tunnels:
            t.stop()


if __name__ == "__main__":
    sys.exit(main())
