"""Asynchronous offline speech output for local demos."""

from __future__ import annotations

import importlib
import queue
import sys
import threading
from itertools import count
from typing import Protocol, cast


class _SpeechEngine(Protocol):
    def say(self, text: str) -> None: ...

    def runAndWait(self) -> None: ...

    def stop(self) -> None: ...

    def setProperty(self, name: str, value: object) -> None: ...


_SpeechTask = tuple[int, int, int, str]


def _create_engine(rate: int, volume: float) -> _SpeechEngine:
    module = importlib.import_module("pyttsx3")
    initialize = getattr(module, "init", None)
    if not callable(initialize):
        raise RuntimeError("pyttsx3 does not expose an init() function")

    engine = cast(_SpeechEngine, initialize())
    engine.setProperty("rate", rate)
    engine.setProperty("volume", volume)
    return engine


class LocalTTSManager:
    """Serialize pyttsx3 access on a dedicated daemon worker thread."""

    def __init__(self, rate: int = 175, volume: float = 1.0) -> None:
        self._rate = rate
        self._volume = volume
        self._tasks: queue.PriorityQueue[_SpeechTask] = queue.PriorityQueue()
        self._sequence = count()
        self._generation = 0
        self._lock = threading.RLock()
        self._engine: _SpeechEngine | None = None
        self._worker = threading.Thread(
            target=self._run_worker,
            name="local-tts-worker",
            daemon=True,
        )
        self._worker.start()

    def speak(
        self, text: str, priority: int = 50, interrupt: bool = False
    ) -> None:
        """Queue speech without blocking the caller."""
        if not isinstance(text, str) or not text.strip():
            return
        if isinstance(priority, bool) or not isinstance(priority, int):
            print("Local TTS skipped speech with a non-integer priority.", file=sys.stderr)
            return

        with self._lock:
            if interrupt:
                self._generation += 1
                self._clear_pending_locked()
                if self._engine is not None:
                    self._stop_engine_locked(self._engine)

            task: _SpeechTask = (
                -priority,
                next(self._sequence),
                self._generation,
                text.strip(),
            )
            self._tasks.put(task)

    def stop(self) -> None:
        """Stop active playback and discard all queued speech."""
        with self._lock:
            self._generation += 1
            self._clear_pending_locked()
            if self._engine is not None:
                self._stop_engine_locked(self._engine)

    def _clear_pending_locked(self) -> None:
        while True:
            try:
                self._tasks.get_nowait()
            except queue.Empty:
                return
            else:
                self._tasks.task_done()

    @staticmethod
    def _stop_engine_locked(engine: _SpeechEngine) -> None:
        try:
            engine.stop()
        except Exception as exc:
            print(f"Local TTS could not stop the speech driver: {exc}", file=sys.stderr)

    def _run_worker(self) -> None:
        try:
            engine = _create_engine(self._rate, self._volume)
        except Exception as exc:
            print(
                f"Local TTS unavailable; offline speech is disabled: {exc}",
                file=sys.stderr,
            )
            while True:
                self._tasks.get()
                self._tasks.task_done()

        with self._lock:
            self._engine = engine

        while True:
            task = self._tasks.get()
            try:
                _, _, generation, text = task
                with self._lock:
                    if generation != self._generation:
                        continue

                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    print(f"Local TTS playback failed: {exc}", file=sys.stderr)
            finally:
                self._tasks.task_done()


_manager: LocalTTSManager | None = None
_manager_lock = threading.Lock()


def speak(text: str, priority: int = 50, interrupt: bool = False) -> None:
    """Speak locally without blocking the calling application thread."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = LocalTTSManager()
        manager = _manager
    manager.speak(text, priority=priority, interrupt=interrupt)
