# JarvisClaw — Local Voice Assistant for OpenClaw agent

## Updates

Added new 3D orb rendered with PyQt and vispy, can still use simpler tkinter ui by changing ui script in config.

JarvisClaw is a local assistant that connects to your OpenClaw agent and gives it voice input, voice output, a 3D animated orb UI, and an always-on wake word listener.

Think of it as the interface layer — **OpenClaw is the brain, Jarvis is the face and voice.**

Built for mac-os but can also be run on windows with slightly less functionality.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     macOS (your Mac)                    │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │ wake_listener│    │  jarvis_ui   │    │  OpenClaw │  │
│  │ (background) │───▶│  (Tkinter/   │───▶│  (gateway)│  │
|  |              |    |   PyQt)      |    |           |  |
│  │              │    │  - orb       │    │           │  │
│  │ listens for  │    │  - chat      │    │  OpenClaw │  │
│  │ "hey jarvis" │    │  - mic/STT   │    │  agent    │  │
│  │              │    │  - TTS       │    │           │  │
│  └──────────────┘    └──────────────┘    └───────────┘  │
│         │                                          │    │
│         └─── closes UI on "bye jarvis" ────────────┘    │
│                                                         │
│  LaunchAgent (always-on at login)                       │
└─────────────────────────────────────────────────────────┘
```

## Installation

```bash
git clone https://github.com/ranvirsinghn/jarvisclaw.git
```

## Files

| File | Role |
|------|------|
| `jarvis_ui.py` | Tkinter UI — fake 3d orb, chat, voice controls, inactivity timer |
| `jarvis_ui_PyQt.py` | Newer PyQt UI — fully 3d orb, chat, voice controls, inactivity timer |
| `wake_listener.py` | Lightweight background process — listens for wake/close phrases |
| `openclaw_adapter.py` | Bridge between the Python app and OpenClaw (CLI backend) |
| `speech_input.py` | Microphone recording + Whisper STT |
| `orb_widget.py` | 3D animated orb canvas widget (orb only, no app logic) |
| `config.py` | All settings: wake words, voices, mic, API keys, session ID |

---

## Requirements

### Python version

Python 3.9+ (the version that ships with macOS or Homebrew).

### System dependencies

| Tool | Purpose |

| `openclaw` CLI | Sends messages to your OpenClaw agent from Python |
| Whisper CLI | Local speech-to-text (`pip install -U openai-whisper`) |

### Python packages

```bash
pip install sounddevice scipy numpy PyQt6 vispy
```

### Optional: Piper offline TTS

If you want offline neural TTS (no API key needed), install Piper:

```bash
pip install piper
# Set TTS_BACKEND = "piper" in config.py
```

### Optional: ElevenLabs cloud TTS

Sign up at [elevenlabs.io](https://elevenlabs.io), get an API key and voice ID, then set:

```python
TTS_BACKEND = "eleven_api"
ELEVENLABS_API_KEY = "sk_..."
ELEVENLABS_VOICE_ID = "..."
```

---

## Configuration

All settings live in `config.py`. Here's what you'll want to change:

### 1. Connect to your OpenClaw session (REQUIRED)

```python
JARVIS_SESSION_ID = "your-session-uuid-here"
```

Find your session ID by running `openclaw status` in a terminal, or by typing `/status` inside your OpenClaw web chat and copying the UUID from the session card.

### 2. Wake and close phrases

```python
WAKE_WORDS = ["hey jarvis"]          # opens the UI
CLOSE_WORDS = ["bye jarvis"]         # closes the UI, listener stays alive
```

### 3. TTS voice

Choose one of three backends:

```python
TTS_BACKEND = "say"          # built-in macOS voice (free, no setup)
TTS_BACKEND = "piper"        # offline neural voice (free, needs Piper installed) (ONLY FREE OPTION FOR WINDOWS)
TTS_BACKEND = "eleven_api"   # cloud neural voice (sounds best, needs API key)
```

### 4. Speech recognition

```python
STT_BACKEND = "whisper_local"   # local Whisper (privacy-friendly, no API key)
WHISPER_MODEL = "base"          # tiny / base / small / medium / large
```

### 5. Lifecycle

```python
INACTIVITY_QUIT_SECONDS = 60.0   # close UI after this many idle seconds
AUTO_LISTEN_ON_LAUNCH = True     # start mic automatically when UI opens
```

---

## Running Manually

### Launch the full UI

```bash
cd /Applications/Building_Jarvis
python3 jarvis_ui_PyQt.py
```

This opens the PyQt window with the orb, chat display, and voice controls. It connects to your OpenClaw session immediately.

### Run the wake listener (terminal mode) (ONLY OPTION FOR WINDOWS)

```bash
cd /Applications/Building_Jarvis
python3 wake_listener.py
```

This starts the lightweight listener. You have two wake modes:

- **Terminal mode** — type `hey jarvis` and press Enter → launches the UI. Type `bye jarvis` to close it.
- **Microphone mode** — say "hey jarvis" aloud → launches the UI. Say "bye jarvis" to close it.

Optional flags:

```bash
python3 wake_listener.py --no-mic          # terminal-only, no microphone
python3 wake_listener.py --no-terminal     # microphone-only (good for LaunchAgent)
python3 wake_listener.py --dry-run         # test without actually launching the UI
```

---

## Keeping the Wake Listener Always Running (LaunchAgent) (ONLY FOR MAC-OS)

You can install the wake listener as a macOS LaunchAgent so it starts automatically at login and stays alive in the background.

### Step 1: Choose your Python

Decide which Python interpreter to use. **Homebrew Python is recommended** (`/opt/homebrew/bin/python3`) because it manages packages cleanly. The system Python (`/usr/bin/python3`) works but may not see user-installed pip packages when running as a background LaunchAgent.

### Step 2: Install required packages for that Python

```bash
# For Homebrew Python:
/opt/homebrew/bin/pip3 install --break-system-packages sounddevice scipy numpy

