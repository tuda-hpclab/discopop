# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
import sys

from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.PatchRepair.PatchRepairArguments import DEFAULT_HOTSPOT_TYPES, PatchRepairArguments
from discopop_library.PatchRepair.llm_backends import available_backends
from discopop_library.PatchRepair.llm_config import CONFIG_ENV_VAR, CONFIG_FILE_NAME
from discopop_library.PatchRepair.repair import run


def parse_args() -> PatchRepairArguments:
    """Parse the arguments passed to discopop_patch_repair."""
    parser = ArgumentParser(
        description="DiscoPoP Patch Repair: find the parallelization suggestions whose patches do not "
        "compile and let an LLM agent fix them."
    )

    # fmt: off
    parser.add_argument("--dot-dp-path", type=str, default=os.getcwd(), help="Path to the .discopop folder. Default: $(cwd)")
    parser.add_argument("-c", "--config", default="tiny", help="Execution configuration used to build the suggestions. Default: tiny")
    parser.add_argument("-ht", "--hotspot-types", type=str, default=DEFAULT_HOTSPOT_TYPES, help="Hotspot types to be considered. Suggestions classified 'no' contribute negligibly to the runtime, so they are skipped by default to save time and agent cost. If no hotspot information exists, all suggestions are classified as 'yes'. Options: yes,no,maybe. Default: " + DEFAULT_HOTSPOT_TYPES)
    parser.add_argument("-s", "--suggestions", default=None, help="Comma separated list of suggestion ids to repair. Overrides the hotspot filter.")
    parser.add_argument("-t", "--threads", type=int, default=1, help="Value of OMP_NUM_THREADS passed to the builds. Default: 1")

    parser.add_argument("--prompts", type=int, default=2, help="Independent repair attempts per suggestion, each starting from a fresh context and using the next template of the prompt ladder. Default: 2")
    parser.add_argument("--retries", type=int, default=2, help="Follow-up turns within one attempt: the previous failure is fed back into the same conversation. An attempt therefore costs at most 1 + retries agent calls. Default: 2")
    parser.add_argument("--max-attempts", dest="max_attempts", type=int, default=6, help="Hard ceiling on agent calls per suggestion, independent of --prompts x --retries. Default: 6")
    parser.add_argument("--max-repairs", dest="max_repairs", type=int, default=0, help="Stop after this many repaired suggestions. 0 disables the limit. Default: 0")
    parser.add_argument("--agent-error-retries", dest="agent_error_retries", type=int, default=2, help="Extra agent calls allowed per suggestion when a call produces no answer at all (unreachable provider, server error, no response within --agent-timeout). Such a call costs no tokens and gives the model no chance, so it is repeated in place instead of consuming a prompt or a retry. Once this allowance is used up the suggestion is recorded as 'agent_unreachable' rather than as a failed repair. Default: 2")

    parser.add_argument("--connection", default=None, help="Name of a connection from the LLM configuration (which model, through which backend). Default: the only connection defined, or an implicit one through the first installed agent.")
    parser.add_argument("--backend", default=None, help="LLM agent backend to use. Overrides the connection. Options: " + ", ".join(available_backends()))
    parser.add_argument("--model", default=None, help="Backend specific model id. Overrides the connection.")
    parser.add_argument("--agent-timeout", dest="agent_timeout", type=float, default=300.0, help="Timeout in seconds for a single agent call. Default: 300")
    parser.add_argument("--llm-config", dest="llm_config", default=None, help="Path to the LLM configuration (connections and backends). Default: <dot-dp-path>/patch_repair/" + CONFIG_FILE_NAME + ", overridable with $" + CONFIG_ENV_VAR + ".")
    parser.add_argument("--prompt-dir", dest="prompt_dir", default=None, help="Directory holding the prompt templates to use instead of the built-in ones.")

    parser.add_argument("--context-lines", dest="context_lines", type=int, default=60, help="Source lines of context included around each patched region. Default: 60")
    parser.add_argument("--max-error-chars", dest="max_error_chars", type=int, default=8000, help="Maximum number of characters of compiler diagnostics included in a prompt. Default: 8000")
    parser.add_argument("--max-prompt-chars", dest="max_prompt_chars", type=int, default=60000, help="Maximum prompt size. Content is dropped in a fixed order when exceeded; the patches themselves are never dropped. Default: 60000")

    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Run the whole pipeline but leave patch_generator/ untouched. Results are written to patch_repair/ only.")
    parser.add_argument("--restore", action="store_true", help="Restore the patches backed up by an earlier repair run and exit.")

    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # fmt: on

    arguments = parser.parse_args()

    try:
        return PatchRepairArguments(
            log_level=arguments.log.upper(),
            write_log=arguments.write_log,
            dot_dp_path=arguments.dot_dp_path,
            configuration=arguments.config,
            hotspot_types=arguments.hotspot_types,
            suggestions=arguments.suggestions,
            thread_count=arguments.threads,
            prompts=arguments.prompts,
            retries=arguments.retries,
            max_attempts=arguments.max_attempts,
            max_repairs=arguments.max_repairs,
            agent_error_retries=arguments.agent_error_retries,
            connection=arguments.connection,
            backend=arguments.backend,
            model=arguments.model,
            agent_timeout=arguments.agent_timeout,
            llm_config=arguments.llm_config,
            prompt_dir=arguments.prompt_dir,
            context_lines=arguments.context_lines,
            max_error_chars=arguments.max_error_chars,
            max_prompt_chars=arguments.max_prompt_chars,
            dry_run=arguments.dry_run,
            restore=arguments.restore,
        )
    except (ValueError, FileNotFoundError) as error:
        # A missing prerequisite names the file it is missing; printing that beats a
        # stack trace from the first subprocess that trips over it.
        print("ERROR: " + str(error))
        sys.exit(1)


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    arguments.log()
    sys.exit(run(arguments))


if __name__ == "__main__":
    main()
