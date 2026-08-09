# -*- coding: utf-8 -*-
"""Re-register Mi Dia Nutricional windows so Windows reloads their taskbar icon."""

import ctypes
import sys
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown


APP_TITLE = "Mi D\u00eda Nutricional"
LOG_PATH = Path(__file__).resolve().parent / "logs" / "taskbar-refresh.log"
CLSID_TASKBAR_LIST = GUID("{56FDF344-FD6D-11d0-958A-006097C9A090}")


class ITaskbarList(IUnknown):
    _iid_ = GUID("{56FDF342-FD6D-11d0-958A-006097C9A090}")
    _methods_ = [
        COMMETHOD([], HRESULT, "HrInit"),
        COMMETHOD([], HRESULT, "AddTab", (["in"], wintypes.HWND, "hwnd")),
        COMMETHOD([], HRESULT, "DeleteTab", (["in"], wintypes.HWND, "hwnd")),
        COMMETHOD([], HRESULT, "ActivateTab", (["in"], wintypes.HWND, "hwnd")),
        COMMETHOD([], HRESULT, "SetActiveAlt", (["in"], wintypes.HWND, "hwnd")),
    ]


user32 = ctypes.windll.user32
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND


def log(message):
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except Exception:
        pass


def window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def main(argv):
    handles = []
    for value in argv:
        try:
            hwnd = int(value)
        except ValueError:
            continue
        if hwnd > 0 and hwnd not in handles:
            handles.append(hwnd)

    if not handles:
        log("status=no-handles")
        return 2

    refreshed = []
    failed = []
    comtypes.CoInitialize()
    try:
        taskbar = comtypes.CoCreateInstance(
            CLSID_TASKBAR_LIST,
            interface=ITaskbarList,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        taskbar.HrInit()
        foreground = int(user32.GetForegroundWindow() or 0)

        for hwnd in handles:
            if not user32.IsWindow(hwnd) or window_title(hwnd) != APP_TITLE:
                failed.append(f"{hwnd}:window-mismatch")
                continue

            try:
                taskbar.DeleteTab(hwnd)
                taskbar.AddTab(hwnd)
                if hwnd == foreground:
                    taskbar.ActivateTab(hwnd)
                refreshed.append(hwnd)
            except Exception as error:
                failed.append(f"{hwnd}:{type(error).__name__}:{error}")
    except Exception:
        log("status=error detail=" + traceback.format_exc().replace("\n", " | "))
        return 3
    finally:
        comtypes.CoUninitialize()

    log(
        "status={0} refreshed={1} failed={2}".format(
            "ok" if refreshed and not failed else "partial" if refreshed else "failed",
            ",".join(str(hwnd) for hwnd in refreshed),
            ";".join(failed),
        )
    )
    return 0 if refreshed and not failed else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
