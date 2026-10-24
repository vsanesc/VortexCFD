"""Field widgets of the properties panel (D-148): a section header that collapses its rows, an "Auto" checkbox field
that shows the value in use, a vector field "(x, y, z)" with a unit, and a length entered in multiples of a reference
length or in metres / millimetres.

Every widget reports a finished edit through ``edited`` (the panel commits on it); the panel fills them without
signals (``blockSignals``).
"""

import math

from PySide6.QtCore import QEvent, Qt, Signal
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

from vortexcfd.gui.theme import metrics
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
    bad input is shown on the field (highlighted border, the reason as its tooltip) and not committed. With ``auto``
    an "Auto" checkbox: checked, ``value()`` is None and the field shows the computed vector, read-only.
    ``editingFinished`` follows a valid finished edit (or a change of the Auto box)."""

    editingFinished = Signal()

    def __init__(self, unit: str = "m", tooltip: str = "", auto: bool = False) -> None:
        super().__init__()
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("(x, y, z)")
        self.edit.setMinimumWidth(1)
        self.unit = QLabel(unit)
        self.unit.setObjectName("unitLabel")
        self._tip = tooltip
        self.edit.setToolTip(tooltip)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.auto: QCheckBox | None = None
        if auto:
            self.auto = QCheckBox("Auto")
            self.auto.setToolTip("Checked: the value is computed (shown greyed); uncheck to set it")
            self.auto.toggled.connect(self._auto_toggled)
            box.addWidget(self.auto)
        box.addWidget(self.edit, 1)
        box.addWidget(self.unit)
        self.edit.editingFinished.connect(self._finished)
        self.edit.textEdited.connect(lambda _t: self.check())
        self._computed = None

    def _auto_toggled(self, on: bool) -> None:
        self.edit.setReadOnly(on)
        self.edit.setEnabled(not on)
        if not on and self._computed is not None:
            self.edit.setText(format_vector_text(self._computed))
        set_invalid(self.edit, None, self._tip)
        self.editingFinished.emit()

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
        if self.auto is not None and self.auto.isChecked():
            return
        if self.check() is None:
            self.editingFinished.emit()

    @property
    def valid(self) -> bool:
        return self.edit.property("invalid") is not True

    def value(self):
        if self.auto is not None and self.auto.isChecked():
            return None
        return parse_vector_text(self.edit.text())

    def setValue(self, v) -> None:
        self.set_state(v, self._computed)

    def set_state(self, value, computed=None) -> None:
        """``value`` None (with Auto): Auto checked, showing ``computed``; else the vector."""
        self._computed = computed
        widgets = (self.edit, self.auto) if self.auto is not None else (self.edit,)
        for w in widgets:
            w.blockSignals(True)
        try:
            auto = value is None and self.auto is not None
            if self.auto is not None:
                self.auto.setChecked(auto)
                self.edit.setReadOnly(auto)
                self.edit.setEnabled(not auto)
            shown = computed if auto else value
            self.edit.setText(format_vector_text(shown) if shown is not None else "")
        finally:
            for w in widgets:
                w.blockSignals(False)
        set_invalid(self.edit, None, self._tip)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)

    def setToolTip(self, text: str) -> None:
        self._tip = text
        super().setToolTip(text)
        if self.valid:
            self.edit.setToolTip(text)


LENGTH_UNITS = {"L": None, "m": 1.0, "mm": 1e-3}


UNIT_TIP = ("Enter in multiples of L (the domain follows the parts), or in metres or millimetres (a fixed length); "
            "click to switch: the value is converted to the same length")
NO_L_TIP = "Import a part first: L, the parts' largest extent, converts between L and metres"


class ReferenceLengthField(QWidget):
    """A domain extent in multiples of the reference length L (D-078) or in m / mm (D-157), with a button to switch;
    the other form is shown under it. ``value()`` is in ``unit``; switching the unit converts the value to the same
    length in the new unit and finishes an edit, so the model stores the value with its unit. ``editingFinished``
    follows a finished edit (like a spin box's)."""

    editingFinished = Signal()
    unit_changed = Signal(str)

    def __init__(self, tooltip: str = "") -> None:
        super().__init__()
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.001, 1e9)
        self.spin.setDecimals(4)
        self.spin.setKeyboardTracking(False)
        self.unit_button = QPushButton("L")
        self.unit_button.setObjectName("unitBtn")
        self.unit_button.setToolTip(UNIT_TIP)
        self.unit_button.clicked.connect(self._next_unit)
        self.other = QLabel()
        self.other.setObjectName("muted")
        self.other.setMinimumWidth(1)
        self.other.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(self)  # the value and its unit, the other form under them
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        box = QHBoxLayout()
        box.setSpacing(4)
        box.addWidget(self.spin, 1)
        box.addWidget(self.unit_button)
        outer.addLayout(box)
        outer.addWidget(self.other)
        self.unit = "L"
        self.reference: float | None = None  # L in metres (None: no parts yet)
        self._value = 1.0  # in ``unit``
        self.spin.editingFinished.connect(self._finished)
        self.spin.valueChanged.connect(lambda _v: self._show_other())
        self.setToolTip(tooltip)

    def set_reference(self, length_m: float | None) -> None:
        """L in metres; without it (no parts) the unit cannot be switched, as there is nothing to convert with."""
        self.reference = length_m if length_m and length_m > 0 else None
        self.unit_button.setEnabled(self.reference is not None)
        self.unit_button.setToolTip(UNIT_TIP if self.reference is not None else NO_L_TIP)
        self._show_other()

    def _metres(self, value: float, unit: str) -> float | None:
        factor = LENGTH_UNITS[unit]
        if factor is not None:
            return value * factor
        return value * self.reference if self.reference is not None else None

    def _in_unit(self, metres: float, unit: str) -> float:
        factor = LENGTH_UNITS[unit]
        return metres / factor if factor is not None else metres / (self.reference or 1.0)

    def _next_unit(self) -> None:
        """The next unit, the same length: the value converted and committed with its unit."""
        order = list(LENGTH_UNITS)
        unit = order[(order.index(self.unit) + 1) % len(order)]
        metres = self._metres(self.spin.value(), self.unit)
        if metres is None:
            return
        self.setValue(self._in_unit(metres, unit), unit)
        self.unit_changed.emit(unit)
        self.editingFinished.emit()

    def setValue(self, value: float, unit: str | None = None) -> None:
        if unit is not None:
            self.unit = unit if unit in LENGTH_UNITS else "L"
            self.unit_button.setText(self.unit)
        self._value = float(value)
        self.spin.blockSignals(True)
        self.spin.setDecimals({"L": 3, "m": 4, "mm": 1}[self.unit])
        self.spin.setValue(self._value)
        self.spin.blockSignals(False)
        self._show_other()

    def _show_other(self) -> None:
        metres = self._metres(self.spin.value(), self.unit)
        if self.unit == "L":
            self.other.setText(f"= {metres:.4g} m" if metres is not None else "")
        elif self.reference is not None:
            self.other.setText(f"= {metres / self.reference:.4g} L (fixed in {self.unit} when L changes)")
        else:
            self.other.setText("")

    def _finished(self) -> None:
        self._value = self.spin.value()
        self.editingFinished.emit()

    def value(self) -> float:
        """In ``unit``."""
        return self._value

    def suffix(self) -> str:
        return f" {self.unit}"

    def text(self) -> str:
        return self.spin.text()

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self.spin.setToolTip(text)


