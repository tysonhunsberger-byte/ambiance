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
