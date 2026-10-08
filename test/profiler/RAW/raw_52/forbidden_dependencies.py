from typing import List, Tuple

# (dependency type, variable name) pairs that must NEVER appear in the dynamic dependency trace for
# this test case. Nothing to guard against here: the case is about whether accesses are recorded at
# all, and every access this program makes is a real one.
forbidden_dependencies_list: List[Tuple[str, str]] = []
