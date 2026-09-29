from typing import List, Tuple

# (dependency type, variable name) pairs that must NEVER appear in the
# dynamic dependency trace for this test case. `a` and `b` are two disjoint
# arrays never accessed from the same loop; a cross-array dependency between
# them would indicate an address/alias resolution bug.
forbidden_dependencies_list: List[Tuple[str, str]] = [
    ("RAW", "GEPRESULT_a"),
    ("WAR", "GEPRESULT_a"),
    ("WAW", "GEPRESULT_a"),
    ("RAW", "GEPRESULT_b"),
    ("WAR", "GEPRESULT_b"),
    ("WAW", "GEPRESULT_b"),
]
