"""GUI package for vortexcfd.

``MainWindow`` and ``main`` are imported on first access, so the Qt-free orchestration modules of
this package (meshing, solving, part_ops) can be imported without loading Qt (the benchmark, D-082).
"""

__all__ = ["MainWindow", "main"]


def __getattr__(name: str):
    if name in __all__:
        from vortexcfd.gui import main_window

        return getattr(main_window, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
