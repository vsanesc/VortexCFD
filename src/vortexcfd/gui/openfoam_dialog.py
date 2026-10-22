"""The OpenFOAM installation dialog (D-137): shown at start-up when OpenFOAM v2606 is not found, and from
Help > OpenFOAM Installation. It lists what was looked for, shows the official ESI install commands as text (the app
never runs them) and takes the path of an etc/bashrc, checked before it is accepted."""

from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.foam.installation import INSTALL_COMMANDS, VERSION, OpenFOAMCheck, check_openfoam


def _mono(text: str, lines: int) -> QPlainTextEdit:
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    font = QFont("monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    box.setFont(font)
    box.setFixedHeight(box.fontMetrics().lineSpacing() * (lines + 1) + 12)
    return box


class OpenFOAMDialog(QDialog):
    """``check`` the result to show; ``result_check()`` the check of the path the user set (or the first one)."""

    def __init__(self, check: OpenFOAMCheck, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"OpenFOAM {VERSION}")
        self.setMinimumWidth(640)
        self._check = check
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Looked for:"))
        self.looked = _mono("", 4)
        layout.addWidget(self.looked)
        self.install_label = QLabel(
            f"To install OpenFOAM {VERSION} (ESI) on Ubuntu, run these commands in a terminal. They need sudo; "
            "VortexCFD never runs them:")
        self.install_label.setWordWrap(True)
        layout.addWidget(self.install_label)
        self.commands = _mono(INSTALL_COMMANDS, len(INSTALL_COMMANDS.splitlines()))
        layout.addWidget(self.commands)
        layout.addWidget(QLabel("Or give the etc/bashrc of an OpenFOAM v2606 installed elsewhere:"))
        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(check.bashrc) if check.bashrc else "")
        self.path_edit.setPlaceholderText("/path/to/openfoam2606/etc/bashrc")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.check_button = QPushButton("Check")
        self.check_button.clicked.connect(lambda: self.set_path(self.path_edit.text()))
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        row.addWidget(self.check_button)
        layout.addLayout(row)
        self.note = QLabel(
            "Without OpenFOAM the app opens projects and shows their meshes and results; meshing and solving stay "
            "disabled until it is found.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        self.use_button = buttons.addButton("Use this installation", QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        self._show(check)

    def _show(self, check: OpenFOAMCheck) -> None:
        self._check = check
        self.status.setText(f"OpenFOAM {VERSION} found: {check.bashrc}" if check.ok else (check.problem() or ""))
        self.looked.setPlainText("\n".join(f"{i.path} ({i.source}): {i.outcome}" for i in check.looked)
                                 + "".join(f"\n{p}: other version {v}" for p, v in check.others))
        self.use_button.setEnabled(check.ok)

    def _browse(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "OpenFOAM etc/bashrc", "/usr/lib/openfoam", "bashrc (bashrc);;All files (*)")
        if name:
            self.set_path(name)

    def set_path(self, text: str) -> OpenFOAMCheck:
        """Check the bashrc ``text`` (empty: the standard places again) and show the result."""
        text = text.strip()
        self.path_edit.setText(text)
        check = check_openfoam(Path(text)) if text else check_openfoam()
        self._show(check)
        return check

    def result_check(self) -> OpenFOAMCheck:
        return self._check

    def configured_path(self) -> Path | None:
        """The path to remember: the one typed when it is the bashrc found."""
        text = self.path_edit.text().strip()
        return Path(text) if text and self._check.ok and Path(text) == self._check.bashrc else None
