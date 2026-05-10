#!/usr/bin/env python3
"""Lightweight wake listener for the local Jarvis assistant.

This is the always-on layer:
- terminal mode: type a wake phrase such as "Hey Jarvis"
- microphone mode: continuously waits for speech, transcribes it, and checks for
  a configured wake phrase

When a wake phrase is detected, this launches jarvis_ui.py. The full UI is not
kept running permanently.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import config
from speech_input import SpeechInput

PROJECT_DIR = Path(__file__).resolve().parent
WAKE_WORDS = list(getattr(config, "WAKE_WORDS", ["hey jarvis"]))
CLOSE_WORDS = list(getattr(config, "CLOSE_WORDS", ["bye jarvis"]))
UI_SCRIPT = PROJECT_DIR / getattr(config, "WAKE_UI_SCRIPT", "jarvis_ui.py")
UI_COOLDOWN_SECONDS = float(getattr(config, "WAKE_UI_COOLDOWN_SECONDS", 5.0))
WAKE_TERMINAL_MODE = bool(getattr(config, "WAKE_TERMINAL_MODE", True))
WAKE_MIC_MODE = bool(getattr(config, "WAKE_MIC_MODE", True))


def normalise(text: str) -> str:
    """Lowercase and squash whitespace/punctuation enough for wake matching."""
    cleaned = text.lower()
    for char in ",.!?:;\"'()[]{}":
        cleaned = cleaned.replace(char, " ")
    return " ".join(cleaned.split())


def matches_wake_word(text: str, wake_words: Iterable[str] = WAKE_WORDS) -> bool:
    heard = normalise(text)
    return any(normalise(word) in heard for word in wake_words)


def matches_close_word(text: str, close_words: Iterable[str] = CLOSE_WORDS) -> bool:
    heard = normalise(text)
    return any(normalise(word) in heard for word in close_words)


@dataclass
class WakeLauncher:
    """Launch Jarvis UI with a small cooldown to avoid window spam."""

    dry_run: bool = False

    def __post_init__(self) -> None:
        self._last_launch = 0.0
        self._lock = threading.Lock()
        self._ui_process: subprocess.Popen | None = None

    def trigger(self, source: str, phrase: str) -> None:
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._last_launch
            if elapsed < UI_COOLDOWN_SECONDS:
                remaining = UI_COOLDOWN_SECONDS - elapsed
                print(f"Wake detected via {source}, UI cooldown active ({remaining:.1f}s left).")
                return
            self._last_launch = now

        print(f"Wake word detected via {source}: {phrase!r}")

        if self.dry_run:
            print(f"Dry run: would launch {UI_SCRIPT}")
            return

        try:
            process = subprocess.Popen(
                [sys.executable, str(UI_SCRIPT)],
                cwd=str(PROJECT_DIR),
                start_new_session=True,
            )
            with self._lock:
                self._ui_process = process
            print("Jarvis UI launch requested.")
        except Exception as exc:
            print(f"Failed to launch Jarvis UI: {exc}", file=sys.stderr)

    def close_ui(self, source: str, phrase: str) -> None:
        """Close any Jarvis UI launched by this listener, plus matching orphan UIs."""
        print(f"Close phrase detected via {source}: {phrase!r}")

        if self.dry_run:
            print(f"Dry run: would close UI process for {UI_SCRIPT}")
            return

        closed_any = False
        with self._lock:
            process = self._ui_process

        if process is not None and process.poll() is None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                closed_any = True
            except Exception as exc:
                print(f"Failed to terminate tracked Jarvis UI: {exc}", file=sys.stderr)

        # If the listener restarted, it may not have a handle to the UI process.
        # On macOS we can still find the exact jarvis_ui.py command and stop it.
        closed_any = self._close_orphan_ui_processes() or closed_any

        if closed_any:
            print("Jarvis UI close requested. Wake listener is still running.")
        else:
            print("No running Jarvis UI process found. Wake listener is still running.")

    def _close_orphan_ui_processes(self) -> bool:
        try:
            result = subprocess.run(
                ["pgrep", "-f", str(UI_SCRIPT)],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except Exception:
            return False

        if result.returncode not in {0, 1}:
            return False

        closed_any = False
        current_pid = os.getpid()
        for raw_pid in result.stdout.split():
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            if pid == current_pid:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                closed_any = True
            except ProcessLookupError:
                continue
            except PermissionError as exc:
                print(f"No permission to terminate Jarvis UI pid {pid}: {exc}", file=sys.stderr)
        return closed_any


def terminal_loop(launcher: WakeLauncher, stop: threading.Event) -> None:
    wake_hint = " / ".join(WAKE_WORDS)
    close_hint = " / ".join(CLOSE_WORDS)
    print(f'Terminal mode ready. Type "{wake_hint}" and press Enter to open Jarvis.')
    print(f'Type "{close_hint}" and press Enter to close the UI while keeping the listener alive.')
    print('Type "quit" to stop the wake listener.')

    while not stop.is_set():
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            stop.set()
            return

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in {"q", "quit", "exit"}:
            stop.set()
            return
        if matches_close_word(stripped):
            launcher.close_ui("terminal", stripped)
        elif matches_wake_word(stripped):
            launcher.trigger("terminal", stripped)
        else:
            print(f'Waiting for wake/close phrase. Try: "{WAKE_WORDS[0]}" or "{CLOSE_WORDS[0]}"')


def mic_loop(launcher: WakeLauncher, stop: threading.Event) -> None:
    """Continuously listen for utterances and check transcripts for wake words."""
    speech = SpeechInput()
    print(f"Microphone mode ready. Say wake: {', '.join(WAKE_WORDS)}")
    print(f"Microphone close phrases: {', '.join(CLOSE_WORDS)}")
    print("First run may require macOS microphone permission for Terminal/Python.")

    while not stop.is_set():
        try:
            audio_path = speech.listen_for_utterance(
                cancel_event=stop,
                voice_start_threshold=getattr(config, "WAKE_VOICE_START_THRESHOLD", None),
            )
            if stop.is_set() or audio_path is None:
                continue

            transcript = speech.transcribe(audio_path).strip()
            if not transcript:
                continue

            print(f"heard: {transcript}")
            if matches_close_word(transcript):
                launcher.close_ui("microphone", transcript)
            elif matches_wake_word(transcript):
                launcher.trigger("microphone", transcript)
        except Exception as exc:
            if stop.is_set():
                break
            print(f"Wake microphone loop error: {exc}", file=sys.stderr)
            print("Retrying microphone wake listener in 2s. Terminal mode still works if enabled.")
            time.sleep(2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis wake-word listener")
    parser.add_argument("--no-terminal", action="store_true", help="disable terminal wake-word mode")
    parser.add_argument("--no-mic", action="store_true", help="disable microphone wake-word mode")
    parser.add_argument("--dry-run", action="store_true", help="detect wake words without launching the UI")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stop = threading.Event()

    def request_stop(signum, frame) -> None:  # noqa: ANN001
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    use_terminal = WAKE_TERMINAL_MODE and not args.no_terminal
    use_mic = WAKE_MIC_MODE and not args.no_mic

    if not use_terminal and not use_mic:
        print("Both terminal and microphone wake modes are disabled.", file=sys.stderr)
        return 2

    print("Jarvis wake listener starting.")
    print(f"Wake words: {', '.join(WAKE_WORDS)}")
    print(f"Close words: {', '.join(CLOSE_WORDS)}")
    print("The full UI will only launch after wake detection.")

    launcher = WakeLauncher(dry_run=args.dry_run)
    threads: list[threading.Thread] = []

    if use_mic:
        mic_thread = threading.Thread(target=mic_loop, args=(launcher, stop), daemon=True)
        mic_thread.start()
        threads.append(mic_thread)

    if use_terminal:
        # Keep terminal input on the main thread so Ctrl+C behaves naturally.
        terminal_loop(launcher, stop)
    else:
        while not stop.is_set():
            time.sleep(0.25)

    stop.set()
    for thread in threads:
        thread.join(timeout=1.0)

    print("Jarvis wake listener stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
