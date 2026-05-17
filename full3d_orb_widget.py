"""VisPy-powered 3D Jarvis orb widget.

This module upgrades the Tkinter pseudo-3D orb from ``orb_widget.py`` into a
real PyQt6 widget rendered with VisPy. The public surface stays intentionally
small: create ``Jarvis3DOrbWidget`` and call ``set_state(...)`` with one of the
Jarvis UI states.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from PyQt6.QtCore import QSize, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from vispy import scene
from vispy.geometry import create_sphere
from vispy.scene import visuals


ORB_BG = "#050816"


def _hex_to_rgb(colour: str) -> tuple[float, float, float]:
    colour = colour.strip().lstrip("#")
    return tuple(int(colour[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def _rgba(rgb: Iterable[float], alpha: float) -> tuple[float, float, float, float]:
    red, green, blue = rgb
    return (float(red), float(green), float(blue), float(np.clip(alpha, 0.0, 1.0)))


def _normalised(vector: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(vector)
    if length == 0:
        return vector
    return vector / length


def _rotation_matrix(axis: str, angle: float) -> np.ndarray:
    c = math.cos(angle)
    s = math.sin(angle)
    if axis == "x":
        return np.array(((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c)), dtype=np.float32)
    if axis == "y":
        return np.array(((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)), dtype=np.float32)
    return np.array(((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0)), dtype=np.float32)


def _combined_rotation(*rotations: tuple[str, float]) -> np.ndarray:
    matrix = np.eye(3, dtype=np.float32)
    for axis, angle in rotations:
        matrix = _rotation_matrix(axis, angle) @ matrix
    return matrix


@dataclass(frozen=True)
class OrbStateStyle:
    label: str
    core: tuple[float, float, float]
    mid: tuple[float, float, float]
    shadow: tuple[float, float, float]
    glow: tuple[float, float, float]
    phase_speed: float
    pulse_amp: float
    spin_rate: float
    camera_rate: float
    glow_strength: float
    particle_strength: float


ORB_STYLES: dict[str, OrbStateStyle] = {
    "idle": OrbStateStyle(
        label="IDLE",
        core=_hex_to_rgb("#f8fafc"),
        mid=_hex_to_rgb("#cbd5e1"),
        shadow=_hex_to_rgb("#475569"),
        glow=_hex_to_rgb("#e2e8f0"),
        phase_speed=1.05,
        pulse_amp=0.018,
        spin_rate=0.26,
        camera_rate=0.10,
        glow_strength=0.52,
        particle_strength=0.26,
    ),
    "listening": OrbStateStyle(
        label="LISTENING",
        core=_hex_to_rgb("#fef08a"),
        mid=_hex_to_rgb("#facc15"),
        shadow=_hex_to_rgb("#a16207"),
        glow=_hex_to_rgb("#fde047"),
        phase_speed=3.3,
        pulse_amp=0.040,
        spin_rate=0.62,
        camera_rate=0.22,
        glow_strength=1.08,
        particle_strength=0.82,
    ),
    "transcribing": OrbStateStyle(
        label="TRANSCRIBING",
        core=_hex_to_rgb("#fed7aa"),
        mid=_hex_to_rgb("#fb923c"),
        shadow=_hex_to_rgb("#c2410c"),
        glow=_hex_to_rgb("#fdba74"),
        phase_speed=6.9,
        pulse_amp=0.030,
        spin_rate=1.24,
        camera_rate=0.34,
        glow_strength=0.90,
        particle_strength=0.62,
    ),
    "thinking": OrbStateStyle(
        label="THINKING",
        core=_hex_to_rgb("#ddd6fe"),
        mid=_hex_to_rgb("#a855f7"),
        shadow=_hex_to_rgb("#6b21a8"),
        glow=_hex_to_rgb("#c084fc"),
        phase_speed=7.5,
        pulse_amp=0.032,
        spin_rate=1.36,
        camera_rate=0.38,
        glow_strength=0.96,
        particle_strength=0.72,
    ),
    "speaking": OrbStateStyle(
        label="SPEAKING",
        core=_hex_to_rgb("#bae6fd"),
        mid=_hex_to_rgb("#38bdf8"),
        shadow=_hex_to_rgb("#0369a1"),
        glow=_hex_to_rgb("#7dd3fc"),
        phase_speed=5.4,
        pulse_amp=0.10,
        spin_rate=0.86,
        camera_rate=0.26,
        glow_strength=1.12,
        particle_strength=0.88,
    ),
    "text_input": OrbStateStyle(
        label="TEXT INPUT",
        core=_hex_to_rgb("#bbf7d0"),
        mid=_hex_to_rgb("#34d399"),
        shadow=_hex_to_rgb("#047857"),
        glow=_hex_to_rgb("#86efac"),
        phase_speed=2.4,
        pulse_amp=0.026,
        spin_rate=0.48,
        camera_rate=0.18,
        glow_strength=0.76,
        particle_strength=0.54,
    ),
    "error": OrbStateStyle(
        label="ERROR",
        core=_hex_to_rgb("#fecaca"),
        mid=_hex_to_rgb("#ef4444"),
        shadow=_hex_to_rgb("#991b1b"),
        glow=_hex_to_rgb("#f87171"),
        phase_speed=8.4,
        pulse_amp=0.055,
        spin_rate=1.52,
        camera_rate=0.18,
        glow_strength=1.22,
        particle_strength=0.92,
    ),
}

STATE_ALIASES = {
    "listen": "listening",
    "transcribe": "transcribing",
    "transcription": "transcribing",
    "think": "thinking",
    "speak": "speaking",
    "talking": "speaking",
    "text": "text_input",
    "input": "text_input",
    "warning": "error",
}


class Jarvis3DOrbWidget(QWidget):
    """Reusable PyQt6 widget that renders a state-driven 3D Jarvis orb."""

    state_changed = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_state: str = "idle",
        fps: int = 60,
        interactive_camera: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Jarvis3DOrbWidget")
        self.setMinimumSize(320, 320)

        self.state = self._normalise_state(initial_state)
        self._phase = 0.0
        self._last_tick = time.perf_counter()
        self._audio_level = 0.0
        self._energy = 0.0
        self._rng = np.random.default_rng(42)

        self.canvas = scene.SceneCanvas(
            keys="interactive",
            bgcolor=_rgba(_hex_to_rgb(ORB_BG), 1.0),
            dpi=96,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas.native)

        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.TurntableCamera(
            fov=42,
            distance=4.55,
            elevation=18,
            azimuth=32,
            roll=0,
        )
        self.view.camera.interactive = interactive_camera

        mesh_data = create_sphere(rows=72, cols=96, radius=1.0, method="latitude")
        self._vertices = mesh_data.get_vertices().astype(np.float32)
        self._faces = mesh_data.get_faces().astype(np.uint32)
        self._normals = self._vertices / np.maximum(
            np.linalg.norm(self._vertices, axis=1, keepdims=True),
            1e-6,
        )

        self._core_vertices = self._vertices * 0.98
        self._atmosphere_vertices = self._vertices * 1.08
        self._halo_vertices = self._vertices * 1.34
        self._circle = self._make_circle_points(1.0, 192)
        self._particle_dirs = self._make_particle_dirs(190)
        self._particle_radii = self._rng.uniform(1.05, 1.42, len(self._particle_dirs)).astype(np.float32)
        self._particle_offsets = self._rng.uniform(0.0, math.tau, len(self._particle_dirs)).astype(np.float32)

        self._build_visuals()
        self._apply_state_immediately()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(max(1, int(1000 / max(1, fps))))

    def sizeHint(self) -> QSize:
        return QSize(540, 540)

    def start(self) -> None:
        """Start the orb animation."""
        if not self.timer.isActive():
            self._last_tick = time.perf_counter()
            self.timer.start()

    def stop(self) -> None:
        """Stop the orb animation."""
        self.timer.stop()

    def set_state(self, state: str) -> None:
        """Set the visual state.

        Supported states are ``idle``, ``listening``, ``transcribing``,
        ``thinking``, ``speaking``, ``text_input``, and ``error``.
        Unknown values fall back to ``idle``.
        """
        next_state = self._normalise_state(state)
        if next_state == self.state:
            return
        self.state = next_state
        self._apply_state_immediately()
        self.state_changed.emit(self.state)

    def set_speaking_level(self, level: float) -> None:
        """Set a 0..1 audio level for the speaking pulse.

        The widget also animates without live audio, but this method lets a TTS
        player make the blue speaking state react more naturally.
        """
        self._audio_level = float(np.clip(level, 0.0, 1.0))

    def _build_visuals(self) -> None:
        style = ORB_STYLES[self.state]
        core_colours, atmosphere_colours, halo_colours = self._sphere_colours(style, 0.0, 0.0)

        self.halo_mesh = visuals.Mesh(
            vertices=self._halo_vertices,
            faces=self._faces,
            vertex_colors=halo_colours,
            shading=None,
            parent=self.view.scene,
        )
        self.halo_mesh.set_gl_state("translucent", depth_test=False, cull_face=False)

        self.atmosphere_mesh = visuals.Mesh(
            vertices=self._atmosphere_vertices,
            faces=self._faces,
            vertex_colors=atmosphere_colours,
            shading=None,
            parent=self.view.scene,
        )
        self.atmosphere_mesh.set_gl_state("translucent", depth_test=False, cull_face=False)

        self.core_mesh = visuals.Mesh(
            vertices=self._core_vertices,
            faces=self._faces,
            vertex_colors=core_colours,
            shading="smooth",
            parent=self.view.scene,
        )
        self.core_mesh.set_gl_state("translucent", depth_test=True, cull_face=False)

        self.orbital_rings = [
            visuals.Line(pos=self._circle * 1.24, color=_rgba(style.glow, 0.16), width=1.4, method="gl", parent=self.view.scene),
            visuals.Line(pos=self._circle * 1.38, color=_rgba(style.glow, 0.12), width=1.2, method="gl", parent=self.view.scene),
            visuals.Line(pos=self._circle * 1.55, color=_rgba(style.glow, 0.10), width=1.0, method="gl", parent=self.view.scene),
        ]

        self.loading_arcs = [
            visuals.Line(pos=np.zeros((96, 3), dtype=np.float32), color=_rgba(style.glow, 0.0), width=4.0, method="gl", parent=self.view.scene),
            visuals.Line(pos=np.zeros((80, 3), dtype=np.float32), color=_rgba(style.glow, 0.0), width=2.4, method="gl", parent=self.view.scene),
        ]

        self.listening_rays = visuals.Line(
            pos=np.zeros((36, 3), dtype=np.float32),
            color=_rgba(style.glow, 0.0),
            width=2.0,
            connect="segments",
            method="gl",
            parent=self.view.scene,
        )

        self.speaking_waves = [
            visuals.Line(pos=self._circle * 1.2, color=_rgba(style.glow, 0.0), width=2.2, method="gl", parent=self.view.scene),
            visuals.Line(pos=self._circle * 1.36, color=_rgba(style.glow, 0.0), width=1.8, method="gl", parent=self.view.scene),
            visuals.Line(pos=self._circle * 1.52, color=_rgba(style.glow, 0.0), width=1.4, method="gl", parent=self.view.scene),
        ]

        self.particles = visuals.Markers(parent=self.view.scene)
        self.particles.set_gl_state("translucent", depth_test=False)

        triangle = np.array(
            ((0.0, 1.05, 1.12), (0.92, -0.55, 1.12), (-0.92, -0.55, 1.12), (0.0, 1.05, 1.12)),
            dtype=np.float32,
        )
        self.warning_triangle = visuals.Line(
            pos=triangle,
            color=_rgba(style.glow, 0.0),
            width=4.0,
            method="gl",
            parent=self.view.scene,
        )
        self.warning_stem = visuals.Line(
            pos=np.array(((0.0, 0.38, 1.18), (0.0, -0.12, 1.18)), dtype=np.float32),
            color=_rgba((0.27, 0.04, 0.04), 0.0),
            width=5.0,
            method="gl",
            parent=self.view.scene,
        )
        self.warning_dot = visuals.Markers(parent=self.view.scene)
        self.warning_dot.set_gl_state("translucent", depth_test=False)

        self.label = visuals.Text(
            text=style.label,
            color=_rgba(style.glow, 0.82),
            bold=True,
            font_size=18,
            pos=(0.0, -1.78, 0.0),
            anchor_x="center",
            anchor_y="center",
            parent=self.view.scene,
        )

        for line in [*self.orbital_rings, *self.loading_arcs, self.listening_rays, *self.speaking_waves, self.warning_triangle, self.warning_stem]:
            line.set_gl_state("translucent", depth_test=False)

    def _animate(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last_tick, 1.0 / 20.0)
        self._last_tick = now

        style = ORB_STYLES[self.state]
        self._phase += dt * style.phase_speed
        energy_target = self._state_energy(style)
        self._energy += (energy_target - self._energy) * min(1.0, dt * 9.0)

        self._update_orb_body(style)
        self._update_rings(style)
        self._update_particles(style)
        self._update_state_effects(style)
        self._update_camera(style)

        self._audio_level *= max(0.0, 1.0 - dt * 4.0)
        self.canvas.update()

    def _normalise_state(self, state: str) -> str:
        clean = (state or "idle").strip().lower().replace("-", "_").replace(" ", "_")
        clean = STATE_ALIASES.get(clean, clean)
        return clean if clean in ORB_STYLES else "idle"

    def _apply_state_immediately(self) -> None:
        style = ORB_STYLES[self.state]
        self.label.text = style.label
        self.label.color = _rgba(style.glow, 0.84)

    def _state_energy(self, style: OrbStateStyle) -> float:
        wave = 0.5 + 0.5 * math.sin(self._phase)
        if self.state == "idle":
            return 0.18 + 0.10 * wave
        if self.state == "listening":
            return 0.62 + 0.30 * wave
        if self.state in {"transcribing", "thinking"}:
            return 0.54 + 0.28 * (0.5 + 0.5 * math.sin(self._phase * 1.8))
        if self.state == "speaking":
            synthetic_level = max(0.0, math.sin(self._phase * 1.45)) ** 1.7
            return 0.45 + 0.50 * max(self._audio_level, synthetic_level)
        if self.state == "error":
            return 0.54 + 0.45 * (1.0 if math.sin(self._phase * 2.2) > 0.0 else 0.18)
        return 0.35 + 0.22 * wave

    def _update_orb_body(self, style: OrbStateStyle) -> None:
        pulse_wave = math.sin(self._phase)
        if self.state == "speaking":
            pulse_wave = self._energy
        elif self.state == "error":
            pulse_wave = 1.0 if math.sin(self._phase * 2.25) > 0.0 else -0.35

        pulse = 1.0 + style.pulse_amp * pulse_wave
        spin = self._phase * style.spin_rate
        body_rotation = _combined_rotation(("y", spin * 0.32), ("z", spin * 0.18))

        core_colours, atmosphere_colours, halo_colours = self._sphere_colours(style, spin, self._energy)
        self.core_mesh.set_data(vertices=self._core_vertices, faces=self._faces, vertex_colors=core_colours)
        self.atmosphere_mesh.set_data(vertices=self._atmosphere_vertices, faces=self._faces, vertex_colors=atmosphere_colours)
        self.halo_mesh.set_data(vertices=self._halo_vertices, faces=self._faces, vertex_colors=halo_colours)

        transform = scene.transforms.MatrixTransform()
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, :3] = body_rotation * pulse
        transform.matrix = matrix
        self.core_mesh.transform = transform
        self.atmosphere_mesh.transform = transform

        halo_transform = scene.transforms.STTransform(scale=(pulse * 1.015, pulse * 1.015, pulse * 1.015))
        self.halo_mesh.transform = halo_transform

    def _sphere_colours(
        self,
        style: OrbStateStyle,
        spin: float,
        energy: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        normals = self._normals
        light = _normalised(np.array((-0.34, -0.58, 0.86), dtype=np.float32))
        view = np.array((0.0, 0.0, 1.0), dtype=np.float32)
        half_vector = _normalised(light + view)

        diffuse = np.clip(normals @ light, 0.0, 1.0)
        rim = np.clip(1.0 - np.maximum(normals @ view, 0.0), 0.0, 1.0) ** 1.75
        specular = np.clip(normals @ half_vector, 0.0, 1.0) ** 34.0
        longitude = np.arctan2(normals[:, 1], normals[:, 0])
        latitude = np.arcsin(np.clip(normals[:, 2], -1.0, 1.0))
        plasma = 0.5 + 0.5 * np.sin(longitude * 5.0 + latitude * 7.0 - spin * 2.4)
        filament = 0.5 + 0.5 * np.sin(longitude * 11.0 - latitude * 4.0 + spin * 1.8)

        core = np.array(style.core, dtype=np.float32)
        mid = np.array(style.mid, dtype=np.float32)
        shadow = np.array(style.shadow, dtype=np.float32)
        glow = np.array(style.glow, dtype=np.float32)

        body_rgb = (
            shadow * (0.28 + 0.34 * (1.0 - diffuse))[:, None]
            + mid * (0.42 + 0.35 * diffuse + 0.08 * plasma * energy)[:, None]
            + core * (0.16 + 0.26 * specular)[:, None]
            + glow * (0.10 * rim + 0.08 * filament * energy)[:, None]
        )
        body_alpha = np.full((len(normals), 1), 0.94, dtype=np.float32)
        body = np.concatenate((np.clip(body_rgb, 0.0, 1.0), body_alpha), axis=1).astype(np.float32)

        atmosphere_alpha = (
            0.025
            + 0.20 * rim * style.glow_strength
            + 0.075 * plasma * energy
        )
        atmosphere_rgb = glow * (0.52 + 0.42 * rim)[:, None] + core * (0.10 + 0.12 * plasma)[:, None]
        atmosphere = np.concatenate(
            (np.clip(atmosphere_rgb, 0.0, 1.0), atmosphere_alpha[:, None]),
            axis=1,
        ).astype(np.float32)

        halo_alpha = (0.018 + 0.16 * rim**1.35 * style.glow_strength + 0.045 * energy * plasma)
        halo_rgb = glow * (0.62 + 0.35 * rim)[:, None]
        halo = np.concatenate((np.clip(halo_rgb, 0.0, 1.0), halo_alpha[:, None]), axis=1).astype(np.float32)
        return body, atmosphere, halo

    def _update_rings(self, style: OrbStateStyle) -> None:
        glow = style.glow
        base_alpha = 0.07 + 0.20 * style.glow_strength * (0.35 + 0.65 * self._energy)
        ring_specs = (
            (1.25, ("x", 1.15), ("z", self._phase * 0.24 * style.spin_rate), 1.0),
            (1.42, ("y", 1.04), ("z", -self._phase * 0.18 * style.spin_rate), 0.72),
            (1.58, ("x", 0.54), ("y", self._phase * 0.15 * style.spin_rate), 0.55),
        )
        for ring, (radius, first_rotation, second_rotation, alpha_scale) in zip(self.orbital_rings, ring_specs):
            matrix = _combined_rotation(first_rotation, second_rotation)
            points = (self._circle * radius) @ matrix.T
            ring.set_data(pos=points, color=_rgba(glow, base_alpha * alpha_scale), width=1.0 + 1.4 * self._energy * alpha_scale)

    def _update_particles(self, style: OrbStateStyle) -> None:
        drift = 0.025 * np.sin(self._phase * 0.8 + self._particle_offsets)
        radii = self._particle_radii + drift
        matrix = _combined_rotation(("y", self._phase * 0.09 * style.spin_rate), ("z", self._phase * 0.13))
        positions = (self._particle_dirs * radii[:, None]) @ matrix.T

        shimmer = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(self._phase * 2.1 + self._particle_offsets))
        alpha = (0.035 + 0.20 * self._energy * style.particle_strength * shimmer).astype(np.float32)
        colour = np.array(_rgba(style.glow, 1.0), dtype=np.float32)
        colours = np.tile(colour, (len(positions), 1))
        colours[:, 3] = np.clip(alpha, 0.0, 0.42)
        size = 3.0 + 5.0 * self._energy * style.particle_strength
        self.particles.set_data(pos=positions.astype(np.float32), face_color=colours, edge_color=colours, size=size)

    def _update_state_effects(self, style: OrbStateStyle) -> None:
        self._update_loading_arcs(style)
        self._update_listening_rays(style)
        self._update_speaking_waves(style)
        self._update_warning(style)

    def _update_loading_arcs(self, style: OrbStateStyle) -> None:
        visible = self.state in {"transcribing", "thinking"}
        for index, arc in enumerate(self.loading_arcs):
            arc.visible = visible
            if not visible:
                continue
            radius = 1.44 + index * 0.18
            start = self._phase * (0.72 + index * 0.22)
            extent = math.radians(118 - index * 22)
            points = self._make_arc_points(radius, start, start + extent, 96 - index * 16)
            matrix = _combined_rotation(("x", 0.85 + index * 0.32), ("z", self._phase * (0.32 + index * 0.18)))
            alpha = 0.64 - index * 0.18
            arc.set_data(pos=points @ matrix.T, color=_rgba(style.glow, alpha), width=4.2 - index * 1.2)

    def _update_listening_rays(self, style: OrbStateStyle) -> None:
        visible = self.state == "listening"
        self.listening_rays.visible = visible
        if not visible:
            return

        ray_count = 18
        points = np.zeros((ray_count * 2, 3), dtype=np.float32)
        for index in range(ray_count):
            angle = math.tau * index / ray_count + self._phase * 0.12
            tilt = 0.34 * math.sin(self._phase * 0.55 + index)
            direction = _normalised(np.array((math.cos(angle), math.sin(angle), tilt), dtype=np.float32))
            inner = 1.16 + 0.04 * math.sin(self._phase + index)
            outer = 1.50 + 0.18 * math.sin(self._phase * 1.4 + index * 0.72)
            points[index * 2] = direction * inner
            points[index * 2 + 1] = direction * outer

        self.listening_rays.set_data(pos=points, color=_rgba(style.glow, 0.46 + 0.18 * self._energy), width=2.2)

    def _update_speaking_waves(self, style: OrbStateStyle) -> None:
        visible = self.state == "speaking"
        for index, wave in enumerate(self.speaking_waves):
            wave.visible = visible
            if not visible:
                continue
            phase = (self._phase * 0.42 + index / len(self.speaking_waves)) % 1.0
            radius = 1.18 + phase * 0.78
            alpha = (1.0 - phase) * (0.32 + 0.36 * self._energy)
            matrix = _combined_rotation(("x", 1.04 + index * 0.16), ("z", self._phase * 0.09))
            wave.set_data(pos=(self._circle * radius) @ matrix.T, color=_rgba(style.glow, alpha), width=2.8 - index * 0.35)

    def _update_warning(self, style: OrbStateStyle) -> None:
        visible = self.state == "error"
        self.warning_triangle.visible = visible
        self.warning_stem.visible = visible
        self.warning_dot.visible = visible
        if not visible:
            return

        blink = 0.45 + 0.55 * (1.0 if math.sin(self._phase * 2.4) > 0.0 else 0.25)
        self.warning_triangle.set_data(color=_rgba(style.glow, 0.42 + 0.38 * blink), width=4.2)
        self.warning_stem.set_data(color=_rgba((0.27, 0.04, 0.04), 0.80 * blink), width=5.0)
        dot_colour = _rgba((0.27, 0.04, 0.04), 0.80 * blink)
        self.warning_dot.set_data(
            pos=np.array(((0.0, -0.34, 1.19),), dtype=np.float32),
            face_color=dot_colour,
            edge_color=dot_colour,
            size=12.0,
        )

    def _update_camera(self, style: OrbStateStyle) -> None:
        error_jitter = 0.0
        if self.state == "error":
            error_jitter = 0.8 * math.sin(self._phase * 3.5)

        self.view.camera.azimuth += style.camera_rate + error_jitter * 0.02
        self.view.camera.elevation = 18 + 2.8 * math.sin(self._phase * 0.14)

    def _make_circle_points(self, radius: float, count: int) -> np.ndarray:
        angles = np.linspace(0.0, math.tau, count, endpoint=True, dtype=np.float32)
        return np.column_stack(
            (
                np.cos(angles) * radius,
                np.sin(angles) * radius,
                np.zeros_like(angles),
            )
        ).astype(np.float32)

    def _make_arc_points(self, radius: float, start: float, stop: float, count: int) -> np.ndarray:
        angles = np.linspace(start, stop, count, endpoint=True, dtype=np.float32)
        return np.column_stack(
            (
                np.cos(angles) * radius,
                np.sin(angles) * radius,
                np.zeros_like(angles),
            )
        ).astype(np.float32)

    def _make_particle_dirs(self, count: int) -> np.ndarray:
        raw = self._rng.normal(size=(count, 3)).astype(np.float32)
        raw /= np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-6)
        return raw


class OrbDemoWindow(QMainWindow):
    """Small standalone preview window for running this file directly."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Jarvis 3D Orb")
        self.resize(720, 720)

        self.orb = Jarvis3DOrbWidget(initial_state="idle", interactive_camera=True)
        self.setCentralWidget(self.orb)

        self._demo_states = ("idle", "listening", "transcribing", "thinking", "speaking", "text_input", "error")
        self._demo_index = 0
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._cycle_state)
        self._demo_timer.start(3500)

    def _cycle_state(self) -> None:
        self._demo_index = (self._demo_index + 1) % len(self._demo_states)
        self.orb.set_state(self._demo_states[self._demo_index])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OrbDemoWindow()
    window.show()
    sys.exit(app.exec())
