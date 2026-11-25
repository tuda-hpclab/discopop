# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import importlib.metadata
import json
import multiprocessing
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from discopop_library.tools.update_notifications import update_notifier as un
from discopop_library.tools.update_notifications.update_notifier import (
    AvailableUpdate,
    InstalledPackage,
    UpdateSettings,
)


def pkg(name: str, version: str, source: str = un.SOURCE_INDEX, installer: str = "pip") -> InstalledPackage:
    return InstalledPackage(name, version, installer, source, "/src" if source != un.SOURCE_INDEX else "")


def fetcher(releases: Dict[str, List[str]], calls: Optional[List[str]] = None):  # type: ignore[no-untyped-def]
    def fetch(name: str) -> List[str]:
        if calls is not None:
            calls.append(name)
        if name not in releases:
            raise ConnectionError("offline")
        return releases[name]

    return fetch


STABLE_USER = [pkg("discopop", "5.0.2"), pkg("discopop-library", "0.0.1a11"), pkg("discopop-profiler", "0.0.1a6")]
PRE_USER = [pkg("discopop", "5.0.3a2"), pkg("discopop-library", "0.0.1a11"), pkg("discopop-profiler", "0.0.1a6")]
RELEASES = {
    "discopop": ["5.0.1", "5.0.2", "5.0.3a1", "5.0.3a2", "5.0.3a3"],
    "discopop-library": ["0.0.1a11", "0.0.1a12"],
    "discopop-profiler": ["0.0.1a6"],
}


# --- settings ---


