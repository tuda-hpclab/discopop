# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser

from .hotspot_analyzer import HotspotAnalyzerArguments, run


def parse_args() -> HotspotAnalyzerArguments:
    """Parse the arguments passed to the hotspot_analyzer"""
    parser = ArgumentParser(description="Hotspot Analyzer")
    parser.add_argument(
        "--input-dir",
        default="private",
        help="Directory inside hotspot_detection/ holding cs_id.txt and the "
        "hotspot_result_<N>.txt files to analyze. Default: private",
    )
    parser.add_argument(
        "--no-merge-runs",
        action="store_true",
        help="Analyze the input directory verbatim instead of first renumbering its runs "
        "into one build-independent id space. Region ids are only unique within a single "
        "instrumented build, so this is only correct for a project compiled exactly once.",
    )
    arguments = parser.parse_args()
    return HotspotAnalyzerArguments(input_dir=arguments.input_dir, merge_runs=not arguments.no_merge_runs)


def main() -> None:
    arguments = parse_args()
    run(arguments)


if __name__ == "__main__":
    main()
