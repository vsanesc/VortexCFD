"""The simulation tree's context menus and keyboard actions (D-145), mixed into MainWindow.

Every node has a right-click menu with the actions that apply to it (``tree_menu_for``); Delete removes the
selected item after a confirmation, F2 renames it (the name field of its properties), a double-click opens its
properties. The imported refinement regions (a surface file, or a part marked "Use as refinement region") are
added here too.
"""

import logging
import os
import shutil
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QTreeWidgetItem

from vortexcfd.core.model import VOLUME_SHAPES as _SHAPES
from vortexcfd.foam.mesh_case import CaseDirectoryNotOursError, clear_mesh
from vortexcfd.geometry.cad import BREP_EXTENSIONS, CAD_EXTENSIONS, CadImportError, read_cad
from vortexcfd.geometry.loader import SurfaceLoadError
from vortexcfd.gui.properties_panel import face_type, face_type_options
from vortexcfd.workflow import part_ops, refinement
from vortexcfd.workflow.meshing import case_dir_for

log = logging.getLogger(__name__)

# Node kinds whose item can be deleted, and those with a name field (F2).
DELETABLE = ("part", "refinement_volume", "scene_object", "saved_view")
RENAMABLE = ("root", "part", "refinement_volume", "scene_object")
REGION_FROM_FILE = "Add from imported geometry…"
USE_AS_REGION_TIP = ("The part's surface becomes a refinement volume: the cells inside it (a closed surface) or within "
                     "a distance of it (an open one) are refined to a target size; it is no longer meshed as a wall "
                     "(undoable)")
REGION_MODE_LOG = {"inside": "inside", "distance": "within a distance: the surface is open"}


