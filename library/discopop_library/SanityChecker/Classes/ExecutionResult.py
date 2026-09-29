# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from typing import Optional


class ExecutionResult(object):
    return_code: int
    thread_sanitizer: bool
    validation_result: Optional[bool]

    def __init__(self, return_code: int, thread_sanitizer: bool, validation_result: Optional[bool]):
        self.return_code = return_code
        self.thread_sanitizer = thread_sanitizer
        self.validation_result = validation_result

    def __str__(self) -> str:
        return (
            ""
            + " code: "
            + str(self.return_code)
            + " TSAN: "
            + str(self.thread_sanitizer)
            + " VALIDATION: "
            + str(self.validation_result)
        )
