# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A visualized detection must not write the visualizer (and its Tk frame) into the dumped results."""

from typing import Any, cast

import jsonpickle  # type: ignore
import networkx as nx  # type: ignore
import pytest

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.functions.PEGraph.output.json import dump_to_pickled_json
from discopop_library.result_classes.DetectionResult import DetectionResult

pytest.importorskip("discopop_gui.Extendables.Plottable")


class _FakeVisualizer:
    """Stands in for the visualizer, which holds the Tk frame of the GUI."""

    marker = "tk-frame-of-the-gui"


def _visualized_pet() -> PEGraphX:
    return PEGraphX(nx.MultiDiGraph(), [], {}, visualizer=cast(Any, _FakeVisualizer()))


def test_the_detection_result_dump_leaves_out_the_visualizer() -> None:
    result = DetectionResult(_visualized_pet())

    dumped = result.dump_to_pickled_json()

    assert "_FakeVisualizer" not in dumped
    restored = jsonpickle.decode(dumped, keys=True)
    assert restored.pet._visualizer is None
    assert not restored.pet.plottable()
    # the running detection keeps drawing
    assert result.pet.plottable()


def test_the_pet_dump_leaves_out_the_visualizer() -> None:
    assert "_FakeVisualizer" not in dump_to_pickled_json(_visualized_pet())