class TreeActionsMixin:
    """Context menus, Delete / F2 / double-click and the actions they call (MainWindow only)."""

    # -- menus -----------------------------------------------------------------------------------

    def tree_menu_for(self, key) -> QMenu | None:
        """The right-click menu of the tree node ``key`` = (kind, index), or None (no project)."""
        if not self.has_project or key not in self._items:
            return None
        kind, index = key
        menu = QMenu(self.tree)
        menu.setToolTipsVisible(True)

        def add(text: str, slot, enabled: bool = True, tip: str = "") -> QAction:
            act = menu.addAction(text, slot)
            act.setEnabled(enabled)
            act.setToolTip(tip)
            return act

        props = lambda: self.open_properties(key)  # noqa: E731
        sim = self._project.sim
        if kind in ("geometry", "parts"):
            menu.addAction(self.act_import)
            menu.addAction(self.act_import_airfoil)
            menu.addSeparator()
            add("Show all", self.show_all_parts, bool(sim.geometry.parts))
            add("Hide all", self.hide_all_parts, bool(sim.geometry.parts))
            menu.addSeparator()
            menu.addAction(self.act_prepare_surfaces)
        elif kind == "part" and index is not None and index < len(sim.geometry.parts):
            part = sim.geometry.parts[index]
            visible = self.part_visibility.get(part.name, True)
            add("Hide" if visible else "Show", lambda: self.toggle_part_visibility(index))
            add("Isolate", lambda: self.isolate_part(index), tip="Show only this part")
            menu.addSeparator()
            add("Rename", self.rename_selected)
            add("Delete", self.delete_selected)
            menu.addSeparator()
            add("Use as refinement region", lambda: self.use_part_as_region(index), bool(part.source_file),
                USE_AS_REGION_TIP)
            menu.addAction(self.act_repair_part)
            menu.addSeparator()
            add("Properties", props)
        elif kind == "surface_prep":
            menu.addAction(self.act_prepare_surfaces)
            add("Remove preparation", self.remove_surface_prep, sim.surface_prep is not None)
            menu.addSeparator()
            add("Properties", props)
        elif kind == "mesh":
            add("Generate mesh", self.generate_mesh, self.top_bar.mesh_button.isEnabled(),
                self.top_bar.mesh_button.toolTip())
            add("Clear mesh", self.clear_mesh, self.mesh_report is not None and not self.mesh_worker.is_running())
            add("Mesh report", self.show_mesh_report, self.mesh_report is not None)
            menu.addSeparator()
            self._add_volume_items(menu)
            menu.addSeparator()
            add("Properties", props)
        elif kind == "refinement_volumes":
            self._add_volume_items(menu)
        elif kind == "refinement_volume":
            vid = self._selected_volume_id() if self._selection == key else self._volume_id_at(index)
            enabled = vid is not None and self._project.volume(vid).enabled
            add("Disable" if enabled else "Enable", self.toggle_selected_volume)
            add("Rename", self.rename_selected)
            add("Duplicate", self.duplicate_selected_volume)
            add("Delete", self.delete_selected)
            menu.addSeparator()
            add("Properties", props)
        elif kind in ("fluid_domain", "generate_domain"):
            menu.addAction(self.act_generate_domain)
            add("Edit", props, kind == "fluid_domain" and sim.domain.enabled, "The domain's shape and sizes")
        elif kind.startswith("boundary_"):
            self._add_boundary_items(menu, kind.removeprefix("boundary_"))
            menu.addSeparator()
            add("Properties", props)
        elif kind in ("results", "scene_object", "saved_view"):
            self._add_results_items(menu, kind, index)
        elif kind == "mesh_study":
            add("Run mesh independence study", lambda: self.properties.study_run_requested.emit("mesh"))
            add("Properties", props)
        elif kind == "polar_sweep":
            on = sim.studies.polar.enabled
            if on:
                add("Run polar sweep", lambda: self.properties.study_run_requested.emit("polar"))
            add("Disable polar sweep" if on else "Enable polar sweep",
                lambda: self._run_edit(lambda: self._project.update_study("polar", enabled=not on)))
            add("Properties", props)
        elif kind == "root":
            menu.addAction(self.act_save)
            add("Rename", self.rename_selected)
            add("Properties", props)
        else:
            add("Properties", props)
        return menu

    def _add_volume_items(self, menu: QMenu) -> None:
        shapes = menu.addMenu("Add refinement volume")
        for shape in _SHAPES:
            shapes.addAction(shape.capitalize(), lambda s=shape: self.add_refinement_volume(s))
        act = menu.addAction(REGION_FROM_FILE, self.add_region_from_file)
        act.setToolTip("A closed surface (STL, OBJ, PLY, STEP, IGES, BREP) as a refinement region: inside it, or "
                       "within a distance of it; it is not meshed as a wall")
        menu.addAction(self.act_add_wake)

    def _add_boundary_items(self, menu: QMenu, role: str) -> None:
        """The boundary type of a domain face (D-147): every kind, the ground plane on the box's bottom face."""
        sim = self._project.sim
        options = face_type_options(sim, role)
        sub = menu.addMenu("Boundary type")
        current = face_type(sim, role)
        if not options:
            act = sub.addAction("Symmetry plane (Fluid Domain > Symmetry)")
            act.setEnabled(False)
            return
        for value, label in options:
            act = sub.addAction(label, lambda v=value: self.set_boundary_type(role, v))
            act.setCheckable(True)
            act.setChecked(value == current)

    def set_boundary_type(self, face: str, value: str) -> None:
        """A domain face's boundary type from the tree's menu (one undo step), the face's node selected after."""
        if value == face_type(self._project.sim, face):
            return
        self._flush_edits()
        self._run_edit(lambda: self._project.set_face_type(face, value))
        target = "ground" if value == "ground" else ("bottom" if face == "ground" else face)
        self._select_node(f"boundary_{target}", None)

    def _add_results_items(self, menu: QMenu, kind: str, index) -> None:
        from vortexcfd.core.model import SCENE_OBJECT_KINDS, SCENE_OBJECT_LABELS

        if kind == "scene_object" and index is not None and index < len(self._project.sim.results.objects):
            obj = self._project.sim.results.objects[index]
            menu.addAction("Hide" if obj.visible else "Show",
                           lambda: self._run_edit(lambda: self._project.update_scene_object(
                               obj.id, visible=not obj.visible)))
            menu.addAction("Rename", self.rename_selected)
            menu.addAction("Delete", self.delete_selected)
            menu.addSeparator()
            menu.addAction("Properties", lambda: self.open_properties(("scene_object", index)))
            return
        if kind == "saved_view" and index is not None and index < len(self._project.sim.results.views):
            view = self._project.sim.results.views[index]
            menu.addAction("Apply view", lambda: self._on_scene_action(f"go_view:{view.name}"))
            menu.addAction("Delete", self.delete_selected)
            return
        add = menu.addMenu("Add results object")
        for k in SCENE_OBJECT_KINDS:
            add.addAction(SCENE_OBJECT_LABELS[k], lambda kk=k: self._on_scene_action(f"add:{kk}"))
        menu.addAction("Save current view", lambda: self._on_scene_action("save_view"))
        menu.addSeparator()
        menu.addAction(self.act_export_image)
        menu.addAction(self.act_create_report)
        if hasattr(self, "act_paraview"):
            menu.addAction(self.act_paraview)

    def _tree_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None or not self.has_project:
            return
        key = tuple(item.data(0, self._role_node()))
        self.tree.setCurrentItem(item)
        menu = self.tree_menu_for(key)
        if menu is not None:
            menu.popup(self.tree.viewport().mapToGlobal(position))

    @staticmethod
    def _role_node():
        from vortexcfd.gui.main_window import ROLE_NODE

        return ROLE_NODE

    def _volume_id_at(self, index) -> str | None:
        volumes = self._project.sim.refinement_volumes
        return volumes[index].id if index is not None and 0 <= index < len(volumes) else None

    # -- keyboard and double-click ---------------------------------------------------------------

    def open_properties(self, key=None) -> None:
        """Select the node (if given) and bring its properties forward (the panel shown, focused)."""
        if key is not None and key in self._items:
            self.tree.setCurrentItem(self._items[key])
        dock = getattr(self, "properties_dock", None)
        if dock is not None and not dock.isVisible():
            dock.show()
        self.properties.setFocus()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        kind, index = item.data(0, self._role_node())
        if kind == "generate_domain":
            return  # the item's own activation runs the operation
        self.open_properties((kind, index))

    def rename_selected(self) -> None:
        """F2: focus and select the name field of the selected node's properties."""
        kind, index = self._selection or ("root", None)
        if kind not in RENAMABLE:
            return
        self.open_properties()
        field = {"refinement_volume": "vol_name", "scene_object": "sc_name"}.get(kind, "name_edit")
        edit = getattr(self.properties, field)
        edit.setFocus()
        edit.selectAll()

    def delete_selected(self) -> None:
        """Delete: remove the selected part, refinement volume, results object or saved view after a
        confirmation (one undo step)."""
        kind, index = self._selection or ("root", None)
        if kind not in DELETABLE or index is None:
            return
        self._flush_edits()
        sim = self._project.sim
        if kind == "part":
            name = sim.geometry.parts[index].name
            if self.dialogs.confirm("Delete part", f"Delete the part '{name}'? (Undo restores it.)"):
                self._run_edit(lambda: self._project.remove_part(index))
        elif kind == "refinement_volume":
            name = sim.refinement_volumes[index].name
            if self.dialogs.confirm("Delete refinement volume", f"Delete the refinement volume '{name}'?"):
                self.delete_selected_volume()
        elif kind == "scene_object":
            obj = sim.results.objects[index]
            if self.dialogs.confirm("Delete results object", f"Delete '{obj.name}'?"):
                self._selection = ("results", None)
                self._run_edit(lambda: self._project.remove_scene_object(obj.id))
        elif kind == "saved_view":
            view = sim.results.views[index]
            if self.dialogs.confirm("Delete view", f"Delete the saved view '{view.name}'?"):
                self._selection = ("results", None)
                self._run_edit(lambda: self._project.remove_view(view.name))

    # -- parts -----------------------------------------------------------------------------------

    def _set_parts_visible(self, visible_of) -> None:
        for i, part in enumerate(self._project.sim.geometry.parts):
            self.part_visibility[part.name] = bool(visible_of(i))
            item = self._items.get(("part", i))
            if item is not None:
                item.setData(0, self._role_eye(), self.part_visibility[part.name])
        self.tree.viewport().update()
        self._sync_scene()

    @staticmethod
    def _role_eye():
        from vortexcfd.gui.main_window import ROLE_EYE

        return ROLE_EYE

    def show_all_parts(self) -> None:
        self._set_parts_visible(lambda i: True)

    def hide_all_parts(self) -> None:
        self._set_parts_visible(lambda i: False)

    def toggle_part_visibility(self, index: int) -> None:
        name = self._project.sim.geometry.parts[index].name
        shown = self.part_visibility.get(name, True)
        self._set_parts_visible(lambda i: (not shown) if i == index
                                else self.part_visibility.get(self._project.sim.geometry.parts[i].name, True))

    def isolate_part(self, index: int) -> None:
        self._set_parts_visible(lambda i: i == index)

    def use_part_as_region(self, index: int) -> None:
        """Part > Use as refinement region (D-145): the part's surface becomes a refinement volume (inside mode,
        target the part surface cell size) and is no longer a wall; one undo step."""
        self._flush_edits()
        part = self._project.sim.geometry.parts[index]
        try:  # a closed part refines inside itself, an open one within a distance of itself (D-159)
            mode = refinement.region_mode(self._project.folder / part.source_file, part.units)
        except refinement.RegionFileError as exc:
            self.show_message(f"'{part.name}' cannot be a refinement region: {exc}", "error")
            return
        target = self._region_target_size()
        if target is None:
            return
        added: list[str] = []
        distance = target if mode == "distance" else 0.0
        self._run_edit(lambda: added.append(self._project.part_to_refinement_region(index, target, mode, distance)))
        if added:
            self._select_volume(added[0])
            log.info("Part '%s' is now the refinement region '%s' (%s, target %.4g m)", part.name,
                     self._project.volume(added[0]).name, REGION_MODE_LOG[mode], target)

    def _region_target_size(self) -> float | None:
        """The default target cell size of a new imported region: the part surface cell size (needs the domain)."""
        context = self._volume_context()
        if context is None:
            return None
        _box, est, _bounds = context
        return est.surface_size

    # -- imported refinement regions -------------------------------------------------------------

    def add_region_from_file(self) -> None:
        """Refinement volumes > Add from imported geometry (D-145): a closed surface file copied into
        <project>/geometry/ (a CAD file tessellated on the geometry worker) as an inside-mode refinement volume."""
        self._flush_edits()
        if self._volume_context() is None or self._import_folder() is None:
            return
        source = self.dialogs.ask_import_path()
        if source is None:
            return
        cad = source.suffix.lower() in CAD_EXTENSIONS
        units = None
        if not cad or source.suffix.lower() in BREP_EXTENSIONS:
            units = self.dialogs.ask_units()
            if units is None:
                return
        project_dir = self._project.folder
        try:
            (project_dir / "geometry").mkdir(exist_ok=True)
            dest = self._unique_path(project_dir / "geometry", source.name)
            shutil.copy2(source, dest)
        except OSError as exc:
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        if not cad:
            self._add_region(source, Path(os.path.relpath(dest, project_dir)).as_posix(), units, [dest])
            return
        taken = {p.name for p in self._project.sim.geometry.parts}

        def tessellate():
            return part_ops.cad_parts(project_dir, dest, units, "regions", taken, model=read_cad(dest))

        def done(parts) -> None:
            surface = parts[0]
            extra = [project_dir / surface.source_file]
            if surface.region_ids:
                extra.append(project_dir / surface.region_ids)
            self._add_region(source, surface.source_file, surface.units, [dest, *extra])

        def failed(exc) -> None:
            dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")

        self._start_geometry_job(f"Tessellating {source.name}", tessellate, done, failed)

    def _add_region(self, source: Path, relative: str, units: str, written: list[Path]) -> None:
        context = self._volume_context()
        try:
            if context is None:
                raise refinement.RegionFileError("the domain is not ready")
            _box, est, _bounds = context
            volume = refinement.surface_volume(self._project, relative, units, est, name=source.stem)
        except (refinement.RegionFileError, SurfaceLoadError, CadImportError, ValueError) as exc:
            for path in written:
                path.unlink(missing_ok=True)
            self.show_message(f"Could not use {source.name} as a refinement region: {exc}", "error")
            return
        self._add_volume(volume, f"Add refinement region '{volume.name}' from {source.name}")
        log.info("Imported %s as the refinement region '%s' (%s, target %.4g m)", source.name, volume.name,
                 REGION_MODE_LOG[volume.shape.mode], volume.target_size)

    # -- Show in OpenFOAM file (D-150) ----------------------------------------------------------

    def show_in_openfoam_file(self, key: str):
        """The case file a property is written to, at its entry (a preview when the case has none yet); returns
        the entries shown (empty with a message when the value is not written or the case cannot be built)."""
        from vortexcfd.workflow import foam_entries
        from vortexcfd.workflow.meshing import MeshingNotReady

        self._flush_edits()
        if not self.has_project or self._project.path is None:
            self.show_message("Save the project first: the case is written next to it.", "warning")
            return []
        try:
            entries = foam_entries.entries_for(self._project, key)
        except (MeshingNotReady, ValueError, OSError) as exc:
            self.show_message(f"The case files cannot be written yet: {exc}", "warning")
            return []
        if not entries:
            self.show_message("This value is not written to a case file with the current settings (it is used by "
                              "the app's own sizing or by another shape or mode).", "warning")
            return []
        files = {}
        for entry in entries:
            files[entry] = foam_entries.case_file(self._project, entry)
        self.dialogs.show_foam_file(key, entries, files)
        return entries

    # -- mesh ------------------------------------------------------------------------------------

    def clear_mesh(self) -> None:
        """Mesh > Clear mesh: delete the generated mesh (constant/polyMesh, the mesh record) and the solver results
        of the project's case, after a confirmation. The meshing dictionaries stay."""
        if self.mesh_worker.is_running() or self.solver_worker.is_running():
            self.show_message("Stop the running mesh or solver first.", "warning")
            return
        case = case_dir_for(self._project)
        if case is None or not self.dialogs.confirm(
                "Clear mesh", "Delete the mesh and the solver results of this project? The settings are kept."):
            return
        try:
            removed = clear_mesh(case)
        except (OSError, CaseDirectoryNotOursError) as exc:
            self.show_message(f"Could not clear the mesh: {exc}", "error")
            return
        log.info("Cleared the mesh: %s", ", ".join(removed) or "nothing to remove")
        self.mesh_report = None
        self._mesh_hash = None
        self.properties.set_mesh_report(None)
        if self.mesh_view is not None:
            self.mesh_view.clear()
        self.run_record = None
        self.properties.set_run_record(None)
        self.monitors.clear()
        self._update_mesh_stale()
        self._update_results_stale(force=True)
        self._update_results_tab()
        self._set_scene_mode("geometry")
        self.show_message("Mesh cleared", "success", log_it=False)

    def show_mesh_report(self) -> None:
        """Mesh > Mesh report: the last checkMesh summary and layer coverage as text."""
        report = self.mesh_report
        if report is None:
            return
        lines = [report.summary()]
        lines += [f"hard failure: {line}" for line in report.hard_failures]
        lines += [f"warning: {line}" for line in report.soft_warnings]
        if report.extruded_percent is not None:
            lines.append(f"Surface faces with layers: {report.extruded_percent:g} %")
        lines += [f"Layers {cov.patch}: {cov.description()}" for cov in report.layers]
        if report.first_cell is not None:
            lines.append(f"First cell at the wall: {report.first_cell.description()}")
        if report.lost_parts:
            lines += report.lost_messages()
        self.dialogs.show_text("Mesh report", "\n".join(lines))
