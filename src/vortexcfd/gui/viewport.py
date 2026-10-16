"""Pieces drawn inside the 3D viewport with VTK (never Qt widgets over OpenGL)."""

import numpy as np
import pyvista as pv
from PySide6.QtGui import QColor
from vtkmodules.vtkRenderingCore import vtkTextActor

from vortexcfd.gui.settings_store import settings
from vortexcfd.gui.theme import (
    EMPTY_SCENE_POINT_FRACTION,
    GRID_HALF_LINES,
    GRID_MAJOR_EVERY,
    GRID_SPACING,
    TELEMETRY_FONT_U,
    TELEMETRY_GAP_CHARS,
    TELEMETRY_LINE_SPACING,
    TELEMETRY_OFFSET_U,
    TELEMETRY_OPACITY,
    TELEMETRY_TITLE_SCALE,
    Metrics,
    Theme,
)

TITLE = "VIEWPORT TELEMETRY"
# Telemetry fields in display order: (key, label).
TELEMETRY_FIELDS = (
    ("parts", "Parts"),
    ("selected", "Selected node"),
    ("triangles", "Triangles"),
    ("cells", "Cells"),
    ("domain", "Domain"),
    ("view", "View"),
)
EMPTY_MESSAGE = "No geometry yet"


def _rgb(color: str) -> tuple[float, float, float]:
    c = QColor(color)
    return c.redF(), c.greenF(), c.blueF()


# -- telemetry settings ------------------------------------------------------


def load_telemetry_settings() -> tuple[bool, dict[str, bool]]:
    """(show, {field key: checked}); everything is on by default."""
    s = settings()
    show = str(s.value("telemetry/show", "true")).lower() == "true"
    fields = {
        key: str(s.value(f"telemetry/field_{key}", "true")).lower() == "true"
        for key, _ in TELEMETRY_FIELDS
    }
    return show, fields


def save_telemetry_settings(show: bool, fields: dict[str, bool]) -> None:
    s = settings()
    s.setValue("telemetry/show", show)
    for key, checked in fields.items():
        s.setValue(f"telemetry/field_{key}", checked)
    s.sync()


# -- ground grid and empty-scene message ---------------------------------------


def _grid_lines(major: bool) -> pv.PolyData:
    half = GRID_HALF_LINES * GRID_SPACING
    points: list[list[float]] = []
    cells: list[int] = []
    for i in range(-GRID_HALF_LINES, GRID_HALF_LINES + 1):
        if (i % GRID_MAJOR_EVERY == 0) != major:
            continue
        pos = i * GRID_SPACING
        for a, b in (([pos, -half, 0.0], [pos, half, 0.0]), ([-half, pos, 0.0], [half, pos, 0.0])):
            n = len(points)
            points += [a, b]
            cells += [2, n, n + 1]
    return pv.PolyData(np.array(points), lines=np.array(cells))


def add_ground_grid(plotter, theme: Theme) -> list:
    """Subtle reference grid on z=0: `border` lines, `border_active` every Nth line."""
    actors = []
    for major, color in ((False, theme.border), (True, theme.border_active)):
        actors.append(
            plotter.add_mesh(
                _grid_lines(major), color=color, line_width=1, lighting=False,
                pickable=False, reset_camera=False, name="grid_major" if major else "grid_minor",
            )
        )
    return actors


class EmptySceneMessage:
    """Centered muted "No geometry yet", a VTK text actor."""

    def __init__(self, renderer) -> None:
        self.actor = vtkTextActor()
        self.actor.SetInput(EMPTY_MESSAGE)
        prop = self.actor.GetTextProperty()
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        coord = self.actor.GetPositionCoordinate()
        coord.SetCoordinateSystemToNormalizedViewport()
        coord.SetValue(0.5, 0.5)
        renderer.add_actor(self.actor, reset_camera=False, render=False)

    def configure(self, theme: Theme, m: Metrics, dpr: float) -> None:
        prop = self.actor.GetTextProperty()
        prop.SetColor(*_rgb(theme.muted_text))
        prop.SetBackgroundColor(*_rgb(theme.canvas))
        prop.SetBackgroundOpacity(TELEMETRY_OPACITY)
        prop.SetFontSize(max(1, round(m.u * EMPTY_SCENE_POINT_FRACTION * dpr)))

    def set_visible(self, visible: bool) -> None:
        self.actor.SetVisibility(visible)


# -- telemetry card ---------------------------------------------------------------


