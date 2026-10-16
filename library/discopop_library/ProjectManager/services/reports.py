# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Lookup of the reports the ProjectManager generated below ``<project_dir>/reports``."""

import os
from enum import Enum
from typing import Optional, Tuple

REPORT_PDF_NAME = "full_report.pdf"


class ReportProblem(Enum):
    NO_REPORTS_DIRECTORY = "no reports directory"
    NO_REPORT = "no report"
    NO_PDF = "no pdf"


def find_latest_report_pdf(project_dir: str) -> Tuple[Optional[str], Optional[ReportProblem]]:
    """The PDF of the newest report (the last one in name order), or why there is none."""
    reports_dir = os.path.join(project_dir, "reports")
    if not os.path.exists(reports_dir):
        return None, ReportProblem.NO_REPORTS_DIRECTORY
    report_dirs = sorted(d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d)))
    if not report_dirs:
        return None, ReportProblem.NO_REPORT
    pdf_path = os.path.join(reports_dir, report_dirs[-1], REPORT_PDF_NAME)
    if not os.path.exists(pdf_path):
        return None, ReportProblem.NO_PDF
    return pdf_path, None
