"""The app's ticks (core/ticks.py, D-169) on matplotlib axes: the line plots, the Compare overlays and the report's
pictures. The locator computes the ticks from the axis' current view, so they follow a zoom or a pan."""

from matplotlib.ticker import Formatter, Locator

from vortexcfd.core import ticks as tk

GRID_ALPHA = 0.28  # the light grid: major lines
MINOR_GRID_ALPHA = 0.10


class NiceLocator(Locator):
    """Major (or minor) ticks of core/ticks for the axis' view interval: about ``target`` majors per axis, whole
    iterations on an ``integer`` axis."""

    def __init__(self, target: int = 6, integer: bool = False, minor: bool = False) -> None:
        self.target, self.integer, self.minor = target, integer, minor

    def _ticks(self, vmin: float, vmax: float) -> tk.Ticks:
        return tk.ticks(vmin, vmax, self.target, self.integer)

    def tick_values(self, vmin, vmax):
        t = self._ticks(float(vmin), float(vmax))
        return list(t.minor if self.minor else t.major)

    def __call__(self):
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)


class NiceFormatter(Formatter):
    """Labels with the decimals the step needs and thousands separators (core/ticks.label)."""

    def __init__(self, locator: NiceLocator) -> None:
        self.locator = locator

    def __call__(self, x, pos=None) -> str:
        vmin, vmax = self.axis.get_view_interval()
        return tk.label(float(x), self.locator._ticks(float(vmin), float(vmax)).step)


def apply(ax, x_integer: bool = False, y: bool = True, target: int = 6) -> None:
    """The app's ticks on ``ax``: x always (``x_integer`` for an iteration axis); y too unless it is logarithmic or
    ``y`` is False; a light major grid and a lighter minor one."""
    axes = [(ax.xaxis, x_integer)]
    if y and ax.get_yscale() == "linear":
        axes.append((ax.yaxis, False))
    for axis, integer in axes:
        major = NiceLocator(target, integer)
        axis.set_major_locator(major)
        axis.set_minor_locator(NiceLocator(target, integer, minor=True))
        axis.set_major_formatter(NiceFormatter(major))
    ax.grid(True, which="major", alpha=GRID_ALPHA)
    ax.grid(True, which="minor", alpha=MINOR_GRID_ALPHA, lw=0.5)
    ax.tick_params(which="minor", length=2)
