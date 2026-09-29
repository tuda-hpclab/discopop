# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
from typing import Any, Dict, List
import requests  # type: ignore
from importlib.metadata import version  # type: ignore
from packaging.version import Version  # type: ignore
import os
import json
from datetime import date
from discopop_library.StatusReporting.console import warn
from .notification_dialog import notify

logger = logging.getLogger("UpdateNotifier")


def run(module_name: str, module_api_url: str, module_release_url: str) -> None:

    config_dir = os.path.join(str(os.getenv("HOME")), ".discopop_config")
    auto_updater_dir = os.path.join(config_dir, "auto_updater")
    settings_file = os.path.join(auto_updater_dir, "settings.json")
    modules_file = os.path.join(auto_updater_dir, "modules.json")

    # check if folder structure is set up
    setup_folder_structure(config_dir, auto_updater_dir, settings_file, modules_file)
    # check if current module is registered
    register_current_module(modules_file, module_name, module_api_url, module_release_url)

    # check if automatic updates are activate
    if not automatic_updates_active(settings_file):
        return
    # update registered modules
    check_for_updates(modules_file, settings_file)


def automatic_updates_active(settings_file: str) -> bool:
    with open(settings_file, "r") as f:
        settings = json.load(f)
        if "automatic_check_active" in settings:
            return bool(settings["automatic_check_active"])
        return False


def register_current_module(modules_file: str, module_name: str, module_api_url: str, module_release_url: str) -> None:
    tmp_modules_file = modules_file + ".tmp"
    with open(modules_file, "r") as f:
        modules = json.load(f)
        if module_name not in modules:
            module_dict = {
                "api_url": module_api_url,
                "release_url": module_release_url,
                "last_checked": None,
                "last_result": "",
            }
            modules[module_name] = module_dict

            with open(tmp_modules_file, "w+") as g:
                json.dump(modules, g)

    if os.path.exists(tmp_modules_file):
        os.remove(modules_file)
        os.rename(tmp_modules_file, modules_file)


def setup_folder_structure(config_dir: str, auto_updater_dir: str, settings_file: str, modules_file: str) -> None:
    logger.debug("Checking existence of " + config_dir)
    if not os.path.exists(config_dir):
        os.mkdir(config_dir)
    if not os.path.exists(auto_updater_dir):
        os.mkdir(auto_updater_dir)
    if not os.path.exists(settings_file):
        settings = {"automatic_check_active": True, "enable_interactive_notifications": True}
        with open(settings_file, "w+") as f:
            json.dump(settings, f)
    if not os.path.exists(modules_file):
        modules: Dict[str, Dict[str, Any]] = dict()
        with open(modules_file, "w+") as f:
            json.dump(modules, f)


def check_for_updates(modules_file: str, settings_file: str) -> None:
    logger.debug("Checking for updates")
    # load registered modules
    modules: Dict[str, Dict[str, Any]] = dict()
    with open(modules_file, "r") as f:
        modules = json.load(f)

    # load settings
    settings: Dict[str, Any] = dict()
    with open(settings_file, "r") as f:
        settings = json.load(f)

    for module in modules:
        logger.debug("Checking module: " + module)
        try:
            # get date stamp of last check
            if not enough_time_elapsed(modules[module]["last_checked"]):
                logger.debug("Skipped due to recent check.")
                if "last_result" in modules[module]:
                    if len(modules[module]["last_result"]) > 0:
                        logger.debug("Last result: " + modules[module]["last_result"])
                continue

            # read current version
            version_str = version(module)
            # read latest version
            url = modules[module]["api_url"]
            response = requests.get(url).json()
            latest_tag_name = response["tag_name"]
            if latest_tag_name.startswith("v"):
                latest_version = latest_tag_name[1:]
            else:
                latest_version = latest_tag_name
            # compare semantic versioning
            if Version(latest_version) > Version(version_str):
                notify(
                    version_str,
                    latest_version,
                    modules[module]["release_url"],
                    settings["enable_interactive_notifications"],
                )

                modules[module]["last_result"] = (
                    "A newer version was found! Installed: "
                    + str(version_str)
                    + " Latest: "
                    + str(latest_version)
                    + " Releases: "
                    + modules[module]["release_url"]
                )

            else:
                modules[module]["last_result"] = "Up to date."
                logger.debug("Up to date.")
            # update last_checked timestamp
            modules[module]["last_checked"] = str(date.today())

        except Exception as ex:
            warn(f"Update check for {module} failed with: {type(ex)}: {ex}")

    # write potentially updated modules to file
    tmp_modules_file = modules_file + ".tmp"
    with open(tmp_modules_file, "w+") as g:
        json.dump(modules, g)
    if os.path.exists(tmp_modules_file):
        os.remove(modules_file)
        os.rename(tmp_modules_file, modules_file)


def enough_time_elapsed(last_timestamp: Any) -> bool:
    # unpack last_timestamp
    if last_timestamp is None:
        return True
    if last_timestamp == "None":
        return True
    current_date = date.today()
    loaded_year = int(last_timestamp.split("-")[0])
    loaded_month = int(last_timestamp.split("-")[1])
    loaded_day = int(last_timestamp.split("-")[2])
    loaded_date = date(loaded_year, loaded_month, loaded_day)
    return current_date > loaded_date
