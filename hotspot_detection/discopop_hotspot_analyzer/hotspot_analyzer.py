# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os.path
import numpy as np
import json
import sys
from typing import Dict, List, Optional
from dataclasses import dataclass

from .region_keys import merged_dir, render_merged_analysis_input

inf = float("inf")


@dataclass
class HotspotAnalyzerArguments(object):
    """Container Class for the arguments passed to the hotspot analyzer

    ``input_dir`` names the directory holding ``cs_id.txt`` and the
    ``hotspot_result_<N>.txt`` files, relative to ``hotspot_detection/``. It
    defaults to ``private`` -- the profiler's own output -- and exists so a caller
    can supply a pre-merged measurement series instead, whose region ids span
    several instrumented builds.

    ``merge_runs`` renumbers the profiler's runs into one canonical,
    build-independent id space before analyzing them (see
    :mod:`~discopop_hotspot_analyzer.region_keys`). On by default, because region
    ids in ``private/`` are only unique within one instrumented build: analyzing
    it directly joins measurements of different regions as soon as the project
    was compiled more than once. It only applies to the default ``input_dir`` --
    a caller naming one explicitly has already prepared the series it wants
    analyzed, and gets it analyzed verbatim.
    """

    DEFAULT_INPUT_DIR = "private"

    input_dir: str = DEFAULT_INPUT_DIR
    merge_runs: bool = True

    @property
    def merges_runs(self) -> bool:
        """Whether this invocation renumbers the runs before analyzing them."""
        return self.merge_runs and self.input_dir == self.DEFAULT_INPUT_DIR

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        """Validate the arguments passed to the hotspot analyzer, e.g check if given files exist"""
        validation_failure = False

        if os.path.isabs(self.input_dir) or os.path.pardir in self.input_dir.split(os.sep):
            print(f"--input-dir must be a relative path inside hotspot_detection/: {self.input_dir}")
            validation_failure = True

        if validation_failure:
            print("Exiting...")
            sys.exit()


class cs:
    def __init__(self, csid: int) -> None:
        self.csid = csid  # note: csid is a unique identifier
        self.typ = "FUNCTION"  # options: FUNCTION, LOOP
        self.fid = 0  # file id
        self.lineNum = 0  # line number
        self.name = ""  # only for functions: name of function
        self.runtimes: List[float] = []
        self.level = 0
        self.hot = True
        self.hotness = "MAYBE"  # possible: YES, NO, MAYBE

        self.delta = -1.0
        self.avr = 0.0
        self.sum: float = -1
        self.minVal = inf
        self.maxVal = 0.0
        self.ratio = 0.0
        self.topAvr = False
        self.topRatio = False

    def toJSON(self) -> str:
        return json.dumps(self.__dict__, indent=4)

    def addData(self, runtime: float) -> None:
        self.runtimes.append(runtime)

    def addInfo(self, tp: str, linN: int, filN: int, namN: str) -> None:
        self.typ = tp
        self.lineNum = linN
        self.fid = filN
        self.name = namN

    def updateLevel(self, lvl: int) -> None:
        self.level = lvl

    def calMin(self) -> None:
        for x in self.runtimes:
            self.minVal = min(x, self.minVal)

    def roundMin(self) -> None:
        if self.minVal == 0:
            self.minVal = 0.000001

    def calMax(self) -> None:
        for x in self.runtimes:
            self.maxVal = max(x, self.maxVal)

    def calDelta(self) -> None:
        self.delta = self.maxVal - self.minVal

    def calRatio(self) -> None:
        self.ratio = 1 / ((self.minVal / self.maxVal) + 1)

    def calAvr(self) -> None:
        temp_sum = 0.0
        for i in self.runtimes:
            temp_sum += i
        self.avr = temp_sum / len(self.runtimes)
        self.sum = temp_sum

    def isHot(self, bl: bool) -> None:
        self.hot = bl

    def isTopAvr(self, bl: bool) -> None:
        self.topAvr = bl

    def isTopRatio(self, bl: bool) -> None:
        self.topRatio = bl

    def getHotness(self) -> str:
        if self.topAvr and self.topRatio:
            return "YES"
        if self.topAvr != self.topRatio:
            return "MAYBE"
        return "NO"


