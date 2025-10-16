import sys
import zipfile

from ambiance.integrations.external_apps import ExternalAppManager


def test_status_handles_missing_installers(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)

    status = manager.status()

    assert status["modalys"]["zip_present"] is False
    assert status["modalys"]["installed"] is False
    assert status["praat"]["zip_present"] is False
    assert status["platform_supported"] in {True, False}


def test_installation_paths_created_on_extract(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)
    modalys_folder = tmp_path / ".cache" / "external_apps" / "modalys"
    modalys_folder.mkdir(parents=True)
    target = modalys_folder / manager.modalys_executable_name
    target.write_bytes(b"")

    assert manager.modalys_installation() == target


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


def test_ensure_workspace_from_zip(tmp_path):
    src = tmp_path / "source"
    nested = src / "demo"
    nested.mkdir(parents=True)
    (nested / "index.html").write_text("<html>demo</html>", encoding="utf-8")
    bin_dir = nested / "bin"
    bin_dir.mkdir()
    (bin_dir / "tool.exe").write_text("echo hi", encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in nested.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())

    manager = ExternalAppManager(base_dir=tmp_path)
    info = manager.ensure_workspace(archive, name="Demo Workspace")

    assert info.slug == "demo-workspace"
    assert info.entry == "index.html"
    assert info.executable == "bin/tool.exe"
    payloads = manager.workspaces_payload()
    assert payloads and payloads[0]["entry_url"].endswith("index.html")
    asset = manager.workspace_asset(info.slug, None)
    assert asset and asset.name == "index.html"


def test_launch_workspace_runs_executable(tmp_path):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "index.html").write_text("<html>runner</html>", encoding="utf-8")
    runner = workspace_dir / "runner.py"
    runner.write_text("#!/usr/bin/env python3\nprint('workspace ok')\n", encoding="utf-8")
    runner.chmod(0o755)

    manager = ExternalAppManager(base_dir=tmp_path)
    info = manager.ensure_workspace(
        workspace_dir,
        name="Runner",
        entry="index.html",
        executable="runner.py",
    )

    result = manager.launch_workspace(info.slug, wait=True, timeout=5)

    assert result["ok"] is True
    assert "workspace ok" in result["stdout"]
    assert manager.remove_workspace(info.slug) is True
    assert manager.workspace_info(info.slug) is None
