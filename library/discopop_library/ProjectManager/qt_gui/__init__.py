# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The ProjectManager GUI drawn with Qt (PySide6).

It shares the logic in ``ProjectManager/services`` and the charts in ``ProjectManager/plots`` with the Tk GUI in
``ProjectManager/gui``, which it replaces panel by panel. Widgets are touched only on the main thread: background
work runs on the runners of ``services/jobs.py`` and reaches the widgets through ``qt_gui/job_adapter.py``.
"""

import os

# matplotlib picks its Qt binding from QT_API; without it, an installed PyQt could be chosen next to PySide6
os.environ.setdefault("QT_API", "PySide6")
