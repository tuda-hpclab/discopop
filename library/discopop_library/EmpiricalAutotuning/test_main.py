# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any
from unittest import mock

import pytest

from discopop_library.EmpiricalAutotuning import __main__ as autotuner_main


def test_an_interrupt_ends_the_autotuner_without_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    def interrupted(_arguments: Any) -> None:
        raise KeyboardInterrupt

    with (
        mock.patch.object(autotuner_main, "parse_args"),
        mock.patch.object(autotuner_main, "setup_logger"),
        mock.patch.object(autotuner_main, "run", interrupted),
    ):
        with pytest.raises(SystemExit) as exit_info:
            autotuner_main.main()
    assert exit_info.value.code == autotuner_main.INTERRUPTED_EXIT_CODE
    assert capsys.readouterr().err == "Autotuning interrupted.\n"