# For system Python (requires sudo):
sudo /usr/bin/pip3 install sounddevice scipy numpy
```

### Step 3: Install the LaunchAgent

The plist template is included in the `launch_agents/` directory of this repository. The file is named `com.jarvis.wake-listener.plist`. Edit it if you want to change the Python path, then:

```bash
# Copy to LaunchAgents directory
cp launch_agents/com.jarvis.wake-listener.plist \
   ~/Library/LaunchAgents/com.jarvis.wake-listener.plist

# Load it into launchd
launchctl bootstrap gui/$(id -u) \
   ~/Library/LaunchAgents/com.jarvis.wake-listener.plist

# Enable it (survives reboots)
launchctl enable gui/$(id -u)/com.jarvis.wake-listener

# Start it now
launchctl kickstart -k gui/$(id -u)/com.jarvis.wake-listener
```

### Step 4: Verify it's running

```bash
# Check launchd status
launchctl print gui/$(id -u)/com.jarvis.wake-listener | head -40

# Check the process
pgrep -laf wake_listener

# Check logs
tail -f /tmp/jarvis-wake-listener.out.log
```

Look for:
```text
state = running
```

And in the stdout log:
```text
Jarvis wake listener starting.
Wake words: hey jarvis
Microphone mode ready.
```

### Step 5: macOS permissions

The first time the wake listener's microphone mode runs, macOS will prompt:

> "Python" would like to access the microphone.

You must allow this, or microphone wake detection won't work. The terminal mode (typing "hey jarvis") doesn't need any permissions.

If the listener can't open files (you see "Operation not permitted" in the error log), make sure the project folder is **not inside `~/Documents`**. macOS privacy restrictions block background agents from reading `~/Documents`. A good location is `/Applications/Building_Jarvis/`.

### Managing the LaunchAgent

```bash
# Stop it
launchctl bootout gui/$(id -u)/com.jarvis.wake-listener

# Check status
launchctl print gui/$(id -u)/com.jarvis.wake-listener

# Restart after config changes
launchctl kickstart -k gui/$(id -u)/com.jarvis.wake-listener

# Uninstall completely
launchctl bootout gui/$(id -u)/com.jarvis.wake-listener
rm ~/Library/LaunchAgents/com.jarvis.wake-listener.plist
```

### What the LaunchAgent does

- Starts `wake_listener.py --no-terminal` at login
- Runs in the background (`KeepAlive = true` — relaunches if it crashes)
- Listens for "hey jarvis" via microphone → opens `jarvis_ui.py`
- Listens for "bye jarvis" via microphone → closes the UI
- The full Tkinter UI only runs on demand, not permanently
- Logs go to `/tmp/jarvis-wake-listener.out.log` and `.err.log`


## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| "Operation not permitted" in error log | Project is inside `~/Documents` — move it to `/Applications/` or `~/.local/share/` |
| "Missing dependency: sounddevice" | Install with `pip install sounddevice` for the same Python the LaunchAgent uses |
| Mic mode silent / no detection | macOS mic permission not granted; check System Settings → Privacy → Microphone |
| UI opens but "OpenClaw CLI not found" | `openclaw` isn't on PATH — add it to `config.DEBUG = True` and check |
| UI opens but no response | Wrong `JARVIS_SESSION_ID` in config.py |
| TTS doesn't speak | Check `TTS_BACKEND` setting; for ElevenLabs verify API key |
| Whisper transcription errors | `pip install -U openai-whisper` — the Whisper CLI must be available |

---

## Build Order (for development)

1. ✅ Text-only terminal OpenClaw chat (`openclaw_adapter.py`)
2. ✅ OpenClaw adapter layer (`ask_openclaw(message) -> str`)
3. ✅ Wake-word proof of concept (`wake_listener.py`)
4. ✅ Wake word launches UI (wake → `jarvis_ui.py`)
5. ✅ Basic UI with text/chat/status (`jarvis_ui.py` + Tkinter)
6. ✅ Speech output (TTS via macOS say / Piper / ElevenLabs)
7. ✅ Speech input (microphone → Whisper → OpenClaw)
8. ✅ 3D orb UI (`orb_widget.py` — idle/listening/thinking/speaking states)
9. ✅ Inactivity auto-close
10. LaunchAgent auto-start (functionally working, package dependency tuning)

---

## Next Steps

- Access openclaw through gateway ws to reduce latency
- Implement JarvisClaw to work with API keys for openai etc

Please get in touch if you have questions or have ideas on where I should take this next!

## Acknowledgement

- AI tools (gpt 5.5, grok and deepseekv4 pro) were used in my openclaw environment to help design and craft the
ui architecture. 

*Built by Ranvir Narang - upcoming PhD student Mathematical AI @ MARS Lancaster*

