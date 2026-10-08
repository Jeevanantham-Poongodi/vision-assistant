from __future__ import annotations

import queue
import threading
import time

import pytest

from speech import local_tts


class FakeEngine:
    def __init__(self) -> None:
        self.started: queue.Queue[str] = queue.Queue()
        self.releases: queue.Queue[None] = queue.Queue()
        self.stop_calls = 0
        self._next_text = ""

    def say(self, text: str) -> None:
        self._next_text = text

    def runAndWait(self) -> None:
        self.started.put(self._next_text)
        self.releases.get(timeout=2)

    def stop(self) -> None:
        self.stop_calls += 1
        self.releases.put(None)

    def setProperty(self, name: str, value: object) -> None:
        pass

    def wait_for_text(self) -> str:
        return self.started.get(timeout=2)

    def finish_current(self) -> None:
        self.releases.put(None)


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    engine = FakeEngine()
    monkeypatch.setattr(local_tts, "_create_engine", lambda rate, volume: engine)
    return engine


def test_speech_runs_on_worker_and_uses_priority_order(
    fake_engine: FakeEngine,
) -> None:
    manager = local_tts.LocalTTSManager()
    try:
        manager.speak("currently speaking")
        assert fake_engine.wait_for_text() == "currently speaking"

        manager.speak("low priority", priority=20)
        manager.speak("high priority", priority=80)
        fake_engine.finish_current()
        assert fake_engine.wait_for_text() == "high priority"

        fake_engine.finish_current()
        assert fake_engine.wait_for_text() == "low priority"
        fake_engine.finish_current()
    finally:
        manager.stop()


def test_interrupt_stops_current_and_flushes_pending_speech(
    fake_engine: FakeEngine,
) -> None:
    manager = local_tts.LocalTTSManager()
    try:
        manager.speak("current")
        assert fake_engine.wait_for_text() == "current"
        manager.speak("must be discarded")
        manager.speak("urgent", priority=100, interrupt=True)

        assert fake_engine.wait_for_text() == "urgent"
        assert fake_engine.stop_calls == 1
        fake_engine.finish_current()
        with pytest.raises(queue.Empty):
            fake_engine.started.get(timeout=0.05)
    finally:
        manager.stop()


def test_stop_halts_current_and_flushes_queue(fake_engine: FakeEngine) -> None:
    manager = local_tts.LocalTTSManager()
    try:
        manager.speak("current")
        assert fake_engine.wait_for_text() == "current"
        manager.speak("queued")
        manager.stop()

        assert fake_engine.stop_calls == 1
        manager._tasks.join()
    finally:
        manager.stop()


def test_driver_initialization_failure_is_reported_and_nonfatal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failed = threading.Event()

    def fail_initialization(rate: int, volume: float) -> FakeEngine:
        failed.set()
        raise RuntimeError("audio driver unavailable")

    monkeypatch.setattr(local_tts, "_create_engine", fail_initialization)
    manager = local_tts.LocalTTSManager()
    assert failed.wait(timeout=2)

    manager.speak("cannot be played")
    manager._tasks.join()
    assert "offline speech is disabled" in capsys.readouterr().err


def test_module_speak_returns_without_waiting_for_playback(
    fake_engine: FakeEngine,
) -> None:
    started = time.monotonic()
    local_tts.speak("background request")

    assert time.monotonic() - started < 0.5
    assert fake_engine.wait_for_text() == "background request"
