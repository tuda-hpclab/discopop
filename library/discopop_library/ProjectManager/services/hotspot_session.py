# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The hotspot measurement flow of the Hotspot Detection tab, without a toolkit.

Accumulating runs is the whole point of the tab: ``ratio`` measures how a region's
runtime varies with the input, and each configuration's ``execute.sh`` is its own
input, so a single run leaves ``ratio`` at exactly ``0.5`` everywhere and hotness
degenerates to "above-average runtime". Measuring several configurations is
therefore what makes the analysis meaningful -- and configurations generally differ
in their ``compile.sh``, so this must work across instrumented builds.

Raw region ids cannot carry that across builds. ``HotspotDetection.cpp`` appends to
``cs_id.txt`` and resumes numbering from ``temp.txt``, so a second compile gives the
same source region a second id, and the runtime -- which sizes its output by
counting ``cs_id.txt``'s lines -- writes ``0.0`` for every region belonging to a
build other than its own. Handing that directly to the analyzer, which joins purely
by id, is what destroys the YES/MAYBE/NO distinction: ``roundMin`` turns those zeros
into ``1e-6`` and ``ratio`` collapses to ~1.0 for everything.

So ids are never used to combine anything. Each run's measurements are resolved to
build-independent :class:`~...hotspot_data.RegionKey`\\ s (source path, line, kind,
name) as soon as it completes and stored that way in the sidecar; before analysis
all accumulated runs are renumbered into one canonical id space
(:func:`~...hotspot_data.write_merged_analysis_input`) in which a region absent from
a run is *omitted* rather than zeroed, so the analyzer averages it over the runs
where it actually exists. Nothing is discarded on recompile; clearing is manual.

:class:`HotspotSession` reads and writes the files of one project; :meth:`HotspotSession.run` is the work a
:class:`~...jobs.WorkRunner` executes (it touches no widget).
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import shutil
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.plots import demangle, hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import HotspotRegion, MeasurementLog, MeasurementRun
from discopop_library.ProjectManager.services.commands import (
    environment_with_interpreter_on_path,
    hotspot_analyzer_command,
)
from discopop_library.ProjectManager.services.hotspot_build import hotspot_build_state
from discopop_library.ProjectManager.services.jobs import JobSpec, StatusKind, WorkContext
from discopop_library.ProjectManager.services.text import clean_ansi_output

logger = logging.getLogger("HotspotPanel")

HOTSPOT_ANALYZER = "discopop_hotspot_analyzer"

Timeouts = Tuple[Optional[float], Optional[float], Optional[float]]


@dataclass(frozen=True)
class HotspotRunRequest:
    """What one measurement asks the worker to do, read from the widgets on the main thread."""

    config_name: str
    config_path: str
    compile_sh: str
    settings_path: str
    # a private copy of the arguments with the timeouts and execution settings of the measurement
    arguments: ProjectManagerArguments
    needs_compile: bool
    repetitions: int


@dataclass(frozen=True)
class HotspotResults:
    """The analysis (``Hotspots.json``) and the accumulated runs, as they are on disk."""

    regions: List[HotspotRegion]
    runs: List[MeasurementRun]


def timestamp() -> str:
    """Local wall-clock time, to the second, for the run log."""
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return None


