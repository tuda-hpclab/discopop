# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Reusable suggestion-ID selection widget.

A :class:`SuggestionSelector` is a compact, self-contained control for picking a
subset of the parallelization suggestions produced by the explorer. It shows
*only* the suggestion IDs (never the patch content -- use the suggestion browser
for that), a Select-all / Deselect-all toggle, and an entry that accepts a
comma-separated list of IDs and ID ranges (e.g. ``1,3,5-8``).

The same widget is embedded independently in several places (Execute tab manual
mode, Autotuning search-space / evaluate selectors). Each instance keeps its own
state, distinguished by a ``storage_key``; all instances persist into a single
``suggestion_selections.json`` under the project manager directory so choices
survive across sessions.

Persistence stores the set of *de-selected* IDs per key rather than the selected
set. That way "all selected" is the natural default and any newly detected
suggestion is selected automatically without needing to know the full ID
universe at save time.
"""

import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Set

from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import caption_label


def discover_suggestion_ids(dot_dp_path: str) -> List[str]:
    """Return the available suggestion IDs, sorted numerically.

    An ID is a subdirectory of ``<dot_dp>/patch_generator`` that contains at
    least one ``.patch`` file -- the same rule the suggestion browser uses.
    """
    patch_gen_dir = os.path.join(dot_dp_path, "patch_generator")
    ids: List[str] = []
    if not os.path.isdir(patch_gen_dir):
        return ids
    for sid in sorted(os.listdir(patch_gen_dir), key=lambda x: int(x) if x.isdigit() else x):
        sid_dir = os.path.join(patch_gen_dir, sid)
        if not os.path.isdir(sid_dir):
            continue
        if any(f.endswith(".patch") for f in os.listdir(sid_dir)):
            ids.append(sid)
    return ids


def parse_id_ranges(spec: str, available: List[str]) -> Set[str]:
    """Parse a ``1,3,5-8`` style spec into the set of matching available IDs.

    Tokens that don't resolve to an available ID (bad syntax, out of range) are
    silently ignored so a typo never raises. ``a-b`` with ``a > b`` is treated
    as the same range as ``b-a``.
    """
    available_set = set(available)
    result: Set[str] = set()
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        if "-" in token:
            lo_str, _, hi_str = token.partition("-")
            try:
                lo, hi = int(lo_str), int(hi_str)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            for value in range(lo, hi + 1):
                candidate = str(value)
                if candidate in available_set:
                    result.add(candidate)
        else:
            if token in available_set:
                result.add(token)
            else:
                # tolerate leading zeros / non-canonical integer spelling
                try:
                    canonical = str(int(token))
                except ValueError:
                    continue
                if canonical in available_set:
                    result.add(canonical)
    return result


class SuggestionSelector(ttk.Frame):
    """A checkbox list of suggestion IDs with select-all and range-entry helpers."""

    def __init__(
        self,
        parent: tk.Misc,
        dot_dp_path: str,
        storage_key: str,
        on_change: Optional[Callable[[], None]] = None,
        *,
        list_height: int = 130,
    ) -> None:
        super().__init__(parent)
        self._dot_dp_path = dot_dp_path
        self._storage_key = storage_key
        self._on_change = on_change
        self._list_height = list_height

        self._ids: List[str] = []
        self._vars: Dict[str, tk.BooleanVar] = {}
        self._enabled = True

        self._build_ui()
        self.refresh()

    # ── persistence ──────────────────────────────────────────────────────────

    def _selections_path(self) -> str:
        return os.path.join(self._dot_dp_path, "project", "manager", "suggestion_selections.json")

    def _load_all(self) -> Dict[str, Any]:
        path = self._selections_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _load_deselected(self) -> Set[str]:
        entry = self._load_all().get(self._storage_key, {})
        if isinstance(entry, dict):
            return set(str(s) for s in entry.get("deselected", []))
        return set()

    def _persist(self) -> None:
        deselected = sorted(
            (sid for sid, var in self._vars.items() if not var.get()),
            key=lambda x: int(x) if x.isdigit() else x,
        )
        data = self._load_all()
        data[self._storage_key] = {"deselected": deselected}
        path = self._selections_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError:
            pass

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, pady=(0, 3))

        # Row 1: "Select IDs:" label + entry + Apply button. Apply is packed
        # against the right edge *before* the entry so pack always reserves its
        # space; the entry takes (and shrinks into) whatever remains, keeping
        # Apply visible no matter how narrow the window gets.
        entry_row = ttk.Frame(controls)
        entry_row.pack(fill=tk.X)

        ttk.Label(entry_row, text="Select IDs:").pack(side=tk.LEFT)
        self._placeholder_text = "e.g. 1,3,5-8"
        self._entry_has_placeholder = False
        self._entry_var = tk.StringVar(value="")
        self._entry = ttk.Entry(entry_row, textvariable=self._entry_var, width=16)
        self._entry_default_fg = str(self._entry.cget("foreground")) or "black"
        widgets.create_button(entry_row, text="Apply", command=self._on_apply_entry, width=7).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self._entry.bind("<FocusIn>", self._on_entry_focus_in)
        self._entry.bind("<FocusOut>", self._on_entry_focus_out)
        self._entry.bind("<Return>", lambda _e: self._on_apply_entry())
        self._show_placeholder()

        # Row 2: the Select-all / Deselect-all toggle, below the entry row.
        self._toggle_button = widgets.create_button(
            controls, text="Deselect all", command=self._on_toggle_all, width=11
        )
        self._toggle_button.pack(anchor=tk.W, pady=(3, 0))

        list_outer = ttk.Frame(self)
        list_outer.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(list_outer, highlightthickness=0, height=self._list_height)
        scrollbar = ttk.Scrollbar(list_outer, orient=tk.VERTICAL, command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)

        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._list_window = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._list_window, width=e.width))

        # Wheel scrolling: bind directly to the canvas and its inner frame (each
        # checkbutton is bound in refresh()). Direct binding avoids the
        # <Enter>/<Leave> + bind_all pattern, which mis-fires here because moving
        # onto a child checkbutton generates a <Leave> on the canvas.
        self._bind_mousewheel(self._canvas)
        self._bind_mousewheel(self._inner)

        self._empty_label = caption_label(self._inner, "No suggestions available.")

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        """Route wheel events on ``widget`` to the list canvas (all platforms)."""
        widget.bind("<MouseWheel>", self._on_mousewheel)  # Windows / macOS
        widget.bind("<Button-4>", self._on_mousewheel)  # X11 scroll up
        widget.bind("<Button-5>", self._on_mousewheel)  # X11 scroll down

    def _on_mousewheel(self, event: Any) -> str:
        """Scroll the list, but only when the content overflows the viewport."""
        bbox = self._canvas.bbox("all")
        if bbox is None or (bbox[3] - bbox[1]) <= self._canvas.winfo_height():
            return "break"
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")
        return "break"

    # ── public API ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-scan available IDs and rebuild the checkbox list.

        The persisted de-selection is re-applied; IDs that are newly detected
        (not present in the stored de-selected set) default to selected.
        """
        deselected = self._load_deselected()
        self._ids = discover_suggestion_ids(self._dot_dp_path)

        for child in self._inner.winfo_children():
            child.destroy()
        self._vars = {}

        if not self._ids:
            self._empty_label = caption_label(self._inner, "No suggestions available.")
            self._empty_label.pack(anchor=tk.W, padx=4, pady=2)
            self._bind_mousewheel(self._empty_label)
            self._update_toggle_label()
            return

        for sid in self._ids:
            var = tk.BooleanVar(value=sid not in deselected)
            self._vars[sid] = var
            cb = ttk.Checkbutton(
                self._inner,
                text=f"Suggestion {sid}",
                variable=var,
                command=self._on_check_change,
            )
            if not self._enabled:
                cb.configure(state="disabled")
            cb.pack(anchor=tk.W, padx=4, pady=1)
            self._bind_mousewheel(cb)

        self._update_toggle_label()

    def get_selected_ids(self) -> List[str]:
        """Return the currently checked suggestion IDs, numerically sorted."""
        return [sid for sid in self._ids if sid in self._vars and self._vars[sid].get()]

    def get_available_ids(self) -> List[str]:
        """Return all suggestion IDs currently offered, numerically sorted."""
        return list(self._ids)

    def is_all_selected(self) -> bool:
        """True if every available ID is selected (or there are none)."""
        return all(var.get() for var in self._vars.values())

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the whole control (toggle, entry, checkboxes)."""
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self._toggle_button.config(state=state)
        self._entry.config(state=state)
        for child in self._inner.winfo_children():
            if isinstance(child, ttk.Checkbutton):
                child.configure(state=state)

    # ── event handlers ───────────────────────────────────────────────────────

    def _on_toggle_all(self) -> None:
        target = not self.is_all_selected()  # if all selected -> deselect; else select all
        for var in self._vars.values():
            var.set(target)
        self._after_change()

    def _on_apply_entry(self) -> None:
        spec = self._entry_text()
        selected = parse_id_ranges(spec, self._ids)
        for sid, var in self._vars.items():
            var.set(sid in selected)
        self._after_change()

    # ── entry placeholder ────────────────────────────────────────────────────

    def _entry_text(self) -> str:
        """The real entry text, treating the shown placeholder as empty."""
        return "" if self._entry_has_placeholder else self._entry_var.get()

    def _show_placeholder(self) -> None:
        self._entry_has_placeholder = True
        self._entry_var.set(self._placeholder_text)
        self._entry.configure(foreground=widgets.PLACEHOLDER_FG)

    def _clear_placeholder(self) -> None:
        if not self._entry_has_placeholder:
            return
        self._entry_has_placeholder = False
        self._entry_var.set("")
        self._entry.configure(foreground=self._entry_default_fg)

    def _on_entry_focus_in(self, _event: Any) -> None:
        self._clear_placeholder()

    def _on_entry_focus_out(self, _event: Any) -> None:
        if not self._entry_var.get():
            self._show_placeholder()

    def _on_check_change(self) -> None:
        self._after_change()

    def _after_change(self) -> None:
        self._update_toggle_label()
        self._persist()
        if self._on_change is not None:
            self._on_change()

    def _update_toggle_label(self) -> None:
        self._toggle_button.config(text="Deselect all" if self.is_all_selected() and self._vars else "Select all")
