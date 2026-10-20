"""GUI package for vortexcfd."""

# Under WSL, pick the NVIDIA adapter before Qt or VTK is imported (D-104); nothing changes elsewhere,
# when the user set the variables, or offscreen.
from vortexcfd.core.gpu_select import select_gpu

GPU_SELECTION = select_gpu()

from vortexcfd.gui.main_window import MainWindow, main  # noqa: E402 (after the GPU selection)

__all__ = ["MainWindow", "main"]
