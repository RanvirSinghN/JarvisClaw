"""
Jarvis desktop UI.

This file contains the main Tkinter interface for the local Jarvis assistant.
It coordinates the visual orb, voice input, text input, OpenClaw requests, and
text-to-speech output. The actual OpenClaw call, microphone/STT logic, and orb
rendering live in separate modules so this file can focus on UI state and user
interaction flow.
"""

import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import scrolledtext, ttk

import config
from openclaw_adapter import ask_openclaw
from orb_widget import ORB_BG, OrbWidget
from speech_input import SpeechInput


BOT_NAME = getattr(config, "bot_name", "Jarvis")
WINDOW_TITLE = BOT_NAME
WINDOW_WIDTH_RATIO = 0.9
WINDOW_HEIGHT_RATIO = 0.88

# UI colours. Keeping them as constants makes the placeholder style easy to tweak.
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
STOP_SPEAKING_PHRASE = getattr(config, "STOP_SPEAKING_PHRASE", "stop jarvis").lower()


class JarvisUI:
    """Small Tkinter chat UI connected to the OpenClaw adapter."""

    def __init__(self, root: tk.Tk):
        self.root = root
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

        self.root.title(WINDOW_TITLE)
        self._set_initial_window_size()
        self.root.minsize(620, 440)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_widgets()
        self.set_status("idle")

        # Periodically check whether background OpenClaw/TTS work has finished.
        self.root.after(100, self._poll_response_queue)

        if AUTO_LISTEN_ON_LAUNCH:
            self.root.after(500, self._start_auto_listening)

        self.root.after(1000, self._check_inactivity_timeout)

    def _set_initial_window_size(self) -> None:
        """Launch Jarvis large and centered, covering most of the screen."""
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = int(screen_width * WINDOW_WIDTH_RATIO)
        height = int(screen_height * WINDOW_HEIGHT_RATIO)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_widgets(self) -> None:
        """Create the orb-centred Jarvis UI skeleton."""
        outer = tk.Frame(self.root, bg=BG, padx=18, pady=18)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 10))

        title = tk.Label(
            header,
            text="JARVIS",
            font=("Helvetica", 24, "bold"),
            fg=ACCENT,
            bg=BG,
        )
        title.pack(side="left")

        self.status_label = tk.Label(
            header,
            text="status: idle",
            font=("Helvetica", 12),
            fg=MUTED,
            bg=BG,
        )
        self.status_label.pack(side="right")

        orb_frame = tk.Frame(outer, bg=ORB_BG, highlightthickness=1, highlightbackground="#1e293b")
        orb_frame.pack(fill="both", expand=True)

        self.orb_widget = OrbWidget(orb_frame)
        self.orb_widget.pack(fill="both", expand=True)

        bottom_panel = tk.Frame(outer, bg=BG)
        bottom_panel.pack(fill="x", pady=(12, 0))

        self.chat_output = scrolledtext.ScrolledText(
            bottom_panel,
            height=4,
            wrap="word",
            state="disabled",
            bg=TEXT_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            relief="flat",
            padx=12,
            pady=10,
            font=("Helvetica", 11),
        )
        self.chat_output.pack(side="left", fill="x", expand=True)

        self.chat_output.tag_configure("user", foreground="#fbbf24")
        self.chat_output.tag_configure("assistant", foreground=TEXT_FG)
        self.chat_output.tag_configure("system", foreground=MUTED)
        self.chat_output.tag_configure("error", foreground=ERROR)

        controls = tk.Frame(bottom_panel, bg=BG)
        controls.pack(side="right", padx=(10, 0), fill="y")

        self.stop_button = ttk.Button(
            controls,
            text="Stop",
            command=self._on_stop_pressed,
        )
        self.stop_button.pack(fill="x", pady=(0, 6))

        self.text_mode_button = ttk.Button(
            controls,
            text="Text Input",
            command=self._enter_text_input_mode,
        )
        self.text_mode_button.pack(fill="x", pady=(0, 6))

        self.mic_button = ttk.Button(
            controls,
            text="🎙 Voice",
            command=self._on_mic_pressed,
        )
        self.mic_button.pack(fill="x", pady=(0, 6))

        self.send_button = ttk.Button(
            controls,
            text="Send",
            command=self._on_send_pressed,
        )
        self.send_button.pack(fill="x")

        self.message_input = tk.Text(
            outer,
            height=3,
            bg=PANEL_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            font=("Helvetica", 12),
        )
        self.message_input.bind("<Return>", self._on_send_pressed)
        self.message_input.bind("<Shift-Return>", self._insert_newline)
        self.message_input.pack_forget()

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
        self.status_label.config(
            text=f"status: {status}",
            fg=colours.get(status, MUTED),
        )
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
                self._on_close()
                return

        self.root.after(1000, self._check_inactivity_timeout)

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
        label = labels.get(role, role.title())

        self.chat_output.config(state="normal")
        self.chat_output.insert("end", f"{label}: ", role)
        self.chat_output.insert("end", f"{message}\n\n")
        self.chat_output.config(state="disabled")
        self.chat_output.see("end")

    def _insert_newline(self, event=None):
        """Allow Shift+Enter to create a newline inside the input textbox."""
        self.message_input.insert("insert", "\n")
        return "break"

    def _on_stop_pressed(self) -> None:
        """Stop speech/listening work and return to voice listening mode."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.is_waiting_for_response = False
        self.message_input.pack_forget()
        self.send_button.config(state="normal")
        self.text_mode_button.config(state="normal")
        self._start_auto_listening()

    def _enter_text_input_mode(self) -> None:
        """Interrupt voice mode and reveal the bottom typed-input area."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.is_waiting_for_response = False
        self.set_status("text_input")
        self.mic_button.config(text="🎙 Voice", state="normal")
        self.send_button.config(state="normal")
        self.message_input.config(state="normal")
        self.message_input.delete("1.0", "end")
        self.message_input.pack(fill="x", pady=(10, 0))
        self.message_input.focus_set()

    def _on_mic_pressed(self) -> None:
        """Manually pause/resume automatic speech listening."""
        if self.is_waiting_for_response:
            return

        if self.is_listening:
            self._cancel_voice_listener()
            self.set_status("idle")
            return

        self._start_auto_listening()

    def _start_auto_listening(self, allow_barge_in: bool = False) -> None:
        """Start background speech capture with silence-based auto-stop."""
        if self.is_closing or self.is_waiting_for_response:
            return

        if self.voice_thread and self.voice_thread.is_alive():
            # A cancelled listener can take a moment to release the microphone.
            # Retry shortly so stop-command listening still starts during TTS.
            if self.voice_cancel_event and self.voice_cancel_event.is_set():
                self.root.after(
                    100,
                    lambda: self._start_auto_listening(allow_barge_in=allow_barge_in),
                )
            return

        self.voice_thread = None
        self.voice_cancel_event = threading.Event()
        self.is_listening = True
        self.message_input.pack_forget()
        self.mic_button.config(text="■ Listening", state="normal")
        self.send_button.config(state="normal")
        self.message_input.config(state="normal")

        if not allow_barge_in:
            self.set_status("listening")

        self.voice_thread = threading.Thread(
            target=self._listen_and_transcribe_in_background,
            args=(self.voice_cancel_event, allow_barge_in),
            daemon=True,
        )
        self.voice_thread.start()

    def _cancel_voice_listener(self) -> None:
        """Stop the current automatic speech listener, if one is active."""
        if self.voice_cancel_event:
            self.voice_cancel_event.set()
        self.is_listening = False
        self.mic_button.config(text="🎙 Voice", state="normal")

    def _listen_and_transcribe_in_background(
        self,
        cancel_event: threading.Event,
        allow_barge_in: bool,
    ) -> None:
        """Listen for one utterance, transcribe it, and queue the transcript."""
        try:
            audio_path = self.speech_input.listen_for_utterance(
                cancel_event=cancel_event,
            )
            if self.is_closing or cancel_event.is_set() or audio_path is None:
                return

            if not allow_barge_in:
                self.response_queue.put(("transcribing", ""))

            transcript = self.speech_input.transcribe(audio_path)
            self.speech_input.cleanup_last_audio()
        except Exception as exc:
            if not self.is_closing and not cancel_event.is_set():
                self.response_queue.put(("error", f"Speech input failed: {exc}"))
        else:
            if not self.is_closing and not cancel_event.is_set():
                role = "voice_command" if allow_barge_in else "transcript"
                self.response_queue.put((role, transcript))

    def _on_send_pressed(self, event=None):
        """Handle send button clicks and Enter key presses."""
        if self.is_waiting_for_response:
            return "break"

        message = self.message_input.get("1.0", "end").strip()
        if not message:
            return "break"

        self.message_input.delete("1.0", "end")
        self._send_user_message(message)
        return "break"

    def _send_user_message(self, message: str) -> None:
        """Display a user message and send it to the OpenClaw session."""
        self._cancel_voice_listener()
        self._stop_speech(interrupted=True)
        self.message_input.pack_forget()
        self._append_message("user", message)
        self.is_waiting_for_response = True
        self.mic_button.config(state="disabled")
        self.send_button.config(state="disabled")
        self.message_input.config(state="disabled")
        self.set_status("thinking")

        # Run the OpenClaw request in a background thread so Tkinter stays responsive.
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
        # Remove most pictographic emoji characters and variation selectors.
        text = re.sub(
            "["
            "\U0001F300-\U0001FAFF"  # emojis, symbols, objects, faces, etc.
            "\U00002700-\U000027BF"  # dingbats
            "\U00002600-\U000026FF"  # miscellaneous symbols
            "\U0000FE0F"             # emoji variation selector
            "]+",
            "",
            text,
        )

        # Remove Markdown emphasis markers so TTS does not say "asterisk".
        text = text.replace("*", "")

        # Collapse whitespace left behind by removed emoji/formatting, but only
        # inside a speech chunk. Newlines are handled separately as deliberate
        # pauses between chunks.
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

            # Piper generation is usually short; playback is the long-running bit.
            # Both still go through cancellable process handling so closing Jarvis
            # stops speech even if this method is running in a background thread.
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
        self._start_auto_listening(allow_barge_in=True)
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
            self.root.after(100, self._poll_response_queue)
            return

        if role == "error":
            self._append_message("error", message)
            self.is_waiting_for_response = False
            self.is_listening = False
            self.mic_button.config(text="🎙 Voice", state="normal")
            self.send_button.config(state="normal")
            self.message_input.config(state="normal")
            self.message_input.focus_set()
            self.set_status("error")
        elif role == "voice_command":
            if STOP_SPEAKING_PHRASE in message.lower():
                self._stop_speech(interrupted=True)
                self._cancel_voice_listener()
                self._start_auto_listening()
            elif not self.tts_process:
                self._start_auto_listening()
        elif role == "transcribing":
            self.is_listening = False
            self.mic_button.config(text="🎙 Voice", state="disabled")
            self.set_status("transcribing")
        elif role == "transcript":
            self.mic_button.config(text="🎙 Voice", state="normal")
            if message:
                self._send_user_message(message)
            else:
                self._append_message("system", "No speech detected.")
                self.send_button.config(state="normal")
                self.message_input.config(state="normal")
                self.message_input.focus_set()
                self._start_auto_listening()
        elif role == "assistant":
            self._mark_agent_spoke()
            self._append_message("assistant", message)
            self.is_waiting_for_response = False
            self.mic_button.config(state="normal")
            self.send_button.config(state="normal")
            self.message_input.config(state="normal")
            self.message_input.focus_set()
            self._start_speaking(message)
        elif role == "speech_done":
            if not self.is_waiting_for_response:
                self._mark_agent_spoke()
                self._start_auto_listening()
                self.set_status("listening")

        # Keep polling for future background events.
        if not self.is_closing:
            self.root.after(100, self._poll_response_queue)

    def _on_close(self) -> None:
        """Close the UI and stop any background speech immediately."""
        self.is_closing = True
        if hasattr(self, "orb_widget"):
            self.orb_widget.stop()
        self._cancel_voice_listener()
        self.speech_input.cancel()
        self._stop_speech()
        self.root.destroy()


def main():
    """Start the Jarvis UI."""
    root = tk.Tk()
    JarvisUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
