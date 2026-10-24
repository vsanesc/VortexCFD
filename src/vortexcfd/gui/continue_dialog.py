"""Continue Solver after "Criteria met" (D-176): how many more iterations to run and, in the same dialog, the stopping
criteria's values (a residual's threshold, a tolerance) to tighten; the changes are saved in the project."""

import math

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from vortexcfd.core.model import StoppingCriteria
from vortexcfd.foam import convergence
from vortexcfd.gui.properties_panel import SciEdit
from vortexcfd.gui.widgets import set_invalid

TIGHTEN_TEXT = ("Tighten the stopping criteria (the changes are saved in the project). A criterion that is still "
                "met stops the run again as soon as it may: its window reaches back into the earlier iterations.")


class ContinueMetDialog(QDialog):
    def __init__(self, latest: int, limit: int, stopping: StoppingCriteria, met_iteration: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Continue solver")
        self._stopping = stopping
        layout = QVBoxLayout(self)
        at = f" at iteration {met_iteration:,}" if met_iteration is not None else ""
        intro = QLabel(f"The stopping criteria were met{at}. Continue the solution from iteration {latest:,}: run "
                       "how many more iterations? The iteration limit becomes the new total.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.more = QSpinBox()
        self.more.setRange(1, 10_000_000)
        self.more.setSingleStep(100)
        self.more.setSuffix(" it.")
        self.more.setValue(max(100, limit // 2))
        form.addRow("More iterations", self.more)
        layout.addLayout(form)
        self.values: dict[int, SciEdit] = {}
        if stopping.criteria:
            note = QLabel(TIGHTEN_TEXT)
            note.setWordWrap(True)
            layout.addWidget(note)
            criteria = QFormLayout()
            for i, criterion in enumerate(stopping.criteria):
                name = convergence.value_field(criterion)
                edit = SciEdit()
                edit.setValue(getattr(criterion, name))
                edit.setToolTip(convergence.describe(criterion))
                edit.textChanged.connect(self._check)
                criteria.addRow(f"{convergence.short_label(criterion)}: {name}", edit)
                self.values[i] = edit
            layout.addLayout(criteria)
        else:
            note = QLabel("The project has no stopping criteria: the run goes on to the new iteration limit.")
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Continue Solver")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _value(self, edit: SciEdit) -> float | None:
        try:
            value = edit.value()
        except ValueError:
            return None
        return value if math.isfinite(value) and value > 0 else None

    def _check(self) -> None:
        valid = True
        for i, edit in self.values.items():
            ok = self._value(edit) is not None
            set_invalid(edit, None if ok else "A positive number", convergence.describe(self._stopping.criteria[i]))
            valid = valid and ok
        self._ok.setEnabled(valid)

    def answer(self) -> tuple[int, dict[int, float]]:
        """(the more iterations, {criterion index: new value} for the values that changed)."""
        changed = {}
        for i, edit in self.values.items():
            value = self._value(edit)
            old = getattr(self._stopping.criteria[i], convergence.value_field(self._stopping.criteria[i]))
            if value is not None and not math.isclose(value, old, rel_tol=1e-9):
                changed[i] = value
        return self.more.value(), changed
