# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

install: venv
# install discopop_explorer, library, profiler and hotspot_detection
	venv/bin/pip install -e . ./profiler -e ./explorer -e ./library -e ./GUI ./hotspot_detection -e ./mcp_server

install_gui: venv
	venv/bin/pip install -e ./GUI

venv:
	python3 -m venv venv

uninstall:
	venv/bin/pip uninstall . ./profiler ./explorer ./library ./hotspot_detection

veryclean:
	rm -rf venv
	rm -rf build
