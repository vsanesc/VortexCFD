"""The line plot's chart in the properties panel (D-136): a matplotlib figure embedded with the Qt Agg canvas, drawn
by workflow/line_plot.draw (the same chart as the PNG export and the report)."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy

from PySide6.QtCore import Qt

from vortexcfd.gui.plot_interaction import ZoomPan
from vortexcfd.gui.theme import DARK, Theme, role_point_size
from vortexcfd.workflow.line_plot import LineSamples, draw

CHART_HEIGHT = 260  # px per field, before the first


class LinePlotCanvas(FigureCanvasQTAgg):
    """Shows ``LineSamples`` (or a note without samples)."""

    def __init__(self) -> None:
        self.figure_ = Figure(figsize=(4.0, 2.6), dpi=90)
        super().__init__(self.figure_)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(CHART_HEIGHT)
        self.samples: LineSamples | None = None
        self.note_color = DARK.muted_text
        self.zoom_pan = ZoomPan(self, ctrl_wheel=True)  # D-169

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """The wheel scrolls the properties panel; with Ctrl it zooms the chart."""
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        super().wheelEvent(event)

    def configure(self, theme: Theme) -> None:
        self.note_color = theme.muted_text

    def set_samples(self, samples: LineSamples | None, title: str = "") -> None:
        self.samples = samples
        if samples is None:
            self.figure_.clear()
            self.figure_.text(0.5, 0.5, "No samples: the line needs results inside the fluid", ha="center",
                              va="center", fontsize=role_point_size("caption"), color=self.note_color)
        else:
            draw(self.figure_, samples, title)
        n = len(samples.values) if samples is not None else 1
        self.setMinimumHeight(CHART_HEIGHT + 150 * (n - 1))
        self.draw_idle()
