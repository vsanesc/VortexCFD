"""Image export of the viewer (D-133): the scene rendered OFFSCREEN at the requested size (a new render window of
that size, not a screenshot scaled up), with the current camera, the visible 3D actors and the scalar bars, the
background colour or a transparent background, written as PNG.

Each actor is copied with its own mapper instance (the input, colours and range shared), so the offscreen render
window allocates its own graphics resources; the viewer's 2D overlays other than the scalar bars (the telemetry
card, notes) are left out.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

PRESETS = {"1920 x 1080 (Full HD)": (1920, 1080), "2560 x 1440 (QHD)": (2560, 1440),
           "3840 x 2160 (4K UHD)": (3840, 2160)}
CUSTOM = "Custom"
MAX_SIZE = 8192


@dataclass(frozen=True)
class RenderedImage:
    """The image (rows x columns x 3 or 4, uint8) and what it contains."""

    pixels: np.ndarray
    actors: int
    scalar_bars: int


def _copy_actor(actor: vtk.vtkActor) -> vtk.vtkActor:
    copy = vtk.vtkActor()
    copy.ShallowCopy(actor)
    mapper = actor.GetMapper()
    if mapper is not None:
        own = mapper.NewInstance()
        own.ShallowCopy(mapper)  # colours, range, lookup table: not the input
        if mapper.GetNumberOfInputConnections(0):
            own.SetInputConnection(mapper.GetInputConnection(0, 0))
        else:
            own.SetInputDataObject(mapper.GetInputDataObject(0, 0))
        copy.SetMapper(own)
    return copy


def render_image(plotter, size: tuple[int, int], transparent: bool = False) -> RenderedImage:
    """The scene of ``plotter`` (a pyvista Plotter or QtInteractor) rendered offscreen at ``size`` (width, height)."""
    width, height = int(size[0]), int(size[1])
    if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
        raise ValueError(f"the image size must be 1 to {MAX_SIZE} pixels each way")
    off = pv.Plotter(off_screen=True, window_size=(width, height))
    try:
        off.set_background(plotter.background_color)
        actors = bars = 0
        props = plotter.renderer.GetViewProps()
        props.InitTraversal()
        for _ in range(props.GetNumberOfItems()):
            prop = props.GetNextProp()
            if not prop.GetVisibility():
                continue
            if isinstance(prop, vtk.vtkScalarBarActor):
                bar = vtk.vtkScalarBarActor()
                bar.ShallowCopy(prop)
                bar.SetUnconstrainedFontSize(prop.GetUnconstrainedFontSize())  # not part of ShallowCopy
                off.renderer.AddViewProp(bar)
                bars += 1
            elif isinstance(prop, vtk.vtkActor):
                off.renderer.AddActor(_copy_actor(prop))
                actors += 1
        off.renderer.GetActiveCamera().DeepCopy(plotter.renderer.GetActiveCamera())
        off.camera_set = True  # else PyVista's first render replaces the copied camera with its default view
        off.renderer.ResetCameraClippingRange()
        pixels = off.screenshot(transparent_background=transparent, return_img=True)
    finally:
        off.close()
        off.deep_clean()
        del off
        # the offscreen plotter's VTK objects are freed now, with no OpenGL context current, not by a later
        # collection while the viewer's context is current (D-193)
        from vortexcfd.gui.teardown import collect_garbage

        collect_garbage()
    return RenderedImage(np.asarray(pixels), actors, bars)


def export_image(plotter, path: Path, size: tuple[int, int], transparent: bool = False) -> RenderedImage:
    """``render_image`` written to ``path`` as PNG (folders created)."""
    from PIL import Image

    image = render_image(plotter, size, transparent)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image.pixels, mode="RGBA" if image.pixels.shape[2] == 4 else "RGB").save(path)
    return image


def png_bytes(plotter, size: tuple[int, int]) -> bytes:
    """``render_image`` as PNG bytes (the HTML report)."""
    import io

    from PIL import Image

    image = render_image(plotter, size)
    buffer = io.BytesIO()
    Image.fromarray(image.pixels).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass(frozen=True)
class ExportSpec:
    path: Path
    size: tuple[int, int]
    transparent: bool


class ExportImageDialog(QDialog):
    """The size (a preset or custom), the transparent background and the file."""

    def __init__(self, suggested: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export image")
        self.preset = QComboBox()
        self.preset.addItems([*PRESETS, CUSTOM])
        self.width_spin, self.height_spin = QSpinBox(), QSpinBox()
        for spin, value in ((self.width_spin, 1920), (self.height_spin, 1080)):
            spin.setRange(1, MAX_SIZE)
            spin.setValue(value)
            spin.setSuffix(" px")
        size_row = QHBoxLayout()
        size_row.addWidget(self.width_spin)
        size_row.addWidget(self.height_spin)
        self.transparent = QCheckBox("Transparent background")
        self.path_edit = QLineEdit(str(suggested))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Resolution", self.preset)
        form.addRow("Size", size_row)
        form.addRow("", self.transparent)
        form.addRow("File", path_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.preset.currentTextChanged.connect(self._preset_changed)
        self._preset_changed(self.preset.currentText())

    def _preset_changed(self, text: str) -> None:
        custom = text == CUSTOM
        for spin in (self.width_spin, self.height_spin):
            spin.setEnabled(custom)
        if not custom:
            self.width_spin.setValue(PRESETS[text][0])
            self.height_spin.setValue(PRESETS[text][1])

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export image", self.path_edit.text(), "PNG images (*.png)")
        if name:
            self.path_edit.setText(name)

    def spec(self) -> ExportSpec:
        path = Path(self.path_edit.text().strip())
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        return ExportSpec(path, (self.width_spin.value(), self.height_spin.value()), self.transparent.isChecked())
