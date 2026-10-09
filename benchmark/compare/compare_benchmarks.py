# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Turn the raw results of ``run_ab_benchmarks.py`` into the comparison report.

Writes the report as markdown (pull request comment and job summary), as a self-contained HTML page with charts,
and as JSON. A change is flagged when it exceeds ``--threshold`` and, where measured repeatedly, is significant.
The report is informative: this script fails only when it cannot read the results, never because of a regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from benchmark_compare.report_html import format_html
from benchmark_compare.report_markdown import format_report
from benchmark_compare.results import Comparison, Metric, load
from benchmark_compare.stats import DEFAULT_THRESHOLD


def _metrics(**metrics: Metric) -> Dict[str, Any]:
    return {name: metric.to_json() for name, metric in metrics.items()}


def comparison_to_json(comparison: Comparison) -> Dict[str, Any]:
    """Everything the report shows, in machine readable form."""
    data: Dict[str, Any] = {
        "threshold": comparison.threshold,
        "regressions": comparison.regressions,
        "improvements": comparison.improvements,
    }
    if comparison.pass_overhead is not None:
        section = comparison.pass_overhead
        data["pass_overhead"] = {
            "manifest": section.manifest.to_json(),
            "compiler": section.compiler,
            "programs": {
                program.name: _metrics(
                    run_factor=program.run_factor,
                    compile_factor=program.compile_factor,
                    size_factor=program.size_factor,
                )
                for program in section.programs
            },
            "geometric_mean": _metrics(
                run_factor=section.geomean_run_factor,
                compile_factor=section.geomean_compile_factor,
                size_factor=section.geomean_size_factor,
            ),
        }
    if comparison.callbacks is not None:
        data["callbacks"] = {
            "manifest": comparison.callbacks.manifest.to_json(),
            "callbacks": {
                callback.name: _metrics(total_ns=callback.total, call_only_ns=callback.call_only, body_ns=callback.body)
                for callback in comparison.callbacks.callbacks
            },
        }
    if comparison.breakdown is not None:
        breakdown = comparison.breakdown
        data["breakdown"] = {
            "manifest": breakdown.manifest.to_json(),
            "run_factors": {
                configuration: {program: metric.to_json() for program, metric in programs.items()}
                for configuration, programs in breakdown.factors.items()
            },
            "geometric_means": {name: metric.to_json() for name, metric in breakdown.geomeans.items()},
        }
    return data


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, required=True, help="raw results of run_ab_benchmarks.py")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="relative change from which on a result is flagged (default: %(default)s)",
    )
    parser.add_argument("--markdown-out", type=Path, default=None, help="write the markdown report here")
    parser.add_argument("--html-out", type=Path, default=None, help="write the HTML report here")
    parser.add_argument("--json-out", type=Path, default=None, help="write the comparison as JSON here")
    parser.add_argument("--run-url", default=None, help="link to the workflow run, shown in the reports")
    parser.add_argument("--report-url", default=None, help="link to the full (HTML) report, shown in the markdown")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_arguments(argv)
    if not arguments.results_dir.is_dir():
        print(f"ERROR: {arguments.results_dir} does not exist", file=sys.stderr)
        return 2
    comparison = load(arguments.results_dir, arguments.threshold)

    markdown = format_report(comparison, arguments.run_url, arguments.report_url)
    print(markdown)
    outputs = [
        (arguments.markdown_out, lambda: markdown),
        (arguments.html_out, lambda: format_html(comparison, arguments.run_url)),
        (arguments.json_out, lambda: json.dumps(comparison_to_json(comparison), indent=2) + "\n"),
    ]
    for path, content in outputs:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content(), encoding="utf-8")
            print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