class FloatingPanel(QWidget):
    """A panel detached from the main window into its own window (D-148): ``take`` moves a widget in, ``release``
    gives it back; closing the window calls ``on_close`` (the owner docks the panel back)."""

    def __init__(self, title: str, on_close, minimum_u: tuple[int, int] = (16, 8)) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self._minimum_u = minimum_u  # the window's minimum size in font heights (D-155)
        self._apply_minimum()
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

    def _apply_minimum(self) -> None:
        u = metrics().u
        self.setMinimumSize(self._minimum_u[0] * u, self._minimum_u[1] * u)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange):
            self._apply_minimum()  # follows the interface size

    def closeEvent(self, event) -> None:
        if self.content is not None:  # closed by the user: dock the panel back
            self._on_close()
        super().closeEvent(event)


class _OptionLabel(QLabel):
    """The wrapped text of a ChoiceField option; a click on it chooses the option."""

    def __init__(self, text: str, button: QRadioButton) -> None:
        super().__init__(text)
        self._button = button
        self.setWordWrap(True)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._button.isEnabled():
            self._button.setChecked(True)
        super().mousePressEvent(event)


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
        self.labels: dict[str, QLabel] = {}
        for value, label in pairs:
            # The option's text is a label beside its radio button, so a long option wraps in a narrow panel instead
            # of being cut (a radio button's own text cannot wrap; D-165); clicking the text chooses the option.
            button = QRadioButton()
            button.setAccessibleName(label)
            text = _OptionLabel(label, button)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            self.group.addButton(button)
            self.buttons[value] = button
            self.labels[value] = text
            box.addLayout(row)
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
        for b in (*self.buttons.values(), *self.labels.values()):
            b.setToolTip(text)

    def text_of(self, value) -> str:
        """The shown text of an option."""
        return self.labels[value].text()

    def setEnabled(self, on: bool) -> None:
        super().setEnabled(on)
