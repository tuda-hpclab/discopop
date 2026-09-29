# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple, TypeVar, Union, overload

import numpy as np

from discopop_library.discopop_optimizer.Microbench.Microbench import (
    Microbench,
    MicrobenchType,
    MicrobenchDimension,
    MicrobenchCoordinate,
)

T = TypeVar("T")


def __partition(pred: Callable[[T], bool], list: List[T]) -> Tuple[List[T], List[T]]:
    trues: List[T] = []
    falses: List[T] = []
    for item in list:
        if pred(item):
            trues.append(item)
        else:
            falses.append(item)
    return trues, falses


def __remove_outliers_using_iqr(values: List[float], iqr_factor: float = 1.5) -> List[float]:
    values.sort()
    q1, q3 = np.percentile(values, [25, 75], method="linear")
    iqr = q3 - q1
    lower_bound = q1 - iqr_factor * iqr
    upper_bound = q3 + iqr_factor * iqr
    trimmed, outliers = __partition(lambda x: (x >= lower_bound and x <= upper_bound), values)
    return trimmed


@dataclass
class PureDataMicrobench(Microbench):
    measurements: Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]

    @overload
    def __getitem__(
        self, key: MicrobenchType
    ) -> Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]]: ...

    @overload
    def __getitem__(
        self, key: Tuple[MicrobenchType, MicrobenchDimension]
    ) -> Dict[MicrobenchCoordinate, List[float]]: ...

    @overload
    def __getitem__(self, key: Tuple[MicrobenchType, MicrobenchDimension, MicrobenchCoordinate]) -> List[float]: ...

    # allow to use this class like a dictionary
    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, MicrobenchType):
            return self.measurements[key]
        elif (
            (isinstance(key, tuple) or isinstance(key, List))
            and len(key) == 2
            and isinstance(key[0], MicrobenchType)
            and isinstance(key[1], MicrobenchDimension)
        ):
            return self.measurements[key[0]][key[1]]
        elif (
            (isinstance(key, tuple) or isinstance(key, List))
            and len(key) == 3
            and isinstance(key[0], MicrobenchType)
            and isinstance(key[1], MicrobenchDimension)
            and isinstance(key[2], MicrobenchCoordinate)
        ):
            return self.measurements[key[0]][key[1]][key[2]]
        else:
            raise KeyError("Invalid key type:" + str(type(key)))

    # allow to use this class like a dictionary
    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(key, MicrobenchType):
            if not isinstance(value, Dict):
                raise ValueError(
                    "Invalid value type: "
                    + str(type(value))
                    + " expected: Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]]"
                )
            self.measurements[key] = value
        elif (
            (isinstance(key, tuple) or isinstance(key, List))
            and len(key) == 2
            and isinstance(key[0], MicrobenchType)
            and isinstance(key[1], MicrobenchDimension)
        ):
            if not isinstance(value, Dict):
                raise ValueError(
                    "Invalid value type: " + str(type(value)) + " expected: Dict[MicrobenchCoordinate, List[float]]"
                )
            self.measurements[key[0]][key[1]] = value
        elif (
            (isinstance(key, tuple) or isinstance(key, List))
            and len(key) == 3
            and isinstance(key[0], MicrobenchType)
            and isinstance(key[1], MicrobenchDimension)
            and isinstance(key[2], MicrobenchCoordinate)
        ):
            if not isinstance(value, List):
                self.measurements[key[0]][key[1]][key[2]] = value
        else:
            raise KeyError("Invalid key type:" + str(type(key)))

    def removeOutliers(self) -> None:
        for type, dimMap in self.measurements.items():
            for dim, coordMap in dimMap.items():
                for coord, values in coordMap.items():
                    self.measurements[type][dim][coord] = __remove_outliers_using_iqr(values)

    def useMedian(self) -> None:
        for type, dimMap in self.measurements.items():
            for dim, coordMap in dimMap.items():
                for coord, values in coordMap.items():
                    self.measurements[type][dim][coord] = [np.median(values).item()]

    def useMean(self) -> None:
        for type, dimMap in self.measurements.items():
            for dim, coordMap in dimMap.items():
                for coord, values in coordMap.items():
                    self.measurements[type][dim][coord] = [np.mean(values).item()]

    def removeZeroParameters(self) -> None:
        for type, dimMap in self.measurements.items():
            for dim, coordMap in dimMap.items():
                for coord in list(coordMap.keys()):
                    if 0 in coord:
                        del self.measurements[type][dim][coord]

    def clampValues(
        self,
        dim: List[MicrobenchDimension] = [
            MicrobenchDimension.REFERENCE,
            MicrobenchDimension.TEST,
            MicrobenchDimension.OVERHEAD,
        ],
        min: float = float("-inf"),
        max: float = float("inf"),
    ) -> None:
        for type, dimMap in self.measurements.items():
            for d in dim:
                if d in dimMap:
                    for coord, values in dimMap[d].items():
                        self.measurements[type][d][coord] = [
                            v if v >= min and v <= max else (min if v < min else max) for v in values
                        ]

    def merge(self, other: PureDataMicrobench) -> None:
        for type, dimMap in other.measurements.items():
            if type not in self.measurements:
                self.measurements[type] = {}
            for dim, coordMap in dimMap.items():
                if dim not in self.measurements[type]:
                    self.measurements[type][dim] = {}
                for coord, values in coordMap.items():
                    if coord not in self.measurements[type][dim]:
                        self.measurements[type][dim][coord] = []
                    self.measurements[type][dim][coord].extend(values)
        # TODO check for duplicates? (but maybe we want them?)

    def mergeAll(self, others: List[PureDataMicrobench]) -> None:
        for other in others:
            self.merge(other)

    # inherited from Microbench
    def getMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        return self.measurements

    # inherited from Microbench
    def toJSON(self) -> str:
        return json.dumps(
            {
                "measurements": {
                    type.value: {
                        dim.value: [
                            {"point": list(point), "values": values}
                            for point, values in self.measurements[type][dim].items()
                        ]
                        for dim in self.measurements[type].keys()
                        # for dim in MicrobenchDimension
                    }
                    for type in self.measurements.keys()
                    # for type in MicrobenchType
                },
                "parameters": ["Threads", "Workload", "Iterations"],
            }
        )

    # inherited from Microbench
    def evaluateInterpolation(
        self,
        benchType: MicrobenchType,
        benchDim: MicrobenchDimension,
        benchCoord: Union[MicrobenchCoordinate, Tuple[int, float, float]],
    ) -> float:
        raise TypeError("This class does not support interpolation.")
