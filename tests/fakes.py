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
        self.duplicate_sizes: list = []
        self.export_spec = None  # ask_export_image's answer (an ExportSpec or None)
        self.export_asked: list = []
        self.line_export_path = None  # ask_line_export's answer (a Path or None)
        self.line_export_asked: list = []
        self.chart_export_path = None  # ask_chart_export's answer (a Path or None)
        self.choices: list = []  # choose's answers in order (a choice key, or None: cancelled)
        self.choices_asked: list = []  # (title, text, the choice keys)
        self.more_iterations = None  # ask_more_iterations' answer
        self.more_iterations_asked: list = []
        self.continue_met = None  # ask_continue_met's answer: (more iterations, {index: value}) or None
        self.continue_met_asked: list = []
        self.chart_export_asked: list = []
        self.report_omit = None  # ask_report_sections' answer; None keeps the project's choice
        self.report_sections_asked: list = []
        self.openfoam_answer = None  # show_openfoam's answer: (check, bashrc to remember) or None
        self.openfoam_shown: list = []
        self.confirm_answer = True  # confirm's answer
        self.snapshot_name = None  # ask_snapshot_name's answer
        self.snapshot_names_asked: list = []
        self.foam_files: list = []  # show_foam_file calls: (title, entries, files)
        self.confirmed: list = []
        self.texts: list = []  # show_text calls: (title, text)

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

    def ask_snapshot_name(self, suggested):
        self.snapshot_names_asked.append(suggested)
        return self.snapshot_name

    def show_foam_file(self, title, entries, files):
        self.foam_files.append((title, list(entries), dict(files)))

    def confirm(self, title, text):
        self.confirmed.append((title, text))
        return self.confirm_answer

    def show_text(self, title, text):
        self.texts.append((title, text))

    def show_warning(self, title, text):
        self.warnings.append((title, text))

    def ask_export_image(self, suggested):
        self.export_asked.append(suggested)
        return self.export_spec

    def ask_csv_path(self, suggested):
        return self.csv_path

    def ask_line_export(self, suggested, kind):
        self.line_export_asked.append((suggested, kind))
        return self.line_export_path

    def choose(self, title, text, choices, default=None):
        self.choices_asked.append((title, text, [key for key, _label in choices]))
        return self.choices.pop(0) if self.choices else None

    def ask_more_iterations(self, latest, limit):
        self.more_iterations_asked.append((latest, limit))
        return self.more_iterations

    def ask_continue_met(self, latest, limit, stopping, met_iteration):
        self.continue_met_asked.append((latest, limit, stopping.model_copy(deep=True), met_iteration))
        return self.continue_met

    def ask_chart_export(self, suggested, kind):
        self.chart_export_asked.append((suggested, kind))
        return self.chart_export_path

    def ask_report_sections(self, omit):
        self.report_sections_asked.append(list(omit))
        return list(omit) if self.report_omit is None else list(self.report_omit)

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

    def show_openfoam(self, check):
        self.openfoam_shown.append(check)
        return self.openfoam_answer

    def ask_surface_prep(self, strategies, default):
        self.surface_prep_asked.append((list(strategies), default))
        return self.surface_prep_strategy

    def ask_generate_domain(self, part_names, checked, domain):
        self.domain_asked.append((list(part_names), list(checked)))
        return self.domain_fields

    def ask_duplicate(self, current_name, current_parent, copy_size=None):
        self.duplicate_asked.append((current_name, current_parent))
        self.duplicate_sizes.append(copy_size)  # the size the dialog shows (D-174)
        return self.duplicate_target
