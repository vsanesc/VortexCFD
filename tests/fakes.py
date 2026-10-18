"""Fake dialogs for GUI tests: never opens a real modal dialog."""

from pathlib import Path


class FakeDialogs:
    def __init__(self, open_path=None, save_path=None, discard="discard", import_path=None,
                 units="m", paraview_path=None, csv_path=None, solids_mode="regions") -> None:
        self.csv_path = csv_path
        self.solids_mode = solids_mode
        self.solids_asked: list = []
        self.paraview_path = paraview_path
        self.import_path = import_path
        self.units = units
        self.open_path: Path | None = open_path
        self.save_path: Path | None = save_path
        self.discard = discard
        self.confirm_calls = 0

    def ask_open_path(self):
        return self.open_path

    def ask_save_path(self, suggested):
        return self.save_path

    def ask_csv_path(self, suggested):
        return self.csv_path

    def ask_import_path(self):
        return self.import_path

    def ask_units(self):
        return self.units

    def ask_solids_mode(self, file_name, solids):
        self.solids_asked.append((file_name, list(solids)))
        return self.solids_mode

    def confirm_discard(self):
        self.confirm_calls += 1
        return self.discard

    def ask_paraview_path(self, current, detected):
        return self.paraview_path
