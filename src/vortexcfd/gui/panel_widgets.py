"""Field widgets of the properties panel (D-148): a section header that collapses its rows, an "Auto" checkbox field
that shows the value in use, a vector field "(x, y, z)" with a unit, and a length entered in multiples of a reference
length or in metres / millimetres.

Every widget reports a finished edit through ``edited`` (the panel commits on it); the panel fills them without
signals (``blockSignals``).
"""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.widgets import set_invalid

CHEVRON_OPEN = "▾"
CHEVRON_CLOSED = "▸"


class SectionHeader(QWidget):
    """A section title inside a node's rows: a chevron that collapses the section (``toggled(key, collapsed)``) and
    an optional "?" that opens the matching manual section (``help_requested(anchor)``)."""

    toggled = Signal(str, bool)
    help_requested = Signal(str)

    def __init__(self, key: str, text: str, help_anchor: str | None = None) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("sectionHeader2")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.collapsed = False
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.chevron = QToolButton()
        self.chevron.setObjectName("chevronBtn")
        self.chevron.setText(CHEVRON_OPEN)
        self.chevron.setToolTip("Collapse or expand this section (remembered for this kind of node)")
        self.chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chevron.clicked.connect(self.toggle)
        self.title = QLabel(text.upper())
        self.title.setObjectName("subSection")
        self.title.setMinimumWidth(1)  # a long title never widens the panel
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.addWidget(self.chevron)
        box.addWidget(self.title, 1)
        self.help_anchor = help_anchor
        self.help = QToolButton()
        self.help.setObjectName("helpBtn")
        self.help.setText("?")
        self.help.setToolTip("Open the manual section about this")
        self.help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help.clicked.connect(lambda: self.help_requested.emit(self.help_anchor or ""))
        self.help.setVisible(help_anchor is not None)
        box.addWidget(self.help)

    def text(self) -> str:
        return self.title.text()

    def setFont(self, font) -> None:  # the title carries the section font
        self.title.setFont(font)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self.chevron.setText(CHEVRON_CLOSED if collapsed else CHEVRON_OPEN)

    def toggle(self) -> None:
        self.set_collapsed(not self.collapsed)
        self.toggled.emit(self.key, self.collapsed)

    def mouseReleaseEvent(self, event) -> None:  # a click anywhere on the title toggles too
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
        super().mouseReleaseEvent(event)


class AutoField(QWidget):
    """An optional value with an "Auto" checkbox (D-148): checked, the field is read-only and greyed and shows the
    computed value in use; unchecked, the value is the user's. ``value()`` is None while Auto is checked."""

    edited = Signal()

    def __init__(self, spin: QSpinBox | QDoubleSpinBox, auto_tip: str = "") -> None:
        super().__init__()
        self.spin = spin
        self.auto = QCheckBox("Auto")
        self.auto.setToolTip(auto_tip or "Checked: the value is computed (shown greyed); uncheck to set it")
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(self.auto)
        box.addWidget(spin, 1)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        spin.setKeyboardTracking(False)
        self._computed: float | None = None
        self.auto.toggled.connect(self._auto_toggled)
        spin.editingFinished.connect(self._spin_finished)

    def _auto_toggled(self, on: bool) -> None:
        self.spin.setReadOnly(on)
        self.spin.setEnabled(not on)
        if not on and self._computed is not None:
            self.spin.setValue(self._computed)  # start from the value in use
        self.edited.emit()

    def _spin_finished(self) -> None:
        if not self.auto.isChecked():
            self.edited.emit()

    def set_state(self, value, computed=None) -> None:
        """``value`` None: Auto, showing ``computed`` (None: unknown, the spin's minimum); else the user's value."""
        self._computed = computed
        for w in (self.auto, self.spin):
            w.blockSignals(True)
        try:
            auto = value is None
            self.auto.setChecked(auto)
            self.spin.setReadOnly(auto)
            self.spin.setEnabled(not auto)
            shown = value if not auto else computed
            if shown is not None:
                self.spin.setValue(shown)
            else:
                self.spin.setValue(self.spin.minimum())
        finally:
            for w in (self.auto, self.spin):
                w.blockSignals(False)

    def value(self):
        return None if self.auto.isChecked() else self.spin.value()

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self.spin.setToolTip(text)


def parse_vector_text(text: str) -> tuple[float, float, float]:
    """"1.2 0 -0.5", "(1.2, 0, -0.5)", "1.2;0;-0.5" -> (1.2, 0.0, -0.5). Raises ValueError with the reason."""
    clean = text.strip()
    for opening, closing in (("(", ")"), ("[", "]")):
        if clean.startswith(opening) and clean.endswith(closing):
            clean = clean[1:-1]
    parts = [p for p in clean.replace(",", " ").replace(";", " ").replace("\t", " ").split() if p]
    if len(parts) != 3:
        raise ValueError(f"expected three numbers (x, y, z), got {len(parts)}")
    values = []
    for p in parts:
        try:
            v = float(p)
        except ValueError:
            raise ValueError(f"'{p}' is not a number") from None
        if not math.isfinite(v):
            raise ValueError(f"'{p}' is not a finite number")
        values.append(v)
    return values[0], values[1], values[2]


def format_vector_text(v) -> str:
    return "(" + ", ".join(f"{x:.6g}" for x in v) + ")"


