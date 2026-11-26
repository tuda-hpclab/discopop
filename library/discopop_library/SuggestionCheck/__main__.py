# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import os
import sys
from argparse import ArgumentParser

from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.SuggestionCheck.SuggestionCheckArguments import VERIFY_CHOICES, VERIFY_NONE
from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.run import run


def parse_args() -> SuggestionCheckArguments:
    parser = ArgumentParser(
        description="Checks the unsure suggestions of discopop_explorer --unsure-suggestions with an LLM agent. An "
        "approved suggestion rests on an assumption the agent states, and stays apart from DiscoPoP's suggestions."
    )
    # fmt: off
    parser.add_argument("--dot-dp-path", default=os.getcwd(), help="Path to the .discopop folder. Default: current "
                        "directory.")
    parser.add_argument("--project-root", default=None, help="The project; the agent works in a copy of its files. "
                        "Default: the directory holding the .discopop folder.")
    parser.add_argument("-s", "--suggestions", default=None, help="Comma separated pattern ids of unsure suggestions "
                        "to check. Default: all.")
    parser.add_argument("--max-suggestions", type=int, default=0, help="Check at most this many. Default: 0, no limit.")
    parser.add_argument("--prompts", type=int, default=2, help="Independent attempts per suggestion, each with a new "
                        "conversation. Default: 2")
    parser.add_argument("--retries", type=int, default=2, help="Follow-up turns within one attempt for answers which "
                        "cannot be used. Default: 2")
    parser.add_argument("--agent-error-retries", type=int, default=2, help="Calls without an answer (unreachable, "
                        "timeout) allowed per suggestion; they use none of the budget above. Default: 2")
    parser.add_argument("--no-review", dest="review", action="store_false", help="Do not have an approval reviewed "
                        "by a second agent call with a fresh conversation.")
    parser.add_argument("--verify", choices=VERIFY_CHOICES, default=VERIFY_NONE, help="Verify an approval by building "
                        "(build) or building, running and validating (run) it. Only none is implemented so far.")
    parser.add_argument("--connection", default=None, help="Connection of the LLM configuration (shared with "
                        "discopop_patch_repair).")
    parser.add_argument("--backend", default=None, help="LLM agent backend; overrides the connection.")
    parser.add_argument("--model", default=None, help="Model; overrides the connection.")
    parser.add_argument("--agent-timeout", type=float, default=600.0, help="Seconds per agent call. Default: 600")
    parser.add_argument("--llm-config", default=None, help="Alternative LLM configuration file.")
    parser.add_argument("--reject-rounding", dest="accept_rounding", action="store_false", help="Reject approvals "
                        "whose results may differ from the sequential program by rounding, i.e. through floating-point "
                        "operations in another order. Accepted by default; such approvals are marked in the results.")
    parser.add_argument("--prompt-dir", default=None, help="Directory with the project's own prompt "
                        "templates (check.md, review.md, retry.md). Default: "
                        ".discopop/project/prompts/suggestion_check, as edited in the GUI (Settings > Suggestion "
                        "check prompts). A template not found there is the shipped one.")
    parser.add_argument("--log", dest="log_level", default="WARNING", help="Log level. Default: WARNING")
    parser.add_argument("--write-log", action="store_true", help="Create a log file.")
    # fmt: on
    arguments = parser.parse_args()
    try:
        return SuggestionCheckArguments(
            log_level=arguments.log_level.upper(),
            write_log=arguments.write_log,
            dot_dp_path=arguments.dot_dp_path,
            project_root=arguments.project_root,
            suggestions=arguments.suggestions,
            max_suggestions=arguments.max_suggestions,
            prompts=arguments.prompts,
            retries=arguments.retries,
            agent_error_retries=arguments.agent_error_retries,
            review=arguments.review,
            verify=arguments.verify,
            connection=arguments.connection,
            backend=arguments.backend,
            model=arguments.model,
            agent_timeout=arguments.agent_timeout,
            llm_config=arguments.llm_config,
            accept_rounding=arguments.accept_rounding,
            prompt_dir=arguments.prompt_dir,
        )
    except ValueError as error:
        parser.error(str(error))


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    sys.exit(run(arguments))


if __name__ == "__main__":
    main()
