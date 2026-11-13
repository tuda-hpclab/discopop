# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The widgets of the stages that compile and run a configuration for its builds and runs.

:class:`BuildOptions` is what a run needs to know (when to compile, whether to run at all, build in place),
:class:`BuildsAndRuns` lists the builds and the profiling runs of the project, checks whether a build is still current
and deletes builds and runs on request: nothing is deleted automatically.
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import BuildPolicy, list_builds
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.services import build_overview
from discopop_library.ProjectManager.services.jobs import WorkEvent, WorkFinished, WorkRunner

POLICY_TEXTS = (
    (BuildPolicy.AUTO, "Compile if there is no current build"),
    (BuildPolicy.REBUILD, "Always compile"),
    (BuildPolicy.REUSE, "Never compile (use the existing build)"),
)
POLICY_HINT = (
    "A build is kept after it was compiled and serves further runs as long as the project files, the compile "
    "script, the settings and the project directories are unchanged."
)


class BuildOptions(widgets.FormSection):
    """When to compile, whether to run, and whether to build in the project directory (as before builds existed)."""

    def __init__(self, parent: Optional[QWidget] = None, *, offer_in_place: bool = True) -> None:
        super().__init__(parent=parent)
        self.policy_combo = QComboBox()
        for policy, text in POLICY_TEXTS:
            self.policy_combo.addItem(text, policy.value)
        self.build_only_check = QCheckBox("Only compile, do not run")
        self.in_place_check = QCheckBox("Compile and run in the project directory (no build is kept or reused)")
        self.add_row("Build:", self.policy_combo, POLICY_HINT)
        self.add_widget(self.build_only_check)
        if offer_in_place:
            self.add_widget(self.in_place_check)
        self.in_place_check.setVisible(offer_in_place)
        self.in_place_check.toggled.connect(self._in_place_changed)

    def _in_place_changed(self, checked: bool) -> None:
        # a build is neither kept nor reused in the project directory
        self.policy_combo.setEnabled(not checked)

    def build_policy(self) -> str:
        return str(self.policy_combo.currentData())

    def build_only(self) -> bool:
        return self.build_only_check.isChecked()

    def in_place(self) -> bool:
        return self.in_place_check.isChecked()


_BUILD_COLUMNS = ("Build", "Mode", "Suggestions", "Built", "Compile time", "Size", "State")
_RUN_COLUMNS = ("Run", "Build", "Mode", "Threads", "Started", "Result", "Size", "Active")


def _table(columns: tuple) -> QTableWidget:  # type: ignore[type-arg]
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(110)
    return table


