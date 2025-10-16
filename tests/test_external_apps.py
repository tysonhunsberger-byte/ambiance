import sys
import zipfile

from ambiance.integrations.external_apps import ExternalAppManager


def test_status_handles_missing_installers(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)

    status = manager.status()

    assert status["modalys"]["zip_present"] is False
    assert status["modalys"]["installed"] is False
    assert status["modalys"]["installer_only"] is False
    assert status["modalys"]["path"] is None
    assert status["praat"]["zip_present"] is False
    assert status["platform_supported"] in {True, False}


def test_installation_paths_created_on_extract(tmp_path):
    manager = ExternalAppManager(base_dir=tmp_path)
    modalys_folder = tmp_path / ".cache" / "external_apps" / "modalys"
    modalys_folder.mkdir(parents=True)
    target = modalys_folder / manager.modalys_executable_name
    target.write_bytes(b"")

    assert manager.modalys_installation() == target


def test_status_detects_installer_only(tmp_path):
    archive = tmp_path / "Modalys 3.9.0 for Windows.zip"
    installer_name = "Modalys for Max 3.9.0 Installer.exe"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(installer_name, b"")

    manager = ExternalAppManager(base_dir=tmp_path)

    # Extraction should yield the installer path.
    located = manager.ensure_modalys_installed()
    assert located is not None
    assert located.name == installer_name

    status = manager.status()
    assert status["modalys"]["zip_present"] is True
    assert status["modalys"]["installer_only"] is True
    assert status["modalys"]["installed"] is False
    assert "installer" in (status["modalys"]["kind"] or "")


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
