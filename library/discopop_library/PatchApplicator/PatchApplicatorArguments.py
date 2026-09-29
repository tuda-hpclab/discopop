# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import sys
from dataclasses import dataclass
from typing import List

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments


@dataclass
class PatchApplicatorArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop_patch_applicator"""

    verbose: bool
    apply: List[str]
    rollback: List[str]
    clear: bool
    load: bool
    list: bool

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop_patch_applicator, e.g check if given files exist"""
        # check mutually exclusive arguments
        exit_required = False
        if self.clear and self.load:
            print("Please use only one of `--clear` or `--load`.")
            exit_required = True
        if len(self.apply) > 0 and len(self.rollback) > 0:
            print("Please use only one of '--apply' or '--rollback'.")
            exit_required = True
        if self.clear and (len(self.apply) > 0 or len(self.rollback)):
            print("Please use either '--clear' or any of '--apply' or '--rollback'.")
            exit_required = True
        if self.load and (len(self.apply) > 0 or len(self.rollback)):
            print("Please use either '--load' or any of '--apply' or '--rollback'.")
            exit_required = True
        if self.list:
            self.apply = []
            self.rollback = []
            self.clear = False
            self.load = False
        if exit_required:
            print("Exiting.")
            sys.exit(0)
