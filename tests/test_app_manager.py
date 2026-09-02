# tests/test_app_manager.py
import types
import pytest

# We'll monkeypatch win32 functions and psutil for a simulated environment
import app_manager

def test_list_user_windows_monkeypatch(monkeypatch):
    # Prepare fake window list
    fake_windows = [
        {"hwnd": 100, "title": "Notepad - test", "pid": 2000, "exe": "notepad.exe"},
        {"hwnd": 101, "title": "System Window", "pid": 4, "exe": "System"},
        {"hwnd": 102, "title": "MyApp", "pid": 3000, "exe": "myapp.exe"},
    ]

    # Monkeypatch win32gui.EnumWindows to call callback with titles we created
    def fake_enum(callback, _):
        for w in fake_windows:
            callback(w["hwnd"], None)
    monkeypatch.setattr(app_manager, "win32gui", types.SimpleNamespace(
        EnumWindows=fake_enum,
        IsWindowVisible=lambda h: True,
        GetWindowText=lambda hwnd: next((w["title"] for w in fake_windows if w["hwnd"]==hwnd), ""),
    ))
    # Mock win32process
    monkeypatch.setattr(app_manager, "win32process", types.SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (0, next((w["pid"] for w in fake_windows if w["hwnd"]==hwnd), 0))
    ))
    # Mock psutil.Process to return name for pid
    class FakeProc:
        def __init__(self, pid):
            self.pid = pid
        def name(self):
            return next((w["exe"] for w in fake_windows if w["pid"]==self.pid), "")
    monkeypatch.setattr(app_manager, "psutil", types.SimpleNamespace(Process=lambda pid: FakeProc(pid)))
    # Now call list_user_windows with whitelist to skip 'myapp'
    whitelist = ["myapp"]
    results = app_manager.list_user_windows(whitelist=whitelist)
    # Should include Notepad but skip myapp and system
    assert any("Notepad" in r["title"] for r in results)
    assert not any("MyApp" in r["title"] for r in results)
