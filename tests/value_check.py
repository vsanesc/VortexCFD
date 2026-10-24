"""What the properties panel shows the user, for the readable-values test (D-166): the visible values of a node's rows
(combo boxes, fields, read-only values, choice options) and its numeric inputs with their units."""

import re
from dataclasses import dataclass

from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLabel, QLineEdit, QWidget

# snake_case (two lower-case words joined by "_") or camelCase (a lower-case word followed by an upper-case one)
SNAKE = re.compile(r"(?<![\w./\\-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w./\\(-])")
CAMEL = re.compile(r"(?<![\w./\\-])[a-z]+[A-Z][A-Za-z0-9]*(?![\w./\\(-])")


@dataclass
class Shown:
    node: str
    row: str  # the row's label (or the widget's tooltip head when it has no row)
    kind: str  # "combo", "field", "value", "option"
    text: str
    widget: QWidget


def _text(label) -> str:
    full = label.full_text  # the panel's elided labels: a method; the shared ElidedLabel: an attribute
    return full() if callable(full) else full


def _row_label(panel, widget: QWidget) -> str:
    """The label of the row ``widget`` sits in."""
    parent = widget
    while parent is not None and parent is not panel:
        for key, row in panel._rows.items():
            if row is parent:
                return _text(panel._row_labels[key])
        for row, title in panel._dynamic_titles():
            if row is parent:
                return _text(title)
        parent = parent.parentWidget()
    return ""


def shown_values(panel, node: str) -> list[Shown]:
    """Every value the node's rows show the user."""
    out: list[Shown] = []
    content = panel._content
    for widget in content.findChildren(QWidget):
        if not widget.isVisibleTo(content):
            continue
        row = _row_label(panel, widget)
        if isinstance(widget, QComboBox):
            out.append(Shown(node, row, "combo", widget.currentText(), widget))
            out += [Shown(node, row, "combo_item", widget.itemText(i), widget) for i in range(widget.count())]
        elif isinstance(widget, QLineEdit) and not isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
            out.append(Shown(node, row, "field", widget.text(), widget))
        elif isinstance(widget, QLabel) and widget.objectName() == "checkValue":
            out.append(Shown(node, row, "value", widget.text(), widget))
        elif type(widget).__name__ == "_OptionLabel":
            out.append(Shown(node, row, "option", widget.text(), widget))
    return out


def identifiers(text: str, allowed: set[str]) -> list[str]:
    """Words of ``text`` that look like internal identifiers (snake_case or camelCase), less the allowed ones."""
    words = SNAKE.findall(text) + CAMEL.findall(text)
    return [w for w in words if w not in allowed]


def numeric_inputs(panel) -> list[tuple[str, QWidget, str]]:
    """(row label, widget, unit) of every visible numeric input: spin boxes (their suffix) and the scientific
    fields (their unit label)."""
    content = panel._content
    out = []
    for widget in content.findChildren(QWidget):
        if not widget.isVisibleTo(content):
            continue
        if isinstance(widget, QAbstractSpinBox):
            owner = widget.parentWidget()
            unit = widget.suffix().strip()
            if not unit and hasattr(owner, "unit_button"):  # a domain extent: its unit is a button beside it
                unit = owner.unit_button.text()
            out.append((_row_label(panel, widget), widget, unit))
        elif type(widget).__name__ == "SciEdit":
            out.append((_row_label(panel, widget), widget, widget.unit()))
    return out
