"""
Speech input support for the Jarvis UI.

This module deliberately does not know about Tkinter or OpenClaw.
It only records microphone audio, saves it to a temporary WAV file, and
transcribes that file. The UI decides what to do with the returned text.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import config


class SpeechInput:
    """Record microphone audio and transcribe it with a configurable STT backend."""

    def __init__(self) -> None:
        self.sample_rate = getattr(config, "MIC_SAMPLE_RATE", 16_000)
        self.channels = getattr(config, "MIC_CHANNELS", 1)
        self.stt_backend = getattr(config, "STT_BACKEND", "whisper_local")
        self.whisper_model = getattr(config, "WHISPER_MODEL", "base")
        self.whisper_language = getattr(config, "WHISPER_LANGUAGE", "en")

        self.voice_start_threshold = getattr(config, "VOICE_START_THRESHOLD", 0.015)
        self.voice_silence_threshold = getattr(config, "VOICE_SILENCE_THRESHOLD", 0.01)
        self.silence_stop_seconds = getattr(config, "SILENCE_STOP_SECONDS", 3.0)
        self.min_utterance_seconds = getattr(config, "MIN_UTTERANCE_SECONDS", 0.4)
        self.max_utterance_seconds = getattr(config, "MAX_UTTERANCE_SECONDS", 45.0)

        self._frames: list[object] = []
        self._stream = None
        self._recording_lock = threading.Lock()
        self._transcription_process: subprocess.Popen | None = None
        self._last_audio_path: Path | None = None

    @property
    def is_recording(self) -> bool:
        """Return True if a manual microphone recording stream is currently active."""
        return self._stream is not None

    def start_recording(self) -> None:
        """Start manual microphone recording into memory."""
        with self._recording_lock:
            if self._stream is not None:
                return

            sounddevice = self._import_sounddevice()
            self._frames = []
            self._stream = sounddevice.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
            )
            self._stream.start()

    def stop_recording(self) -> Path:
        """Stop manual recording, save the captured audio, and return the WAV path."""
        with self._recording_lock:
            if self._stream is None:
                raise RuntimeError("No active recording to stop.")

            stream = self._stream
            self._stream = None

        stream.stop()
        stream.close()

        if not self._frames:
            raise RuntimeError("No audio was recorded.")

        return self._write_temp_wav(self._frames)

    def listen_for_utterance(
        self,
        cancel_event: threading.Event,
        on_voice_start: Callable[[], None] | None = None,
        voice_start_threshold: float | None = None,
    ) -> Path | None:
        """
        Listen until speech starts, then stop after sustained silence.

        Returns a temporary WAV path, or None if listening was cancelled before a
        usable utterance was captured.
        """
        sounddevice = self._import_sounddevice()
        numpy = self._import_numpy()

        start_threshold = voice_start_threshold or self.voice_start_threshold
        chunks: list[object] = []
        speech_started = False
        voice_callback_fired = False
        speech_start_time = 0.0
        last_voice_time = 0.0

        def callback(indata, frames, time_info, status) -> None:
            if status:
                pass
            chunks.append(indata.copy())

        with sounddevice.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=callback,
        ):
            read_index = 0
            while not cancel_event.is_set():
                if read_index >= len(chunks):
                    time.sleep(0.02)
                    continue

                chunk = chunks[read_index]
                read_index += 1
                now = time.monotonic()
                rms = float(numpy.sqrt(numpy.mean(numpy.square(chunk))))

                if not speech_started:
                    if rms >= start_threshold:
                        speech_started = True
                        speech_start_time = now
                        last_voice_time = now
                        if on_voice_start and not voice_callback_fired:
                            voice_callback_fired = True
                            on_voice_start()
                    else:
                        # Drop room noise before speech starts so Whisper receives
                        # the actual utterance rather than a long silent prefix.
                        chunks = chunks[read_index:]
                        read_index = 0
                        continue

                if rms >= self.voice_silence_threshold:
                    last_voice_time = now

                utterance_duration = now - speech_start_time
                silent_duration = now - last_voice_time
                if (
                    silent_duration >= self.silence_stop_seconds
                    and utterance_duration >= self.min_utterance_seconds
                ):
                    return self._write_temp_wav(chunks)

                if utterance_duration >= self.max_utterance_seconds:
                    return self._write_temp_wav(chunks)

        return None

    def transcribe(self, audio_path: Path) -> str:
        """Transcribe an audio file and return plain text."""
        if self.stt_backend == "whisper_local":
            return self._transcribe_with_local_whisper(audio_path)

        raise ValueError(f"Unsupported STT_BACKEND: {self.stt_backend}")

    def cancel(self) -> None:
        """Stop any active manual recording/transcription work."""
        with self._recording_lock:
            stream = self._stream
            self._stream = None

        if stream is not None:
            stream.stop()
            stream.close()

        if self._transcription_process and self._transcription_process.poll() is None:
            self._transcription_process.terminate()
            try:
                self._transcription_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._transcription_process.kill()
                self._transcription_process.wait(timeout=1)

        self._transcription_process = None

    def cleanup_last_audio(self) -> None:
        """Delete the most recent temporary audio file, if it still exists."""
        if self._last_audio_path and self._last_audio_path.exists():
            self._last_audio_path.unlink()
        self._last_audio_path = None

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """Receive audio chunks from sounddevice for manual recording."""
        if status:
            pass
        self._frames.append(indata.copy())

    def _write_temp_wav(self, frames: list[object]) -> Path:
        """Write captured frames to a temporary WAV file."""
        numpy = self._import_numpy()
        wavfile = self._import_wavfile()

        audio = numpy.concatenate(frames, axis=0)
        temp_file = tempfile.NamedTemporaryFile(
            prefix="jarvis_mic_",
            suffix=".wav",
            delete=False,
        )
        temp_file.close()

        audio_path = Path(temp_file.name)
        wavfile.write(audio_path, self.sample_rate, audio)
        self._last_audio_path = audio_path
        return audio_path

    def _transcribe_with_local_whisper(self, audio_path: Path) -> str:
        """Run the local Whisper CLI and return the transcript."""
        if not shutil.which("whisper"):
            raise RuntimeError(
                "Whisper CLI not found. Install it with: pip install -U openai-whisper"
            )

        output_dir = Path(tempfile.mkdtemp(prefix="jarvis_whisper_"))
        command = [
            "whisper",
            str(audio_path),
            "--model",
            self.whisper_model,
            "--language",
            self.whisper_language,
            "--output_format",
            "txt",
            "--output_dir",
            str(output_dir),
        ]

        self._transcription_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = self._transcription_process.communicate()
        return_code = self._transcription_process.returncode
        self._transcription_process = None

        if return_code != 0:
            error = stderr.strip() or stdout.strip() or "Whisper transcription failed."
            raise RuntimeError(error)

        transcript_path = output_dir / f"{audio_path.stem}.txt"
        if not transcript_path.exists():
            raise RuntimeError("Whisper finished but did not produce a transcript file.")

        return transcript_path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _import_sounddevice():
        try:
            import sounddevice
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: sounddevice. Install it with: pip install sounddevice"
            ) from exc
        return sounddevice

    @staticmethod
    def _import_numpy():
        try:
            import numpy
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: numpy. Install it with: pip install numpy"
            ) from exc
        return numpy

    @staticmethod
    def _import_wavfile():
        try:
            from scipy.io import wavfile
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: scipy. Install it with: pip install scipy"
            ) from exc
        return wavfile
