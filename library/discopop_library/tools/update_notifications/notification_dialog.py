# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from termcolor import colored  # type: ignore


def notify(version: str, latest_version: str, release_url: str, enable_interactive_notifications: bool) -> None:
    # try interactive notification
    notify_interactively(version, latest_version, release_url, enable_interactive_notifications)
    # notify on console
    notifiy_on_console(version, latest_version, release_url)


def notify_interactively(
    version: str, latest_version: str, release_url: str, enable_interactive_notifications: bool
) -> None:
    # return True, if the interactive notification was successful
    # return False otherwise
    # check if interactive notifications are enables
    if not enable_interactive_notifications:
        return
    # try interactive notifications
    try:
        import tkinter as tk
        from tkinter import messagebox

        window = tk.Tk()
        window.wm_withdraw()
        window.geometry("200x600")

        update_notification_msg = "A newer version was found!"
        update_notification_msg += "\n\t" + "Installed: " + str(version)
        update_notification_msg += "\n\t" + "Latest:    " + str(latest_version)
        update_notification_msg += "\n\t" + "Visit " + release_url + " to download the latest version."

        messagebox.showinfo(title="DiscoPoP - Update notifier", message=update_notification_msg)

    except ModuleNotFoundError as ex:
        print(str(ex) + " -> Fallback to Terminal output")
        return
    except Exception as ex:
        raise ex


def notifiy_on_console(version: str, latest_version: str, release_url: str) -> None:
    print("\t" + colored("A newer version was found!", "yellow"))
    print("\t" + colored("Installed: " + str(version), "yellow"))
    print("\t" + colored("Latest:    " + str(latest_version), "yellow"))
    print(
        "\t"
        + colored("Visit ", "yellow")
        + colored(release_url, "yellow", attrs=["underline"])
        + colored(" to download the latest version.", "yellow")
    )
