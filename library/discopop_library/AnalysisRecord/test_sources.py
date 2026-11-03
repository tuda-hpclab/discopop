# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path

from discopop_library.AnalysisRecord import changed_files, source_files, source_fingerprint
from discopop_library.AnalysisRecord import sources as sources_module


def _write(root: Path, rel: str, text: str = "int x;\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_walker_suffixes_and_pruning(tmp_path: Path) -> None:
    for rel in ["a.c", "b.CPP", "sub/c.hpp", "sub/d.cxx", "e.c++", "f.hh", "g.hxx", "h.cc", "i.h"]:
        _write(tmp_path, rel)
    for rel in [
        "notes.txt",
        ".git/x.c",
        ".discopop/x.c",
        ".discopop_variant/x.c",
        ".venv/x.c",
        "build/x.c",
        "venv/x.c",
        "__pycache__/x.c",
        "node_modules/x.c",
        "CMakeFiles/x.c",
        "deep/CMakeFiles/x.c",
        "mybuild/CMakeCache.txt",
        "mybuild/gen.c",
        "mybuild/inner/gen2.c",
    ]:
        _write(tmp_path, rel)
    assert source_files(str(tmp_path)) == sorted(
        ["a.c", "b.CPP", "sub/c.hpp", "sub/d.cxx", "e.c++", "f.hh", "g.hxx", "h.cc", "i.h"]
    )


def test_fingerprint_stable_and_detects_change(tmp_path: Path) -> None:
    _write(tmp_path, "a.c", "one")
    _write(tmp_path, "b.c", "two")
    fp1 = source_fingerprint(str(tmp_path))
    fp2 = source_fingerprint(str(tmp_path))
    assert fp1 == fp2
    assert fp1.digest.startswith("sha256:")
    assert set(fp1.files) == {"a.c", "b.c"}

    # same size, new content, mtime reset to the old value is still caught only if cache key differs;
    # a plain rewrite must be detected
    _write(tmp_path, "a.c", "ONE")
    fp3 = source_fingerprint(str(tmp_path))
    assert fp3.digest != fp1.digest
    assert changed_files(fp1.files, fp3.files) == ["a.c"]

    # touching without changing content keeps the digest (mtime is no decision input)
    os.utime(tmp_path / "b.c", (1, 1))
    assert source_fingerprint(str(tmp_path)).digest == fp3.digest


def test_fingerprint_add_remove(tmp_path: Path) -> None:
    _write(tmp_path, "a.c")
    fp1 = source_fingerprint(str(tmp_path))
    _write(tmp_path, "new.h")
    fp2 = source_fingerprint(str(tmp_path))
    assert changed_files(fp1.files, fp2.files) == ["new.h"]
    (tmp_path / "a.c").unlink()
    fp3 = source_fingerprint(str(tmp_path))
    assert changed_files(fp2.files, fp3.files) == ["a.c"]
    assert fp3.digest != fp2.digest


def test_rename_changes_digest(tmp_path: Path) -> None:
    _write(tmp_path, "a.c", "same")
    d1 = source_fingerprint(str(tmp_path)).digest
    (tmp_path / "a.c").rename(tmp_path / "b.c")
    assert source_fingerprint(str(tmp_path)).digest != d1


def test_cache_rehashes_only_changed_files(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _write(tmp_path, "a.c", "aaa")
    _write(tmp_path, "b.c", "bbb")
    source_fingerprint(str(tmp_path))
    calls: list[str] = []
    real = sources_module._hash_file

    def counting(p: str) -> str:
        calls.append(p)
        return real(p)

    monkeypatch.setattr(sources_module, "_hash_file", counting)
    source_fingerprint(str(tmp_path))
    assert calls == []
    _write(tmp_path, "b.c", "bbbb")
    source_fingerprint(str(tmp_path))
    assert [os.path.basename(c) for c in calls] == ["b.c"]


def test_changed_files_sorted() -> None:
    assert changed_files({"b": "1", "a": "1", "c": "1"}, {"a": "2", "c": "1", "d": "1"}) == ["a", "b", "d"]
