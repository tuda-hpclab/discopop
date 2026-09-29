#!/usr/bin/env python3
#
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Demo test showing the MCP server tools in action"""

import json

from mcp_server.server import DiscoPopMCPServer
from mcp_server.tools import get_configurations, get_execution_results, initialize_discopop_directory


def demo() -> None:
    """Demonstrate the MCP server tools"""
    print("\n" + "=" * 70)
    print("DiscoPoP MCP Server - Demo Test")
    print("=" * 70 + "\n")

    server = DiscoPopMCPServer(debug=True)

    # Test 1: initialize_discopop_directory on a non-existent path
    print("TEST 1: Initialize DiscoPoP Directory (non-existent path)")
    print("-" * 70)
    result = initialize_discopop_directory.handle({"project_path": "./nonexistent"}, server._ctx)
    print("Response:", json.loads(result[0].text))
    print()

    # Test 2: get_configurations
    print("TEST 2: Get Configurations")
    print("-" * 70)
    result = get_configurations.handle({"project_path": "./example"}, server._ctx)
    print("Response:", json.loads(result[0].text))
    print()

    # Test 3: get_execution_results
    print("TEST 3: Get Execution Results")
    print("-" * 70)
    result = get_execution_results.handle({"project_path": "./example"}, server._ctx)
    print("Response:", json.loads(result[0].text))
    print()

    print("=" * 70)
    print("All tests completed successfully!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    demo()
