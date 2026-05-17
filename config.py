# -----------------------------------------------------------------------------
# Jarvis identity / OpenClaw connection
# -----------------------------------------------------------------------------

bot_name = "Jarvis"

# CLI backend target: internal UUID session id.
# Replace this with the OpenClaw session ID you want Jarvis to talk to.
JARVIS_SESSION_ID = "SESSION_ID_HERE"

# Max time to wait for an OpenClaw response before surfacing an error in the UI.
DEFAULT_TIMEOUT_SECONDS = 120

# Print raw OpenClaw CLI stdout/stderr for debugging adapter issues.
DEBUG = False


# -----------------------------------------------------------------------------
# Speech input / transcription
# -----------------------------------------------------------------------------

# Speech-to-text backend.
# Current option: "whisper_local" uses the local Whisper CLI.
STT_BACKEND = "whisper_local"

# Microphone recording settings.
# 16 kHz mono is a good default for Whisper: small files, clear speech, fast STT.
MIC_SAMPLE_RATE = 16_000
MIC_CHANNELS = 1

# Local Whisper settings.
# Model options, roughly: "tiny", "base", "small", "medium", "large".
# Bigger = better transcription but slower. "base" is a sensible first test.
WHISPER_MODEL = "base"
WHISPER_LANGUAGE = "en"

# Automatic listening / lifecycle behaviour.
AUTO_LISTEN_ON_LAUNCH = True

# Wake listener settings.
# Edit these lists to change what Jarvis listens for before/while the UI is open.
WAKE_WORDS = [
    "hey jarvis",
]

# These phrases will close the Jarvis UI but keep the wake listener running, so you can say a wake word again to reopen the UI.
CLOSE_WORDS = [
    "bye jarvis",
]

# The wake listener starts this UI on demand and can close it again when it hears
# a close phrase. The wake listener itself keeps running.
WAKE_UI_SCRIPT = "jarvis_ui_PyQt.py"
WAKE_UI_COOLDOWN_SECONDS = 5.0
WAKE_TERMINAL_MODE = True
WAKE_MIC_MODE = True

# Close the active Jarvis UI after this many seconds without Jarvis speaking.
# The lightweight wake_listener.py should keep running separately and can relaunch the UI.
# Set to 0 or None to disable automatic quitting.
INACTIVITY_QUIT_SECONDS = 60.0

SILENCE_STOP_SECONDS = 3.0       # Stop recording after this much silence.
MIN_UTTERANCE_SECONDS = 0.4      # Ignore tiny accidental blips.
MAX_UTTERANCE_SECONDS = 45.0     # Safety cap for one spoken message.

# Voice activity thresholds based on microphone RMS volume.
# If Jarvis cuts off too early or misses you, tune these slightly.
VOICE_START_THRESHOLD = 0.015
VOICE_SILENCE_THRESHOLD = 0.01

# While Jarvis is speaking, do not interrupt on arbitrary speech.
# Jarvis only stops speaking if this phrase is heard in the transcript. (Or you can press manual stop button in UI).
STOP_SPEAKING_PHRASE = "stop speaking"


# -----------------------------------------------------------------------------
# Text-to-speech output
# -----------------------------------------------------------------------------

# Text-to-speech backend.
# Options:
# - "say": built-in macOS voice
# - "piper": offline local neural voice
# - "eleven_api": ElevenLabs cloud voice
TTS_BACKEND = "eleven_api"

# ElevenLabs cloud TTS.
ELEVENLABS_API_KEY = "YOUR_ELEVENLABS_API_KEY_HERE" #Your ElevenLabs API key here. Get one at https://elevenlabs.com if you want to use the ElevenLabs TTS backend.
ELEVENLABS_VOICE_ID = "j57KDF72L6gxbLk4sOo5"  # British male voice
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"

# ElevenLabs delivery tuning.
# Stability controls how expressive the voice is, with 0.0 being most expressive and 1.0 being least. 
# Similarity boost controls how much the voice sticks to the original voice sample, with 0.0 being more creative and 1.0 being more similar. Adjust these to find your preferred balance of naturalness and consistency.
# speed: 1.0 is normal. Slightly above 1.0 makes Jarvis snappier without rushing.
ELEVENLABS_STABILITY = 0.3
ELEVENLABS_SIMILARITY_BOOST = 0.5
ELEVENLABS_SPEED = 1.15

# Piper offline TTS settings.
PIPER_MODEL_PATH = "voices/en_GB-northern_english_male-medium.onnx"

# This northern English male Piper voice is single-speaker, so no speaker ID is needed.
PIPER_SPEAKER_ID = None

# Higher = slower speech. 1.0 is normal-ish; 1.35 is relaxed but not painfully slow.
PIPER_LENGTH_SCALE = 1.35

# Pause inserted between newline-separated chunks in Jarvis responses.
# Keep this tiny for ElevenLabs because ElevenLabs already adds natural phrasing pauses.
SPEECH_NEWLINE_PAUSE_SECONDS = 0.0
