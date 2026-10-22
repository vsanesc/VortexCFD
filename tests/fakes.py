"""Fake dialogs for GUI tests: never opens a real modal dialog."""

from pathlib import Path


class FakeDialogs:
    def __init__(self, open_path=None, save_path=None, discard="discard", import_path=None,
                 units="m", paraview_path=None, csv_path=None, solids_mode="regions") -> None:
        self.csv_path = csv_path
        self.surface_prep_strategy = None  # ask_surface_prep's answer
        self.surface_prep_asked: list = []
        self.solids_mode = solids_mode
        self.solids_asked: list = []
        self.repair_reports: list = []
        self.overwrite = True  # confirm_overwrite's answer
        self.overwrite_asked: list = []
        self.errors: list = []
        self.warnings: list = []
        self.save_asked: list = []
        self.paraview_path = paraview_path
        self.import_path = import_path
        self.units = units
        self.open_path: Path | None = open_path
        self.save_path: Path | None = save_path
        self.discard = discard
        self.confirm_calls = 0
        self.start_choice = None  # ask_start's answer
        self.start_asked = 0
        self.airfoil = None  # ask_airfoil's answer: (path, scale, closure) or None
        self.new_simulation = None  # ask_new_simulation's answer (a NewSimulationSpec or None)
        self.new_asked = 0
        self.preset_name = None
        self.preset_overwrite = True
        self.preset_overwrite_asked: list = []
        self.presets_managed = 0
        self.about_shown = 0
        self.domain_fields = None  # ask_generate_domain's answer (a dict of Domain fields or None)
        self.domain_asked: list = []
        self.duplicate_target = None  # ask_duplicate's answer: (name, parent folder) or None
        self.duplicate_asked: list = []

    def ask_open_path(self):
        return self.open_path

    def ask_save_path(self, suggested):
        self.save_asked.append(suggested)
        return self.save_path

    def confirm_overwrite(self, path):
        self.overwrite_asked.append(path)
        return self.overwrite

    def show_error(self, title, text):
        self.errors.append((title, text))

    def show_warning(self, title, text):
        self.warnings.append((title, text))

    def ask_csv_path(self, suggested):
        return self.csv_path

    def ask_airfoil(self):
        return self.airfoil

    def ask_import_path(self):
        return self.import_path

    def ask_units(self):
        return self.units

    def ask_solids_mode(self, file_name, solids):
        self.solids_asked.append((file_name, list(solids)))
        return self.solids_mode

    def show_repair_report(self, part, method, rows, notes):
        self.repair_reports.append((part, method, rows, notes))

    def confirm_discard(self):
        self.confirm_calls += 1
        return self.discard

    def ask_paraview_path(self, current, detected):
        return self.paraview_path

    def ask_start(self, recent):
        self.start_asked += 1
        return self.start_choice

    def ask_new_simulation(self, store):
        self.new_asked += 1
        return self.new_simulation

    def ask_preset_name(self, suggested):
        return self.preset_name

    def confirm_overwrite_preset(self, name):
        self.preset_overwrite_asked.append(name)
        return self.preset_overwrite

    def manage_presets(self, store):
        self.presets_managed += 1

    def show_about(self):
        self.about_shown += 1

    def ask_surface_prep(self, strategies, default):
        self.surface_prep_asked.append((list(strategies), default))
        return self.surface_prep_strategy

    def ask_generate_domain(self, part_names, checked, domain):
        self.domain_asked.append((list(part_names), list(checked)))
        return self.domain_fields

    def ask_duplicate(self, current_name, current_parent):
        self.duplicate_asked.append((current_name, current_parent))
        return self.duplicate_target
