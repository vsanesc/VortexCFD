"""Colormaps of the Results Scene, all in one place (D-054).

The lookup tables come from matplotlib (installed with PyVista, declared in pyproject.toml):
viridis and plasma (CC0, van der Walt and Smith), turbo (Apache-2.0, Google), coolwarm (Moreland's
diverging map) and gray. Only the names below are offered.
"""

import numpy as np
from matplotlib import colormaps as _mpl

# label -> matplotlib name
COLORMAPS = {
    "viridis": "viridis",
    "plasma": "plasma",
    "turbo": "turbo",
    "coolwarm": "coolwarm",
    "grayscale": "gray",
}
DEFAULT_COLORMAP = "viridis"
LUT_SIZE = 256


def lookup_table(name: str, n: int = LUT_SIZE) -> np.ndarray:
    """(n, 3) RGB values in [0, 1] of the colormap ``name`` (a key of COLORMAPS)."""
    cmap = _mpl[COLORMAPS[name]].resampled(n)
    return np.asarray(cmap(np.linspace(0.0, 1.0, n)))[:, :3]


def matplotlib_name(name: str) -> str:
    """The name PyVista's ``cmap`` argument takes."""
    return COLORMAPS[name]


def relative_luminance(rgb: np.ndarray) -> np.ndarray:
    """WCAG relative luminance of sRGB rows (used to check lightness ordering)."""
    c = np.asarray(rgb, dtype=float)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])
