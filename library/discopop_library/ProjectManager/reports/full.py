# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import datetime
import json
import os
import textwrap
import time

from matplotlib import pyplot as plt

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

import logging

from discopop_library.ProjectManager.reports.console import print_console_report
from discopop_library.ProjectManager.reports.csv import generate_csv_report
from discopop_library.ProjectManager.reports.efficiency import generate_efficiency_report
from discopop_library.ProjectManager.reports.execution_time import generate_execution_time_report
from matplotlib.backends.backend_pdf import PdfPages  # type: ignore

from discopop_library.ProjectManager.reports.execution_time_full import generate_execution_time_report_full
from discopop_library.ProjectManager.reports.speedup import generate_speedup_report

logger = logging.getLogger("ProjectManager")


def generate_full_report(arguments: ProjectManagerArguments) -> None:
    timestamp = datetime.datetime.fromtimestamp(time.time()).strftime("%Y_%m_%d_%H-%M-%S")
    # create settings page
    settings_page = plt.figure()
    settings_page.clf()

    settings_text = ""
    settings_text += "Project path: " + "\n    ".join(textwrap.wrap(arguments.project_root, width=70))

    text_obj = settings_page.text(0.05, 0.75, settings_text, transform=settings_page.transFigure, ha="left")  # type: ignore
    text_obj.set_fontsize("small")

    # create plots
    print_console_report(arguments, timestamp)
    generate_csv_report(arguments, timestamp)
    generate_execution_time_report_full(arguments, timestamp)
    generate_execution_time_report(arguments, timestamp)
    generate_speedup_report(arguments, timestamp)
    generate_efficiency_report(arguments, timestamp)

    # setup PDF creation
    report_path = os.path.join(arguments.project_dir, "reports", timestamp, "full_report.pdf")
    page = PdfPages(report_path)

    fig_nums = plt.get_fignums()  # type: ignore
    figs = [plt.figure(n) for n in fig_nums]
    for fig in figs:
        fig.savefig(page, format="pdf")  # type: ignore
    page.close()
    logger.info("Created full report: " + str(report_path))

    if arguments.show_report:
        logger.info("Opening the stored report..")
        os.system("xdg-open " + report_path)
