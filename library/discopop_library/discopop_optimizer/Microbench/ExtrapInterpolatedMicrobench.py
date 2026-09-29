# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Dict, List, Tuple, Union, cast


import sympy  # type: ignore
from extrap.entities.callpath import Callpath  # type: ignore
from extrap.entities.metric import Metric  # type: ignore
from extrap.entities.model import Model  # type: ignore
from extrap.entities.parameter import Parameter  # type: ignore
from extrap.fileio.json_file_reader import read_json_file  # type: ignore
from extrap.modelers.model_generator import ModelGenerator  # type: ignore
from extrap.modelers.multi_parameter.multi_parameter_modeler import MultiParameterModeler  # type: ignore
from sympy.parsing.sympy_parser import parse_expr  # type: ignore

from discopop_library.discopop_optimizer.Microbench.Microbench import (
    Microbench,
    MicrobenchType,
    MicrobenchDimension,
    MicrobenchCoordinate,
)


# This class uses extrap to extrapolate microbench measurements.
class ExtrapInterpolatedMicrobench(Microbench):
    models: Dict[Tuple[Callpath, Metric], Model]

    def __init__(self, jsonFile: str):
        experiment = read_json_file(jsonFile)
        modeler = MultiParameterModeler()
        modeler.single_parameter_modeler.use_crossvalidation = False
        model_generator = ModelGenerator(experiment, modeler=modeler)  # TODO use_median??
        model_generator.model_all()
        self.models = experiment.modelers[0].models

    # convenient for debugging: print the model functions
    def printModelFunctions(self) -> None:
        for callpathMetric, model in self.models.items():
            test = str(callpathMetric[0]).ljust(12)
            metric = str(callpathMetric[1])
            if metric == "Test time in us":
                metric = "Test:      "
            elif metric == "Reference time in us":
                metric = "Reference: "
            elif metric == "Overhead time in us":
                metric = "Overhead:  "
            function = model.hypothesis.function.to_string()
            print(test, metric, function)

    def getFunctionString(
        self,
        benchType: MicrobenchType = MicrobenchType.DOALL,
        benchDim: MicrobenchDimension = MicrobenchDimension.OVERHEAD,
    ) -> str:
        return str(self.models[(Callpath(benchType), Metric(benchDim))].hypothesis.function.to_string())

    def getFunctionSympy(
        self,
        benchType: MicrobenchType = MicrobenchType.DOALL,
        benchDim: MicrobenchDimension = MicrobenchDimension.OVERHEAD,
    ) -> sympy.Expr:
        function_str = self.getFunctionString(benchType, benchDim)
        # NOTE: replacement order matters! "ab".replace("a","b").replace("b","a") --> "aa", NOT "ba"
        function_str = function_str.replace("^", "**")
        function_str = function_str.replace("r", "iterations")
        function_str = function_str.replace("p", "threads")
        function_str = function_str.replace("q", "workload")
        # define replacements to match representations used in extrap output
        function_mappings = {"log2": lambda x: sympy.log(x, 2)}
        expr = parse_expr(function_str, local_dict=function_mappings)
        return cast(sympy.Expr, expr)

    def getMeasurements(
        self,
    ) -> Dict[
        MicrobenchType,
        Dict[MicrobenchDimension, Dict[MicrobenchCoordinate, List[float]]],
    ]:
        raise NotImplementedError("TODO")  # TODO

    def toJSON(self) -> str:
        raise NotImplementedError("TODO")  # TODO

    def evaluateInterpolation(
        self,
        benchType: MicrobenchType,
        benchDim: MicrobenchDimension,
        benchCoord: Union[MicrobenchCoordinate, Tuple[int, float, float]],
    ) -> float:
        return cast(
            float, self.models[(Callpath(benchType), Metric(benchDim))].hypothesis.function.evaluate([*benchCoord])
        )
