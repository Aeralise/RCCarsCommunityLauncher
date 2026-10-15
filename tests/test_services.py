import json
import struct
import tempfile
import zipfile
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rccars_launcher import services
from rccars_launcher.services import (
    write_ini_value, read_ini_value, patch_crs_resolutions,
    patch_config_gm, is_large_address_aware, enable_large_address_aware,
    game_language_registry_value, game_language_ui_value, detect_instance,
)
from rccars_launcher.modmanager import ModRecord, apply_mods, scan_mods


def test_ini_preserve_comment_and_sections():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.ini"
        path.write_bytes(b"[MAIN]\r\nWidth=800 ; original width\r\nHeight=600\r\n\r\n[FPS]\r\nLimit=0\r\n")
        write_ini_value(path, "MAIN", "Width", "1920")
        write_ini_value(path, "DEBUG", "NoMinimize", "1")
        assert read_ini_value(path, "MAIN", "Width") == "1920"
        raw = path.read_bytes()
        assert b"1920 ; original width" in raw
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")
        assert read_ini_value(path, "DEBUG", "NoMinimize") == "1"


def test_language_registry_russian_mapping():
    assert game_language_registry_value("Russian") == "Русский"
    assert game_language_registry_value("Русский") == "Русский"
    assert game_language_registry_value("Polish") == "Polish"
    assert game_language_ui_value("Русский") == "Russian"
    assert game_language_ui_value("English") == "English"


def test_portable_data_directory():
    with tempfile.TemporaryDirectory() as td:
        launcher_dir = Path(td)
        with patch.object(services, "runtime_dir", return_value=launcher_dir):
            assert services.user_data_dir() == launcher_dir / "data"
            assert (launcher_dir / "data").is_dir()


def test_pack_extraction_renames_archive_in_place():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "game"
        root.mkdir()
        pack = root / "RCCars.pack"
        pack.write_bytes(b"HEADpayload")
        entry = SimpleNamespace(path="CacheData/sample.bin", size=7, data_offset=0, flags=0)
        chunk = SimpleNamespace(chunk_id=services.DATA_CHUNK, extra=7, data_start=4, end=11)
        with patch.object(services, "parse_pack", return_value=("CREAT Studio Pack 1.0", "key", [entry], 0)), \
             patch.object(services, "read_chunk", return_value=chunk):
            extracted = services.extract_pack_to_game_root(pack, root, root / "launcher-backups")
        assert extracted == 1
        assert not pack.exists()
        assert (root / "_RCCars.pack").read_bytes() == b"HEADpayload"
        assert (root / "CacheData" / "sample.bin").read_bytes() == b"payload"
        for folder in ("CacheData", "CarProfiles", "FacesSys"):
            (root / folder).mkdir(exist_ok=True)
        assert detect_instance(root)["pack_status"] == "unpacked"


def test_pack_detection_for_new_instance_with_loose_game_folders():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "fresh-instance"
        root.mkdir()
        exe = root / "RCCars.exe"
        exe.write_bytes(b"not-a-real-pe")
        (root / "CacheData").mkdir()
        (root / "Textures1").mkdir()
        details = detect_instance(root)
        assert details["pack_status"] == "unpacked"
        assert details["pack_file"] is False


def test_multiple_loose_game_folders_override_pack_status():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "partially-unpacked-instance"
        root.mkdir()
        (root / "RCCars.exe").write_bytes(b"not-a-real-pe")
        (root / "RCCars.pack").write_bytes(b"archive still present")
        for name in ("CacheData", "CarProfiles", "Textures1"):
            (root / name).mkdir()
        assert detect_instance(root)["pack_status"] == "unpacked"


def test_pack_absence_is_treated_as_unpacked_for_new_instance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pack-removed-instance"
        root.mkdir()
        (root / "RCCars.exe").write_bytes(b"not-a-real-pe")
        assert detect_instance(root)["pack_status"] == "unpacked"