class HotspotSession:
    """The hotspot data of one project (``.discopop/hotspot_detection``) and the flow that fills it."""

    def __init__(self, arguments: ProjectManagerArguments) -> None:
        self.arguments = arguments

    # ── data loading ───────────────────────────────────────────────────────────

    def load_region_keys(self, *, merged: bool = False) -> Dict[int, hotspot_data.RegionKey]:
        """Resolve region ids to source locations.

        Two id spaces exist and must not be confused. ``private/cs_id.txt`` is the
        profiler's, in which the raw ``hotspot_result_<N>.txt`` files are written;
        ``merged/cs_id.txt`` is the canonical one spanning all builds, in which
        ``Hotspots.json`` is expressed. Pass ``merged=True`` for the latter.
        """
        dot_dp = self.arguments.dot_dp
        path = hotspot_data.merged_cs_id_path(dot_dp) if merged else hotspot_data.cs_id_path(dot_dp)
        cs_id_text = read_text(path)
        if cs_id_text is None:
            return {}
        file_mapping_text = read_text(os.path.join(dot_dp, "FileMapping.txt")) or ""
        return hotspot_data.resolve_keys(
            hotspot_data.parse_cs_id(cs_id_text),
            hotspot_data.parse_file_mapping(file_mapping_text),
        )

    def load_log(self) -> MeasurementLog:
        data = hotspot_data.load_json_file(hotspot_data.sidecar_path(self.arguments.dot_dp))
        return hotspot_data.deserialize_log(data) if data is not None else MeasurementLog()

    def save_log(self, log: MeasurementLog) -> None:
        path = hotspot_data.sidecar_path(self.arguments.dot_dp)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(hotspot_data.serialize_log(log), f, indent=4, sort_keys=True)
        except OSError as e:
            logger.warning("could not write the hotspot measurement log: %s", e)

    def load_results(self) -> HotspotResults:
        """Reload ``Hotspots.json`` and the run log (the demangler is primed for the regions' names)."""
        dot_dp = self.arguments.dot_dp
        keys = self.load_region_keys(merged=True)
        hotspots = hotspot_data.load_json_file(hotspot_data.hotspots_json_path(dot_dp))
        regions = hotspot_data.parse_hotspots_json(hotspots, keys) if hotspots is not None else []
        # one batched demangler call, rather than one per rendered row
        demangle.prefetch(region.key.name for region in regions if region.key.name)

        log = self.load_log()
        indices = hotspot_data.result_file_indices(hotspot_data.private_dir(dot_dp))
        return HotspotResults(regions, hotspot_data.merge_external_runs(log, indices))

    # ── build state ────────────────────────────────────────────────────────────

    def current_region_fingerprint(self) -> Optional[str]:
        keys = self.load_region_keys()
        return hotspot_data.region_fingerprint(keys.values()) if keys else None

    def compile_script_differs(self, current_config: Optional[str]) -> bool:
        """Whether the selected configuration needs its own instrumented build."""
        log = self.load_log()
        if not current_config or not log.compile_script:
            return False
        expected = resolve_compile_script_path(self.arguments.project_config_dir, current_config)
        return os.path.abspath(expected) != os.path.abspath(log.compile_script)

    def build_state(self, current_config: Optional[str]) -> Tuple[str, str]:
        """Whether the current build can serve another run directly, and why not."""
        return hotspot_build_state(
            hotspot_data.cs_id_path(self.arguments.dot_dp),
            self.arguments.project_root,
            lambda: self.compile_script_differs(current_config),
        )

    def has_data(self) -> bool:
        return os.path.isdir(hotspot_data.hotspot_dir(self.arguments.dot_dp))

    # ── running measurements ───────────────────────────────────────────────────

    def make_request(
        self, config_name: str, *, needs_compile: bool, repetitions: int, timeouts: Timeouts
    ) -> HotspotRunRequest:
        """The request of one measurement; the timeouts are those of the Execute tab."""
        args_copy = copy.copy(self.arguments)
        args_copy.execute_inplace = True
        args_copy.skip_cleanup = False
        args_copy.label_prefix = ""
        args_copy.apply_suggestions = None
        args_copy.log_level = "INFO"
        args_copy.timeout_execution, args_copy.timeout_compilation, args_copy.timeout_validation = timeouts
        return HotspotRunRequest(
            config_name=config_name,
            config_path=os.path.join(self.arguments.project_config_dir, config_name),
            compile_sh=resolve_compile_script_path(self.arguments.project_config_dir, config_name),
            settings_path=os.path.join(self.arguments.project_config_dir, "hd_settings.json"),
            arguments=args_copy,
            needs_compile=needs_compile,
            repetitions=repetitions,
        )

    def run(self, ctx: WorkContext, request: HotspotRunRequest) -> bool:
        """Compile if needed, execute ``request.repetitions`` runs, then analyze.

        Runs on a worker thread; it reports through ``ctx`` and touches no widget.
        """
        dot_dp = self.arguments.dot_dp
        args_copy = request.arguments
        config_name = request.config_name
        config_path = request.config_path
        settings_path = request.settings_path

        if not os.path.exists(settings_path):
            ctx.output(f"hd_settings.json not found at {settings_path}\n")
            return False

        log = self.load_log()

        if request.needs_compile:
            # The accumulated runs are deliberately kept. The pass appends to
            # cs_id.txt and resumes numbering from temp.txt, so the new build's
            # regions get fresh ids alongside the old ones and the runtime picks the
            # next free hotspot_result_<N>.txt -- nothing that the previous runs
            # refer to is overwritten. The analysis joins them by source location.
            if log.runs:
                ctx.output(f"Keeping the {len(log.runs)} accumulated run(s); they will be combined.\n")

            ctx.status("⏳ Instrumenting...", StatusKind.BUSY)
            ctx.output(f"Compiling '{config_name}' in 'hd' mode (inplace)...\n")
            result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                settings_path,
                request.compile_sh,
                1,
                args_copy.timeout_compilation,
                process_started_callback=ctx.register_process,
            )
            ctx.clear_process()
            if result is None or result[0] != 0:
                code = result[0] if result else "None"
                ctx.output(f"Instrumentation failed (return code: {code})\n")
                return False
            _code, elapsed, stdout, stderr = result
            ctx.output(f"Instrumentation succeeded ({elapsed:.2f}s)\n")
            if stdout:
                ctx.output(f"stdout: {stdout}\n")
            if stderr:
                ctx.output(f"stderr: {stderr}\n")

            fingerprint = self.current_region_fingerprint()
            if fingerprint is None:
                ctx.output(
                    "Warning: no code regions were instrumented (cs_id.txt is missing or empty).\n"
                    "Check that the configuration compiles with the hotspot detection wrappers.\n"
                )
            log.region_fingerprint = fingerprint
            log.instrumented_at = timestamp()
            log.compile_script = os.path.abspath(request.compile_sh)
            self.save_log(log)

        if ctx.cancel_event.is_set():
            ctx.output("Stopped by user.\n")
            return False

        keys = self.load_region_keys()
        private = hotspot_data.private_dir(dot_dp)
        repetitions = request.repetitions

        for repetition in range(repetitions):
            if ctx.cancel_event.is_set():
                ctx.output("Stopped by user.\n")
                return False

            label = f" ({repetition + 1}/{repetitions})" if repetitions > 1 else ""
            ctx.status("⏳ Measuring...", StatusKind.BUSY)
            ctx.output(f"\nExecuting '{config_name}'{label}...\n")

            before = set(hotspot_data.result_file_indices(private))
            result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                settings_path,
                os.path.join(config_path, "execute.sh"),
                1,
                args_copy.timeout_execution,
                process_started_callback=ctx.register_process,
            )
            ctx.clear_process()
            if result is None:
                ctx.output("Execution failed (no result)\n")
                return False
            code, elapsed, stdout, stderr = result
            if code != 0:
                ctx.output(f"Execution failed (return code: {code})\n")
                if stderr:
                    ctx.output(f"stderr: {stderr}\n")
                return False
            ctx.output(f"Execution succeeded ({elapsed:.2f}s)\n")
            if stdout:
                ctx.output(f"stdout: {stdout}\n")

            after = set(hotspot_data.result_file_indices(private))
            new_indices = sorted(after - before)
            if not new_indices:
                ctx.output(
                    "Warning: the binary ran but produced no hotspot_result_*.txt file.\n"
                    "It is probably not instrumented -- use Re-instrument.\n"
                )
                return False

            for index in new_indices:
                log.runs.append(
                    MeasurementRun(
                        index=index,
                        config=config_name,
                        timestamp=timestamp(),
                        time=elapsed,
                        code=code,
                        regions=self.resolve_run_regions(private, index, keys),
                    )
                )
                ctx.output(f"Recorded run {index}.\n")
            self.save_log(log)

        if ctx.cancel_event.is_set():
            ctx.output("Stopped by user.\n")
            return False

        return self.invoke_analyzer(ctx)

    def resolve_run_regions(
        self, private: str, index: int, keys: Dict[int, hotspot_data.RegionKey]
    ) -> Dict[str, float]:
        """One run's measurements, keyed by resolved region key rather than id."""
        text = read_text(os.path.join(private, f"hotspot_result_{index}.txt"))
        if text is None:
            return {}
        regions: Dict[str, float] = {}
        for csid, runtime in hotspot_data.parse_hotspot_result(text).items():
            key = keys.get(csid)
            # Regions that never ran dominate the file and carry no information.
            if key is not None and runtime > 0:
                regions[key.serialize()] = runtime
        return regions

    def runs_for_analysis(self) -> List[MeasurementRun]:
        """The accumulated runs, each with its per-region measurements resolved.

        Read from the sidecar rather than from what a view shows: that mirrors the
        *rendered* state and is only refreshed once the worker finishes, so a
        measurement in progress would analyze the runs as they were before it started.

        Runs the GUI recorded itself already carry ``regions``; externally
        produced ones (Execute tab, CLI, MCP server) are resolved from their raw
        result file here so they contribute to the analysis like any other run.
        """
        private = hotspot_data.private_dir(self.arguments.dot_dp)
        log = self.load_log()
        keys = self.load_region_keys()
        runs: List[MeasurementRun] = []
        for run in hotspot_data.merge_external_runs(log, hotspot_data.result_file_indices(private)):
            if not run.regions:
                run = replace(run, regions=self.resolve_run_regions(private, run.index, keys))
            if run.regions:
                runs.append(run)
        return runs

    def invoke_analyzer(self, ctx: WorkContext) -> bool:
        """Run ``discopop_hotspot_analyzer`` over the accumulated runs.

        The analyzer is not pointed at ``private/`` directly. Region ids there are
        only unique within one instrumented build, so runs from two configurations
        would be joined by ids that mean different things. Instead every
        accumulated run is renumbered into one canonical id space keyed by source
        location (:func:`hotspot_data.write_merged_analysis_input`) and the
        analyzer reads that -- which is what lets several configurations be
        combined into one hotness verdict.

        Executed as a subprocess because the analyzer chdirs into the profiling
        data directory and does not restore the working directory afterwards.
        """
        dot_dp = self.arguments.dot_dp
        private = hotspot_data.private_dir(dot_dp)

        if not os.path.isdir(private):
            ctx.output(f"\nAnalysis skipped: no profiling data found at {private}\n")
            return False
        runs = self.runs_for_analysis()
        if not runs:
            ctx.output("\nAnalysis skipped: no accumulated runs with measurements.\n")
            return False

        file_mapping = hotspot_data.parse_file_mapping(read_text(os.path.join(dot_dp, "FileMapping.txt")) or "")
        merged = hotspot_data.merged_dir(dot_dp)
        try:
            region_count = hotspot_data.write_merged_analysis_input(runs, file_mapping, merged)
        except OSError as e:
            ctx.output(f"\nAnalysis skipped: could not write merged analysis input: {e}\n")
            return False
        if not region_count:
            ctx.output("\nAnalysis skipped: the accumulated runs contain no known code regions.\n")
            return False
        configs = sorted({run.config for run in runs if run.config})
        ctx.output(
            f"\nMerged {len(runs)} run(s) over {region_count} code region(s)"
            + (f" from configuration(s): {', '.join(configs)}\n" if configs else "\n")
        )

        my_env = environment_with_interpreter_on_path()
        analyzer = shutil.which(HOTSPOT_ANALYZER, path=my_env["PATH"])
        if analyzer is None:
            ctx.output(f"\nAnalysis skipped: {HOTSPOT_ANALYZER} not found on PATH.\n")
            return False

        ctx.status("⏳ Analyzing...", StatusKind.BUSY)
        ctx.output(f"Running hotspot analysis over {len(runs)} accumulated run(s)...\n")

        def on_analyzer_line(line: str) -> None:
            cleaned = clean_ansi_output(line)
            if cleaned:
                ctx.output(cleaned + "\n")

        try:
            returncode = ctx.run_command(
                JobSpec(
                    hotspot_analyzer_command(analyzer, hotspot_data.MERGED_DIRNAME),
                    cwd=dot_dp,
                    env=my_env,
                    new_session=True,
                ),
                on_analyzer_line,
            )
        except OSError as e:
            ctx.output(f"\nAnalysis skipped: could not start {HOTSPOT_ANALYZER}: {e}\n")
            return False

        if returncode != 0:
            ctx.output(f"Hotspot analysis failed (return code: {returncode})\n")
            return False
        ctx.output("Hotspot analysis complete.\n")
        return True

    # ── clearing ───────────────────────────────────────────────────────────────

    def delete_hotspot_dir(self) -> None:
        """Remove ``.discopop/hotspot_detection/``.

        Deliberately leaves ``.discopop/FileMapping.txt`` alone: it is shared with
        the ``dp`` flow, and keeping it preserves the file ids that already-resolved
        region keys refer to.
        """
        target = hotspot_data.hotspot_dir(self.arguments.dot_dp)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