def test_settings_default_when_missing_or_broken(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert un.load_settings(str(path)) == UpdateSettings(True, un.CHANNEL_AUTO)
    path.write_text("{not json")
    assert un.load_settings(str(path)) == UpdateSettings(True, un.CHANNEL_AUTO)
    path.write_text(json.dumps({"automatic_check_active": "yes", "release_channel": "nightly"}))
    assert un.load_settings(str(path)) == UpdateSettings(True, un.CHANNEL_AUTO)


def test_settings_round_trip_keeps_other_keys(tmp_path: Path) -> None:
    path = tmp_path / "auto_updater" / "settings.json"
    path.parent.mkdir()
    # written by older versions and by test/end_to_end/pipeline.py
    path.write_text(json.dumps({"automatic_check_active": False, "enable_interactive_notifications": False}))
    assert un.load_settings(str(path)) == UpdateSettings(False, un.CHANNEL_AUTO)
    un.save_settings(UpdateSettings(True, un.CHANNEL_PRE), str(path))
    assert json.loads(path.read_text()) == {
        "automatic_check_active": True,
        "enable_interactive_notifications": False,
        "release_channel": "pre",
    }
    assert list(path.parent.glob("*.tmp")) == []


def test_save_settings_creates_the_directory(tmp_path: Path) -> None:
    path = tmp_path / ".discopop_config" / "auto_updater" / "settings.json"
    un.save_settings(UpdateSettings(False, un.CHANNEL_STABLE), str(path))
    assert un.load_settings(str(path)) == UpdateSettings(False, un.CHANNEL_STABLE)
    with pytest.raises(ValueError):
        un.save_settings(UpdateSettings(True, "nightly"), str(path))


def test_settings_path_follows_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert un.settings_path() == str(tmp_path / ".discopop_config" / "auto_updater" / "settings.json")


def _save_repeatedly(path: str, iterations: int) -> None:
    for i in range(iterations):
        un.save_settings(UpdateSettings(i % 2 == 0, un.CHANNEL_AUTO), path)
        un.load_settings(path)


def test_concurrent_processes_share_the_settings(tmp_path: Path) -> None:
    path = str(tmp_path / "settings.json")
    ctx = multiprocessing.get_context("spawn")
    processes = [ctx.Process(target=_save_repeatedly, args=(path, 50)) for _ in range(8)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=120)
    assert [p.exitcode for p in processes] == [0] * len(processes)
    assert isinstance(json.loads(Path(path).read_text()), dict)
    assert list(tmp_path.glob("*.tmp")) == []


# --- installed packages ---


class FakeDistribution(importlib.metadata.Distribution):
    def __init__(self, version: str, files: Dict[str, str]) -> None:
        self._version = version
        self._files = files

    @property
    def version(self) -> str:
        return self._version

    def read_text(self, filename: str) -> Optional[str]:
        return self._files.get(filename)

    def locate_file(self, path):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def test_installed_packages_reads_the_source() -> None:
    dists = {
        "discopop": FakeDistribution("5.0.2", {"INSTALLER": "pip\n"}),
        "discopop-library": FakeDistribution(
            "0.0.1a11",
            {
                "INSTALLER": "pip",
                "direct_url.json": json.dumps({"url": "file:///src/lib", "dir_info": {"editable": True}}),
            },
        ),
        "discopop-profiler": FakeDistribution(
            "0.0.1a6", {"INSTALLER": "pip", "direct_url.json": json.dumps({"url": "file:///src/a%20b", "dir_info": {}})}
        ),
        "discopop-explorer": FakeDistribution(
            "0.0.1a3",
            {"INSTALLER": "pip", "direct_url.json": json.dumps({"url": "https://x/y.git", "vcs_info": {"vcs": "git"}})},
        ),
        "discopop-gui": FakeDistribution("0.0.1a3", {"INSTALLER": "conda"}),
        "discopop_mcp_server": FakeDistribution("0.0.1a9", {"INSTALLER": "uv"}),
    }

    def find(name: str) -> importlib.metadata.Distribution:
        if name not in dists:
            raise importlib.metadata.PackageNotFoundError(name)
        return dists[name]

    packages = {p.name: p for p in un.installed_packages(find)}
    assert list(packages) == [n for n in un.DISCOPOP_PACKAGES if n in dists]
    assert packages["discopop"] == InstalledPackage("discopop", "5.0.2", "pip", un.SOURCE_INDEX, "")
    assert packages["discopop"].from_index
    assert packages["discopop-library"].source == un.SOURCE_EDITABLE
    assert packages["discopop-library"].describe_source() == "editable: /src/lib"
    assert packages["discopop-profiler"].source == un.SOURCE_DIRECTORY
    assert packages["discopop-profiler"].origin == "/src/a b"
    assert packages["discopop-explorer"].source == un.SOURCE_VCS
    # conda manages its packages itself
    assert not packages["discopop-gui"].from_index
    assert packages["discopop_mcp_server"].from_index


def test_development_install() -> None:
    assert not un.is_development_install(STABLE_USER)
    assert un.is_development_install([pkg("discopop", "5.0.2", un.SOURCE_EDITABLE), pkg("discopop-library", "1")])
    # without the meta-package: only if none came from an index
    assert un.is_development_install([pkg("discopop-library", "1", un.SOURCE_DIRECTORY)])
    assert not un.is_development_install([pkg("discopop-library", "1", un.SOURCE_DIRECTORY), pkg("discopop-gui", "1")])
    assert not un.is_development_install([])


# --- available versions ---


def test_latest_version() -> None:
    assert str(un.latest_version(["0.0.1a9", "0.0.1a10", "0.0.1a2"], False)) == "0.0.1a10"
    assert str(un.latest_version(["1.0", "1.1a1", "garbage"], False)) == "1.0"
    assert str(un.latest_version(["1.0", "1.1a1"], True)) == "1.1a1"
    assert un.latest_version([], True) is None


def test_fetch_skips_yanked_and_empty_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Dict[str, object]:
            return {
                "releases": {
                    "1.0": [{"yanked": False}],
                    "1.1": [{"yanked": True}, {"yanked": True}],
                    "1.2": [],
                    "1.3": [{"yanked": True}, {"yanked": False}],
                }
            }

    requested: List[object] = []

    def get(url: str, timeout: float) -> Response:
        requested.append((url, timeout))
        return Response()

    monkeypatch.setattr("discopop_library.tools.update_notifications.update_notifier.requests.get", get)
    assert un.fetch_release_versions("discopop") == ["1.0", "1.3"]
    assert requested == [("https://pypi.org/pypi/discopop/json", un.REQUEST_TIMEOUT_S)]


def test_stable_user_gets_only_the_meta_package_and_no_alphas() -> None:
    calls: List[str] = []
    result = un.check_for_updates(un.CHANNEL_AUTO, STABLE_USER, fetcher(RELEASES, calls))
    assert result.channel == un.CHANNEL_STABLE
    # the new alpha of discopop-library is not offered to a stable user
    assert calls == ["discopop"]
    assert result.updates == ()
    released = dict(RELEASES, discopop=RELEASES["discopop"] + ["5.0.3"])
    result = un.check_for_updates(un.CHANNEL_AUTO, STABLE_USER, fetcher(released))
    assert result.updates == (AvailableUpdate("discopop", "5.0.2", "5.0.3"),)
    assert result.can_update_with_pip


def test_pre_release_user_gets_every_package() -> None:
    result = un.check_for_updates(un.CHANNEL_AUTO, PRE_USER, fetcher(RELEASES))
    assert result.channel == un.CHANNEL_PRE
    assert set(result.checked) == {"discopop", "discopop-library", "discopop-profiler"}
    assert result.updates == (
        AvailableUpdate("discopop", "5.0.3a2", "5.0.3a3"),
        AvailableUpdate("discopop-library", "0.0.1a11", "0.0.1a12"),
    )
    # the stable release of the tested version ends the pre-release channel
    released = dict(RELEASES, discopop=RELEASES["discopop"] + ["5.0.3"])
    assert un.check_for_updates(un.CHANNEL_AUTO, PRE_USER, fetcher(released)).updates[0].latest == "5.0.3"


def test_explicit_channels_override_auto() -> None:
    assert un.check_for_updates(un.CHANNEL_PRE, STABLE_USER, fetcher(RELEASES)).updates[0] == AvailableUpdate(
        "discopop", "5.0.2", "5.0.3a3"
    )
    # stable for an alpha user: 5.0.2 is older than the installed 5.0.3a2
    assert un.check_for_updates(un.CHANNEL_STABLE, PRE_USER, fetcher(RELEASES)).updates == ()


def test_without_meta_package_every_package_by_its_version() -> None:
    packages = [pkg("discopop-library", "0.0.1a11"), pkg("discopop-gui", "1.0")]
    releases = {"discopop-library": ["0.0.1a12"], "discopop-gui": ["1.0", "1.1a1"]}
    result = un.check_for_updates(un.CHANNEL_AUTO, packages, fetcher(releases))
    assert result.channel == un.CHANNEL_AUTO
    assert result.updates == (AvailableUpdate("discopop-library", "0.0.1a11", "0.0.1a12"),)


def test_local_packages_are_listed_but_not_checked() -> None:
    packages = [pkg("discopop", "5.0.2"), pkg("discopop-profiler", "0.0.1a6", un.SOURCE_DIRECTORY)]
    released = {"discopop": ["5.0.3"]}
    result = un.check_for_updates(un.CHANNEL_AUTO, packages, fetcher(released))
    assert result.updates == (AvailableUpdate("discopop", "5.0.2", "5.0.3"),)
    assert [p.name for p in result.not_checked] == ["discopop-profiler"]
    assert not result.development_install
    # pip could replace the local profiler by the PyPI build
    assert not result.can_update_with_pip


def test_development_install_checks_nothing() -> None:
    calls: List[str] = []
    packages = [
        pkg("discopop", "5.0.3a2", un.SOURCE_EDITABLE),
        pkg("discopop-profiler", "0.0.1a6", un.SOURCE_DIRECTORY),
    ]
    result = un.check_for_updates(un.CHANNEL_AUTO, packages, fetcher(RELEASES, calls))
    assert result.development_install
    assert calls == []
    assert result.updates == ()


def test_errors_are_reported_per_package() -> None:
    result = un.check_for_updates(un.CHANNEL_PRE, PRE_USER, fetcher({"discopop": ["5.0.4"]}))
    assert result.updates == (AvailableUpdate("discopop", "5.0.3a2", "5.0.4"),)
    assert [e.split(":")[0] for e in result.errors] == ["discopop-library", "discopop-profiler"]
    assert "ConnectionError" in result.errors[0]


# --- the update command ---


def test_installer_prefix() -> None:
    assert un.installer_prefix("/venv/bin/python", has_pip=True) == (["/venv/bin/python", "-m", "pip", "install"], True)
    assert un.installer_prefix("/venv/bin/python", has_pip=False, uv="/usr/bin/uv") == (
        ["/usr/bin/uv", "pip", "install", "--python", "/venv/bin/python"],
        True,
    )
    assert un.installer_prefix("/venv/bin/python", has_pip=False, uv="") == (
        ["/venv/bin/python", "-m", "pip", "install"],
        False,
    )


def test_upgrade_command_pins_the_found_versions() -> None:
    updates = [AvailableUpdate("discopop", "5.0.3a2", "5.0.3a3"), AvailableUpdate("discopop-library", "1", "2a1")]
    assert un.upgrade_command(updates, ["py", "-m", "pip", "install"]) == [
        "py",
        "-m",
        "pip",
        "install",
        "discopop==5.0.3a3",
        "discopop-library==2a1",
    ]


def test_a_hanging_request_ends_at_the_deadline() -> None:
    import threading
    import time

    release = threading.Event()

    def fetch(name: str) -> List[str]:
        if name == "discopop-library":
            release.wait(30)
        return RELEASES[name]

    start = time.monotonic()
    result = un.check_for_updates(un.CHANNEL_PRE, PRE_USER, fetch, deadline_s=0.5)
    release.set()
    assert time.monotonic() - start < 5
    assert result.updates == (AvailableUpdate("discopop", "5.0.3a2", "5.0.3a3"),)
    assert result.errors == ("discopop-library: no answer within 0.5 s",)
