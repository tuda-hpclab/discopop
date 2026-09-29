# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import TypeVar

from discopop_gui.Objects.Canvases.Viewables.Base import Base as ViewableCanvas

ViewableCanvasT = TypeVar("ViewableCanvasT", bound=ViewableCanvas)