def test_pack_rename_preserves_existing_archive():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "game"; root.mkdir()
        pack = root / "RCCars.pack"; pack.write_bytes(b"current archive")
        (root / "_RCCars.pack").write_bytes(b"older archive")
        entry = SimpleNamespace(path="sample.bin", size=7, data_offset=0, flags=0)
        chunk = SimpleNamespace(chunk_id=services.DATA_CHUNK, extra=7, data_start=4, end=11)
        with patch.object(services, "parse_pack", return_value=("CREAT Studio Pack 1.0", "key", [entry], 0)), \
             patch.object(services, "read_chunk", return_value=chunk):
            services.extract_pack_to_game_root(pack, root, root / "launcher-backups")
        assert (root / "_RCCars.pack").read_bytes() == b"older archive"
        assert list(root.glob("_RCCars-*.pack"))


def test_new_ini_defaults_use_crlf():
    with tempfile.TemporaryDirectory() as td:
        ini = Path(td) / "RCCars_WidescreenFix.ini"
        services.ensure_widescreen_ini(ini, 2560, 1440)
        raw = ini.read_bytes()
        assert b"Width=2560\r\nHeight=1440\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")


def test_compatibility_installer_skips_current_components_and_updates_changed_release():
    messages = []
    remote = {"wsf": "v1.5", "loader": "loader-sha-1"}

    def progress(value, message):
        messages.append((value, message))

    def api_response(url):
        if f"repos/{services.WSF_REPO}/releases/latest" in url:
            return {"tag_name": remote["wsf"], "assets": []}
        if url.endswith("/releases/tags/Win32-latest"):
            return {"tag_name": "Win32-latest", "assets": [{"name": "dinput8-Win32.zip", "digest": remote["loader"], "updated_at": remote["loader"], "size": 4567}]}
        raise AssertionError(f"Unexpected GitHub API URL: {url}")

    def fake_loader(root, backup, callback=None):
        (root / "dinput8.dll").write_bytes(b"MZ fake ASI loader")
        if callback:
            callback(100, "fake loader downloaded")
        return "loader installed"

    def fake_fix(root, backup, callback=None, release_info=None):
        assert release_info["tag_name"] == remote["wsf"]
        (root / "RCCars_WidescreenFix.asi").write_bytes(b"fake widescreen fix " + remote["wsf"].encode())
        if callback:
            callback(100, "fake fix downloaded")
        return "fix installed"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "game"; root.mkdir()
        backup = Path(td) / "backup"
        with patch.object(services, "github_json", side_effect=api_response), \
             patch.object(services, "install_asi_loader", side_effect=fake_loader) as loader, \
             patch.object(services, "install_widescreen_fix", side_effect=fake_fix) as fix:
            first = services.install_compatibility_components(root, backup, progress)
            loader.assert_called_once()
            fix.assert_called_once()
            assert "loader installed" in first and "fix installed" in first
            assert messages[-1][0] == 100

            loader.reset_mock(); fix.reset_mock()
            second = services.install_compatibility_components(root, backup, progress)
            loader.assert_not_called()
            fix.assert_not_called()
            assert "up to date" in second.lower()

            remote["wsf"] = "v1.6"
            third = services.install_compatibility_components(root, backup, progress)
            loader.assert_not_called()
            fix.assert_called_once()
            state = services._read_component_state(backup)
            assert state["components"]["widescreen_fix"]["version"] == "v1.6"


def test_component_file_hash_detects_manual_replacement():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "game"; root.mkdir()
        backup = Path(td) / "backup"; backup.mkdir()
        dll = root / "dinput8.dll"; dll.write_bytes(b"version one")
        state = {"components": {"asi_loader": {"version": "abc123", "sha256": services._sha256_file(dll)}}}
        assert services._component_is_current(root, state, "asi_loader", "dinput8.dll", "abc123")
        dll.write_bytes(b"manually replaced")
        assert not services._component_is_current(root, state, "asi_loader", "dinput8.dll", "abc123")