class VectorField(QWidget):
    """One "(x, y, z)" field with a unit label (D-148): accepts pasted text like "1.2 0 -0.5" or "(1.2, 0, -0.5)";
    bad input is shown on the field (highlighted border, the reason as its tooltip) and not committed."""

    edited = Signal()

    def __init__(self, unit: str = "m", tooltip: str = "") -> None:
        super().__init__()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("(x, y, z)")
        self.unit = QLabel(unit)
        self.unit.setObjectName("muted")
        self._tip = tooltip
        self.edit.setToolTip(tooltip)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addWidget(self.edit, 1)
        box.addWidget(self.unit)
        self.edit.editingFinished.connect(self._finished)
        self.edit.textEdited.connect(lambda _t: self.check())
        self._value: tuple[float, float, float] | None = None

    def check(self) -> str | None:
        """The parse error of the text (shown on the field), or None."""
        try:
            parse_vector_text(self.edit.text())
        except ValueError as exc:
            set_invalid(self.edit, f"Invalid vector: {exc}", self._tip)
            return str(exc)
        set_invalid(self.edit, None, self._tip)
        return None

    def _finished(self) -> None:
        if self.check() is None:
            self.edited.emit()

    def value(self) -> tuple[float, float, float]:
        return parse_vector_text(self.edit.text())

    def setValue(self, v) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(format_vector_text(v))
        self.edit.blockSignals(False)
        set_invalid(self.edit, None, self._tip)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)


LENGTH_UNITS = {"L": None, "m": 1.0, "mm": 1e-3}


class ReferenceLengthField(QWidget):
    """A domain extent stored in multiples of a reference length L (D-078), entered either in L or in m / mm with a
    toggle (D-148); the other form is shown live next to it. ``value()`` is always in L."""

    edited = Signal()
    unit_changed = Signal(str)

    def __init__(self, tooltip: str = "") -> None:
        super().__init__()
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.0, 1e9)
        self.spin.setDecimals(4)
        self.spin.setKeyboardTracking(False)
        self.spin.setToolTip(tooltip)
        self.unit_button = QPushButton("L")
        self.unit_button.setObjectName("unitBtn")
        self.unit_button.setToolTip("Enter in multiples of L, in metres or in millimetres (click to switch)")
        self.unit_button.clicked.connect(self._next_unit)
        self.other = QLabel()
        self.other.setObjectName("muted")
        self.other.setMinimumWidth(1)
        self.other.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addWidget(self.spin, 3)
        box.addWidget(self.unit_button)
        box.addWidget(self.other, 2)
        self.unit = "L"
        self.reference = 1.0  # L in metres
        self._in_l = 1.0
        self.spin.editingFinished.connect(self._finished)
        self.spin.valueChanged.connect(lambda _v: self._show_other())

    def set_reference(self, length_m: float | None) -> None:
        self.reference = length_m if length_m and length_m > 0 else 1.0

    def set_unit(self, unit: str) -> None:
        self.unit = unit if unit in LENGTH_UNITS else "L"
        self.unit_button.setText(self.unit)
        self._show_value()

    def _next_unit(self) -> None:
        order = list(LENGTH_UNITS)
        self.set_unit(order[(order.index(self.unit) + 1) % len(order)])
        self.unit_changed.emit(self.unit)

    def _to_l(self, shown: float) -> float:
        factor = LENGTH_UNITS[self.unit]
        return shown if factor is None else shown * factor / self.reference

    def _from_l(self, value_l: float) -> float:
        factor = LENGTH_UNITS[self.unit]
        return value_l if factor is None else value_l * self.reference / factor

    def setValue(self, value_l: float) -> None:
        self._in_l = float(value_l)
        self._show_value()

    def _show_value(self) -> None:
        self.spin.blockSignals(True)
        self.spin.setDecimals(4 if self.unit != "mm" else 1)
        self.spin.setValue(self._from_l(self._in_l))
        self.spin.blockSignals(False)
        self._show_other()

    def _show_other(self) -> None:
        value_l = self._to_l(self.spin.value())
        metres = value_l * self.reference
        if self.unit == "L":
            self.other.setText(f"= {metres:.4g} m")
        else:
            self.other.setText(f"= {value_l:.4g} L")

    def _finished(self) -> None:
        value = self._to_l(self.spin.value())
        if abs(value - self._in_l) > 1e-12 * max(1.0, abs(value)):
            self._in_l = value
            self.edited.emit()

    def value(self) -> float:
        return self._in_l


class FloatingPanel(QWidget):
    """A panel detached from the main window into its own window (D-148): ``take`` moves a widget in, ``release``
    gives it back; closing the window calls ``on_close`` (the owner docks the panel back)."""

    def __init__(self, title: str, on_close) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_close = on_close
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self.content: QWidget | None = None

    def take(self, widget: QWidget) -> None:
        self.content = widget
        widget.setParent(self)
        self._box.addWidget(widget)
        widget.show()

    def release(self) -> None:
        if self.content is not None:
            self._box.removeWidget(self.content)
        self.content = None

    def closeEvent(self, event) -> None:
        if self.content is not None:  # closed by the user: dock the panel back
            self._on_close()
        super().closeEvent(event)


class ChoiceField(QWidget):
    """A choice between a few long, self-explaining options as radio buttons stacked vertically (D-148); ``value()``
    is the chosen option's model value."""

    edited = Signal()

    def __init__(self, pairs) -> None:
        super().__init__()
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for value, label in pairs:
            button = QRadioButton(label)
            button.setMinimumWidth(1)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.group.addButton(button)
            self.buttons[value] = button
            box.addWidget(button)
            button.toggled.connect(lambda on: on and self.edited.emit())

    def value(self):
        return next((v for v, b in self.buttons.items() if b.isChecked()), None)

    def setValue(self, value) -> None:
        for b in self.buttons.values():
            b.blockSignals(True)
        try:
            if value in self.buttons:
                self.buttons[value].setChecked(True)  # the exclusive group unchecks the others
        finally:
            for b in self.buttons.values():
                b.blockSignals(False)

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        for b in self.buttons.values():
            b.setToolTip(text)

    def setEnabled(self, on: bool) -> None:
        super().setEnabled(on)
