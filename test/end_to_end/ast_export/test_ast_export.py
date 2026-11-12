# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The AST that the compiler wrapper writes with the AST export plugin, against the one of the filtered dump.

The wrapper writes the AST of the files of FileMapping.txt. With the plugin (DiscoPoPASTExport-<clang major>.so, built
if the Clang development files exist) clang never writes the declarations of the other files; without it the complete
dump is filtered. Both have to give the explorer the same nodes.
"""

import json
import os
import shutil
import subprocess
import sysconfig
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import pytest

from discopop_explorer.utilities.ASTUtils import ClangASTGraph
from test.end_to_end.pipeline import _isolated_home

HERE = Path(__file__).parent
SRC_DIR = HERE / "src"

# what the plugin leaves out on purpose, none of it is looked at by the explorer: type aliases (they only carry type
# trees), namespaces (flattened: their declarations are written without them) and the implicit using directive that
# clang adds for an unnamed namespace
NOT_EXPORTED_KINDS = {"TypedefDecl", "TypeAliasDecl", "TypeAliasTemplateDecl", "NamespaceDecl", "UsingDirectiveDecl"}


def _libs_dir() -> Path:
    return Path(sysconfig.get_paths()["purelib"]) / "discopop-profiler.libs"


def _plugins(libs_dir: Path) -> list[Path]:
    return sorted(libs_dir.glob("DiscoPoPASTExport-*.so"))


pytestmark = pytest.mark.skipif(
    shutil.which("discopop_cxx") is None or not _plugins(_libs_dir()),
    reason="the profiler is not installed, or was built without the Clang development files (no AST export plugin)",
)


def _compile(
    libs_dir: Path, work_dir: Path, extra_env: Optional[dict[str, str]] = None
) -> "subprocess.CompletedProcess[str]":
    """Compile main.cpp with the CXX wrapper of libs_dir in work_dir (a copy of src)."""
    env = dict(os.environ)
    env["DP_PROJECT_ROOT_DIR"] = str(work_dir)
    env["HOME"] = str(_isolated_home(work_dir))
    env.pop("DOT_DISCOPOP", None)
    env.pop("DP_AST_NO_PLUGIN", None)
    env.update(extra_env or {})
    return subprocess.run(
        [str(libs_dir / "CXX_wrapper.sh"), "-c", "main.cpp", "-o", "main.o"],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def _graph_nodes(ast_dump: Path) -> Counter[tuple[Any, ...]]:
    """The nodes of all translation units of the dump as the explorer sees them, without the nodes of kinds the plugin
    leaves out and without the (location-less) implicit declarations of clang."""
    text = ast_dump.read_text()
    decoder = json.JSONDecoder()
    position = 0
    nodes: Counter[tuple[Any, ...]] = Counter()
    while position < len(text):
        translation_unit, position = decoder.raw_decode(text, position)
        while position < len(text) and text[position].isspace():
            position += 1
        graph = ClangASTGraph().build_from_ast(translation_unit)
        for _, attributes in graph.nodes(data=True):
            location = attributes["loc"]
            if attributes["kind"] in NOT_EXPORTED_KINDS or location["file"] is None:
                continue
            nodes[
                (
                    attributes["kind"],
                    attributes["name"],
                    attributes["type"],
                    os.path.basename(location["file"]),
                    location["line"],
                    location["column"],
                    attributes["opcode"],
                    attributes["referenced_name"],
                    attributes["referenced_kind"],
                    attributes["storage_class"],
                )
            ] += 1
    return nodes


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "src"
    shutil.copytree(SRC_DIR, destination)
    return destination


def test_plugin_gives_the_nodes_of_the_filtered_dump(tmp_path: Path) -> None:
    libs_dir = _libs_dir()
    dumps = {}
    for variant, env in (("plugin", {}), ("dump", {"DP_AST_NO_PLUGIN": "1"})):
        directory = tmp_path / variant
        shutil.copytree(SRC_DIR, directory)
        result = _compile(libs_dir, directory, env)
        assert result.returncode == 0, result.stdout + result.stderr
        dumps[variant] = directory / ".discopop" / "profiler" / "ast_dump.json"
        assert dumps[variant].stat().st_size > 0
    plugin_nodes = _graph_nodes(dumps["plugin"])
    dump_nodes = _graph_nodes(dumps["dump"])
    assert sum(dump_nodes.values()) > 100, "the program has to have some AST, or the comparison is meaningless"
    assert not plugin_nodes - dump_nodes, "nodes of the plugin that the filtered dump lacks"
    # the dump has the documentation comments of declarations, the plugin has not: not code, nobody asks for them
    missing = Counter(
        {node: count for node, count in (dump_nodes - plugin_nodes).items() if not node[0].endswith("Comment")}
    )
    assert not missing, f"nodes of the filtered dump that the plugin lacks: {list(missing)[:10]}"
    # the declarations of the program and nothing of the standard library
    assert {"main.cpp", "util.hpp"} == {node[3] for node in plugin_nodes}
    assert plugin_nodes.total() <= dump_nodes.total()


def test_plugin_writes_far_less_than_the_complete_dump(work_dir: Path, tmp_path: Path) -> None:
    """The point of the plugin: the declarations of the standard library are never written."""
    libs_dir = _libs_dir()
    plugin = _plugins(libs_dir)[0]
    raw = tmp_path / "raw.json"
    unfiltered = subprocess.run(
        ["clang++", "-std=c++17", "main.cpp", "-fsyntax-only", "-Xclang", "-ast-dump=json"],
        cwd=work_dir,
        capture_output=True,
    )
    assert unfiltered.returncode == 0, unfiltered.stderr
    exported = subprocess.run(
        ["clang++", "-std=c++17", "main.cpp", "-fsyntax-only", "-Xclang", "-load", "-Xclang", str(plugin)]
        + ["-Xclang", "-add-plugin", "-Xclang", "dp-ast-export"]
        + ["-Xclang", "-plugin-arg-dp-ast-export", "-Xclang", f"root={work_dir}"]
        + ["-Xclang", "-plugin-arg-dp-ast-export", "-Xclang", f"out={raw}"],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )
    assert exported.returncode == 0, exported.stderr
    assert 0 < raw.stat().st_size < len(unfiltered.stdout) / 10


@pytest.mark.parametrize("root_through_link", [True, False])
def test_plugin_project_directory_behind_a_symbolic_link(tmp_path: Path, root_through_link: bool) -> None:
    """Without a file mapping the project directory decides; a checkout reached through a symbolic link
    (/home/... -> /mnt/storage/...) must not lose its declarations, whichever form of the path is given."""
    real = tmp_path / "storage" / "src"
    shutil.copytree(SRC_DIR, real)
    link = tmp_path / "home_src"
    link.symlink_to(real)
    root = link if root_through_link else real
    raw = tmp_path / "raw.json"
    result = subprocess.run(
        [
            "clang++",
            "-std=c++17",
            "main.cpp",
            "-fsyntax-only",
            "-Xclang",
            "-load",
            "-Xclang",
            str(_plugins(_libs_dir())[0]),
        ]
        + ["-Xclang", "-add-plugin", "-Xclang", "dp-ast-export"]
        + ["-Xclang", "-plugin-arg-dp-ast-export", "-Xclang", f"root={root}"]
        + ["-Xclang", "-plugin-arg-dp-ast-export", "-Xclang", f"out={raw}"],
        cwd=link,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    nodes = _graph_nodes(raw)
    assert {"main.cpp", "util.hpp"} == {node[3] for node in nodes}


def test_unwritable_output_fails_the_compilation(work_dir: Path) -> None:
    """clang's exit code has to tell the wrapper that there is no output to filter."""
    plugin = _plugins(_libs_dir())[0]
    result = subprocess.run(
        ["clang++", "main.cpp", "-fsyntax-only", "-Xclang", "-load", "-Xclang", str(plugin)]
        + ["-Xclang", "-add-plugin", "-Xclang", "dp-ast-export"]
        + ["-Xclang", "-plugin-arg-dp-ast-export", "-Xclang", "out=/nonexistent/directory/ast.json"],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "dp-ast-export: cannot open the output file" in result.stderr


def test_wrapper_falls_back_when_the_plugin_fails(work_dir: Path, tmp_path: Path) -> None:
    """A plugin that cannot be loaded (e.g. built for another clang) must not cost the AST."""
    libs_copy = tmp_path / "libs"
    shutil.copytree(_libs_dir(), libs_copy)
    for plugin in _plugins(libs_copy):
        plugin.write_bytes(b"not a shared object")
    result = _compile(libs_copy, work_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the AST export plugin failed, filtering the AST dump of clang instead" in result.stderr
    nodes = _graph_nodes(work_dir / ".discopop" / "profiler" / "ast_dump.json")
    assert {"main.cpp", "util.hpp"} == {node[3] for node in nodes}


def test_wrapper_without_plugin_uses_the_filtered_dump(work_dir: Path, tmp_path: Path) -> None:
    libs_copy = tmp_path / "libs"
    shutil.copytree(_libs_dir(), libs_copy)
    for plugin in _plugins(libs_copy):
        plugin.unlink()
    result = _compile(libs_copy, work_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "plugin failed" not in result.stderr
    assert (work_dir / ".discopop" / "profiler" / "ast_dump.json").stat().st_size > 0
