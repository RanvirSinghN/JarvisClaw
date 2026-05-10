"""Animated orb widget for the Jarvis UI.

This file owns the visual orb only. It does not know about OpenClaw, speech
input, TTS, or Jarvis control flow. The UI simply calls `set_state(...)`.
"""

from __future__ import annotations

import math
import tkinter as tk


ORB_BG = "#050816"

ORB_STYLES = {
    # idle = slow pulse, white
    # listening = active/bright, yellow
    # transcribing = spinning/loading, orange
    # thinking = spinning/loading, purple
    # speaking = pulsing/reactive, blue
    # error = warning state, red
    "idle": {
        "core": "#f8fafc",
        "mid": "#cbd5e1",
        "shadow": "#475569",
        "glow": "#e2e8f0",
        "label": "IDLE",
    },
    "listening": {
        "core": "#fef08a",
        "mid": "#facc15",
        "shadow": "#a16207",
        "glow": "#fde047",
        "label": "LISTENING",
    },
    "transcribing": {
        "core": "#fed7aa",
        "mid": "#fb923c",
        "shadow": "#c2410c",
        "glow": "#fdba74",
        "label": "TRANSCRIBING",
    },
    "thinking": {
        "core": "#ddd6fe",
        "mid": "#a855f7",
        "shadow": "#6b21a8",
        "glow": "#c084fc",
        "label": "THINKING",
    },
    "speaking": {
        "core": "#bae6fd",
        "mid": "#38bdf8",
        "shadow": "#0369a1",
        "glow": "#7dd3fc",
        "label": "SPEAKING",
    },
    "text_input": {
        "core": "#bbf7d0",
        "mid": "#34d399",
        "shadow": "#047857",
        "glow": "#86efac",
        "label": "TEXT INPUT",
    },
    "error": {
        "core": "#fecaca",
        "mid": "#ef4444",
        "shadow": "#991b1b",
        "glow": "#f87171",
        "label": "ERROR",
    },
}

ORB_SPEEDS = {
    "idle": 0.035,
    "listening": 0.11,
    "transcribing": 0.23,
    "thinking": 0.25,
    "speaking": 0.18,
    "text_input": 0.08,
    "error": 0.28,
}


