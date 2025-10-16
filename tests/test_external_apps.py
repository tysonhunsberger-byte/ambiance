import stat
import sys

from ambiance.integrations.external_apps import ExternalAppManager


def test_status_reports_workspace(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)

    status = manager.status()

    assert status["workspace"] == str(manager.workspace_path())
    assert status["workspace_exists"] is True
    assert status["executables"] == []
    assert status["count"] == 0
    assert status["platform_supported"] in {True, False}


def test_discover_workspace_finds_executables(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    exe = workspace / "tool.exe"
    exe.write_bytes(b"")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)

    script = workspace / "run.sh"
    script.write_bytes(b"#!/bin/sh\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    nested_dir = workspace / "Something.app"
    (nested_dir / "Contents").mkdir(parents=True)

    entries = manager.discover_workspace()
    names = {entry["name"] for entry in entries}

    assert "tool.exe" in names
    assert "run.sh" in names
    assert "Something.app" in names


def test_non_executables_are_skipped(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    (workspace / "README.txt").write_text("not executable")

    entries = manager.discover_workspace()

    assert entries == []


def test_launch_external_waits_and_captures_output(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)
    script = "print('hello from test')"
    result = manager.launch_external(
        sys.executable,
        args=["-c", script],
        wait=True,
        timeout=5,
    )

    assert result["ok"] is True
    assert "hello from test" in result["stdout"]
    assert result["returncode"] == 0


def test_launch_external_background_returns_pid(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)

    result = manager.launch_external(
        sys.executable,
        args=["-c", "print('background run')"],
        wait=False,
    )

    assert result["ok"] is True
    assert isinstance(result.get("pid"), int)


def test_launch_external_with_string_args(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)

    result = manager.launch_external(
        sys.executable,
        args='-c "print(123)"',
        wait=True,
        timeout=5,
    )

    assert result["ok"] is True
    assert "123" in result["stdout"]
