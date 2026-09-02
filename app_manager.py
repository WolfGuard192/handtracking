# app_manager.py
"""
Windows application/window manager utilities.

Provides:
- list_user_windows(whitelist) -> list of dicts {hwnd, pid, exe, title}
- close_application(entry, simulate=False) -> tries WM_CLOSE then terminate
"""

import time
import logging
import subprocess
import os
import psutil

log = logging.getLogger(__name__)

# Try to import pywin32; degrade gracefully for non-Windows or tests.
try:
    import win32gui
    import win32process
    import win32con
    import win32api
except Exception as e:
    win32gui = None
    win32process = None
    win32con = None
    win32api = None
    log.debug("pywin32 not available: %s", e)


# Extra safe-skip list (titles or exe substrings, case-insensitive)
DEFAULT_SKIP_SUBSTR = [
    # Common overlays & helpers
    "nvidia overlay", "nvidia share", "nvidia shadowplay",
    "textinputhost.exe", "microsoft text input application",
    "game bar", "xbox game bar", "shell experience host",
    "runtimebroker.exe",
    # Common launchers/clients you might want to keep
    "steam overlay", "steamwebhelper.exe",
    # Our own preview window title default
    "handclose (press q to quit)",
]


def _is_system_process(proc_name: str):
    if not proc_name:
        return True
    s = proc_name.lower()
    return s in {
        "system", "system idle process", "services.exe", "wininit.exe", "svchost.exe",
        "lsass.exe", "smss.exe", "csrss.exe", "winlogon.exe", "spoolsv.exe",
        "fontdrvhost.exe", "dwm.exe", "ctfmon.exe", "taskhostw.exe",
    }


def _matches_skip(substrings, title: str, exe: str):
    lt = (title or "").lower()
    le = (exe or "").lower()
    for sub in substrings:
        s = sub.strip().lower()
        if not s:
            continue
        if s in lt or s in le:
            return True
    return False


def list_user_windows(whitelist=None):
    """
    Enumerate top-level visible windows and return candidates for closing.
    whitelist: list of substrings (case-insensitive) for exe names or window titles to ignore.
    Returns list of dicts: {'hwnd': int, 'pid': int, 'exe': str, 'title': str}
    """
    whitelist = whitelist or []
    candidates = []

    if win32gui is None:
        raise RuntimeError("pywin32 is required for listing windows on Windows")

    current_pid = os.getpid()  # protect our own process and its windows

    def enum_handler(hwnd, ctx):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title or title.strip() == "":
                return

            tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            # skip self-process windows (including our preview)
            if pid == current_pid:
                return

            try:
                proc = psutil.Process(pid)
                exe = proc.name()
            except Exception:
                exe = ""

            low_title = (title or "").lower()
            low_exe = (exe or "").lower()

            # skip system processes
            if _is_system_process(exe):
                return

            # skip via whitelist file
            for w in whitelist:
                wlow = (w or "").strip().lower()
                if not wlow or wlow.startswith("#"):
                    continue
                if wlow in low_title or wlow in low_exe:
                    return

            # skip via default safe-skip list (overlays, text input, etc.)
            if _matches_skip(DEFAULT_SKIP_SUBSTR, title, exe):
                return

            candidates.append({"hwnd": hwnd, "pid": pid, "exe": exe, "title": title})
        except Exception:
            log.exception("Error enumerating window %s", hwnd)

    win32gui.EnumWindows(enum_handler, None)
    return candidates


def close_application(entry, simulate=True, grace_period=4.0):
    """
    entry = {'hwnd': int, 'pid': int, 'exe': str, 'title': str}
    simulate=True -> just log; otherwise attempt graceful WM_CLOSE then force.
    Returns dict with result info.
    """
    res = {"entry": entry, "simulated": simulate, "closed": False, "forced": False}
    hwnd = entry.get("hwnd")
    pid = entry.get("pid")
    try:
        if simulate:
            log.info("[SIM] Would close: %s (%s) pid=%s hwnd=%s",
                     entry.get("title"), entry.get("exe"), pid, hwnd)
            return res

        # 1) Post WM_CLOSE
        try:
            log.info("Posting WM_CLOSE to hwnd=%s title=%s", hwnd, entry.get("title"))
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            log.exception("Failed to post WM_CLOSE to hwnd=%s", hwnd)

        # 2) Wait for process to end
        try:
            proc = psutil.Process(pid)
        except Exception:
            proc = None

        t0 = time.time()
        while proc and proc.is_running() and (time.time() - t0 < grace_period):
            time.sleep(0.2)

        if proc and proc.is_running():
            # force
            log.warning("Process pid=%s did not exit after WM_CLOSE — forcing termination", pid)
            try:
                proc.terminate()
                proc.wait(timeout=5)
                res["forced"] = True
            except Exception:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    res["forced"] = True
                except Exception:
                    log.exception("Failed to force-kill pid=%s", pid)
        else:
            res["closed"] = True
    except Exception:
        log.exception("Error closing application: %s", entry)
    return res
