"""Hide the work-in-progress end-to-end tests from ``pytest`` collection.

See ``__init__.py`` for the ``unittest`` counterpart; both run the tests only
when ``DP_RUN_WIP_TESTS=1`` is set.
"""

import os

collect_ignore_glob = [] if os.getenv("DP_RUN_WIP_TESTS", "0") == "1" else ["*"]
