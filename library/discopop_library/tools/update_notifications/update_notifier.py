# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which DiscoPoP packages are installed, and whether PyPI has newer versions of them.

Imports no GUI toolkit: the Qt GUI (``ProjectManager/qt_gui/updates.py``) shows the results.

Release channel: whether pre-releases are offered. ``auto`` follows the installed version of the meta-package
``discopop`` (the release unit): a pre-release installed means the user opted into pre-releases (``pip install --pre``
or a pinned pre-release), a final release means stable updates only. Without the meta-package, every package
decides by its own installed version. A package that has no final release at all is offered its pre-releases on
either channel, as pip does.

On the stable channel with the meta-package installed, only the meta-package is checked: a new release of it raises
the minimum versions of the sub-packages it needs, and pip installs those. On the pre-release channel (or without the
meta-package), every package is checked, and the update pins each one, since pip only accepts a pre-release that is
named explicitly (or with ``--pre``, which would apply to all packages of the command).

Only packages that pip (or uv) installed from an index are updated this way. A package installed from a local
directory, an archive or a VCS URL, or in editable mode (``direct_url.json``, PEP 610), is a development install:
it is listed, but not checked, and a command updating the others is not offered, as pip could replace the local
package by the PyPI build while resolving the dependencies.
"""

import importlib.metadata
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

import requests  # type: ignore
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

META_PACKAGE = "discopop"
# the distributions of the DiscoPoP framework, the meta-package first
DISCOPOP_PACKAGES: Tuple[str, ...] = (
    META_PACKAGE,
    "discopop-library",
    "discopop-explorer",
    "discopop-profiler",
    "discopop-hotspot-detection",
    "discopop-gui",
    "discopop_mcp_server",
)

PYPI_URL = "https://pypi.org/pypi/{name}/json"
# (connect, read) timeouts of one request: a node without network access fails fast
REQUEST_TIMEOUT_S: Tuple[float, float] = (3.05, 10.0)
# the whole check gives up after this long (a timeout of requests applies per attempt and address, DNS is unbounded)
CHECK_DEADLINE_S = 20.0

CHANNEL_AUTO = "auto"
CHANNEL_STABLE = "stable"
CHANNEL_PRE = "pre"
CHANNELS: Tuple[str, ...] = (CHANNEL_AUTO, CHANNEL_STABLE, CHANNEL_PRE)

# how the package came into the environment
SOURCE_INDEX = "index"
SOURCE_EDITABLE = "editable"
SOURCE_DIRECTORY = "directory"
SOURCE_ARCHIVE = "archive"
SOURCE_VCS = "vcs"

# the installers whose installs pip may update
_PIP_INSTALLERS = ("pip", "uv")

# keys of settings.json; tests (test/end_to_end/pipeline.py) and older versions write automatic_check_active too
_KEY_CHECK_AT_START = "automatic_check_active"
_KEY_CHANNEL = "release_channel"


# --- settings ---


@dataclass(frozen=True)
class UpdateSettings:
    check_at_start: bool = True
    channel: str = CHANNEL_AUTO


def settings_path() -> str:
    """``$HOME/.discopop_config/auto_updater/settings.json``, shared by all DiscoPoP tools of the user."""
    return os.path.join(os.path.expanduser("~"), ".discopop_config", "auto_updater", "settings.json")


def _read_settings_dict(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            content = json.load(f)
    except (OSError, ValueError):
        return {}
    return content if isinstance(content, dict) else {}


def load_settings(path: Optional[str] = None) -> UpdateSettings:
    """The saved settings; the defaults for what is missing or unreadable."""
    content = _read_settings_dict(path or settings_path())
    check = content.get(_KEY_CHECK_AT_START, True)
    channel = content.get(_KEY_CHANNEL, CHANNEL_AUTO)
    return UpdateSettings(
        check_at_start=check if isinstance(check, bool) else True,
        channel=channel if channel in CHANNELS else CHANNEL_AUTO,
    )


def save_settings(settings: UpdateSettings, path: Optional[str] = None) -> None:
    """Store ``settings``, keeping the other keys of the file."""
    if settings.channel not in CHANNELS:
        raise ValueError(f"unknown release channel: {settings.channel}")
    path = path or settings_path()
    content = _read_settings_dict(path)
    content[_KEY_CHECK_AT_START] = settings.check_at_start
    content[_KEY_CHANNEL] = settings.channel
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json_atomically(path, content)


def write_json_atomically(path: str, content: Any) -> None:
    """Write content to path such that concurrent readers see either the old or the new file, never a partial one.

    Every writer uses its own temporary file, and os.replace swaps it in atomically.
    """
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(content, f)
        # mkstemp creates the file readable by the owner only
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# --- installed packages ---


@dataclass(frozen=True)
class InstalledPackage:
    name: str
    version: str
    # the tool that installed it (the INSTALLER file of its metadata; "" if unknown)
    installer: str = "pip"
    source: str = SOURCE_INDEX
    # where a package not installed from an index came from (a path or a URL)
    origin: str = ""

    @property
    def from_index(self) -> bool:
        """Installed from an index by pip or uv, i.e. pip may update it."""
        return self.source == SOURCE_INDEX and self.installer in _PIP_INSTALLERS

    @property
    def is_prerelease(self) -> bool:
        try:
            return Version(self.version).is_prerelease
        except InvalidVersion:
            return False

    def describe_source(self) -> str:
        if self.source == SOURCE_INDEX:
            if self.installer in _PIP_INSTALLERS:
                return "PyPI"
            return f"installed by {self.installer or 'an unknown installer'}"
        titles = {
            SOURCE_EDITABLE: "editable",
            SOURCE_DIRECTORY: "local directory",
            SOURCE_ARCHIVE: "archive",
            SOURCE_VCS: "VCS",
        }
        title = titles.get(self.source, self.source)
        return f"{title}: {self.origin}" if self.origin else title


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    return unquote(parsed.path) if parsed.scheme == "file" else url


def _source_of(direct_url: Optional[str]) -> Tuple[str, str]:
    """(source, origin) from the content of ``direct_url.json`` (None: the file does not exist)."""
    if direct_url is None:
        return SOURCE_INDEX, ""
    try:
        data = json.loads(direct_url)
    except ValueError:
        return SOURCE_ARCHIVE, ""
    if not isinstance(data, dict):
        return SOURCE_ARCHIVE, ""
    url = str(data.get("url", ""))
    if "vcs_info" in data:
        return SOURCE_VCS, url
    dir_info = data.get("dir_info")
    if isinstance(dir_info, dict):
        return (SOURCE_EDITABLE if dir_info.get("editable") else SOURCE_DIRECTORY), _path_of(url)
    return SOURCE_ARCHIVE, _path_of(url)


def describe_distribution(dist: importlib.metadata.Distribution, name: str) -> InstalledPackage:
    installer = (dist.read_text("INSTALLER") or "").strip()
    source, origin = _source_of(dist.read_text("direct_url.json"))
    return InstalledPackage(name, dist.version, installer, source, origin)


def installed_packages(
    find: Callable[[str], importlib.metadata.Distribution] = importlib.metadata.distribution,
) -> List[InstalledPackage]:
    """The installed DiscoPoP packages, in the order of ``DISCOPOP_PACKAGES``."""
    packages: List[InstalledPackage] = []
    for name in DISCOPOP_PACKAGES:
        try:
            dist = find(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        packages.append(describe_distribution(dist, name))
    return packages


def is_development_install(packages: Sequence[InstalledPackage]) -> bool:
    """The DiscoPoP packages (the meta-package if it is installed, else any of them) were not installed from an
    index: there is nothing to check, the developer updates the checkout."""
    meta = _meta_of(packages)
    if meta is not None:
        return not meta.from_index
    return bool(packages) and not any(package.from_index for package in packages)


def _meta_of(packages: Sequence[InstalledPackage]) -> Optional[InstalledPackage]:
    return next((p for p in packages if canonicalize_name(p.name) == canonicalize_name(META_PACKAGE)), None)


# --- available versions ---


def fetch_release_versions(name: str, timeout: Tuple[float, float] = REQUEST_TIMEOUT_S) -> List[str]:
    """The versions of ``name`` on PyPI that have files and are not yanked entirely."""
    response = requests.get(PYPI_URL.format(name=name), timeout=timeout)
    response.raise_for_status()
    releases = response.json().get("releases", {})
    return [
        version
        for version, files in releases.items()
        if files and not all(isinstance(f, dict) and f.get("yanked") for f in files)
    ]


def latest_version(versions: Iterable[str], allow_prereleases: bool) -> Optional[Version]:
    """The highest of ``versions``; pre-releases only if allowed or if there is no final release (as pip does)."""
    parsed: List[Version] = []
    for text in versions:
        try:
            parsed.append(Version(text))
        except InvalidVersion:
            continue
    candidates = parsed if allow_prereleases else [v for v in parsed if not v.is_prerelease]
    if not candidates:
        candidates = parsed
    return max(candidates) if candidates else None


@dataclass(frozen=True)
class AvailableUpdate:
    name: str
    installed: str
    latest: str


@dataclass(frozen=True)
class UpdateCheckResult:
    # the channel the check used: stable or pre ("auto" without the meta-package: every package by its version)
    channel: str
    updates: Tuple[AvailableUpdate, ...] = ()
    # installed packages not installed from an index: neither checked nor updated
    not_checked: Tuple[InstalledPackage, ...] = ()
    # "<package>: <reason>" for every package whose versions could not be fetched
    errors: Tuple[str, ...] = ()
    development_install: bool = False
    checked: Tuple[str, ...] = ()

    @property
    def can_update_with_pip(self) -> bool:
        """Updating is safe: no package of the environment comes from somewhere pip would replace it from."""
        return bool(self.updates) and not self.not_checked


def effective_channel(channel: str, packages: Sequence[InstalledPackage]) -> str:
    """``channel`` with ``auto`` resolved by the meta-package; stays ``auto`` if it is not installed."""
    if channel != CHANNEL_AUTO:
        return channel
    meta = _meta_of(packages)
    if meta is None:
        return CHANNEL_AUTO
    return CHANNEL_PRE if meta.is_prerelease else CHANNEL_STABLE


def check_for_updates(
    channel: str = CHANNEL_AUTO,
    packages: Optional[Sequence[InstalledPackage]] = None,
    fetch: Optional[Callable[[str], List[str]]] = None,
    deadline_s: float = CHECK_DEADLINE_S,
) -> UpdateCheckResult:
    """Ask PyPI (``fetch``, by default :func:`fetch_release_versions`) for newer versions of the installed DiscoPoP
    packages (several requests at once); a package without an answer after ``deadline_s`` is reported as an error."""
    if packages is None:
        packages = installed_packages()
    fetch_versions = fetch or fetch_release_versions
    used_channel = effective_channel(channel, packages)
    not_checked = tuple(p for p in packages if not p.from_index)
    development = is_development_install(packages)
    meta = _meta_of(packages)
    if used_channel == CHANNEL_STABLE and meta is not None:
        targets = [meta] if meta.from_index else []
    else:
        targets = [p for p in packages if p.from_index]

    def allow_prereleases(package: InstalledPackage) -> bool:
        if used_channel == CHANNEL_AUTO:
            return package.is_prerelease
        return used_channel == CHANNEL_PRE

    def fetch_one(package: InstalledPackage) -> Tuple[InstalledPackage, Optional[List[str]], str]:
        try:
            return package, fetch_versions(package.name), ""
        except Exception as e:  # network, HTTP status, JSON: reported per package
            return package, None, f"{package.name}: {type(e).__name__}: {e}"

    updates: List[AvailableUpdate] = []
    errors: List[str] = []
    if targets:
        for package, versions, error in _fetch_all(targets, fetch_one, deadline_s):
            if versions is None:
                errors.append(error)
                continue
            latest = latest_version(versions, allow_prereleases(package))
            try:
                newer = latest is not None and latest > Version(package.version)
            except InvalidVersion:
                newer = False
            if newer:
                updates.append(AvailableUpdate(package.name, package.version, str(latest)))
    return UpdateCheckResult(
        channel=used_channel,
        updates=tuple(updates),
        not_checked=not_checked,
        errors=tuple(errors),
        development_install=development,
        checked=tuple(p.name for p in targets),
    )


def _fetch_all(
    targets: Sequence[InstalledPackage],
    fetch_one: Callable[[InstalledPackage], Tuple[InstalledPackage, Optional[List[str]], str]],
    deadline_s: float,
) -> List[Tuple[InstalledPackage, Optional[List[str]], str]]:
    """``fetch_one`` of every target at once, in daemon threads: a request that hangs neither delays the result
    beyond the deadline nor keeps the interpreter from exiting (a thread pool's workers would be joined at exit)."""
    results: Dict[int, Tuple[InstalledPackage, Optional[List[str]], str]] = {}
    lock = threading.Lock()

    def run(index: int, package: InstalledPackage) -> None:
        result = fetch_one(package)
        with lock:
            results[index] = result

    threads = [
        threading.Thread(target=run, args=(index, package), daemon=True, name=f"update-check-{package.name}")
        for index, package in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    end = time.monotonic() + deadline_s
    for thread in threads:
        thread.join(max(0.0, end - time.monotonic()))
    with lock:
        return [
            results.get(index, (package, None, f"{package.name}: no answer within {deadline_s:g} s"))
            for index, package in enumerate(targets)
        ]


# --- the update ---


def installer_prefix(
    python: str = sys.executable,
    has_pip: Optional[bool] = None,
    uv: Optional[str] = None,
) -> Tuple[List[str], bool]:
    """The command installing into the environment of ``python`` and whether it can run here.

    ``python -m pip`` if pip is installed; else ``uv pip --python`` (environments created by uv have no pip);
    else the pip command, which cannot run.
    """
    if has_pip is None:
        has_pip = importlib.util.find_spec("pip") is not None
    if has_pip:
        return [python, "-m", "pip", "install"], True
    if uv is None:
        uv = shutil.which("uv") or ""
    if uv:
        return [uv, "pip", "install", "--python", python], True
    return [python, "-m", "pip", "install"], False


def upgrade_command(updates: Sequence[AvailableUpdate], prefix: Sequence[str]) -> List[str]:
    """Install exactly the versions the check found (a named pre-release needs no ``--pre``)."""
    return list(prefix) + [f"{update.name}=={update.latest}" for update in updates]