class BuildsAndRuns(widgets.FormSection):
    """The builds and the profiling runs of the project, with the actions on them.

    ``changed`` is called after something was activated or deleted (the panels then refresh).
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        changed: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("Builds and runs", parent=parent)
        self.arguments = arguments
        self._changed = changed
        self._job: Optional[WorkRunner] = None
        self._blocked = False
        self.build_table = _table(_BUILD_COLUMNS)
        self.run_table = _table(_RUN_COLUMNS)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.check_button = widgets.create_button(
            "Check selected builds",
            self.check_selected_builds,
            tooltip="Compares the files of the project with the build; reads the whole project, which takes a while "
            "for a large one.",
        )
        self.delete_builds_button = widgets.danger_outline_button("Delete selected builds", self.delete_selected_builds)
        self.activate_button = widgets.create_button(
            "Use selected run for pattern detection",
            self.activate_selected_run,
            tooltip="Puts the data of the run into the .discopop directory of the project, where the pattern "
            "detection reads it.",
        )
        self.delete_runs_button = widgets.danger_outline_button("Delete selected runs", self.delete_selected_runs)
        self.refresh_button = widgets.create_button("Refresh", self.refresh)
        self.sizes_button = widgets.create_button(
            "Calculate sizes",
            lambda: self.refresh(with_sizes=True),
            tooltip="Adds up the files of every build and run, which takes a while for large ones.",
        )
        self.add_widget(
            QLabel(
                "Builds and runs are kept until you delete them. A build is a copy of the project that was compiled; "
                "runs are the profiling runs (dp, hd) that ran in a build, each with its own results."
            ),
        )
        self.add_widget(self.build_table)
        self.add_widget(widgets.hbox(self.check_button, self.delete_builds_button, None, margins=0))
        self.add_widget(self.run_table)
        self.add_widget(widgets.hbox(self.activate_button, self.delete_runs_button, None, margins=0))
        self.add_widget(widgets.hbox(self.refresh_button, self.sizes_button, None, margins=0))
        self.add_widget(self.note)
        self.refresh()

    # ── contents ────────────────────────────────────────────────────────────

    def refresh(self, with_sizes: bool = False) -> None:
        builds = build_overview.build_rows(self.arguments, with_sizes)
        self.build_table.setRowCount(len(builds))
        for row, build in enumerate(builds):
            values = [build.build_id, build.mode, build.suggestions, build.built, build.compile_time, build.size, ""]
            for column, value in enumerate(values):
                self.build_table.setItem(row, column, QTableWidgetItem(value))
        runs = build_overview.run_rows(self.arguments, with_sizes)
        self.run_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            values = [
                run.run_id,
                run.build_id,
                run.mode,
                str(run.threads),
                run.started,
                run.result,
                run.size,
                "yes" if run.active else "",
            ]
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(value))
        self._update_buttons()

    @staticmethod
    def _selected(table: QTableWidget) -> List[str]:
        rows = sorted({index.row() for index in table.selectedIndexes()})
        items = [table.item(row, 0) for row in rows]
        return [item.text() for item in items if item is not None]

    def selected_builds(self) -> List[str]:
        return self._selected(self.build_table)

    def selected_runs(self) -> List[str]:
        return self._selected(self.run_table)

    def _notify(self) -> None:
        if self._changed is not None:
            self._changed()

    # ── actions ─────────────────────────────────────────────────────────────

    def is_busy(self) -> bool:
        return self._job is not None

    def set_blocked(self, blocked: bool) -> None:
        """Another job (a profiling run, Execute) uses the builds and runs: nothing is changed meanwhile."""
        self._blocked = blocked
        self._update_buttons()

    def _update_buttons(self) -> None:
        free = not self._blocked and self._job is None
        has_builds = self.build_table.rowCount() > 0
        has_runs = self.run_table.rowCount() > 0
        self.check_button.setEnabled(free and has_builds)
        self.delete_builds_button.setEnabled(free and has_builds)
        self.activate_button.setEnabled(free and has_runs)
        self.delete_runs_button.setEnabled(free and has_runs)
        self.refresh_button.setEnabled(free)
        self.sizes_button.setEnabled(free)

    def _in_background(
        self, text: str, work: Callable[[], Any], finished: Callable[[Any, Optional[str]], None]
    ) -> None:
        """Run ``work`` on a worker thread (it reads or rewrites whole projects), then ``finished(result, error)``."""
        self.note.setText(text)

        def handle(event: WorkEvent) -> None:
            if isinstance(event, WorkFinished):
                self._job = None
                finished(event.result, None if event.error is None else str(event.error))
                self._update_buttons()

        self._job = start_work(self, lambda _ctx: work(), handle)
        self._update_buttons()

    def check_selected_builds(self) -> None:
        ids = self.selected_builds()
        if not ids:
            self.note.setText("Select the builds to check.")
            return
        records = [record for record in list_builds(self.arguments.project_dir) if record.build_id in ids]

        def work() -> Dict[str, str]:
            return {record.build_id: build_overview.build_state_of(self.arguments, record) for record in records}

        def finished(result: Any, error: Optional[str]) -> None:
            if error is not None:
                self.note.setText("Checking failed: " + error)
                return
            for row in range(self.build_table.rowCount()):
                item = self.build_table.item(row, 0)
                if item is not None and item.text() in result:
                    self.build_table.setItem(row, len(_BUILD_COLUMNS) - 1, QTableWidgetItem(result[item.text()]))
            self.note.setText("")

        self._in_background("Checking the builds (this reads the whole project)...", work, finished)

    def delete_selected_builds(self) -> None:
        ids = self.selected_builds()
        if not ids:
            self.note.setText("Select the builds to delete.")
            return
        if not dialogs.ask_yes_no(
            self,
            "Delete builds",
            "Delete the build trees of " + ", ".join(ids) + "?\n\nThe next run in these modes has to compile again. "
            "Their runs and your project are not touched.",
        ):
            return

        def finished(result: Any, error: Optional[str]) -> None:
            if error is not None:
                self.note.setText("Deleting failed: " + error)
            else:
                skipped = [build for build in ids if build not in result]
                self.note.setText(
                    "Deleted "
                    + (", ".join(result) or "nothing")
                    + "."
                    + (" Not deleted (in use or unknown): " + ", ".join(skipped) + "." if skipped else "")
                )
            self.refresh()
            self._notify()

        self._in_background("Deleting...", lambda: build_overview.delete_selected_builds(self.arguments, ids), finished)

    def delete_selected_runs(self) -> None:
        ids = self.selected_runs()
        if not ids:
            self.note.setText("Select the runs to delete.")
            return
        if not dialogs.ask_yes_no(
            self,
            "Delete runs",
            "Delete the results of the runs " + ", ".join(ids) + "?\n\nData that was put into the project (used for "
            "pattern detection) stays. A run that may still be running is not deleted.",
        ):
            return

        def finished(result: Any, error: Optional[str]) -> None:
            if error is not None:
                self.note.setText("Deleting failed: " + error)
            else:
                self.note.setText("Deleted " + (", ".join(result) or "nothing") + ".")
            self.refresh()
            self._notify()

        self._in_background("Deleting...", lambda: build_overview.delete_selected_runs(self.arguments, ids), finished)

    def activate_selected_run(self) -> None:
        ids = self.selected_runs()
        if len(ids) != 1:
            self.note.setText("Select one run.")
            return
        if not dialogs.ask_yes_no(
            self,
            "Use run for pattern detection",
            "Replace the profiling data of the project by the results of the run " + ids[0] + "?\n\nThe pattern "
            "detection results derived from the data that is there now are outdated afterwards.",
        ):
            return

        def finished(result: Any, error: Optional[str]) -> None:
            problem = error if error is not None else result
            if problem:
                dialogs.show_error(self, "Cannot use the run", str(problem))
                self.note.setText("")
                return
            self.note.setText("The run " + ids[0] + " is the data of the project now.")
            self.refresh()
            self._notify()

        self._in_background(
            "Putting the run into the project...", lambda: build_overview.activate(self.arguments, ids[0]), finished
        )
