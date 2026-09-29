from typing import List, Tuple

# (sink location, variable name) pairs that must NEVER appear together in the
# dynamic dependency trace for this test case. `x` is only ever written/read
# at 1:4/1:7/1:8, `y` only at 1:5/1:11/1:12. A dependency entry whose sink is
# one variable's line but whose attributed variable is the *other* variable
# would indicate a memory-address aliasing bug between two unrelated locals.
forbidden_dependencies_list: List[Tuple[str, str]] = [
    ("1:11", "x"),
    ("1:12", "x"),
    ("1:4", "y"),
    ("1:7", "y"),
    ("1:8", "y"),
]