class TelemetryCard:
    """Card drawn with several VTK text actors anchored at the same top-left point.

    One invisible-text actor carries the elevated background and the 1px border frame (its text
    only sizes the box); a muted label actor, a value actor and an accent_secondary title actor
    overlay it. Monospace text keeps the columns aligned.
    """

    def __init__(self, renderer) -> None:
        self.renderer = renderer
        self.box = self._actor()
        self.title = self._actor()
        self.labels = self._actor()
        self.values = self._actor()
        self.rows: list[tuple[str, str]] = []
        self._theme: Theme | None = None
        self._font_px = 0
        self._offset_px = 0
        self.visible = False
        for actor in self.actors:
            renderer.add_actor(actor, reset_camera=False, render=False)
            actor.SetVisibility(False)

    @property
    def actors(self) -> tuple[vtkTextActor, ...]:
        return (self.box, self.title, self.labels, self.values)

    @staticmethod
    def _actor() -> vtkTextActor:
        actor = vtkTextActor()
        prop = actor.GetTextProperty()
        prop.SetFontFamilyToCourier()
        prop.SetJustificationToLeft()
        prop.SetVerticalJustificationToTop()
        actor.GetPositionCoordinate().SetCoordinateSystemToDisplay()
        return actor

    def configure(self, theme: Theme, m: Metrics, dpr: float) -> None:
        self._theme = theme
        self._font_px = max(1, round(m.u * TELEMETRY_FONT_U * dpr))
        self._offset_px = round(TELEMETRY_OFFSET_U * m.u * dpr)
        for actor in (self.box, self.labels, self.values):
            actor.GetTextProperty().SetFontSize(self._font_px)
            actor.GetTextProperty().SetLineSpacing(TELEMETRY_LINE_SPACING)
        self.title.GetTextProperty().SetFontSize(max(1, round(self._font_px * TELEMETRY_TITLE_SCALE)))
        self.title.GetTextProperty().BoldOn()
        box = self.box.GetTextProperty()
        box.SetOpacity(0.0)  # only the background and frame are visible
        box.SetBackgroundColor(*_rgb(theme.elevated))
        box.SetBackgroundOpacity(TELEMETRY_OPACITY)
        box.FrameOn()
        box.SetFrameColor(*_rgb(theme.border))
        box.SetFrameWidth(1)
        self.title.GetTextProperty().SetColor(*_rgb(theme.accent_secondary))
        self.labels.GetTextProperty().SetColor(*_rgb(theme.muted_text))
        self.values.GetTextProperty().SetColor(*_rgb(theme.text))
        self._apply_text()

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        """Rows shown, in order; an empty list hides the card."""
        self.rows = list(rows)
        self._apply_text()

    def _apply_text(self) -> None:
        self.visible = bool(self.rows)
        for actor in self.actors:
            actor.SetVisibility(self.visible)
        if not self.rows:
            return
        label_w = max(len(label) for label, _ in self.rows)
        title_chars = -(-len(TITLE) * round(TELEMETRY_TITLE_SCALE * 100) // 100)
        value_w = max(max(len(value) for _, value in self.rows),
                      title_chars - label_w - TELEMETRY_GAP_CHARS)
        gap = " " * TELEMETRY_GAP_CHARS
        inner = label_w + TELEMETRY_GAP_CHARS + value_w
        # Line 0 is padding, line 1 holds the title, then one line per row, then padding.
        box = ["x" * (inner + 2), "x" * (inner + 2)]
        label_lines = ["", ""]
        value_lines = ["", ""]
        for label, value in self.rows:
            box.append("x" + label.ljust(label_w) + gap + value.rjust(value_w) + "x")
            label_lines.append(" " + label.ljust(label_w))
            value_lines.append(" " + " " * label_w + gap + value.rjust(value_w))
        box.append("x" * (inner + 2))
        self.box.SetInput("\n".join(box))
        self.labels.SetInput("\n".join(label_lines))
        self.values.SetInput("\n".join(value_lines))
        self.title.SetInput(" " + TITLE)

    def layout(self, viewport_height: int) -> None:
        """Anchor the card ``1u`` from the top-left corner (display coordinates, y up)."""
        x, y = self._offset_px, viewport_height - self._offset_px
        for actor in self.actors:
            actor.SetPosition(x, y)
        # The title sits on the second line, between the top padding and the rows.
        self.title.SetPosition(x, y - round(self._font_px * TELEMETRY_LINE_SPACING))