def test_crs_patch_two_fields_each_axis():
    def record(key: bytes, current: int) -> bytes:
        return key + b"\x00\x00\x01\x00\x04\x00" + struct.pack("<H", current) + b"\x00\x00\x20\x03"
    data = b"PREFIX" + record(b"XResolution", 800) + b"GAP" + record(b"XResolution", 800) + b"GAP2" + record(b"YResolution", 600) + b"GAP3" + record(b"YResolution", 600)
    patched, x_count, y_count = patch_crs_resolutions(data, 1920, 1080)
    assert (x_count, y_count) == (2, 2)
    assert patched.count(struct.pack("<H", 1920)) == 2
    assert patched.count(struct.pack("<H", 1080)) == 2


def test_config_gm_flags():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); backup = root / "backup"
        (root / "Config.gm").write_text('Set "VIDEO_UseFog" 1\nSet "Gamma_Changes" 0\nSet "AutoRunIntro" 1\n', encoding="utf-8")
        result = patch_config_gm(root, {"VIDEO_UseFog": False, "Gamma_Changes": True, "AutoRunIntro": False}, backup)
        text = (root / "Config.gm").read_text(encoding="utf-8")
        assert 'Set "VIDEO_UseFog" 0' in text
        assert 'Set "Gamma_Changes" 1' in text
        assert 'Set "AutoRunIntro" 0' in text
        assert (backup / "Config.gm").is_file()


def test_laa_flag_patch():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); exe = root / "RCCars.exe"; backup = root / "backup"
        data = bytearray(512)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", data, 0x84, 0x14C)
        struct.pack_into("<H", data, 0x80 + 24, 0x10B)
        struct.pack_into("<H", data, 0x80 + 22, 0x0102)
        exe.write_bytes(data)
        assert not is_large_address_aware(exe)
        assert enable_large_address_aware(exe, root, backup)
        assert is_large_address_aware(exe)
        assert (backup / "RCCars.exe").exists()


def test_steam_stub_bind_section_is_detected_outside_steam_folder():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "copied-steam-game"; root.mkdir()
        exe = root / "RCCars.exe"
        data = bytearray(1024)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", data, 0x84, 0x14C)
        struct.pack_into("<H", data, 0x80 + 6, 1)
        struct.pack_into("<H", data, 0x80 + 20, 224)
        struct.pack_into("<H", data, 0x80 + 22, 0x010F)
        struct.pack_into("<H", data, 0x80 + 24, 0x10B)
        section = 0x80 + 24 + 224
        data[section:section + 8] = b".bind\0\0\0"
        exe.write_bytes(data)
        assert services.is_steam_stub_wrapped(exe)
        assert services.detect_instance(root)["steam"]
        try:
            services.enable_large_address_aware(exe, root, Path(td) / "backups")
            raise AssertionError("Expected SteamStub LAA patch to be blocked")
        except ValueError as exc:
            assert "SteamStub-wrapped" in str(exc)
        assert not services.is_large_address_aware(exe)


def test_steam_laa_patch_is_refused():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "steamapps" / "common" / "RC Cars"
        root.mkdir(parents=True)
        manifest = root.parents[1] / "appmanifest_289460.acf"
        manifest.write_text('"AppState" { "appid" "289460" }', encoding="utf-8")
        exe = root / "RCCars.exe"
        data = bytearray(512)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", data, 0x84, 0x14C)
        struct.pack_into("<H", data, 0x80 + 24, 0x10B)
        struct.pack_into("<H", data, 0x80 + 22, 0x0102)
        exe.write_bytes(data)
        try:
            enable_large_address_aware(exe, root, Path(td) / "backup")
            raise AssertionError("Expected Steam LAA patch to be blocked")
        except ValueError as exc:
            assert "Steam-managed" in str(exc)
        assert not is_large_address_aware(exe)


