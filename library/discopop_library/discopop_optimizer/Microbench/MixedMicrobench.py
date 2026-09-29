# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, List, Tuple, Union

from discopop_library.discopop_optimizer.Microbench.Microbench import (
    Microbench,
    MicrobenchCoordinate,
    MicrobenchDimension,
    MicrobenchType,
)


# This class can be used to mix two microbench models.
# The inner model will be used for evaluation of the lower values
# The outer model will be used for evaluation of the higher values (if any coordinate point is higher than the threshold)
class MixedMicrobench(Microbench):
    inner: Microbench
    outer: Microbench
    threshold: MicrobenchCoordinate

    def __init__(self, inner: Microbench, outer: Microbench, threshold: MicrobenchCoordinate):
        self.inner = inner
        self.outer = outer
        self.threshold = threshold

    def getMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        raise TypeError(
            "This MixedMicrobench might be based on two different sets of measurements. Use getInnerMeasurements() or getOuterMeasurements() instead."
        )

    def getInnerMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        return self.inner.getMeasurements()

    def getOuterMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        return self.outer.getMeasurements()

    def toJSON(self) -> str:
        raise TypeError("This class does not support JSON serialization.")

    def evaluateInterpolation(
        self,
        benchType: MicrobenchType,
        benchDim: MicrobenchDimension,
        benchCoord: Union[MicrobenchCoordinate, Tuple[int, float, float]],
    ) -> float:
        if benchCoord[1:] <= self.threshold[1:]:
            return self.inner.evaluateInterpolation(benchType, benchDim, benchCoord)
        else:
            return self.outer.evaluateInterpolation(benchType, benchDim, benchCoord)
