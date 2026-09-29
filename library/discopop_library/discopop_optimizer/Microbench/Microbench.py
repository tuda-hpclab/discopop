# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

import matplotlib  # type: ignore
import numpy as np

matplotlib.use("Agg")
from matplotlib import cm  # type: ignore
from matplotlib import pyplot as plt  # type: ignore
from matplotlib.ticker import LinearLocator  # type: ignore


class MicrobenchType(str, Enum):
    COPYIN = "COPYIN"
    COPYPRIVATE = "COPY_PRIVATE"
    DOALL = "DOALL"
    FIRSTPRIVATE = "FIRSTPRIVATE"
    SEPARATED = "SEPARATED"
    SHARED = "SHARED"
    PRIVATE = "PRIVATE"
    FOR = "FOR"


class MicrobenchDimension(str, Enum):
    REFERENCE = "Reference time in us"
    TEST = "Test time in us"
    OVERHEAD = "Overhead time in us"


class MicrobenchCoordinate(NamedTuple):
    threads: int
    workload: float
    iterations: int


class Microbench(ABC):
    @abstractmethod
    def getMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        raise TypeError("Pure virtual method called")

    @abstractmethod
    def toJSON(self) -> str:
        raise TypeError("Pure virtual method called")

    @abstractmethod
    def evaluateInterpolation(
        self,
        benchType: MicrobenchType,
        benchDim: MicrobenchDimension,
        benchCoord: Union[MicrobenchCoordinate, Tuple[int, float, float]],
    ) -> float:
        raise TypeError("Pure virtual method called")

    def plotInterpolation(
        self,
        type: MicrobenchType,
        dim: MicrobenchDimension,
        iterations: int,
        threads: range = range(1, 9),
        workloads: range = range(0, 201),
        file: Optional[Path] = None,
    ) -> None:
        logging.info("plotting interpolation to %s", str(file.absolute() if file else "<screen>"))
        # coords = list(self.getMeasurements()[type][dim].keys())
        # minWorkload = coords[0].workload
        # maxWorkload = coords[0].workload
        # for coord in coords[1:]:
        #    if coord.workload > maxWorkload:
        #        maxWorkload = coord.workload
        #    if coord.workload < minWorkload:
        #        minWorkload = coord.workload
        # threads = np.linspace(1, 8, 8, endpoint=True).tolist() # threads
        # workloads = np.linspace(minWorkload, maxWorkload, 50).tolist() # workload

        # x axis: threads
        # y axis: workloads
        # z axis: measurement values
        # (iterations are fixed based on input parameter)
        z = [self.evaluateInterpolation(type, dim, (i, j, iterations)) for i in threads for j in workloads]  # results
        X, Y = np.meshgrid(threads, workloads)  # type: ignore
        Z = np.array(z).reshape(len(threads), len(workloads)).transpose()

        fig, ax = plt.subplots(subplot_kw={"projection": "3d"})  # type: ignore
        # ignored type due to incompatibilities between local mypy and GitHub ci
        surf = ax.plot_surface(X, Y, Z, cmap=cm.coolwarm, linewidth=0, antialiased=False)  # type: ignore
        ax.set_zlim(0, np.nanmax(z))  # type: ignore
        ax.zaxis.set_major_locator(LinearLocator(10))  # type: ignore
        fig.colorbar(surf, shrink=0.5, aspect=5)

        plt.xlabel("Threads")
        plt.ylabel("Workload")
        plt.title(f"{type.value} {dim.value}:\ninterpolation for {iterations} iterations")
        if file is None:
            plt.show()
        else:
            plt.savefig(file)
