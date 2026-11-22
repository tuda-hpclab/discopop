# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Dict

from PySide6.QtWidgets import QWidget


class Base(QWidget):
    def __init__(self, parent: QWidget | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent, *args, **kwargs)

    def serialize(self) -> Dict[str, Any]:
        return {}

    def deserialize(self, _: Dict[str, Any]) -> None:
        pass
