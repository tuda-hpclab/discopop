# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The "Ignored in build fingerprints" card of the Build stage: the project's patterns of
``services/fingerprint_ignore.py``, one per line."""

from typing import List, Optional

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import fingerprint_ignore
from discopop_library.ProjectManager.services.hotspot_session import forget_build_states
from discopop_library.ProjectManager.services.project_state import ProjectState, ResultsChanged

TITLE = "Ignored in build fingerprints"
HINT = (
    "Paths whose changes do not make a build stale, one pattern per line, relative to the project directory: "
    "dp_build/ (a directory), *.log (a file name anywhere), docs/*.md. For a build directory inside the project "
    "that git does not ignore. The files are still compiled. Applies to the "
    "existing builds as well, except those compiled by an older version (accept or compile them once)."
)


class FingerprintIgnoreSection(widgets.FormSection):
    """Edits ``.discopop/project/fingerprint_ignore.json``; Save stores the patterns and publishes ``ResultsChanged``
    (whether a build is current may have changed)."""

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(TITLE, parent)
        self.arguments = arguments
        self.project_state = project_state
        self.status = status
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setPlaceholderText("dp_build/")
        self.add_widget(widgets.resizable(self.editor, 90, minimum=40, fixed=True), HINT)
        self.save_button = widgets.create_button("Save", self.save)
        self.add_widget(widgets.hbox(self.save_button, None, margins=0))
        # "Show changes" adds patterns too; an edit not saved yet is kept
        project_state.subscribe(ResultsChanged, lambda _event: self.reload(keep_edits=True))
        self.reload()

    def patterns(self) -> List[str]:
        return [line for line in self.editor.toPlainText().splitlines() if line.strip()]

    def reload(self, keep_edits: bool = False) -> None:
        """Show the stored patterns (they may have been changed outside the card, e.g. by "Show changes"); with
        ``keep_edits``, not while the editor holds changes that were not saved."""
        if keep_edits and self.editor.document().isModified():
            return
        self.editor.setPlainText("\n".join(fingerprint_ignore.load_fingerprint_ignore(self.arguments.project_dir)))

    def save(self) -> None:
        entered = self.patterns()
        invalid = [pattern for pattern in entered if fingerprint_ignore.normalize(pattern) is None]
        if invalid:
            self.status.set(
                "Not saved: patterns must be relative to the project directory: " + ", ".join(invalid),
                widgets.STATUS_FAIL,
            )
            return
        try:
            stored = fingerprint_ignore.save_fingerprint_ignore(self.arguments.project_dir, entered)
        except OSError as error:
            self.status.set("Cannot save the ignore patterns: " + str(error), widgets.STATUS_FAIL)
            return
        self.editor.setPlainText("\n".join(stored))
        forget_build_states()
        self.status.set(
            "Ignored in build fingerprints: " + (", ".join(stored) or "nothing"), widgets.STATUS_OK, reset_ms=3000
        )
        self.project_state.publish(ResultsChanged())
