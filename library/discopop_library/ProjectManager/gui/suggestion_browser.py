# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import (
    heading_label,
    caption_label,
    apply_diff_highlighting,
    create_code_view,
    icon_button,
)


def _get_patch_display_name(patch_path: str) -> str:
    """Extract the source filename from a patch's --- header line."""
    try:
        with open(patch_path, "r") as f:
            for line in f:
                if line.startswith("---"):
                    parts = line[4:].split("\t")
                    name = os.path.basename(parts[0].strip())
                    if name:
                        return name
    except IOError:
        pass
    return os.path.basename(patch_path)


class SuggestionBrowserDialog:
    """Read/edit view of the generated patches (no selection -- see SuggestionSelector)."""

    def __init__(
        self,
        parent: Any,
        dot_dp_path: str,
    ) -> None:
        self.parent = parent
        self.dot_dp_path = dot_dp_path

        self._patches: Dict[str, List[str]] = {}
        self._patch_display_names: Dict[Tuple[str, str], str] = {}

        self._expanded: Dict[str, bool] = {}
        self._expand_buttons: Dict[str, ttk.Button] = {}
        self._child_frames: Dict[str, ttk.Frame] = {}
        self._row_frames: Dict[str, ttk.Frame] = {}

        self._current_patch_path: Optional[str] = None
        self._current_text_modified = False
        self._text_content_on_load = ""
        self._resetting_modified = False

        self._load_patches()
        self._build_dialog()

    # ── patch discovery ──────────────────────────────────────────────────────

    def _load_patches(self) -> None:
        patch_gen_dir = os.path.join(self.dot_dp_path, "patch_generator")
        if not os.path.isdir(patch_gen_dir):
            return
        for suggestion_id in sorted(
            os.listdir(patch_gen_dir),
            key=lambda x: int(x) if x.isdigit() else x,
        ):
            sid_dir = os.path.join(patch_gen_dir, suggestion_id)
            if not os.path.isdir(sid_dir):
                continue
            patch_files = sorted(f for f in os.listdir(sid_dir) if f.endswith(".patch"))
            if patch_files:
                self._patches[suggestion_id] = patch_files
                for filename in patch_files:
                    patch_path = os.path.join(sid_dir, filename)
                    self._patch_display_names[(suggestion_id, filename)] = _get_patch_display_name(patch_path)

    # ── dialog construction ──────────────────────────────────────────────────

    def _build_dialog(self) -> None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Browse Parallelization Suggestions")
        self.dialog.geometry("1300x800")
        self.dialog.minsize(900, 500)

        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()
        w, h = 1300, 800
        self.dialog.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

        main_paned = tk.PanedWindow(self.dialog, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.Frame(main_paned)
        # stretch="always": window growth goes to the left (suggestions) panel first;
        # minsize=420 ensures buttons/checkboxes are never clipped
        main_paned.add(left_frame, minsize=420, stretch="always")

        right_frame = ttk.Frame(main_paned)
        # stretch="never": editor does not absorb window resize — left panel does
        main_paned.add(right_frame, minsize=300, stretch="never")

        self._build_left_panel(left_frame)
        self._build_right_panel(right_frame)

        # Place sash so left starts with more space than its minimum
        self.dialog.after(10, lambda: main_paned.sash_place(0, 500, 0))  # type: ignore[misc]

        self.dialog.transient(self.parent)
        self.dialog.grab_set()

    def _build_left_panel(self, parent: tk.Widget) -> None:
        heading_label(parent, f"Suggestions ({len(self._patches)})").pack(anchor=tk.W, padx=5, pady=(5, 2))

        list_outer = ttk.Frame(parent)
        list_outer.pack(fill=tk.BOTH, expand=True)

        self._list_canvas = tk.Canvas(list_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_outer, orient=tk.VERTICAL, command=self._list_canvas.yview)
        self._list_inner = ttk.Frame(self._list_canvas)

        self._list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._list_window = self._list_canvas.create_window((0, 0), window=self._list_inner, anchor="nw")

        def _on_inner_configure(event: Any) -> None:
            self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

        def _on_canvas_resize(event: Any) -> None:
            self._list_canvas.itemconfig(self._list_window, width=event.width)

        self._list_inner.bind("<Configure>", _on_inner_configure)
        self._list_canvas.bind("<Configure>", _on_canvas_resize)

        if not self._patches:
            caption_label(self._list_inner, "No suggestions found.").pack(anchor=tk.W, padx=10, pady=5)
        else:
            for sid in sorted(self._patches.keys(), key=lambda x: int(x) if x.isdigit() else x):
                self._expanded[sid] = True
                self._add_suggestion_row(self._list_inner, sid)

    def _add_suggestion_row(self, container: tk.Widget, sid: str) -> None:
        row = ttk.Frame(container)
        row.pack(fill=tk.X, padx=2, pady=1)
        self._row_frames[sid] = row

        expand_btn = icon_button(row, "▼", command=lambda s=sid: self._toggle_expand(s))  # type: ignore[misc]
        expand_btn.pack(side=tk.LEFT)
        self._expand_buttons[sid] = expand_btn

        name_label = ttk.Label(row, text=f"Suggestion {sid}", anchor=tk.W, cursor="hand2")
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        name_label.bind("<Button-1>", lambda e, s=sid: self._load_all_patches_in_editor(s))  # type: ignore[misc]

        children_frame = ttk.Frame(container)
        children_frame.pack(fill=tk.X)
        self._child_frames[sid] = children_frame

        for filename in self._patches[sid]:
            self._add_file_row(children_frame, sid, filename)

    def _add_file_row(self, container: tk.Widget, sid: str, filename: str) -> None:
        row = ttk.Frame(container)
        row.pack(fill=tk.X, padx=(28, 2), pady=1)

        display_name = self._patch_display_names.get((sid, filename), filename)
        name_label = ttk.Label(row, text=display_name, anchor=tk.W, foreground=widgets.LINK_FG, cursor="hand2")
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        patch_path = os.path.join(self.dot_dp_path, "patch_generator", sid, filename)
        name_label.bind("<Button-1>", lambda e, p=patch_path: self._load_patch_in_editor(p))  # type: ignore[misc]

    # ── expand / collapse ────────────────────────────────────────────────────

    def _toggle_expand(self, sid: str) -> None:
        self._expanded[sid] = not self._expanded[sid]
        if self._expanded[sid]:
            self._child_frames[sid].pack(fill=tk.X, after=self._row_frames[sid])
            self._expand_buttons[sid].config(text="▼")
        else:
            self._child_frames[sid].pack_forget()
            self._expand_buttons[sid].config(text="▶")

    # ── right panel / editor ─────────────────────────────────────────────────

    def _build_right_panel(self, parent: tk.Widget) -> None:
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        self.save_button = widgets.primary_button(
            header_frame, text="Save File", command=self._save_current_patch, state=tk.DISABLED, width=10
        )
        self.save_button.pack(side=tk.LEFT)

        editor_frame = ttk.Frame(parent)
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self.editor_text = create_code_view(editor_frame, wrap=tk.NONE)
        self.editor_text.bind("<<Modified>>", self._on_text_modified)

    def _load_all_patches_in_editor(self, sid: str) -> None:
        if self._current_text_modified and self._current_patch_path:
            from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no

            if ask_yes_no(self.dialog, "Unsaved Changes", "You have unsaved changes. Save before switching?"):
                self._save_current_patch()

        self._current_patch_path = None
        self._current_text_modified = False

        parts = []
        for filename in self._patches.get(sid, []):
            patch_path = os.path.join(self.dot_dp_path, "patch_generator", sid, filename)
            try:
                with open(patch_path, "r") as f:
                    parts.append(f.read())
            except IOError as e:
                parts.append(f"Error reading {filename}: {e}\n")

        content = "\n".join(parts)
        self._text_content_on_load = content

        self.editor_text.config(state=tk.NORMAL)
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", content)
        self._apply_diff_highlighting()
        self._resetting_modified = True
        self.editor_text.edit_modified(False)
        self._resetting_modified = False

        self.editor_text.config(state=tk.DISABLED)
        self.save_button.config(text="Save File", state=tk.DISABLED)

    def _load_patch_in_editor(self, patch_path: str) -> None:
        if self._current_text_modified and self._current_patch_path:
            from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no

            if ask_yes_no(self.dialog, "Unsaved Changes", "You have unsaved changes. Save before switching?"):
                self._save_current_patch()

        self._current_patch_path = patch_path
        self._current_text_modified = False

        try:
            with open(patch_path, "r") as f:
                content = f.read()
        except IOError as e:
            content = f"Error reading file: {e}"

        self._text_content_on_load = content

        self.editor_text.config(state=tk.NORMAL)
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", content)
        self._apply_diff_highlighting()
        self._resetting_modified = True
        self.editor_text.edit_modified(False)
        self._resetting_modified = False

        self.save_button.config(text="Save File", state=tk.NORMAL)

    def _apply_diff_highlighting(self) -> None:
        apply_diff_highlighting(self.editor_text)

    def _on_text_modified(self, event: Any) -> None:
        if self._resetting_modified:
            return
        self._resetting_modified = True
        self.editor_text.edit_modified(False)
        self._resetting_modified = False

        current = self.editor_text.get("1.0", "end-1c")
        if current != self._text_content_on_load:
            self._current_text_modified = True
            self.save_button.config(text="Save File *")
        else:
            self._current_text_modified = False
            self.save_button.config(text="Save File")

    def _save_current_patch(self) -> None:
        if not self._current_patch_path:
            return
        content = self.editor_text.get("1.0", "end-1c")
        try:
            with open(self._current_patch_path, "w") as f:
                f.write(content)
            self._text_content_on_load = content
            self._current_text_modified = False
            self._resetting_modified = True
            self.editor_text.edit_modified(False)
            self._resetting_modified = False
            self.save_button.config(text="Save File")
            self._apply_diff_highlighting()
        except IOError as e:
            from discopop_library.ProjectManager.gui.mixins.helpers import show_error

            show_error(self.dialog, "Save Error", f"Could not save file: {e}")

    def _on_close(self) -> None:
        if self._current_text_modified:
            from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no

            if ask_yes_no(self.dialog, "Unsaved Changes", "You have unsaved changes. Save before closing?"):
                self._save_current_patch()
        self.dialog.destroy()