def __print_cs_list(list: List[cs]) -> None:
    for x in list:
        print(
            "##cs lists:",
            str(x.typ).ljust(6),
            str(x.csid).ljust(2),
            str(x.fid).ljust(2),
            "{:10.7f}".format(x.runtimes[0] if x.runtimes else 0.0),
            "avr:" + "{:10.7f}".format(x.avr),
            "sum:" + "{:10.7f}".format(x.sum),
            f"ratio:{x.ratio} min:{x.minVal} max:{x.maxVal} topAvr:{x.topAvr} topRatio:{x.topRatio}",
        )
    print(len(list))


def _record_analysis(dot_discopop: str) -> None:
    """Record the finished analysis in the analysis record of ``dot_discopop``, if DiscoPoP's library is available.

    The analyzer is a package of its own and must not depend on ``discopop_library``, so the record is written only
    when the library can be imported. Never raises: the bookkeeping must not fail the analysis.
    """
    try:
        from discopop_library.AnalysisRecord import record_step, step_status
    except ImportError:
        return
    try:
        # the configurations the analyzed runs came from, as recorded by the hotspot detection runs
        recorded = step_status(dot_discopop, "hotspot_detection").params.get("configs", [])
        configs = sorted(str(c) for c in recorded)
        record_step(dot_discopop, "hotspot_analysis", {"configs": configs})
    except Exception as e:
        print("Could not record the hotspot analysis: " + str(e))


