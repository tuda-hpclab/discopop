# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Compare the results of the pass overhead and callback benchmarks between two versions of DiscoPoP.

``run_ab_benchmarks.py`` measures both versions interleaved and stores the raw results, ``compare_benchmarks.py``
turns them into the report (markdown for the pull request comment, HTML, JSON). Only the standard library is
used, so the report can be produced without a venv.
"""
