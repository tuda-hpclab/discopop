<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# Benchmark comparison

Compares two versions of DiscoPoP with the pass overhead benchmark (`benchmark/pass_overhead`) and the callback
benchmark (`benchmark/injected_functions`), and reports what changed. The CI uses it to compare a pull request with
its target branch: it comments on the pull request and uploads an HTML report with charts (artifact
`benchmark-report`).

## Measuring

`run_ab_benchmarks.py` measures the version it belongs to ("head", run it with the Python of the venv that has this
version's profiler installed) and a version to compare with ("base"):

- `--base-python` is the Python of a venv with the base's profiler installed (`pip install <base>/profiler`, without
  `-e`)
- `--base-source-dir` is a checkout of the base, needed by the callback benchmark, which builds the runtime library
  from source

Both versions are measured with the drivers of the head, so the same programs and procedure are used on both sides.
The versions alternate round by round (head, base, base, head, ...), so that a change of the machine's speed during
the measurement affects both alike.

```sh
# pass overhead: 2 rounds x 3 repetitions per version
venv/bin/python benchmark/compare/run_ab_benchmarks.py --results-dir results \
    --head-label mine --base-label new_explorer --base-python ../base_venv/bin/python \
    pass-overhead --rounds 2 --repetitions 3

# callback cost, plus the callback breakdown unless --no-breakdown is given (takes long)
venv/bin/python benchmark/compare/run_ab_benchmarks.py --results-dir results \
    --head-label mine --base-label new_explorer --base-python ../base_venv/bin/python \
    callbacks --base-source-dir ../base_checkout --rounds 3 --repetitions 5
```

Without `--base-python` only the head is measured. A base that cannot be measured (its profiler is missing, its
callback benchmark does not build, a driver fails on it) is left out, and the report says why. A failure of the head
fails the run, as the drivers do on their own.

## Reporting

```sh
python3 benchmark/compare/compare_benchmarks.py --results-dir results \
    --markdown-out report.md --html-out report.html --json-out comparison.json
```

It needs no venv (standard library only). Per quantity it shows the median of both versions, the relative change
and, for repeated measurements, the p-value of a two-sided Mann-Whitney U test. A change is flagged when it is
larger than `--threshold` (default 10%) and significant (p < 0.05); quantities measured once per version (binary
sizes, the breakdown) are judged by the threshold alone, and callback changes below 0.25 ns are never flagged.
Lower is better for every quantity. The report never fails because of a regression.

The pass overhead factors are computed per round: each instrumented time is divided by the median uninstrumented
time of the same round, so the uninstrumented build serves as a control for the speed of the machine.

## Layout

- `run_ab_benchmarks.py`, `compare_benchmarks.py`: the two entry points
- `benchmark_compare/results.py`: the results directory, loading and comparing
- `benchmark_compare/stats.py`: medians, the U test (exact for small samples), the verdict
- `benchmark_compare/report_markdown.py`, `report_html.py`: the reports
- `benchmark_compare/test_*.py`: unit tests (`venv/bin/python -m pytest benchmark/compare`)
