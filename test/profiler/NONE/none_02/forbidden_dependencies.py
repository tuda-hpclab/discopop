from typing import List, Tuple

# (dependency type, variable name) pairs that must NEVER appear in the
# dynamic dependency trace for this test case. Every iteration writes two
# provably disjoint indices of the same array (2*i and 2*i+1), so their
# addresses can never coincide across any pair of iterations.
forbidden_dependencies_list: List[Tuple[str, str]] = [
    ("RAW", "GEPRESULT_arr"),
    ("WAR", "GEPRESULT_arr"),
    ("WAW", "GEPRESULT_arr"),
]