def run(arguments: HotspotAnalyzerArguments) -> None:
    # TO BE USED FROM WITHIN THE .discopop directory!
    discopop_dir = os.getcwd()
    print("DiscoPoP Dir: ", discopop_dir)
    # enter hotspot_detection/private folder
    hotspot_detection_dir = os.path.join(discopop_dir, "hotspot_detection")
    hotspot_detection_private_dir = os.path.join(hotspot_detection_dir, arguments.input_dir)
    if not os.path.exists(hotspot_detection_dir):
        raise FileNotFoundError(
            "Static analysis and profiling results not found: Please execute the static analysis and profiling!"
        )
    if not os.path.exists(hotspot_detection_private_dir):
        raise FileNotFoundError(
            "Static analysis and profiling results not found: Please execute the static analysis and profiling!"
        )

    # Region ids are only unique within one instrumented build, so the runs are
    # renumbered into one canonical id space keyed by source location before
    # being joined. Without this, a project compiled twice (which is what running
    # two configurations amounts to) has its second build's ids appended to
    # cs_id.txt, and each run contributes 0.0 for every id it does not know --
    # which the analyzer would read as a real measurement.
    if arguments.merges_runs:
        merged_regions = render_merged_analysis_input(discopop_dir)
        if merged_regions is None:
            print("Merging runs: nothing to merge, analyzing " + arguments.input_dir + " as-is.")
        else:
            print(f"Merging runs: {merged_regions} code regions across builds.")
            hotspot_detection_private_dir = merged_dir(discopop_dir)

    os.chdir(hotspot_detection_private_dir)

    # CS LIST
    cslist: List[cs] = []

    def getHots(bl: bool) -> List[cs]:
        hots = []
        for x in cslist:
            if x.hot == bl:
                hots.append(x)
        return hots

    def getSum(lst: List[cs]) -> float:
        hot_sum = 0.0
        for i in lst:
            hot_sum += i.avr
        return hot_sum

    # READ FILES
    # cs_id.txt seeds the region list, rather than hotspot_result_0.txt: a region
    # need not be present in every run (it may belong to a build that a later
    # configuration did not instrument), and seeding from one run would drop it.
    print("Reading cs_id.txt ... ", end="")
    cs_index: Dict[int, cs] = {}
    csfile = open("cs_id.txt", "r")
    for line in csfile:
        temp = []
        for word in line.split():
            temp.append(word)
        if len(temp) < 4:
            continue

        csid = int(temp[0])
        temp_cs = cs_index.get(csid)
        if temp_cs is None:
            temp_cs = cs(csid)
            cs_index[csid] = temp_cs
            cslist.append(temp_cs)
        if temp[1] == "func":
            temp_cs.addInfo("FUNCTION", int(temp[2]), int(temp[3]), temp[4] if len(temp) > 4 else "")
        if temp[1] == "loop":
            temp_cs.addInfo("LOOP", int(temp[2]), int(temp[3]), "")
    csfile.close()
    print("Done.")

    print("Reading hotspot results... ", end="")
    i = 0
    result_num = 0
    while True:
        file_name = f"hotspot_result_{i}.txt"
        i += 1
        if os.path.exists(file_name):
            pass
        else:
            break
        result_num += 1
        data_file = open(file_name, "r")
        for line in data_file:
            temp = []
            for word in line.split():
                temp.append(word)
            temp_cs = cs_index.get(int(temp[0]))
            if temp_cs:
                temp_cs.addData(float(temp[1]))
        data_file.close()

    print("Done.")

    # CALCULATE

    __print_cs_list(cslist)

    nz_cs_list: List[cs] = []

    print("Calculate Averages ... ", end="")
    for j in cslist:
        # A region with no measurements at all is not averageable. This happens
        # for regions that exist in the id table but were never entered by any
        # run, and is filtered out below along with the all-zero ones.
        if j.runtimes:
            j.calAvr()
    print("Done.")

    for m in cslist:
        if m.sum > 0:
            nz_cs_list.append(m)

    print("Calculate Min,Max,Avg ... ", end="")
    for j in nz_cs_list:
        j.calMin()
        j.calMax()
        j.calAvr()
    print("Done.")

    print("Calculate Delta and Ratio ... ", end="")
    for j in nz_cs_list:
        j.roundMin()
        j.calDelta()
        j.calRatio()
    print("Done.")

    tempmax = 0.0
    max_cs: Optional[cs] = None

    for x in nz_cs_list:
        if x.maxVal >= tempmax:
            tempmax = x.maxVal
            max_cs = x

    if max_cs is not None:
        print("max cs: ", max_cs.csid, " ", max_cs.maxVal)

    # sorting cs list based on avr and ratio
    print("Sort CS lists ... ", end="")
    sorted_cs_avr = nz_cs_list.copy()
    sorted_cs_avr.sort(key=lambda x: x.avr, reverse=True)

    sorted_cs_ratio = nz_cs_list.copy()
    sorted_cs_ratio.sort(key=lambda x: x.ratio, reverse=True)
    print("Done.")

    # detecting hotspots of each list by mean or median
    print("Detect hotspots ... ", end="")
    mean = True
    if mean:
        avr_middle = np.mean([x.avr for x in nz_cs_list])
        ratio_middle = np.mean([x.ratio for x in nz_cs_list])
    else:
        avr_middle = np.median([x.avr for x in nz_cs_list])
        ratio_middle = np.median([x.ratio for x in nz_cs_list])

    for x in nz_cs_list:
        if x.avr >= avr_middle:
            x.isTopAvr(True)

    for x in nz_cs_list:
        if x.ratio >= ratio_middle:
            x.isTopRatio(True)
    print("Done")

    # print
    __print_cs_list(nz_cs_list)
    print(ratio_middle)

    # WRITE OUT RESULTS
    print("Output results ... ", end="")

    with open("hotspot_result.txt", "w") as f:
        for x in nz_cs_list:
            f.write(f"{x.csid} {x.ratio} {x.avr} {x.minVal} {x.maxVal} {x.getHotness()}\n")

    # categorize Hotspots based on my definition
    f = open("Hotspots.txt", "w")
    f.write("Is this code region a hotspot? \n")
    counter_y = 0
    counter_m = 0
    counter_n = 0
    for x in nz_cs_list:
        if x.topAvr and x.topRatio:
            counter_y += 1
            yes_no_maybe = " is YES"
            x.hotness = "YES"
        if x.topAvr != x.topRatio:
            counter_m += 1
            yes_no_maybe = " is MAYBE"
            x.hotness = "MAYBE"
        if not x.topAvr and not x.topRatio:
            counter_n += 1
            yes_no_maybe = " is NO"
            x.hotness = "NO"
        f.write(str(x.csid) + " " + str(x.name) + " at " + str(x.fid) + ":" + str(x.lineNum) + yes_no_maybe + "\n")
    f.write("Number of YES code regions: " + str(counter_y) + " \n")
    f.write("Number of MAYBE code regions: " + str(counter_m) + " \n")
    f.write("Number of NO code regions: " + str(counter_n) + " \n")
    f.write("Number of Non-zero code regions: " + str(counter_n + counter_m + counter_y) + " \n")
    f.close()

    # export results to Hotspots.json and store in "public" folder
    with open(os.path.join(hotspot_detection_dir, "Hotspots.json"), "w+") as outfile:
        outfile.write('{"code_regions": [')
        for id, x in enumerate(nz_cs_list):
            outfile.write(x.toJSON())
            if id != len(nz_cs_list) - 1:
                outfile.write(",\n")
            else:
                # last element of the list
                outfile.write("\n")
        outfile.write("]\n")
        outfile.write("}\n")

    print("Done")

    # last: the record promises that Hotspots.json is complete
    _record_analysis(discopop_dir)