def test_mod_overlay_and_restore():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "game"; root.mkdir()
        launcher_dir = Path(td) / "launcher"
        launcher_dir.mkdir()
        mods_dir = root / "Mods"; mods_dir.mkdir()
        update = root / "update"; update.mkdir()
        (update / "same.txt").write_text("original", encoding="utf-8")
        zip_path = mods_dir / "TestMod.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("same.txt", "from mod")
            z.writestr("Folder/new.txt", "new")
        with patch.object(services, "runtime_dir", return_value=launcher_dir):
            records, state = scan_mods(root, "test-instance")
            records[0].enabled = True
            apply_mods(root, "test-instance", records, Path(td) / "backups")
            assert (update / "same.txt").read_text(encoding="utf-8") == "from mod"
            assert (update / "Folder/new.txt").read_text(encoding="utf-8") == "new"
            records[0].enabled = False
            apply_mods(root, "test-instance", records, Path(td) / "backups")
            assert (update / "same.txt").read_text(encoding="utf-8") == "original"
            assert not (update / "Folder/new.txt").exists()


if __name__ == "__main__":
    test_ini_preserve_comment_and_sections()
    test_language_registry_russian_mapping()
    test_portable_data_directory()
    test_pack_extraction_renames_archive_in_place()
    test_pack_detection_for_new_instance_with_loose_game_folders()
    test_multiple_loose_game_folders_override_pack_status()
    test_pack_absence_is_treated_as_unpacked_for_new_instance()
    test_pack_rename_preserves_existing_archive()
    test_new_ini_defaults_use_crlf()
    test_combined_installer_runs_both_components()
    test_crs_patch_two_fields_each_axis()
    test_config_gm_flags()
    test_laa_flag_patch()
    test_steam_stub_bind_section_is_detected_outside_steam_folder()
    test_steam_laa_patch_is_refused()
    test_mod_overlay_and_restore()
    print("All tests passed")


def test_launcher_update_prefers_portable_runtime_zip_over_exe():
    release = {
        "tag_name": "v0.1.5",
        "name": "RC Cars Launcher 0.1.5",
        "html_url": "https://github.com/example/RCCarsLauncher/releases/tag/v0.1.5",
        "assets": [
            {"name": "RCCarsLauncher.exe", "browser_download_url": "https://example/launcher.exe", "size": 1000},
            {"name": "RCCarsLauncher_Portable.zip", "browser_download_url": "https://example/launcher.zip", "size": 5000},
        ],
    }
    with patch.object(services, "github_json", return_value=release):
        result = services.check_launcher_update("example/RCCarsLauncher")
    assert result["asset_name"] == "RCCarsLauncher_Portable.zip"
    assert result["asset_url"] == "https://example/launcher.zip"


def test_prepare_self_update_extracts_only_exe_and_runtime_from_portable_zip():
    from io import BytesIO
    from unittest.mock import patch

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("RCCarsLauncher.exe", b"MZlauncher-binary")
        archive.writestr("_runtime/Python.dll", b"python-runtime")
        archive.writestr("_runtime/PySide6/QtCore.pyd", b"qt-runtime")
        archive.writestr("launcher_config.json", b'{"launcher_update_repo":"example/repo"}')
        archive.writestr("data/launcher.json", b'{"instances":[]}')

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "launcher-data"
        with patch.object(services, "user_data_dir", return_value=data_dir), \
             patch.object(services, "download_bytes", return_value=archive_bytes.getvalue()), \
             patch.object(services.sys, "frozen", True, create=True):
            staged_exe, cmd = services.prepare_self_update("https://example/launcher.zip", "RCCarsLauncher_Portable.zip")
        assert staged_exe.read_bytes().startswith(b"MZ")
        assert (staged_exe.parent / "_runtime" / "Python.dll").read_bytes() == b"python-runtime"
        assert (staged_exe.parent / "_runtime" / "PySide6" / "QtCore.pyd").read_bytes() == b"qt-runtime"
        assert not (staged_exe.parent / "launcher_config.json").exists()
        assert not (staged_exe.parent / "data").exists()
        script = cmd.read_text(encoding="utf-8")
        assert "_runtime.old" in script
        assert "RCCarsLauncher.exe" in script
