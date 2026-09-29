from typing import List, Tuple

# (dependency type, variable name) pairs that must NEVER appear in the
# dynamic dependency trace for this test case.
forbidden_dependencies_list: List[Tuple[str, str]] = [
    ("RAW", "GEPRESULT_arr"),
    ("WAR", "GEPRESULT_arr"),
    ("WAW", "GEPRESULT_arr"),
]
