# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tkinter as tk
from typing import Any, Optional


from discopop_library.ProjectManager.configurations.execution_time import (
    EXECUTION_TIME_DISABLED,
    extract_execution_time,
    read_execution_time_settings,
    validate_execution_time_regex,
    write_execution_time_settings,
)
from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_compile_script_path,
    get_per_config_validation_compile_script_path,
    get_shared_compile_script_path,
    resolve_compile_script_path,
)
from discopop_library.ProjectManager.configurations.validation import has_validate_script
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no, show_error, show_warning
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file


class FileEditorMixin(ConfigManagerMixinBase):
    def _format_json_content(self, content: str) -> str:
        try:
            parsed = json.loads(content)
            return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, ValueError):
            return content

    def _load_config(self) -> None:
        if not self.current_config:
            return

        config_path = os.path.join(self.config_dir, self.current_config)

        for filename in ["execute.sh"]:
            file_path = os.path.join(config_path, filename)
            text_area = self.text_areas[filename]
            text_area.delete("1.0", tk.END)

            if os.path.exists(file_path):
                try:
                    with open(file_path, "r") as f:
                        content = f.read()
                        text_area.insert("1.0", content)
                except Exception as e:
                    text_area.insert("1.0", f"Error loading file: {e}")
            else:
                text_area.insert("1.0", f"File not found: {file_path}")

            self.modified_files[filename] = False
            text_area.edit_modified(False)
            self._set_sub_tab_modified(filename, False)

        self._load_compile_override()
        self._load_validate_script()
        self._load_validation_compile_override()
        self._load_execution_time_settings()
        self.right_tabs.tab(self.editor_tab_index, text="Editor")
        self._update_execute_modes()
        self._update_report_display()

    def _set_sub_tab_modified(self, filename: str, modified: bool) -> None:
        tab_index = self.editor_sub_tab_index.get(filename)
        if tab_index is None:
            return
        # The execution time setting is edited in the execute.sh tab but is not a
        # text area, so it carries its own flag and must not be overwritten by the
        # script's own state.
        if filename == "execute.sh":
            modified = modified or self.execution_time_modified
        base_label = self.editor_sub_tab_labels[filename]
        self.editor_notebook.tab(tab_index, text=f"{base_label} *" if modified else base_label)

    def _has_unsaved_editor_changes(self) -> bool:
        """Whether anything in the Editor tab is waiting to be saved."""
        return any(self.modified_files.values()) or self.execution_time_modified

    def _load_execution_time_settings(self) -> None:
        """Show the execution time setting stored for the selected configuration."""
        if not self.current_config:
            return

        config_path = os.path.join(self.config_dir, self.current_config)
        enabled, regex = read_execution_time_settings(config_path)

        # Loading a configuration writes both variables, which must not look like
        # an edit -- hence the guard the trace below honours.
        self._execution_time_loading = True
        try:
            self.execution_time_enabled_var.set(enabled)
            self.execution_time_regex_var.set(regex)
        finally:
            self._execution_time_loading = False
        self.execution_time_modified = False
        self._arm_execution_time_tracking()

        self.execution_time_test_label.config(text="")
        self._update_execution_time_state()
        self._update_execution_time_summary()
        self._set_sub_tab_modified("execute.sh", self.modified_files["execute.sh"])

    def _update_execution_time_summary(self) -> None:
        """Mirror the stored setting into the Execute tab, where runs are started."""
        override = self.arguments.execution_time_regex
        if override is not None:
            text = (
                "from the console output (forced by --execution-time-regex)"
                if override != EXECUTION_TIME_DISABLED
                else "wall clock of execute.sh (forced by --execution-time-regex)"
            )
        elif self.execution_time_enabled_var.get():
            text = "from the console output (see Editor -> execute.sh)"
        else:
            text = "wall clock of execute.sh"
        self.execution_time_summary_label.config(text=text)

    def _arm_execution_time_tracking(self) -> None:
        """Mark the execute.sh tab dirty whenever the execution time setting changes.

        A trace rather than the 500 ms polling the text areas use: these are two
        variables, so a change is observable directly instead of by comparison.
        """
        if getattr(self, "_execution_time_traced", False):
            return

        def on_change(*_args: Any) -> None:
            if self._execution_time_loading or self.execution_time_modified:
                return
            self.execution_time_modified = True
            self._set_sub_tab_modified("execute.sh", self.modified_files["execute.sh"])
            self.right_tabs.tab(self.editor_tab_index, text="Editor *")
            self._update_execution_time_summary()

        self.execution_time_enabled_var.trace_add("write", on_change)
        self.execution_time_regex_var.trace_add("write", on_change)
        self._execution_time_traced = True

    def _update_execution_time_state(self) -> None:
        """Grey out the pattern while the search is switched off."""
        state = "normal" if self.execution_time_enabled_var.get() else "disabled"
        self.execution_time_regex_entry.config(state=state)
        self.execution_time_test_button.config(state=state)

    def _save_execution_time_settings(self, config_path: str) -> bool:
        """Persist the execution time setting; False if it was rejected."""
        if not self.execution_time_modified:
            return True

        regex = self.execution_time_regex_var.get()
        if self.execution_time_enabled_var.get():
            error = validate_execution_time_regex(regex)
            if error is not None:
                show_error(self, "Invalid execution time pattern", "The pattern is " + error)
                return False
        try:
            write_execution_time_settings(config_path, self.execution_time_enabled_var.get(), regex)
        except OSError as e:
            self._set_status(f"Error saving execution time setting: {e}", fg="red")
            return False
        self.execution_time_modified = False
        return True

    def _test_execution_time_regex(self) -> None:
        """Apply the pattern to the output of this configuration's last run.

        Reusing a recorded run means the pattern can be checked without executing
        anything -- which is the point, since a run is what the pattern is meant to
        measure in the first place.
        """
        regex = self.execution_time_regex_var.get()
        error = validate_execution_time_regex(regex)
        if error is not None:
            self.execution_time_test_label.config(text="✗ The pattern is " + error, foreground=widgets.STATUS_FAIL)
            return

        output = self._last_recorded_execution_output()
        if output is None:
            self.execution_time_test_label.config(
                text="No recorded output to test against yet — execute this configuration first.",
                foreground=widgets.STATUS_IDLE,
            )
            return

        stdout, stderr = output
        value = extract_execution_time(stdout, stderr, regex)
        if value is None:
            self.execution_time_test_label.config(
                text="✗ No match in the output of the last recorded run.", foreground=widgets.STATUS_FAIL
            )
        else:
            self.execution_time_test_label.config(
                text=f"✓ Matched in the last recorded run: {value} s", foreground=widgets.STATUS_OK
            )

    def _last_recorded_execution_output(self) -> Optional[tuple[str, str]]:
        """stdout and stderr of the most recent recorded execute.sh run, if any."""
        if not self.current_config:
            return None
        results_path = os.path.join(self.arguments.project_dir, "execution_results.json")
        if not os.path.exists(results_path):
            return None
        try:
            with open(results_path, "r") as f:
                results = json.load(f)
            entries = results.get(self.current_config, {}).get("execute.sh", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

        # A pattern is written for the program as the measured runs execute it, so
        # prefer their output over that of the instrumented profiling runs.
        preferred = ["seq_settings.json", "par_settings.json"]
        ordered = preferred + [name for name in entries if name not in preferred]
        for settings_name in ordered:
            for entry in reversed(entries.get(settings_name, [])):
                if not entry.get("executed", True):
                    continue
                stdout = str(entry.get("stdout", ""))
                stderr = str(entry.get("stderr", ""))
                if stdout or stderr:
                    return stdout, stderr
        return None

    def _load_compile_override(self) -> None:
        if not self.current_config:
            return

        compile_path = get_per_config_compile_script_path(self.arguments.project_config_dir, self.current_config)
        text_area = self.text_areas["compile.sh"]

        text_area.config(state=tk.NORMAL)
        text_area.delete("1.0", tk.END)

        has_override = os.path.exists(compile_path)
        if has_override:
            try:
                with open(compile_path, "r") as f:
                    text_area.insert("1.0", f.read())
            except Exception as e:
                text_area.insert("1.0", f"Error loading file: {e}")
        else:
            text_area.insert(
                "1.0",
                "# This configuration has no compile.sh override.\n"
                "# The shared compile.sh is used to compile it instead.\n"
                "# Click 'Add Override' above to create one for this configuration only.\n",
            )
            text_area.config(state=tk.DISABLED)

        self.modified_files["compile.sh"] = False
        text_area.edit_modified(False)
        self._set_sub_tab_modified("compile.sh", False)
        self.compile_override_button.config(text="Remove Override" if has_override else "Add Override")

    def _toggle_compile_override(self) -> None:
        if not self.current_config:
            return

        compile_path = get_per_config_compile_script_path(self.arguments.project_config_dir, self.current_config)
        if os.path.exists(compile_path):
            self._remove_compile_override(compile_path)
        else:
            self._add_compile_override(compile_path)

    def _add_compile_override(self, compile_path: str) -> None:
        shared_path = get_shared_compile_script_path(self.arguments.project_config_dir)
        seed_content = ""
        if os.path.exists(shared_path):
            with open(shared_path, "r") as f:
                seed_content = f.read()

        write_script_file(compile_path, seed_content)
        self._load_compile_override()
        self._update_execute_modes()
        self._set_status("Added compile.sh override for this configuration", fg="green", reset_delay=2000)

    def _remove_compile_override(self, compile_path: str) -> None:
        if not ask_yes_no(
            self,
            "Remove Override",
            "Remove the compile.sh override for this configuration?\n\n"
            "The configuration will use the shared compile.sh instead.",
        ):
            return

        os.remove(compile_path)
        self._load_compile_override()
        self._update_execute_modes()
        self._set_status("Removed compile.sh override for this configuration", fg="green", reset_delay=2000)

    def _get_validate_script_path(self) -> str:
        assert self.current_config is not None
        return os.path.join(self.config_dir, self.current_config, "validate.sh")

    def _load_validate_script(self) -> None:
        if not self.current_config:
            return

        validate_path = self._get_validate_script_path()
        text_area = self.text_areas["validate.sh"]

        text_area.config(state=tk.NORMAL)
        text_area.delete("1.0", tk.END)

        has_validate = os.path.exists(validate_path)
        if has_validate:
            try:
                with open(validate_path, "r") as f:
                    text_area.insert("1.0", f.read())
            except Exception as e:
                text_area.insert("1.0", f"Error loading file: {e}")
        else:
            text_area.insert(
                "1.0",
                "# This configuration has no validate.sh.\n"
                "# execute.sh alone determines correctness (its exit code).\n"
                "# Click 'Add validate.sh' above to separate output validation from\n"
                "# the timed execute.sh run: validate.sh re-runs the code and validates\n"
                "# its output; a run then counts as correct only if BOTH execute.sh and\n"
                "# validate.sh exit 0.\n",
            )
            text_area.config(state=tk.DISABLED)

        self.modified_files["validate.sh"] = False
        text_area.edit_modified(False)
        self._set_sub_tab_modified("validate.sh", False)
        self.validate_script_button.config(text="Remove validate.sh" if has_validate else "Add validate.sh")

    def _toggle_validate_script(self) -> None:
        if not self.current_config:
            return

        validate_path = self._get_validate_script_path()
        if os.path.exists(validate_path):
            self._remove_validate_script(validate_path)
        else:
            self._add_validate_script(validate_path)

    def _add_validate_script(self, validate_path: str) -> None:
        assert self.current_config is not None
        seed_content = ""
        execute_path = os.path.join(self.config_dir, self.current_config, "execute.sh")
        if os.path.exists(execute_path):
            with open(execute_path, "r") as f:
                seed_content = f.read()

        write_script_file(validate_path, seed_content)
        self._load_validate_script()
        self._load_validation_compile_override()
        self._set_status("Added validate.sh for this configuration", fg="green", reset_delay=2000)

    def _remove_validate_script(self, validate_path: str) -> None:
        if not ask_yes_no(
            self,
            "Remove validate.sh",
            "Remove validate.sh for this configuration?\n\n" "Correctness will then be determined by execute.sh alone.",
        ):
            return

        os.remove(validate_path)
        self._load_validate_script()
        self._load_validation_compile_override()
        self._set_status("Removed validate.sh for this configuration", fg="green", reset_delay=2000)

    def _load_validation_compile_override(self) -> None:
        if not self.current_config:
            return

        validation_compile_path = get_per_config_validation_compile_script_path(
            self.arguments.project_config_dir, self.current_config
        )
        text_area = self.text_areas["compile_validate.sh"]

        text_area.config(state=tk.NORMAL)
        text_area.delete("1.0", tk.END)

        has_override = os.path.exists(validation_compile_path)
        if has_override:
            try:
                with open(validation_compile_path, "r") as f:
                    text_area.insert("1.0", f.read())
            except Exception as e:
                text_area.insert("1.0", f"Error loading file: {e}")
        else:
            text_area.insert(
                "1.0",
                "# This configuration has no compile_validate.sh override.\n"
                "# validate.sh runs against the build produced by the compile script that\n"
                "# execute.sh also uses.\n"
                "# Click 'Add Override' above to build separately for validation: the override\n"
                "# is compiled after the timed execute.sh run and before validate.sh, so it\n"
                "# never affects the measured runtime. It is ignored while no validate.sh exists.\n",
            )
            text_area.config(state=tk.DISABLED)

        # An override without a validate.sh has no effect; say so in the tab label
        # rather than in the editor, so the note can never end up in the file.
        ignored = has_override and not has_validate_script(os.path.join(self.config_dir, self.current_config))
        self.editor_sub_tab_labels["compile_validate.sh"] = (
            "compile_validate.sh (ignored)" if ignored else "compile_validate.sh (override)"
        )

        self.modified_files["compile_validate.sh"] = False
        text_area.edit_modified(False)
        self._set_sub_tab_modified("compile_validate.sh", False)
        self.validation_compile_override_button.config(text="Remove Override" if has_override else "Add Override")

    def _toggle_validation_compile_override(self) -> None:
        if not self.current_config:
            return

        validation_compile_path = get_per_config_validation_compile_script_path(
            self.arguments.project_config_dir, self.current_config
        )
        if os.path.exists(validation_compile_path):
            self._remove_validation_compile_override(validation_compile_path)
        else:
            self._add_validation_compile_override(validation_compile_path)

    def _add_validation_compile_override(self, validation_compile_path: str) -> None:
        assert self.current_config is not None
        if not has_validate_script(os.path.join(self.config_dir, self.current_config)):
            show_warning(
                self,
                "No validate.sh",
                "This configuration has no validate.sh, so a compile_validate.sh is ignored.\n\n"
                "Add a validate.sh first to make the separate validation build take effect.",
            )

        seed_content = ""
        source_path = resolve_compile_script_path(self.arguments.project_config_dir, self.current_config)
        if os.path.exists(source_path):
            with open(source_path, "r") as f:
                seed_content = f.read()

        write_script_file(validation_compile_path, seed_content)
        self._load_validation_compile_override()
        self._set_status("Added compile_validate.sh override for this configuration", fg="green", reset_delay=2000)

    def _remove_validation_compile_override(self, validation_compile_path: str) -> None:
        if not ask_yes_no(
            self,
            "Remove Override",
            "Remove the compile_validate.sh override for this configuration?\n\n"
            "validate.sh will then run against the same build as execute.sh.",
        ):
            return

        os.remove(validation_compile_path)
        self._load_validation_compile_override()
        self._set_status("Removed compile_validate.sh override for this configuration", fg="green", reset_delay=2000)

    def _validate_compile_script(self, file_path: str) -> None:
        try:
            with open(file_path, "r") as f:
                content = f.read()

            if "CC" not in content and "CXX" not in content:
                show_warning(
                    self,
                    "Compilation Script Warning",
                    "The compilation script does not use CC or CXX environment variables.\n\n"
                    "The compilation script should make use of CC or CXX for compatibility "
                    "with the DiscoPoP framework.",
                )
        except Exception as e:
            self._set_status(f"Error validating compile.sh: {e}", fg="red")

    def _save_config(self) -> None:
        if not self.current_config:
            self._set_status("No configuration selected", fg="red")
            return

        config_path = os.path.join(self.config_dir, self.current_config)
        saved_files = []

        if self.execution_time_modified:
            if not self._save_execution_time_settings(config_path):
                return
            saved_files.append("execution time setting")
            # the setting has no text area, so nothing else clears its "*" marker
            self._set_sub_tab_modified("execute.sh", self.modified_files["execute.sh"])

        for filename in self.text_areas:
            if not self.modified_files[filename]:
                continue

            file_path = os.path.join(config_path, filename)
            content = self.text_areas[filename].get("1.0", tk.END).rstrip()

            if filename.endswith(".json"):
                formatted_content = self._format_json_content(content)
            else:
                formatted_content = content

            try:
                with open(file_path, "w") as f:
                    f.write(formatted_content)
                self.modified_files[filename] = False
                self.text_areas[filename].edit_modified(False)
                self._set_sub_tab_modified(filename, False)
                saved_files.append(filename)
            except Exception as e:
                self._set_status(f"Error saving file {filename}: {e}", fg="red")
                return

        if not self._has_unsaved_editor_changes():
            self.right_tabs.tab(self.editor_tab_index, text="Editor")

        if saved_files:
            self._set_status(f"Saved {', '.join(saved_files)}", fg="green", reset_delay=2000)

            for script_name in ("compile.sh", "compile_validate.sh"):
                if script_name in saved_files:
                    self._validate_compile_script(os.path.join(config_path, script_name))
        else:
            self._set_status("No changes to save")

    def _check_modification(self, filename: str) -> None:
        if filename not in self.text_areas:
            return

        text_area = self.text_areas[filename]
        is_modified = text_area.edit_modified()

        if is_modified and not self.modified_files[filename]:
            self.modified_files[filename] = True
            self._set_sub_tab_modified(filename, True)
            self.right_tabs.tab(self.editor_tab_index, text="Editor *")
        elif not is_modified and self.modified_files[filename]:
            self.modified_files[filename] = False
            self._set_sub_tab_modified(filename, False)
            if not self._has_unsaved_editor_changes():
                self.right_tabs.tab(self.editor_tab_index, text="Editor")

    def _start_modification_polling(self) -> None:
        for filename in self.text_areas:
            self._check_modification(filename)
        for filename in self.compilation_text_areas:
            self._check_compilation_modification(filename)
        self.after(500, self._start_modification_polling)  # type: ignore

    def _handle_save_shortcut(self) -> None:
        try:
            selected_tab_index = self.right_tabs.index(self.right_tabs.select())
            if selected_tab_index == 0:
                self._save_config()
            elif selected_tab_index == 1:
                pass
            elif selected_tab_index == 2:
                pass
            elif self.right_tabs.tab(selected_tab_index, option="text") == "Compilation":
                self._save_compilation_files()
        except Exception:
            pass
