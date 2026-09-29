# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Set


def main() -> None:
    gold_result_path = "/home/lukas/dependency_metadata.txt"
    gold_standard: Set[str] = set()

    with open(gold_result_path, "r") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            if line.startswith("#"):
                continue
            gold_standard.add(line)

    tested_result_path = "/home/lukas/git/Benchmarks/miniFE/dp/src/.discopop/profiler/dependency_metadata.txt"
    test_results: Set[str] = set()

    with open(tested_result_path, "r") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            if line.startswith("#"):
                continue
            test_results.add(line)

    print("Total gold standard: ", len(gold_standard))
    print("Total test results: ", len(test_results))
    # identify number of matching results
    matching = gold_standard.intersection(test_results)
    print("Matching: ", len(matching))

    # identify number of missed results
    missed = gold_standard.difference(test_results)
    print("Missed: ", len(missed))

    # identify number of additional results
    additional = test_results.difference(gold_standard)
    print("Additional: ", len(additional))


if __name__ == "__main__":
    main()