class OrbWidget(tk.Canvas):
    """Tkinter canvas that renders a state-driven pseudo-3D animated orb."""

    def __init__(self, parent, *, bg: str = ORB_BG, fps: int = 30, **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.state = "idle"
        self.phase = 0.0
        self.fps = fps
        self._is_running = False
        self.bind("<Configure>", lambda event: self.draw())

    def set_state(self, state: str) -> None:
        """Update the orb's visual state."""
        self.state = state if state in ORB_STYLES else "idle"
        self.draw()

    def start(self) -> None:
        """Start the animation loop."""
        if self._is_running:
            return
        self._is_running = True
        self._animate()

    def stop(self) -> None:
        """Stop the animation loop."""
        self._is_running = False

    def draw(self) -> None:
        """Draw the current orb frame."""
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        cx, cy = width / 2, height / 2
        # Keep the orb visually central but compact enough to fit comfortably
        # inside the Jarvis window.
        base_radius = min(width, height) * 0.17
        style = ORB_STYLES[self.state]
        radius = base_radius * self._pulse_scale()

        self.delete("all")
        self._draw_background_vignette(width, height)
        self._draw_outer_glow(cx, cy, radius, style)
        self._draw_state_effects_behind_orb(cx, cy, radius, style)
        self._draw_3d_orb(cx, cy, radius, style)
        self._draw_state_effects_front(cx, cy, radius, style)
        self._draw_label(cx, cy, radius, style)

    def _animate(self) -> None:
        if not self._is_running:
            return

        self.phase += ORB_SPEEDS.get(self.state, 0.08)
        self.draw()
        self.after(max(1, int(1000 / self.fps)), self._animate)

    def _pulse_scale(self) -> float:
        """State-specific size pulse."""
        wave = math.sin(self.phase)
        if self.state == "idle":
            return 1.0 + 0.018 * wave
        if self.state == "listening":
            return 1.0 + 0.035 * wave
        if self.state == "speaking":
            return 1.0 + 0.06 * max(0.0, wave)
        if self.state == "error":
            return 1.0 + 0.035 * (1 if math.sin(self.phase * 2.2) > 0 else -0.3)
        return 1.0 + 0.025 * wave

    def _draw_background_vignette(self, width: int, height: int) -> None:
        """Subtle centre glow so the orb feels embedded in dark space."""
        cx, cy = width / 2, height / 2
        max_r = min(width, height) * 0.48
        for index, colour in enumerate(("#07111f", "#081827", "#091b2d")):
            r = max_r * (1 - index * 0.18)
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=colour, outline="")

    def _draw_outer_glow(self, cx: float, cy: float, radius: float, style: dict[str, str]) -> None:
        """Layered glow rings around the orb."""
        glow_strength = {
            "idle": 0.55,
            "listening": 1.0,
            "transcribing": 0.85,
            "thinking": 0.9,
            "speaking": 1.05,
            "text_input": 0.75,
            "error": 1.15,
        }.get(self.state, 0.8)
        flicker = 1.0
        if self.state == "error":
            flicker += 0.18 * (1 if math.sin(self.phase * 3.5) > 0 else -1)

        for index, scale in enumerate((1.88, 1.62, 1.38, 1.18)):
            r = radius * scale * glow_strength * flicker
            self.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=style["glow"],
                width=max(1, 6 - index),
                stipple="gray50" if index < 2 else "",
            )

    def _draw_state_effects_behind_orb(
        self,
        cx: float,
        cy: float,
        radius: float,
        style: dict[str, str],
    ) -> None:
        if self.state == "listening":
            self._draw_listening_rays(cx, cy, radius, style["glow"])
        elif self.state in {"thinking", "transcribing"}:
            self._draw_loading_rings(cx, cy, radius, style["glow"])
        elif self.state == "speaking":
            self._draw_speaking_waves(cx, cy, radius, style["glow"])
        elif self.state == "error":
            self._draw_warning_halo(cx, cy, radius, style["glow"])

    def _draw_3d_orb(self, cx: float, cy: float, radius: float, style: dict[str, str]) -> None:
        """Draw a shaded pseudo-sphere using nested offset ovals."""
        # Shadow under/behind the sphere.
        self.create_oval(
            cx - radius * 0.92,
            cy - radius * 0.72,
            cx + radius * 1.02,
            cy + radius * 1.14,
            fill=style["shadow"],
            outline="",
        )

        # Main radial-ish body: larger dark layers to smaller bright layers,
        # offset toward upper-left to fake a lit 3D surface.
        layers = [
            (1.00, 0.00, 0.00, style["shadow"]),
            (0.91, -0.025, -0.035, style["mid"]),
            (0.72, -0.105, -0.135, style["core"]),
            (0.42, -0.245, -0.285, "#ffffff"),
        ]
        for scale, ox, oy, colour in layers:
            r = radius * scale
            x = cx + radius * ox
            y = cy + radius * oy
            self.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline="")

        # Dark lower crescent adds depth/curvature.
        self.create_arc(
            cx - radius * 0.98,
            cy - radius * 0.92,
            cx + radius * 0.98,
            cy + radius * 1.08,
            start=205,
            extent=130,
            outline=style["shadow"],
            width=max(2, int(radius * 0.08)),
            style="arc",
        )

        # Rim light.
        self.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            outline=style["glow"],
            width=3,
        )

        # Gloss highlight.
        self.create_oval(
            cx - radius * 0.48,
            cy - radius * 0.58,
            cx - radius * 0.12,
            cy - radius * 0.22,
            fill="#ffffff",
            outline="",
            stipple="gray50",
        )

    def _draw_state_effects_front(
        self,
        cx: float,
        cy: float,
        radius: float,
        style: dict[str, str],
    ) -> None:
        if self.state in {"thinking", "transcribing"}:
            self._draw_loading_arc(cx, cy, radius, style["glow"])
        elif self.state == "error":
            self._draw_warning_symbol(cx, cy, radius)

    def _draw_listening_rays(self, cx: float, cy: float, radius: float, colour: str) -> None:
        ray_count = 18
        for index in range(ray_count):
            angle = (2 * math.pi * index / ray_count) + self.phase * 0.18
            length = radius * (1.22 + 0.12 * math.sin(self.phase + index))
            inner = radius * 1.05
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * length
            y2 = cy + math.sin(angle) * length
            self.create_line(x1, y1, x2, y2, fill=colour, width=2)

    def _draw_loading_rings(self, cx: float, cy: float, radius: float, colour: str) -> None:
        for ring_index, scale in enumerate((1.28, 1.48)):
            r = radius * scale
            start = int((self.phase * (70 + ring_index * 35)) % 360)
            self.create_arc(
                cx - r,
                cy - r * 0.82,
                cx + r,
                cy + r * 0.82,
                start=start,
                extent=130,
                outline=colour,
                width=3 + ring_index,
                style="arc",
            )

    def _draw_loading_arc(self, cx: float, cy: float, radius: float, colour: str) -> None:
        start = int((self.phase * 75) % 360)
        arc_radius = radius * 1.18
        self.create_arc(
            cx - arc_radius,
            cy - arc_radius,
            cx + arc_radius,
            cy + arc_radius,
            start=start,
            extent=105,
            outline=colour,
            width=7,
            style="arc",
        )

    def _draw_speaking_waves(self, cx: float, cy: float, radius: float, colour: str) -> None:
        for index in range(3):
            scale = 1.18 + index * 0.18 + 0.05 * max(0.0, math.sin(self.phase + index))
            r = radius * scale
            self.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=colour,
                width=max(1, 4 - index),
                stipple="gray50" if index > 0 else "",
            )

    def _draw_warning_halo(self, cx: float, cy: float, radius: float, colour: str) -> None:
        r = radius * (1.32 + 0.05 * math.sin(self.phase * 2.0))
        self.create_polygon(
            cx,
            cy - r,
            cx + r * 0.9,
            cy + r * 0.58,
            cx - r * 0.9,
            cy + r * 0.58,
            outline=colour,
            fill="",
            width=4,
        )

    def _draw_warning_symbol(self, cx: float, cy: float, radius: float) -> None:
        self.create_line(
            cx,
            cy - radius * 0.38,
            cx,
            cy + radius * 0.12,
            fill="#450a0a",
            width=max(3, int(radius * 0.045)),
        )
        dot = radius * 0.055
        self.create_oval(cx - dot, cy + radius * 0.28 - dot, cx + dot, cy + radius * 0.28 + dot, fill="#450a0a", outline="")

    def _draw_label(self, cx: float, cy: float, radius: float, style: dict[str, str]) -> None:
        self.create_text(
            cx,
            cy + radius + 44,
            text=style["label"],
            fill=style["glow"],
            font=("Helvetica", 16, "bold"),
        )
