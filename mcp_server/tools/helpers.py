# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import datetime
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

logger = logging.getLogger("discopop-mcp")


def find_patch_applicator() -> Optional[str]:
    """Locate the discopop_patch_applicator executable.

    The venv this server runs in is searched first: an installation that is not on
    the caller's PATH is the normal case when the MCP client launches the server
    through an absolute path.
    """
    venv_bin = os.path.dirname(sys.executable)
    env_path = os.environ.get("PATH", "")
    search_path = venv_bin + os.pathsep + env_path if venv_bin not in env_path else env_path
    return shutil.which("discopop_patch_applicator", path=search_path)


# Return codes of discopop_patch_applicator: 0 = done, 1 = nothing applied (error),
# 2 = partially applied, 3 = nothing to do (trivially successful).
APPLICATOR_OK_RETURNCODES = (0, 2, 3)
APPLICATOR_TIMEOUT_SECONDS = 60

# What the applicator (really: the `patch` command it drives) prints when a patch no
# longer matches the file it belongs to. Recognising it is what turns an unexplained
# rc=1 into the one sentence a caller can act on.
_STALE_PATCH_MARKERS = (
    "not successful",
    "hunk #",
    "reversed (or previously applied)",
    "malformed patch",
    "can't find file",
)


def run_patch_applicator(
    project_path: str, applicator_args: list[str], timeout: int = APPLICATOR_TIMEOUT_SECONDS
) -> tuple[Optional["subprocess.CompletedProcess[str]"], Optional[str]]:
    """Run discopop_patch_applicator in the project's .discopop directory.

    Returns ``(completed_process, None)`` when the applicator ran at all -- a non-zero
    return code is part of the process, not an error here -- and ``(None, message)``
    when it could not be started. Shared by every tool that patches, so they all treat
    the applicator's exit codes and its output the same way.
    """
    applicator = find_patch_applicator()
    if not applicator:
        return None, "discopop_patch_applicator not found on PATH. Ensure the discopop_library package is installed."
    try:
        proc = subprocess.run(
            [applicator] + applicator_args,
            cwd=str(Path(project_path) / ".discopop"),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"discopop_patch_applicator timed out after {timeout}s."
    except OSError as e:
        return None, f"Could not run discopop_patch_applicator: {e}"
    return proc, None


def applicator_failure_details(proc: "subprocess.CompletedProcess[str]") -> tuple[str, Optional[str]]:
    """The applicator's own account of a failure, plus the likely cause.

    The applicator reports *why* a patch could not be applied or reversed on **stdout**
    (that is where the `patch` command's own output is echoed to), while stderr is
    usually empty. Reporting only stderr therefore produces the least actionable error
    there is -- a return code and nothing else -- so both streams are collected here and
    the recognisable case is named outright.
    """
    output = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
    lowered = output.lower()
    cause: Optional[str] = None
    if any(marker in lowered for marker in _STALE_PATCH_MARKERS):
        cause = (
            "A patch no longer matches the file it belongs to. This happens when the source "
            "was edited by hand after the patch was applied, or when the patches were "
            "generated for an older version of the sources. Undo your manual edits to the "
            "affected file, or re-run gather_data to regenerate the patches for the current "
            "sources; the patch applicator cannot reverse a patch whose context has changed."
        )
    return output, cause


def read_application_result(project_path: str) -> Optional[dict[str, Any]]:
    """The structured outcome the patch applicator writes for an --apply run.

    Says which of the requested suggestions actually reached the code, which is what
    keeps a caller from reviewing or measuring unmodified sources in the belief that
    they were parallelized.
    """
    path = Path(project_path) / ".discopop" / "patch_applicator" / "application_result.json"
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_applied_suggestions(project_path: str) -> tuple[Optional[list[str]], Optional[str]]:
    """The suggestion ids currently applied to the project's sources.

    Returns ``(ids, None)`` on success and ``(None, message)`` when the applicator
    could not be run at all. An empty list means the sources are un-patched.
    """
    proc, error = run_patch_applicator(project_path, ["--list"])
    if proc is None:
        return None, error
    if proc.returncode not in APPLICATOR_OK_RETURNCODES:
        return None, f"discopop_patch_applicator --list failed (rc={proc.returncode}): {proc.stderr.strip()}"
    for line in proc.stdout.splitlines():
        if "Applied suggestions:" in line:
            raw = line.split("Applied suggestions:")[-1].strip()
            try:
                parsed = json.loads(raw.replace("'", '"'))
            except json.JSONDecodeError:
                return [raw] if raw else [], None
            return [str(entry) for entry in parsed] if isinstance(parsed, list) else [str(parsed)], None
    return [], None


class ToolContext:
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        # project_path → (DetectionResult, dump_file_mtime)
        self._detection_cache: dict[str, tuple[Any, float]] = {}
        # project_path → (file_id_to_path, FileMapping.txt mtime)
        self._file_mapping_cache: dict[str, tuple[dict[int, Path], float]] = {}

    def log_to_file(self, project_path: str, marker: str, tool_name: str, message: str) -> None:
        """Append a timestamped entry to <project_path>/.discopop/mcp_server/log.txt.
        Never raises — logging failures must not affect tool execution."""
        try:
            log_dir = Path(project_path) / ".discopop" / "mcp_server"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{ts}  {marker:<8}  {tool_name:<40}  {message}\n"
            with open(log_dir / "log.txt", "a") as f:
                f.write(line)
        except Exception:
            pass

    def log_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        logger.info(f"→ Incoming call: {tool_name}")
        if self.debug:
            logger.debug(f"  Arguments: {json.dumps(arguments, indent=2)}")
        project_path = arguments.get("project_path", "")
        if project_path:
            args_summary = ", ".join(f"{k}={v!r}" for k, v in arguments.items() if k != "script_body")
            self.log_to_file(project_path, "→ CALL", tool_name, args_summary)

    def log_response(self, tool_name: str, result: Any) -> None:
        logger.info(f"← Outgoing response: {tool_name}")
        if self.debug:
            logger.debug(f"  Result: {json.dumps(result if isinstance(result, dict) else str(result), indent=2)}")
        if isinstance(result, dict):
            project_path = result.get("project_path", "")
            if not project_path:
                return
            status = result.get("status", "?")
            extras = {
                k: v
                for k in (
                    "returncode",
                    "elapsed_time",
                    "patterns_found",
                    "hotspots_found",
                    "files_created",
                    "profiling_files",
                    "created_files",
                    "patches",
                )
                if (v := result.get(k)) is not None
            }
            summary = f"status={status}" + (
                ", "
                + ", ".join(
                    f"{k}={v!r}" if not isinstance(v, list) else f"{k}=[{len(v)} items]" for k, v in extras.items()
                )
                if extras
                else ""
            )
            self.log_to_file(project_path, "← RESULT", tool_name, summary)

    def log_action(self, project_path: str, tool_name: str, message: str) -> None:
        logger.debug(f"  Action [{tool_name}]: {message}")
        if project_path:
            self.log_to_file(project_path, "· ACTION", tool_name, message)

    def error(self, message: str, project_path: str = "", tool_name: str = "") -> list[TextContent]:
        result = {"status": "error", "message": message}
        if project_path and tool_name:
            self.log_to_file(project_path, "← RESULT", tool_name, f"status=error, message={message}")
        return [TextContent(type="text", text=json.dumps(result))]

    def make_pm_args(self, project_path: str, timeout_seconds: Optional[int] = None) -> ProjectManagerArguments:
        return ProjectManagerArguments(
            project_root=project_path,
            full_execute=False,
            list=False,
            execute_configurations="",
            execute_inplace=True,
            skip_cleanup=False,
            generate_report=False,
            show_report=False,
            initialize_directory=False,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="mcp",
            timeout_execution=float(timeout_seconds) if timeout_seconds is not None else None,
            timeout_compilation=float(timeout_seconds) if timeout_seconds is not None else None,
            timeout_validation=float(timeout_seconds) if timeout_seconds is not None else None,
            log_level="WARNING",
            write_log=False,
        )

    def get_file_mapping(self, project_path: str) -> Optional[dict[int, Path]]:
        """Return a cached file_id → Path mapping loaded from .discopop/FileMapping.txt.
        Reloads when the file is newer than the cache. Returns None if the file does not exist."""
        fmap_path = Path(project_path) / ".discopop" / "FileMapping.txt"
        if not fmap_path.exists():
            return None
        current_mtime = fmap_path.stat().st_mtime
        cached = self._file_mapping_cache.get(project_path)
        if cached is not None:
            mapping, cached_mtime = cached
            if cached_mtime == current_mtime:
                return mapping
        try:
            from discopop_library.PathManagement.PathManagement import load_file_mapping

            mapping = load_file_mapping(str(fmap_path))
            self._file_mapping_cache[project_path] = (mapping, current_mtime)
            logger.info(f"Loaded FileMapping for {project_path} into cache")
            return mapping
        except Exception as e:
            logger.warning(f"Failed to load FileMapping from {fmap_path}: {e}")
            return None

    def get_detection_result(self, project_path: str) -> Optional[Any]:
        """Return the cached DetectionResult for project_path, loading or reloading from
        .discopop/explorer/detection_result_dump.json when the file is newer than the cache.
        Returns None if the dump file does not exist."""
        dump_path = Path(project_path) / ".discopop" / "explorer" / "detection_result_dump.json"
        if not dump_path.exists():
            return None
        current_mtime = dump_path.stat().st_mtime
        cached = self._detection_cache.get(project_path)
        if cached is not None:
            result, cached_mtime = cached
            if cached_mtime == current_mtime:
                return result
        try:
            import jsonpickle  # type: ignore

            json_str = dump_path.read_text(encoding="utf-8")
            result = jsonpickle.decode(json_str, keys=True)
            self._detection_cache[project_path] = (result, current_mtime)
            logger.info(f"Loaded DetectionResult for {project_path} into cache")
            return result
        except Exception as e:
            logger.warning(f"Failed to load DetectionResult from {dump_path}: {e}")
            return None

    @staticmethod
    def newest_source_mtime(project_path: str) -> Optional[float]:
        """Return the mtime of the most recently modified source file under project_path,
        excluding the .discopop subtree. Returns None if no source files are found."""
        source_exts = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh"}
        newest: Optional[float] = None
        for f in Path(project_path).rglob("*"):
            if ".discopop" in f.parts:
                continue
            if f.suffix.lower() in source_exts and f.is_file():
                mtime = f.stat().st_mtime
                if newest is None or mtime > newest:
                    newest = mtime
        return newest

    @staticmethod
    def fmt_ts(mtime: float) -> str:
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def extract_source_from_patch(patch_content: str) -> Optional[str]:
        """Extract the original source file path from the --- line of a unified diff."""
        for line in patch_content.splitlines():
            if line.startswith("--- "):
                path_part = line[4:].split("\t")[0].strip()
                if path_part and path_part != "/dev/null":
                    return path_part
        return None
