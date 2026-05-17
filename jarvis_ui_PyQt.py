"""
PyQt6 Jarvis desktop UI.

This is a PyQt6 port of ``jarvis_ui.py`` that keeps the same Jarvis flow:
voice input, OpenClaw request, text-to-speech output, automatic listening, and
text input. The visual orb is the VisPy/PyQt6 3D orb from ``3d_orb_widget.py``.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from openclaw_adapter import ask_openclaw
from full3d_orb_widget import ORB_BG, Jarvis3DOrbWidget
from speech_input import SpeechInput


BOT_NAME = getattr(config, "bot_name", "Jarvis")
WINDOW_TITLE = BOT_NAME
WINDOW_WIDTH_RATIO = 0.9
WINDOW_HEIGHT_RATIO = 0.88

BG = "#0b1020"
PANEL_BG = "#111827"
TEXT_BG = "#020617"
TEXT_FG = "#e5e7eb"
MUTED = "#94a3b8"
ACCENT = "#7dd3fc"
ERROR = "#f87171"
SUCCESS = "#34d399"

PROJECT_DIR = Path(__file__).resolve().parent
TTS_BACKEND = getattr(config, "TTS_BACKEND", "say")
PIPER_MODEL_PATH = PROJECT_DIR / getattr(config, "PIPER_MODEL_PATH", "voices/en_GB-vctk-medium.onnx")
PIPER_SPEAKER_ID = getattr(config, "PIPER_SPEAKER_ID", None)
PIPER_LENGTH_SCALE = getattr(config, "PIPER_LENGTH_SCALE", 1.35)
ELEVENLABS_API_KEY = getattr(config, "ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = getattr(config, "ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_MODEL_ID = getattr(config, "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
ELEVENLABS_STABILITY = getattr(config, "ELEVENLABS_STABILITY", 0.3)
ELEVENLABS_SIMILARITY_BOOST = getattr(config, "ELEVENLABS_SIMILARITY_BOOST", 0.75)
ELEVENLABS_SPEED = getattr(config, "ELEVENLABS_SPEED", 1.0)
SPEECH_NEWLINE_PAUSE_SECONDS = getattr(config, "SPEECH_NEWLINE_PAUSE_SECONDS", 0.05)
AUTO_LISTEN_ON_LAUNCH = getattr(config, "AUTO_LISTEN_ON_LAUNCH", True)
INACTIVITY_QUIT_SECONDS = getattr(config, "INACTIVITY_QUIT_SECONDS", 120)


class MessageInput(QTextEdit):
    """Text box that sends on Enter and inserts a newline on Shift+Enter."""

    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_return = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_return and not is_shift:
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class JarvisUIPyQt(QMainWindow):
    """PyQt6 Jarvis chat UI connected to the OpenClaw adapter."""

    def __init__(self) -> None:
        super().__init__()
        self.response_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.is_waiting_for_response = False
        self.is_listening = False
        self.is_closing = False
        self.speech_input = SpeechInput()
        self.voice_cancel_event: threading.Event | None = None
        self.voice_thread: threading.Thread | None = None
        self.speech_was_interrupted = False
        self.current_state = "idle"
        self.last_agent_spoke_at = time.monotonic()
        self.tts_process: subprocess.Popen | None = None
        self.tts_process_lock = threading.Lock()

        self.setWindowTitle(WINDOW_TITLE)
        self._set_initial_window_size()
        self.setMinimumSize(620, 440)

        self._build_widgets()
        self.set_status("idle")

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_response_queue)
        self.poll_timer.start(100)

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self._check_inactivity_timeout)
        self.inactivity_timer.start(1000)

        if AUTO_LISTEN_ON_LAUNCH:
            QTimer.singleShot(500, self._start_auto_listening)

    def _set_initial_window_size(self) -> None:
        """Launch Jarvis large and centered, covering most of the screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1000, 720)
            return

        available = screen.availableGeometry()
        width = int(available.width() * WINDOW_WIDTH_RATIO)
        height = int(available.height() * WINDOW_HEIGHT_RATIO)
        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def _build_widgets(self) -> None:
        """Create the orb-centred Jarvis UI skeleton."""
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        title = QLabel("JARVIS")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch(1)

        self.status_label = QLabel("status: idle")
        self.status_label.setObjectName("statusLabel")
        header.addWidget(self.status_label)
        outer.addLayout(header)

        orb_frame = QFrame()
        orb_frame.setObjectName("orbFrame")
        orb_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        orb_layout = QVBoxLayout(orb_frame)
        orb_layout.setContentsMargins(0, 0, 0, 0)
        orb_layout.setSpacing(0)

        self.orb_widget = Jarvis3DOrbWidget(initial_state="idle", interactive_camera=True)
        self.orb_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        orb_layout.addWidget(self.orb_widget)
        outer.addWidget(orb_frame, 8)

        bottom_panel = QWidget()
        bottom_panel.setObjectName("bottomPanel")
        bottom_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom_panel.setMaximumHeight(190)
        bottom_layout = QHBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(8)

        self.chat_output = QTextEdit()
        self.chat_output.setObjectName("chatOutput")
        self.chat_output.setReadOnly(True)
        self.chat_output.setMinimumHeight(84)
        self.chat_output.setMaximumHeight(118)
        text_column.addWidget(self.chat_output)

        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._on_stop_pressed)
        controls.addWidget(self.stop_button)

        self.text_mode_button = QPushButton("Text Input")
        self.text_mode_button.clicked.connect(self._enter_text_input_mode)
        controls.addWidget(self.text_mode_button)

        self.mic_button = QPushButton("🎙 Voice")
        self.mic_button.clicked.connect(self._on_mic_pressed)
        controls.addWidget(self.mic_button)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._on_send_pressed)
        controls.addWidget(self.send_button)
        controls.addStretch(1)

        self.message_input = MessageInput()
        self.message_input.setObjectName("messageInput")
        self.message_input.setFixedHeight(56)
        self.message_input.send_requested.connect(self._on_send_pressed)
        self.message_input.setVisible(False)
        text_column.addWidget(self.message_input)

        bottom_layout.addLayout(text_column, 1)
        bottom_layout.addLayout(controls)
        outer.addWidget(bottom_panel, 2)

        self.setStyleSheet(
            f"""
            QWidget#central {{
                background: {BG};
                color: {TEXT_FG};
                font-family: Helvetica;
            }}
            QLabel#titleLabel {{
                color: {ACCENT};
                font-size: 24px;
                font-weight: 700;
            }}
            QLabel#statusLabel {{
                color: {MUTED};
                font-size: 12px;
            }}
            QFrame#orbFrame {{
                background: {ORB_BG};
                border: 1px solid #1e293b;
            }}
            QTextEdit#chatOutput {{
                background: {TEXT_BG};
                color: {TEXT_FG};
                border: 0;
                padding: 10px;
                font-size: 11pt;
                selection-background-color: #1e3a8a;
            }}
            QTextEdit#messageInput {{
                background: {PANEL_BG};
                color: {TEXT_FG};
                border: 0;
                padding: 8px 10px;
                font-size: 12pt;
                selection-background-color: #1e3a8a;
            }}
            QPushButton {{
                background: #1f2937;
                color: {TEXT_FG};
                border: 1px solid #334155;
                padding: 7px 12px;
                min-width: 92px;
            }}
            QPushButton:hover {{
                background: #243244;
                border-color: #475569;
            }}
            QPushButton:pressed {{
                background: #172033;
            }}
            QPushButton:disabled {{
                color: #64748b;
                background: #111827;
                border-color: #1f2937;
            }}
            """
        )

        self._append_message(
            "system",
            "Orb UI test ready. Voice mode starts automatically; use Text Input for typed messages.",
        )
        self.orb_widget.start()

    def set_status(self, status: str) -> None:
        """Update status text and the orb visual state."""
        self.current_state = status
        colours = {
            "idle": MUTED,
            "listening": ACCENT,
            "transcribing": "#f472b6",
            "thinking": "#c084fc",
            "speaking": SUCCESS,
            "text_input": SUCCESS,
            "error": ERROR,
        }
        colour = colours.get(status, MUTED)
        self.status_label.setText(f"status: {status}")
        self.status_label.setStyleSheet(f"color: {colour}; font-size: 12px;")
        if hasattr(self, "orb_widget"):
            self.orb_widget.set_state(status)

    def _check_inactivity_timeout(self) -> None:
        """Close the UI after configurable silence so wake_listener can take over."""
        if self.is_closing:
            return

        timeout = INACTIVITY_QUIT_SECONDS
        if timeout:
            active_states = {"thinking", "transcribing", "speaking", "text_input"}
            inactive_for = time.monotonic() - self.last_agent_spoke_at
            if (
                inactive_for >= timeout
                and not self.is_waiting_for_response
                and self.current_state not in active_states
            ):
                self.close()

    def _mark_agent_spoke(self) -> None:
        """Record that Jarvis has recently produced/spoken a response."""
        self.last_agent_spoke_at = time.monotonic()

    def _append_message(self, role: str, message: str) -> None:
        """Append one message to the chat transcript."""
        labels = {
            "user": "You",
            "assistant": BOT_NAME,
            "system": "System",
            "error": "Error",
        }
        label_colours = {
            "user": "#fbbf24",
            "assistant": TEXT_FG,
            "system": MUTED,
            "error": ERROR,
        }
        label = labels.get(role, role.title())
        label_colour = label_colours.get(role, TEXT_FG)

        cursor = self.chat_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        label_format = QTextCharFormat()
        label_format.setForeground(QColor(label_colour))
        body_format = QTextCharFormat()
        body_format.setForeground(QColor(label_colour if role == "error" else TEXT_FG))

        cursor.insertText(f"{label}: ", label_format)
        cursor.insertText(f"{message}\n\n", body_format)
        self.chat_output.setTextCursor(cursor)
        self.chat_output.ensureCursorVisible()

    def _on_stop_pressed(self) -> None:
        """Stop speech/listening work and return to voice listening mode."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.is_waiting_for_response = False
        self.message_input.setVisible(False)
        self.send_button.setEnabled(True)
        self.text_mode_button.setEnabled(True)
        self._start_auto_listening()

    def _enter_text_input_mode(self) -> None:
        """Interrupt voice mode and reveal the bottom typed-input area."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.is_waiting_for_response = False
        self.set_status("text_input")
        self.mic_button.setText("🎙 Voice")
        self.mic_button.setEnabled(True)
        self.send_button.setEnabled(True)
        self.message_input.setEnabled(True)
        self.message_input.clear()
        self.message_input.setVisible(True)
        self.message_input.setFocus()

    def _on_mic_pressed(self) -> None:
        """Manually pause/resume automatic speech listening."""
        if self.is_waiting_for_response:
            return

        if self.is_listening:
            self._cancel_voice_listener()
            self.set_status("idle")
            return

        self._start_auto_listening()

    def _start_auto_listening(self) -> None:
        """Start background speech capture with silence-based auto-stop."""
        if self.is_closing or self.is_waiting_for_response:
            return

        if self.voice_thread and self.voice_thread.is_alive():
            if self.voice_cancel_event and self.voice_cancel_event.is_set():
                QTimer.singleShot(100, self._start_auto_listening)
            return

        self.voice_thread = None
        self.voice_cancel_event = threading.Event()
        self.is_listening = True
        self.message_input.setVisible(False)
        self.mic_button.setText("■ Listening")
        self.mic_button.setEnabled(True)
        self.send_button.setEnabled(True)
        self.message_input.setEnabled(True)

        self.set_status("listening")

        self.voice_thread = threading.Thread(
            target=self._listen_and_transcribe_in_background,
            args=(self.voice_cancel_event,),
            daemon=True,
        )
        self.voice_thread.start()

    def _cancel_voice_listener(self) -> None:
        """Stop the current automatic speech listener, if one is active."""
        if self.voice_cancel_event:
            self.voice_cancel_event.set()
        self.is_listening = False
        self.mic_button.setText("🎙 Voice")
        self.mic_button.setEnabled(True)

    def _listen_and_transcribe_in_background(
        self,
        cancel_event: threading.Event,
    ) -> None:
        """Listen for one utterance, transcribe it, and queue the transcript."""
        try:
            audio_path = self.speech_input.listen_for_utterance(
                cancel_event=cancel_event,
            )
            if self.is_closing or cancel_event.is_set() or audio_path is None:
                return

            self.response_queue.put(("transcribing", ""))

            transcript = self.speech_input.transcribe(audio_path)
            self.speech_input.cleanup_last_audio()
        except Exception as exc:
            if not self.is_closing and not cancel_event.is_set():
                self.response_queue.put(("error", f"Speech input failed: {exc}"))
        else:
            if not self.is_closing and not cancel_event.is_set():
                self.response_queue.put(("transcript", transcript))

    def _on_send_pressed(self) -> None:
        """Handle send button clicks and Enter key presses."""
        if self.is_waiting_for_response:
            return

        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.message_input.clear()
        self._send_user_message(message)

    def _send_user_message(self, message: str) -> None:
        """Display a user message and send it to the OpenClaw session."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.message_input.setVisible(False)
        self._append_message("user", message)
        self.is_waiting_for_response = True
        self.mic_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.message_input.setEnabled(False)
        self.set_status("thinking")

        thread = threading.Thread(
            target=self._ask_openclaw_in_background,
            args=(message,),
            daemon=True,
        )
        thread.start()

    def _ask_openclaw_in_background(self, message: str) -> None:
        """Call OpenClaw off the UI thread, then push the result into a queue."""
        try:
            response = ask_openclaw(message)
        except Exception as exc:
            self.response_queue.put(("error", str(exc)))
        else:
            self.response_queue.put(("assistant", response))

    def _clean_text_for_speech(self, text: str) -> str:
        """
        Remove emojis/symbols that TTS reads awkwardly aloud.

        The original assistant message is still shown in the UI unchanged; this
        only cleans the version sent to text-to-speech.
        """
        text = re.sub(
            "["
            "\U0001F300-\U0001FAFF"
            "\U00002700-\U000027BF"
            "\U00002600-\U000026FF"
            "\U0000FE0F"
            "]+",
            "",
            text,
        )
        text = text.replace("*", "")
        return re.sub(r"\s+", " ", text).strip()

    def _split_text_for_speech(self, text: str) -> list[str]:
        """Split assistant text into speakable chunks separated by newlines."""
        chunks = []
        for raw_chunk in re.split(r"\n+", text):
            chunk = self._clean_text_for_speech(raw_chunk)
            if chunk:
                chunks.append(chunk)
        return chunks

    def _sleep_between_speech_chunks(self) -> None:
        """Pause between newline-separated chunks while staying close-cancellable."""
        pause_remaining = SPEECH_NEWLINE_PAUSE_SECONDS
        while pause_remaining > 0 and not self.is_closing:
            sleep_for = min(0.1, pause_remaining)
            time.sleep(sleep_for)
            pause_remaining -= sleep_for

    def _speak_in_background(self, text: str) -> None:
        """
        Speak text in a background thread so speech does not freeze the UI.

        TTS_BACKEND is selected in config.py:
        - "piper": free/offline neural TTS using the downloaded voice model
        - "eleven_api": ElevenLabs cloud TTS
        - "say": macOS built-in fallback
        """
        speech_chunks = self._split_text_for_speech(text)
        if not speech_chunks:
            if not self.is_closing:
                self.response_queue.put(("speech_done", ""))
            return

        try:
            for index, speech_text in enumerate(speech_chunks):
                if self.is_closing:
                    return

                if index > 0:
                    self._sleep_between_speech_chunks()
                    if self.is_closing:
                        return

                if TTS_BACKEND == "piper":
                    self._speak_with_piper(speech_text)
                elif TTS_BACKEND == "eleven_api":
                    self._speak_with_elevenlabs(speech_text)
                else:
                    self._speak_with_macos_say(speech_text)
        except Exception as exc:
            if not self.is_closing and not self.speech_was_interrupted:
                self.response_queue.put(("error", f"Speech output failed: {exc}"))
        else:
            if not self.is_closing and not self.speech_was_interrupted:
                self.response_queue.put(("speech_done", ""))

    def _run_cancellable_tts_process(
        self,
        command: list[str],
        input_text: str | None = None,
        **kwargs,
    ) -> None:
        """Run one TTS/playback subprocess that can be stopped when the UI closes."""
        if self.is_closing:
            return

        process = subprocess.Popen(command, **kwargs)
        with self.tts_process_lock:
            self.tts_process = process

        try:
            if input_text is None:
                return_code = process.wait()
            else:
                process.communicate(input=input_text)
                return_code = process.returncode
        finally:
            with self.tts_process_lock:
                if self.tts_process is process:
                    self.tts_process = None

        if return_code != 0 and not self.is_closing:
            raise subprocess.CalledProcessError(return_code, command)

    def _stop_speech(self, interrupted: bool = False) -> None:
        """Stop any currently running `say` or `afplay` child process."""
        if interrupted:
            self.speech_was_interrupted = True

        with self.tts_process_lock:
            process = self.tts_process
            self.tts_process = None

        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def _speak_with_macos_say(self, text: str) -> None:
        """Speak text using macOS' built-in `say` command."""
        self._run_cancellable_tts_process(["say", text])

    def _speak_with_elevenlabs(self, text: str) -> None:
        """Generate speech with ElevenLabs, then play the returned mp3 with afplay."""
        if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY.startswith("PASTE_"):
            raise ValueError("Set ELEVENLABS_API_KEY in config.py before using eleven_api")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        body = json.dumps(
            {
                "text": text,
                "model_id": ELEVENLABS_MODEL_ID,
                "voice_settings": {
                    "stability": ELEVENLABS_STABILITY,
                    "similarity_boost": ELEVENLABS_SIMILARITY_BOOST,
                    "speed": ELEVENLABS_SPEED,
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=60) as response:
            audio = response.read()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as mp3_file:
            mp3_file.write(audio)
            mp3_file.flush()
            self._run_cancellable_tts_process(["afplay", mp3_file.name])

    def _speak_with_piper(self, text: str) -> None:
        """Generate speech with Piper, then play the resulting wav with afplay."""
        if not PIPER_MODEL_PATH.exists():
            raise FileNotFoundError(f"Piper voice model not found: {PIPER_MODEL_PATH}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as wav_file:
            command = [
                sys.executable,
                "-m",
                "piper",
                "--model",
                str(PIPER_MODEL_PATH),
                "--output_file",
                wav_file.name,
                "--length_scale",
                str(PIPER_LENGTH_SCALE),
            ]

            if PIPER_SPEAKER_ID is not None:
                command.extend(["--speaker", str(PIPER_SPEAKER_ID)])

            self._run_cancellable_tts_process(
                command,
                input_text=text,
                stdin=subprocess.PIPE,
                text=True,
                cwd=PROJECT_DIR,
            )

            if self.is_closing:
                return

            self._run_cancellable_tts_process(["afplay", wav_file.name])

    def _start_speaking(self, text: str) -> None:
        """Start speech output in the background."""
        if self.is_closing:
            return

        self._mark_agent_spoke()
        self._stop_speech()
        self.speech_was_interrupted = False
        self.set_status("speaking")
        self._cancel_voice_listener()
        thread = threading.Thread(
            target=self._speak_in_background,
            args=(text,),
            daemon=True,
        )
        thread.start()

    def _poll_response_queue(self) -> None:
        """Check for completed OpenClaw/TTS responses and update the UI."""
        if self.is_closing:
            return

        try:
            role, message = self.response_queue.get_nowait()
        except queue.Empty:
            return

        if role == "error":
            self._append_message("error", message)
            self.is_waiting_for_response = False
            self.is_listening = False
            self.mic_button.setText("🎙 Voice")
            self.mic_button.setEnabled(True)
            self.send_button.setEnabled(True)
            self.message_input.setEnabled(True)
            self.message_input.setFocus()
            self.set_status("error")
        elif role == "transcribing":
            self.is_listening = False
            self.mic_button.setText("🎙 Voice")
            self.mic_button.setEnabled(False)
            self.set_status("transcribing")
        elif role == "transcript":
            self.mic_button.setText("🎙 Voice")
            self.mic_button.setEnabled(True)
            if message:
                self._send_user_message(message)
            else:
                self._append_message("system", "No speech detected.")
                self.send_button.setEnabled(True)
                self.message_input.setEnabled(True)
                self.message_input.setFocus()
                self._start_auto_listening()
        elif role == "assistant":
            self._mark_agent_spoke()
            self._append_message("assistant", message)
            self.is_waiting_for_response = False
            self.mic_button.setEnabled(True)
            self.send_button.setEnabled(True)
            self.message_input.setEnabled(True)
            self.message_input.setFocus()
            self._start_speaking(message)
        elif role == "speech_done":
            if not self.is_waiting_for_response:
                self._mark_agent_spoke()
                self.set_status("listening")
                QTimer.singleShot(0, self._start_auto_listening)

    def closeEvent(self, event) -> None:
        """Close the UI and stop any background speech immediately."""
        self._shutdown()
        event.accept()

    def _shutdown(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        if hasattr(self, "poll_timer"):
            self.poll_timer.stop()
        if hasattr(self, "inactivity_timer"):
            self.inactivity_timer.stop()
        if hasattr(self, "orb_widget"):
            self.orb_widget.stop()
        self._cancel_voice_listener()
        self.speech_input.cancel()
        self._stop_speech()


def main() -> int:
    """Start the PyQt6 Jarvis UI."""
    app = QApplication(sys.argv)
    window = JarvisUIPyQt()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
