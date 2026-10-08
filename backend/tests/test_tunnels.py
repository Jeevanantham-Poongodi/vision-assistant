"""BE-07 helpers: cloudflared URL parsing, frontend .env updates, wss URL building."""
import queue

import pytest

from tools import tunnels
from tools.tunnels import TunnelError, env_values, find_url, update_env_lines, wait_for_url, write_frontend_env
from tools.wss_check import ws_base

# What cloudflared prints for a quick tunnel (to stderr).
CLOUDFLARED_LOG = """\
2026-10-09T10:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...
2026-10-09T10:00:01Z INF +--------------------------------------------------------------------------------------------+
2026-10-09T10:00:01Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
2026-10-09T10:00:01Z INF |  https://brave-otter-sample-words.trycloudflare.com                                        |
2026-10-09T10:00:01Z INF +--------------------------------------------------------------------------------------------+
"""


def lines_queue(text: str, end: bool = False) -> "queue.Queue[str | None]":
    q: "queue.Queue[str | None]" = queue.Queue()
    for line in text.splitlines(keepends=True):
        q.put(line)
    if end:
        q.put(None)
    return q


# --- URL parsing ---

def test_find_url_in_cloudflared_log():
    assert wait_for_url(lines_queue(CLOUDFLARED_LOG), timeout_s=1) == "https://brave-otter-sample-words.trycloudflare.com"


def test_cloudflared_api_url_is_not_the_tunnel():
    line = 'ERR failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp: timeout'
    assert find_url(line) is None


def test_no_url_times_out_with_hint():
    with pytest.raises(TunnelError, match="hotspot"):
        wait_for_url(lines_queue("INF starting\n"), timeout_s=0.2)


def test_process_exit_before_url():
    with pytest.raises(TunnelError, match="exited"):
        wait_for_url(lines_queue("ERR no internet\n", end=True), timeout_s=1)


def test_missing_cloudflared_gives_install_hint(monkeypatch):
    monkeypatch.setattr(tunnels.shutil, "which", lambda name: None)
    monkeypatch.setattr(tunnels, "WINDOWS_PATHS", [])
    with pytest.raises(TunnelError, match="winget install --id Cloudflare.cloudflared"):
        tunnels.find_cloudflared()


def test_explicit_cloudflared_path_wins():
    assert tunnels.find_cloudflared(r"D:\tools\cloudflared.exe") == r"D:\tools\cloudflared.exe"


# --- frontend/.env ---

def test_env_values():
    assert env_values("https://abc-def.trycloudflare.com") == {
        "VITE_API_BASE": "https://abc-def.trycloudflare.com/api/v1",
        "VITE_WS_BASE": "wss://abc-def.trycloudflare.com/ws",
    }


def test_update_env_lines_changes_only_the_given_keys():
    text = ("# Copy to frontend/.env\nVITE_API_BASE=http://localhost:8000/api/v1\n"
            "VITE_WS_BASE=ws://localhost:8000/ws\nVITE_USE_MOCKS=false\n# VITE_API_BASE=commented out\n")
    out = update_env_lines(text, env_values("https://x-y.trycloudflare.com"))
    assert out == ("# Copy to frontend/.env\nVITE_API_BASE=https://x-y.trycloudflare.com/api/v1\n"
                   "VITE_WS_BASE=wss://x-y.trycloudflare.com/ws\nVITE_USE_MOCKS=false\n# VITE_API_BASE=commented out\n")


def test_update_env_lines_appends_missing_keys():
    assert update_env_lines("VITE_USE_MOCKS=false", {"VITE_WS_BASE": "wss://h/ws"}) == \
        "VITE_USE_MOCKS=false\nVITE_WS_BASE=wss://h/ws\n"


def test_write_frontend_env_starts_from_example(tmp_path):
    (tmp_path / ".env.example").write_text("VITE_API_BASE=http://localhost:8000/api/v1\nVITE_USE_MOCKS=true\n")
    env = write_frontend_env({"VITE_API_BASE": "https://h/api/v1"}, frontend_dir=tmp_path)
    assert env.read_text() == "VITE_API_BASE=https://h/api/v1\nVITE_USE_MOCKS=true\n"
    (tmp_path / ".env").write_text("VITE_API_BASE=old\nVITE_USE_MOCKS=false\n")  # an existing .env wins
    write_frontend_env({"VITE_API_BASE": "https://new/api/v1"}, frontend_dir=tmp_path)
    assert (tmp_path / ".env").read_text() == "VITE_API_BASE=https://new/api/v1\nVITE_USE_MOCKS=false\n"


# --- wss_check ---

@pytest.mark.parametrize("base, expected", [
    ("https://abc.trycloudflare.com", "wss://abc.trycloudflare.com"),
    ("https://abc.trycloudflare.com/", "wss://abc.trycloudflare.com"),
    ("http://127.0.0.1:8000", "ws://127.0.0.1:8000"),
])
def test_ws_base(base, expected):
    assert ws_base(base) == expected


def test_ws_base_rejects_other_schemes():
    with pytest.raises(ValueError):
        ws_base("abc.trycloudflare.com")
