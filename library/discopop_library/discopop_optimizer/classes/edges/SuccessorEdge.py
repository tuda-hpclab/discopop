# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from sympy import Symbol  # type: ignore

from discopop_library.discopop_optimizer.classes.edges.GenericEdge import GenericEdge


class SuccessorEdge(GenericEdge):
    pass

    # transfer costs will be summed up in the context objects which correspond to a given path
    # since storing update information as property of the edges does not generalize well.
