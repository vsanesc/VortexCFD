"""Fake dialogs for GUI tests: never opens a real modal dialog."""

from pathlib import Path


class FakeDialogs:
    def __init__(self, open_path=None, save_path=None, discard="discard") -> None:
        self.open_path: Path | None = open_path
        self.save_path: Path | None = save_path
        self.discard = discard
        self.confirm_calls = 0

    def ask_open_path(self):
        return self.open_path

    def ask_save_path(self, suggested):
        return self.save_path

    def confirm_discard(self):
        self.confirm_calls += 1
        return self.discard
