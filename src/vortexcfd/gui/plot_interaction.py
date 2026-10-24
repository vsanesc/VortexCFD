"""Zoom and pan on an embedded matplotlib chart (the Compare plots and the line plots, D-169): the wheel zooms about
the pointer (x and y; with Shift x only), a left drag pans, a double click shows everything again. The app's tick
locators (workflow/plot_axes) follow the new view."""

ZOOM_STEP = 1.25
TIP = "Wheel: zoom (Shift: iterations or distance only); drag: pan; double-click: show all"
CTRL_TIP = "Ctrl + wheel: zoom (with Shift: the distance only); drag: pan; double-click: show all"


class ZoomPan:
    """Connects ``canvas`` (a FigureCanvasQTAgg) to zoom and pan; ``zoomed`` is True until a double click."""

    def __init__(self, canvas, ctrl_wheel: bool = False) -> None:
        """``ctrl_wheel``: only Ctrl + wheel zooms (a chart inside a scrolling panel: the wheel scrolls the panel)."""
        self.canvas = canvas
        self.ctrl_wheel = ctrl_wheel
        self.zoomed = False
        self._drag = None  # (axes, x, y in data units, xlim, ylim) at the press
        canvas.setToolTip(CTRL_TIP if ctrl_wheel else TIP)
        canvas.mpl_connect("scroll_event", self._scroll)
        canvas.mpl_connect("button_press_event", self._press)
        canvas.mpl_connect("motion_notify_event", self._move)
        canvas.mpl_connect("button_release_event", self._release)

    def zoom(self, ax, x: float, y: float, factor: float, x_only: bool = False) -> None:
        """Scale the view of ``ax`` by ``factor`` (< 1 zooms in) about (``x``, ``y``); shared x axes follow."""
        x0, x1 = ax.get_xlim()
        ax.set_xlim(x - (x - x0) * factor, x + (x1 - x) * factor)
        if not x_only and ax.get_yscale() == "linear":
            y0, y1 = ax.get_ylim()
            ax.set_ylim(y - (y - y0) * factor, y + (y1 - y) * factor)
        self.zoomed = True
        self.canvas.draw_idle()

    def reset(self) -> None:
        for ax in self.canvas.figure.axes:
            ax.relim()
            ax.autoscale()
        self.zoomed = False
        self.canvas.draw_idle()

    def _scroll(self, event) -> None:
        if event.inaxes is None or event.xdata is None:
            return
        if self.ctrl_wheel and "ctrl" not in (event.key or "") and "control" not in (event.key or ""):
            return
        factor = 1 / ZOOM_STEP if event.button == "up" else ZOOM_STEP
        self.zoom(event.inaxes, event.xdata, event.ydata, factor, x_only="shift" in (event.key or ""))

    def _press(self, event) -> None:
        if event.inaxes is None or event.xdata is None:
            return
        if event.dblclick:
            self.reset()
            return
        if event.button == 1:
            ax = event.inaxes
            self._drag = (ax, event.x, event.y, ax.get_xlim(), ax.get_ylim())

    def _move(self, event) -> None:
        if self._drag is None or event.x is None:
            return
        ax, px, py, (x0, x1), (y0, y1) = self._drag
        box = ax.get_window_extent()
        dx = (event.x - px) / max(box.width, 1) * (x1 - x0)
        ax.set_xlim(x0 - dx, x1 - dx)
        if ax.get_yscale() == "linear":
            dy = (event.y - py) / max(box.height, 1) * (y1 - y0)
            ax.set_ylim(y0 - dy, y1 - dy)
        self.zoomed = True
        self.canvas.draw_idle()

    def _release(self, _event) -> None:
        self._drag = None
