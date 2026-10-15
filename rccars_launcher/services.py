from __future__ import annotations

import configparser
import ctypes
import json
import hashlib
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from rccars_pack_tool import parse_pack, read_chunk, safe_output_path, xor_transform, DATA_CHUNK

APP_NAME = "RC Cars Launcher"
STEAM_APP_ID = "289460"  # RC Cars (2003), Steam
WSF_REPO = "Aeralise/RCCars_WidescreenFix"
ASI_LOADER_REPO = "ThirteenAG/Ultimate-ASI-Loader"
ASI_LOADER_DOWNLOAD = "https://github.com/ThirteenAG/Ultimate-ASI-Loader/releases/download/Win32-latest/dinput8-Win32.zip"
CONFIG_KEYS = {
    "VIDEO_UseFog": "fog",
    "Gamma_Changes": "gamma",
    "AutoRunIntro": "intro",
}


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def legacy_user_data_dir() -> Path:
    """Return the per-user path used by launcher versions before portable-data support."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Aeralise" / "RCCarsLauncher"


def user_data_dir() -> Path:
    """Store mutable launcher state next to the executable in a portable data folder."""
    path = runtime_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_user_data(local_dir: Optional[Path] = None) -> bool:
    """One-time migration of a previous AppData profile to the new portable directory."""
    local_dir = local_dir or user_data_dir()
    legacy = legacy_user_data_dir()
    if legacy.resolve() == local_dir.resolve() or (local_dir / "launcher.json").exists() or not legacy.is_dir():
        return False
    local_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy, local_dir, dirs_exist_ok=True)
    return True


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def new_instance(name: str, path: Path, icon: str = "") -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": name.strip() or path.name or "RC Cars",
        "path": str(path.resolve()),
        "icon": icon,
        "added_at": int(time.time()),
    }


def locate_game_exe(game_root: Path) -> Path:
    candidates = [game_root / "RCCars.exe", game_root / "RCCars" / "RCCars.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Case-insensitive fallback for files copied from unusual archives.
    try:
        for item in game_root.iterdir():
            if item.is_file() and item.name.lower() == "rccars.exe":
                return item
    except OSError:
        pass
    raise FileNotFoundError(f"RCCars.exe was not found in: {game_root}")


def steam_manifest_for_path(game_root: Path) -> Optional[Path]:
    current = game_root.resolve()
    for parent in [current, *current.parents]:
        if parent.name.lower() == "steamapps":
            manifest = parent / f"appmanifest_{STEAM_APP_ID}.acf"
            if manifest.is_file():
                return manifest
    # Typical install: .../steamapps/common/RC Cars.
    for parent in [current, *current.parents]:
        if parent.name.lower() == "common" and parent.parent.name.lower() == "steamapps":
            manifest = parent.parent / f"appmanifest_{STEAM_APP_ID}.acf"
            if manifest.is_file():
                return manifest
    return None


def pe_section_names(path: Path) -> list[str]:
    """Return PE section names; used to recognize SteamStub's characteristic .bind section."""
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("Not a Windows PE executable (MZ header missing)")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_table = pe_offset + 24 + optional_header_size
    if number_of_sections > 96 or section_table + number_of_sections * 40 > len(data):
        raise ValueError("Invalid PE section table")
    names: list[str] = []
    for index in range(number_of_sections):
        offset = section_table + index * 40
        raw_name = data[offset:offset + 8].split(b"\0", 1)[0]
        names.append(raw_name.decode("ascii", errors="replace"))
    return names


def is_steam_stub_wrapped(path: Path) -> bool:
    """SteamStub-protected executables conventionally contain a '.bind' section."""
    try:
        return ".bind" in pe_section_names(path)
    except (OSError, ValueError, struct.error):
        return False


def detect_instance(game_root: Path) -> dict[str, Any]:
    root = game_root.expanduser().resolve()
    exe = root / "RCCars.exe"
    if not exe.is_file():
        try:
            exe = locate_game_exe(root)
        except FileNotFoundError:
            exe = root / "RCCars.exe"
    pack = root / "RCCars.pack"
    archived_pack = root / "_RCCars.pack"
    known_dirs = [
        "CacheData", "CarProfiles", "FacesSys", "Profiles", "Scripts", "Settings",
        "Sound", "Splines", "Textures1", "Textures2", "Textures3",
    ]
    loose_dirs = sum((root / name).is_dir() for name in known_dirs)
    # The retained _RCCars.pack name is a strong signal that the launcher extracted
    # the archive. Loose game folders are also sufficient even if no backup pack
    # remains (for example, a manually unpacked installation).
    if pack.is_file() and not archived_pack.is_file() and loose_dirs < 3:
        pack_status = "packed"
    else:
        # A missing RCCars.pack is treated as already extracted as requested. This
        # also covers copies where the archive was deleted instead of renamed.
        # Multiple known loose directories or the retained _RCCars.pack are an
        # extraction signal even when a fresh RCCars.pack is also present.
        pack_status = "unpacked"
    wsf_files = list(root.glob("*WidescreenFix*.asi")) + list(root.glob("*WidescreenFix*.ASI"))
    if not wsf_files:
        wsf_files = [p for p in root.glob("*.asi") if "rccars" in p.name.lower() and "wide" in p.name.lower()]
    loader = root / "dinput8.dll"
    if not loader.exists():
        loader = root / "DINPUT8.DLL"
    crs = root / "RCCars.crs"
    ini = root / "RCCars_WidescreenFix.ini"
    steam_manifest = steam_manifest_for_path(root)
    steam_stub_wrapped = is_steam_stub_wrapped(exe) if exe.is_file() else False
    return {
        "valid_exe": exe.is_file(),
        "exe": str(exe),
        "steam": steam_manifest is not None or steam_stub_wrapped,
        "steam_manifest": str(steam_manifest or ""),
        "steam_stub_wrapped": steam_stub_wrapped,
        "pack_status": pack_status,
        "pack_file": pack.is_file(),
        "archived_pack": archived_pack.is_file(),
        "loose_dirs": loose_dirs,
        "widescreen_fix": bool(wsf_files),
        "widescreen_files": [str(p) for p in wsf_files],
        "asi_loader": loader.is_file(),
        "asi_loader_file": str(loader) if loader.is_file() else "",
        "crs_file": crs.is_file(),
        "ini_file": ini.is_file(),
        "large_address_aware": is_large_address_aware(exe) if exe.is_file() else False,
    }


def backup_file_once(game_root: Path, source: Path, backup_root: Path) -> Optional[Path]:
    """Copy a file into the per-instance backup tree only if no baseline exists yet."""
    if not source.exists() or not source.is_file():
        return None
    try:
        relative = source.resolve().relative_to(game_root.resolve())
    except ValueError:
        relative = Path("external") / source.name
    dest = backup_root / relative
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    return dest


def write_ini_value(path: Path, section: str, key: str, value: str) -> None:
    """Update one INI key while preserving encoding, line endings, comments and unrelated keys."""
    if path.exists():
        raw = path.read_bytes()
        if b"\r\n" in raw:
            newline = "\r\n"
        elif b"\r" in raw and b"\n" not in raw:
            newline = "\r"
        elif b"\n" in raw:
            newline = "\n"
        else:
            newline = "\r\n" if os.name == "nt" else "\n"
        if raw.startswith(b"\xef\xbb\xbf"):
            text, encoding = raw.decode("utf-8-sig"), "utf-8-sig"
        else:
            try:
                text, encoding = raw.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                text, encoding = raw.decode("cp1252", errors="replace"), "cp1252"
    else:
        text, encoding = "", "utf-8"
        newline = "\r\n" if os.name == "nt" else "\n"
    lines = text.splitlines()
    section_re = re.compile(r"^\s*\[\s*([^\]]+)\s*\]\s*$", re.I)
    key_re = re.compile(r"^\s*" + re.escape(key) + r"\s*=", re.I)
    section_start = None
    section_end = len(lines)
    for i, line in enumerate(lines):
        match = section_re.match(line)
        if match:
            if section_start is not None:
                section_end = i
                break
            if match.group(1).strip().lower() == section.lower():
                section_start = i
                section_end = len(lines)
    if section_start is not None:
        for i in range(section_start + 1, section_end):
            if key_re.match(lines[i]):
                old = lines[i]
                comment_pos = None
                for marker in (";", "#"):
                    found = old.find(marker)
                    if found >= 0 and (comment_pos is None or found < comment_pos):
                        comment_pos = found
                suffix = old[comment_pos:] if comment_pos is not None else ""
                value_part = old[:comment_pos] if comment_pos is not None else old
                prefix_match = re.match(r"^(\s*" + re.escape(key) + r"\s*=\s*).*$", value_part, re.I)
                prefix = prefix_match.group(1) if prefix_match else f"{key}="
                lines[i] = prefix + str(value) + ((" " if suffix and not suffix.startswith(" ") else "") + suffix if suffix else "")
                break
        else:
            lines.insert(section_end, f"{key}={value}")
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", f"{key}={value}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    output = newline.join(lines).rstrip("\r\n") + newline
    path.write_bytes(output.encode(encoding))


def read_ini_value(path: Path, section: str, key: str, default: str = "") -> str:
    if not path.is_file():
        return default
    section_re = re.compile(r"^\s*\[\s*([^\]]+)\s*\]\s*$", re.I)
    key_re = re.compile(r"^\s*" + re.escape(key) + r"\s*=\s*(.*?)\s*(?:[;#].*)?$", re.I)
    active = False
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252", errors="replace")
    for line in text.splitlines():
        section_match = section_re.match(line)
        if section_match:
            active = section_match.group(1).strip().lower() == section.lower()
            continue
        if active:
            match = key_re.match(line)
            if match:
                return match.group(1).strip()
    return default


def ensure_widescreen_ini(path: Path, width: int, height: int, backup_root: Optional[Path] = None, game_root: Optional[Path] = None) -> None:
    if not path.exists():
        template = (
            "[MAIN]\r\n"
            f"Width={width}\r\nHeight={height}\r\nAspect=0\r\nFixFOV=1\r\nCustomFOV=80\r\nFixHUD=1\r\nLegacyFixHUD=1\r\n\r\n"
            "[FPS]\r\nLimit=0\r\n\r\n[DEBUG]\r\nNoMinimize=0\r\n"
        )
        path.write_bytes(template.encode("utf-8"))
    elif backup_root is not None and game_root is not None:
        backup_file_once(game_root, path, backup_root)
    # Ensure expected sections/keys exist without clobbering an existing user's settings.
    defaults = [
        ("MAIN", "Width", str(width)), ("MAIN", "Height", str(height)),
        ("MAIN", "Aspect", "0"), ("MAIN", "FixFOV", "1"),
        ("MAIN", "CustomFOV", "80"), ("MAIN", "FixHUD", "1"),
        ("MAIN", "LegacyFixHUD", "1"), ("FPS", "Limit", "0"),
        ("DEBUG", "NoMinimize", "0"),
    ]
    for section, key, value in defaults:
        if read_ini_value(path, section, key, "__MISSING__") == "__MISSING__":
            write_ini_value(path, section, key, value)


def update_graphics_ini(game_root: Path, width: int, height: int, fix_fov: bool,
                        custom_fov: int, fix_hud: bool, legacy_fix_hud: bool,
                        fps_limit: int, no_minimize: bool, backup_root: Path) -> Path:
    ini_path = game_root / "RCCars_WidescreenFix.ini"
    ensure_widescreen_ini(ini_path, width, height, backup_root, game_root)
    values = [
        ("MAIN", "Width", width), ("MAIN", "Height", height), ("MAIN", "Aspect", 0),
        ("MAIN", "FixFOV", int(fix_fov)), ("MAIN", "CustomFOV", int(custom_fov)),
        ("MAIN", "FixHUD", int(fix_hud)), ("MAIN", "LegacyFixHUD", int(legacy_fix_hud)),
        ("FPS", "Limit", max(0, min(600, int(fps_limit)))),
        ("DEBUG", "NoMinimize", int(no_minimize)),
    ]
    for section, key, value in values:
        write_ini_value(ini_path, section, key, str(value))
    return ini_path


def _find_all(data: bytes, needle: bytes) -> list[int]:
    results: list[int] = []
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            return results
        results.append(pos)
        start = pos + 1


def _resolution_record_positions(data: bytes, keys: tuple[bytes, ...]) -> list[tuple[int, bytes]]:
    """Find actual CSRC records by their length-prefixed key names, not file order."""
    found: list[tuple[int, bytes]] = []
    for key in keys:
        for pos in _find_all(data, key):
            # A standard setting starts with b"CSRC", a little-endian string length,
            # then the NUL-terminated setting name. This filters coincidental text hits.
            if pos < 8 or data[pos - 8:pos - 4] != b"CSRC":
                continue
            name_length = struct.unpack_from("<I", data, pos - 4)[0]
            if name_length != len(key) + 1:
                continue
            if pos + name_length > len(data) or data[pos + len(key)] != 0:
                continue
            found.append((pos, key))
    # De-duplicate and preserve physical position, since typo aliases can overlap in theory.
    return sorted(set(found), key=lambda item: item[0])


def patch_crs_resolutions(data: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Patch both 32-bit LE resolution slots in each X/Y setting record.

    RCCars.crs stores two DWORDs for each resolution setting. In the supplied sample,
    the VideoRace X/Y records hold separate menu and race resolutions (1280x720 and
    1920x1080); the second X/Y pair is another persisted display-state record. Every
    slot is set to the requested resolution so menu and race cannot retain different
    values. Record discovery is name-based and independent of record order.
    """
    if not (1 <= width <= 0xFFFFFFFF and 1 <= height <= 0xFFFFFFFF):
        raise ValueError("Resolution must fit in an unsigned 32-bit integer")
    mutable = bytearray(data)
    marker = b"\x01\x00\x04\x00"
    jobs: list[tuple[int, int, str]] = []
    for label, keys, value in (
        ("X", (b"XResolution", b"XResoultion"), width),
        ("Y", (b"YResolution", b"YResoultion"), height),
    ):
        hits = _resolution_record_positions(data, keys)
        if len(hits) != 2:
            raise ValueError(
                f"RCCars.crs: expected 2 valid {label}Resolution records, found {len(hits)}. File was not modified."
            )
        for key_pos, key in hits:
            type_pos = key_pos + len(key) + 1
            if data[type_pos:type_pos + 4] != marker:
                raise ValueError(
                    f"RCCars.crs: unexpected data type for {label}Resolution near 0x{key_pos:X}. File was not modified."
                )
            value_offset = type_pos + 4
            # Two 32-bit slots follow the type marker. Validate both before writing either.
            if value_offset + 8 > len(data):
                raise ValueError(
                    f"RCCars.crs: incomplete {label}Resolution values near 0x{key_pos:X}. File was not modified."
                )
            jobs.append((value_offset, value, label))
            jobs.append((value_offset + 4, value, label))
    for offset, value, _label in jobs:
        struct.pack_into("<I", mutable, offset, value)
    return bytes(mutable), 4, 4


def patch_crs_file_if_present(game_root: Path, width: int, height: int, backup_root: Path) -> str:
    path = game_root / "RCCars.crs"
    if not path.is_file():
        return "RCCars.crs not present; skipped."
    backup_file_once(game_root, path, backup_root)
    patched, xc, yc = patch_crs_resolutions(path.read_bytes(), width, height)
    path.write_bytes(patched)
    return f"Patched RCCars.crs: {xc} X-resolution values and {yc} Y-resolution values."


def patch_config_gm(game_root: Path, values: dict[str, bool], backup_root: Path) -> str:
    path = game_root / "Config.gm"
    if not path.is_file():
        return "Config.gm not present; skipped."
    backup_file_once(game_root, path, backup_root)
    try:
        text = path.read_text(encoding="utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252", errors="replace")
        encoding = "cp1252"
    for key, enabled in values.items():
        replacement = str(int(enabled))
        pattern = re.compile(
            r"(?im)^(\s*Set\s+[\"']?" + re.escape(key) + r"[\"']?\s+)[\"']?[-+]?\d+[\"']?(.*)$"
        )
        text, count = pattern.subn(lambda m: m.group(1) + replacement + m.group(2), text)
        if count == 0:
            # Add a canonical command if the expected setting isn't already in the file.
            if text and not text.endswith("\n"):
                text += "\n"
            text += f'Set "{key}" {replacement}\n'
    path.write_text(text, encoding=encoding, newline="\n")
    return "Updated Config.gm: " + ", ".join(f"{k}={int(v)}" for k, v in values.items())


def game_language_registry_value(language: str) -> str:
    """Map launcher labels to the exact language token expected by the game."""
    if language.strip().casefold() in {"russian", "русский"}:
        return "Русский"
    return language.strip()


def game_language_ui_value(language: str) -> str:
    """Normalize the Russian registry token back to the launcher combo-box label."""
    if language.strip().casefold() in {"russian", "русский"}:
        return "Russian"
    return language.strip()


def set_game_language(language: str) -> str:
    if os.name != "nt":
        raise OSError("The game language registry setting can only be changed on Windows.")
    import winreg
    value = game_language_registry_value(language)
    key_path = r"SOFTWARE\CREAT Studio\SmashCars"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Language", 0, winreg.REG_SZ, value)
    return f"Game language set to {value}."


def get_game_language() -> str:
    if os.name != "nt":
        return "English"
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\CREAT Studio\SmashCars") as key:
            value, _kind = winreg.QueryValueEx(key, "Language")
            return game_language_ui_value(str(value))
    except OSError:
        return "English"


def pe_info(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("Not a Windows PE executable (MZ header missing)")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 26 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    characteristics = struct.unpack_from("<H", data, pe_offset + 22)[0]
    optional_magic = struct.unpack_from("<H", data, pe_offset + 24)[0]
    return pe_offset, characteristics, optional_magic


def is_large_address_aware(path: Path) -> bool:
    try:
        pe_offset, characteristics, optional_magic = pe_info(path)
        return optional_magic == 0x10B and bool(characteristics & 0x20)
    except (OSError, ValueError, struct.error):
        return False


def enable_large_address_aware(exe_path: Path, game_root: Path, backup_root: Path) -> bool:
    if steam_manifest_for_path(game_root) is not None or is_steam_stub_wrapped(exe_path):
        raise ValueError(
            "Large Address Aware is not applied to Steam-managed or SteamStub-wrapped executables. "
            "This EXE contains Steam's '.bind' bootstrap section or belongs to a Steam installation; "
            "changing its PE header may break the Steam launch/integrity check. Use Steam's Verify integrity "
            "of game files or restore an original EXE backup instead."
        )
    pe_offset, characteristics, optional_magic = pe_info(exe_path)
    if optional_magic != 0x10B:
        raise ValueError("RCCars.exe is not a 32-bit PE executable; refused to patch it")
    if characteristics & 0x20:
        return False
    backup_file_once(game_root, exe_path, backup_root)
    data = bytearray(exe_path.read_bytes())
    struct.pack_into("<H", data, pe_offset + 22, characteristics | 0x20)
    exe_path.write_bytes(data)
    return True


def restore_original_exe(exe_path: Path, game_root: Path, backup_root: Path) -> Path:
    """Restore the first pristine EXE backup created by this launcher."""
    try:
        relative = exe_path.resolve().relative_to(game_root.resolve())
    except ValueError as exc:
        raise ValueError("The executable is not inside the registered game directory") from exc
    source = backup_root / relative
    if not source.is_file():
        raise FileNotFoundError(f"No original EXE backup found at {source}. Use Steam's file verification if this is a Steam copy.")
    shutil.copy2(source, exe_path)
    return exe_path


def launch_game(game_root: Path, dev_mode: bool = False) -> subprocess.Popen:
    exe = locate_game_exe(game_root)
    args = [str(exe)]
    if dev_mode:
        args.append("-dev")
    return subprocess.Popen(args, cwd=str(game_root), close_fds=False)


def safe_archive_relative_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    p = PurePosixPath(normalized)
    if p.is_absolute() or (p.parts and ":" in p.parts[0]) or any(part in ("..", "") for part in p.parts):
        raise ValueError(f"Unsafe archive path: {name!r}")
    clean = [part for part in p.parts if part not in (".", "")]
    if not clean:
        raise ValueError(f"Empty archive path: {name!r}")
    return Path(*clean)


def extract_pack_to_game_root(pack_path: Path, game_root: Path, backup_root: Path,
                              progress: Optional[Callable[[int, str], None]] = None) -> int:
    """Extract RCCars.pack directly to the instance root; back up loose files before overwrite."""
    if not pack_path.is_file():
        raise FileNotFoundError(f"RCCars.pack not found: {pack_path}")
    game_root.mkdir(parents=True, exist_ok=True)
    with pack_path.open("rb") as handle:
        if pack_path.stat().st_size == 0:
            raise ValueError("RCCars.pack is empty")
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            title, key, entries, _data_section = parse_pack(buf)
            total = len(entries)
            for index, entry in enumerate(entries, 1):
                if entry.size is None or entry.data_offset is None:
                    raise ValueError(f"Incomplete directory entry: {entry.path}")
                chunk = read_chunk(buf, entry.data_offset)
                if chunk.chunk_id != DATA_CHUNK:
                    raise ValueError(f"{entry.path}: unexpected data chunk 0x{chunk.chunk_id:04X}")
                if chunk.extra != entry.size:
                    raise ValueError(f"{entry.path}: data chunk size doesn't match directory")
                if chunk.data_start + entry.size != chunk.end:
                    raise ValueError(f"{entry.path}: invalid data chunk boundary")
                dest = safe_output_path(game_root, entry.path)
                if dest.exists() and dest.is_file():
                    backup_file_once(game_root, dest, backup_root / "loose-files")
                payload = bytearray(buf[chunk.data_start:chunk.end])
                if entry.flags & 0x20:
                    xor_transform(payload, key)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
                if progress:
                    progress(round(index * 100 / total), f"[{index}/{total}] {entry.path}")
    # Leave the original archive in the game root under an inactive name, as requested.
    # The game looks for the exact name RCCars.pack, so _RCCars.pack is ignored.
    archived_pack = game_root / "_RCCars.pack"
    if archived_pack.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archived_pack = game_root / f"_RCCars-{stamp}.pack"
        suffix = 2
        while archived_pack.exists():
            archived_pack = game_root / f"_RCCars-{stamp}-{suffix}.pack"
            suffix += 1
    pack_path.rename(archived_pack)
    return total


def github_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "RCCarsLauncher/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"GitHub release not found: {url}") from exc
        if exc.code == 403:
            raise RuntimeError("GitHub API request was forbidden or rate-limited. Try again later.") from exc
        raise RuntimeError(f"GitHub API error {exc.code}: {exc.reason}") from exc


def download_bytes(url: str, progress: Optional[Callable[[int, str], None]] = None, label: str = "Download") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "RCCarsLauncher/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            total = int(response.headers.get("Content-Length", "0") or 0)
            chunks: list[bytes] = []
            downloaded = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(min(95, int(downloaded * 95 / total)), f"{label}: {downloaded // 1024} / {total // 1024} KB")
            if progress:
                progress(98, f"{label}: checking downloaded data")
            return b"".join(chunks)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc


def _install_file(game_root: Path, name: str, payload: bytes, backup_root: Path) -> Path:
    dest = game_root / Path(name).name
    if dest.exists():
        backup_file_once(game_root, dest, backup_root)
    dest.write_bytes(payload)
    return dest


def install_asi_loader(game_root: Path, backup_root: Path,
                       progress: Optional[Callable[[int, str], None]] = None) -> str:
    if progress:
        progress(2, "Querying official Ultimate ASI Loader release…")
    payload = download_bytes(ASI_LOADER_DOWNLOAD, progress, "Downloading Win32 dinput8 loader")
    from io import BytesIO
    import zipfile
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            candidates = [n for n in archive.namelist() if Path(n.replace("\\", "/")).name.lower() == "dinput8.dll"]
            if not candidates:
                raise RuntimeError("The official ASI Loader archive did not contain dinput8.dll")
            # Pick the first exact DLL; the package link is specifically Win32.
            dll_data = archive.read(candidates[0])
    except zipfile.BadZipFile as exc:
        raise RuntimeError("GitHub returned an invalid ASI Loader ZIP archive") from exc
    if not dll_data.startswith(b"MZ"):
        raise RuntimeError("Downloaded dinput8.dll does not have a PE/DLL header")
    dest = _install_file(game_root, "dinput8.dll", dll_data, backup_root)
    if progress:
        progress(100, "Ultimate ASI Loader installed")
    return f"Installed {dest.name} from the official Win32-latest release."


def install_widescreen_fix(game_root: Path, backup_root: Path,
                           progress: Optional[Callable[[int, str], None]] = None,
                           release_info: Optional[dict[str, Any]] = None) -> str:
    api_url = f"https://api.github.com/repos/{WSF_REPO}/releases/latest"
    if progress:
        progress(1, "Checking the latest RC Cars WidescreenFix release…")
    release = release_info or github_json(api_url)
    assets = release.get("assets", [])
    if not assets:
        raise RuntimeError(f"Release {release.get('tag_name', '?')} has no downloadable assets")
    from io import BytesIO
    import zipfile
    install_payloads: dict[str, bytes] = {}
    # Prefer separate compiled ASI/INI assets, plus non-source release archives containing those files.
    direct = [a for a in assets if Path(a.get("name", "")).suffix.lower() in (".asi", ".ini")]
    archives = [a for a in assets if Path(a.get("name", "")).suffix.lower() == ".zip"
                and "source" not in a.get("name", "").lower()]
    total = max(1, len(direct) + len(archives))
    idx = 0
    for asset in direct:
        idx += 1
        name = Path(asset["name"]).name
        if progress:
            progress(min(85, int(idx * 80 / total)), f"Downloading {name}")
        install_payloads[name.lower()] = download_bytes(asset["browser_download_url"], progress, name)
    for asset in archives:
        idx += 1
        name = asset.get("name", "release.zip")
        if progress:
            progress(min(85, int(idx * 80 / total)), f"Inspecting release asset {name}")
        blob = download_bytes(asset["browser_download_url"], progress, name)
        try:
            with zipfile.ZipFile(BytesIO(blob)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    basename = Path(member.filename.replace("\\", "/")).name
                    suffix = Path(basename).suffix.lower()
                    if suffix in (".asi", ".ini"):
                        lower = basename.lower()
                        # Direct assets, if present, take precedence over ZIP contents.
                        if lower not in install_payloads:
                            install_payloads[lower] = archive.read(member)
        except zipfile.BadZipFile:
            # A release may include an unrelated ZIP; don't silently accept it as a plugin.
            continue
    asi_names = [name for name in install_payloads if name.endswith(".asi")]
    if not asi_names:
        raise RuntimeError("Latest WidescreenFix release assets did not contain a compiled .asi plugin")
    if progress:
        progress(88, "Installing the WidescreenFix plugin…")
    installed = []
    for name, content in install_payloads.items():
        if name.endswith(".asi") or name.endswith(".ini"):
            dest_name = "RCCars_WidescreenFix.asi" if name.endswith(".asi") else name
            if name.endswith(".ini"):
                # Game plugin searches for this fixed INI name.
                dest_name = "RCCars_WidescreenFix.ini"
            existing = game_root / dest_name
            if existing.exists() and existing.suffix.lower() == ".ini":
                # Preserve live user settings across a plugin update.
                backup_file_once(game_root, existing, backup_root)
                continue
            _install_file(game_root, dest_name, content, backup_root)
            installed.append(dest_name)
    ini_path = game_root / "RCCars_WidescreenFix.ini"
    if not ini_path.exists():
        ensure_widescreen_ini(ini_path, 0, 0)
        installed.append(ini_path.name)
    if progress:
        progress(100, f"Installed release {release.get('tag_name', 'latest')}")
    return f"Installed RC Cars WidescreenFix {release.get('tag_name', 'latest')}: {', '.join(installed) or 'plugin refreshed; existing INI preserved'}."


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _component_state_path(backup_root: Path) -> Path:
    return backup_root / "component_versions.json"


def _read_component_state(backup_root: Path) -> dict[str, Any]:
    return read_json(_component_state_path(backup_root), {"components": {}})


def _component_is_current(game_root: Path, state: dict[str, Any], key: str,
                          filename: str, version: str) -> bool:
    target = game_root / filename
    record = state.get("components", {}).get(key, {})
    if not target.is_file() or not record or str(record.get("version", "")) != version:
        return False
    try:
        return _sha256_file(target) == str(record.get("sha256", ""))
    except OSError:
        return False


def _record_component(game_root: Path, state: dict[str, Any], key: str,
                      filename: str, version: str) -> None:
    target = game_root / filename
    if not target.is_file():
        raise FileNotFoundError(f"Installed component is missing: {target}")
    state.setdefault("components", {})[key] = {
        "version": version,
        "sha256": _sha256_file(target),
        "filename": filename,
    }


def _asi_loader_update_token() -> str:
    """Return a token that changes with the official Win32-latest asset.

    Win32-latest is a moving release tag rather than a semantic version. Asset
    digest/updated_at/size are therefore better update markers than its tag name.
    """
    release = github_json(f"https://api.github.com/repos/{ASI_LOADER_REPO}/releases/tags/Win32-latest")
    assets = release.get("assets", [])
    asset = next((a for a in assets if str(a.get("name", "")).lower() == "dinput8-win32.zip"), None)
    if asset is None:
        # Fall back to the moving Git ref if GitHub omits the expected asset
        # from release metadata, but still fail clearly if its version is unknown.
        ref = github_json(f"https://api.github.com/repos/{ASI_LOADER_REPO}/git/ref/tags/Win32-latest")
        token = str(ref.get("object", {}).get("sha", "")).strip()
    else:
        parts = [str(asset.get("digest", "")), str(asset.get("updated_at", "")), str(asset.get("size", ""))]
        token = "|".join(part for part in parts if part)
        if not token:
            ref = github_json(f"https://api.github.com/repos/{ASI_LOADER_REPO}/git/ref/tags/Win32-latest")
            token = str(ref.get("object", {}).get("sha", "")).strip()
    if not token:
        raise RuntimeError("Could not determine the current Ultimate ASI Loader Win32-latest revision")
    return token


def install_compatibility_components(game_root: Path, backup_root: Path,
                                     progress: Optional[Callable[[int, str], None]] = None) -> str:
    """Install missing components and update only when their official source changed.

    The installed version is recorded per game instance. SHA-256 checks also detect
    local/manual replacement of the .asi or DLL, in which case the latest file is
    installed again rather than incorrectly reporting the component as current.
    """
    if progress:
        progress(1, "Checking official GitHub releases…")
    wsf_release = github_json(f"https://api.github.com/repos/{WSF_REPO}/releases/latest")
    wsf_version = str(wsf_release.get("tag_name") or wsf_release.get("published_at") or "latest")
    loader_version = _asi_loader_update_token()
    state = _read_component_state(backup_root)

    loader_file = "dinput8.dll"
    fix_file = "RCCars_WidescreenFix.asi"
    loader_current = _component_is_current(game_root, state, "asi_loader", loader_file, loader_version)
    fix_current = _component_is_current(game_root, state, "widescreen_fix", fix_file, wsf_version)
    messages: list[str] = []

    if loader_current and fix_current:
        ini_path = game_root / "RCCars_WidescreenFix.ini"
        if not ini_path.exists():
            ensure_widescreen_ini(ini_path, 0, 0)
        if progress:
            progress(100, "WidescreenFix and ASI Loader are already up to date")
        return (f"Components are up to date. Ultimate ASI Loader revision {loader_version[:12]}, "
                f"WidescreenFix {wsf_version}. No downloads were necessary.")

    if not loader_current:
        def loader_progress(value: int, message: str) -> None:
            if progress:
                progress(max(3, min(48, round(value * 0.45))), f"ASI Loader: {message}")
        messages.append(install_asi_loader(game_root, backup_root, loader_progress))
        _record_component(game_root, state, "asi_loader", loader_file, loader_version)
        write_json(_component_state_path(backup_root), state)
    else:
        messages.append(f"Ultimate ASI Loader is up to date (revision {loader_version[:12]}).")

    if not fix_current:
        def fix_progress(value: int, message: str) -> None:
            if progress:
                progress(max(48, min(98, 48 + round(value * 0.50))), f"WidescreenFix: {message}")
        messages.append(install_widescreen_fix(game_root, backup_root, fix_progress, release_info=wsf_release))
        _record_component(game_root, state, "widescreen_fix", fix_file, wsf_version)
        write_json(_component_state_path(backup_root), state)
    else:
        messages.append(f"WidescreenFix is up to date ({wsf_version}).")

    ini_path = game_root / "RCCars_WidescreenFix.ini"
    if not ini_path.exists():
        ensure_widescreen_ini(ini_path, 0, 0)
    if progress:
        progress(100, "Compatibility components checked and updated")
    return "\n".join(messages)


def check_launcher_update(repo: str) -> Optional[dict[str, Any]]:
    repo = repo.strip().strip("/")
    if not repo or "/" not in repo or any(part in repo for part in ("..", "?", "#")):
        raise ValueError("Set launcher_update_repo in launcher_config.json to 'owner/repository' first.")
    release = github_json(f"https://api.github.com/repos/{repo}/releases/latest")
    assets = release.get("assets", [])

    # Prefer a complete one-directory package, because it contains the EXE and
    # PyInstaller's external runtime DLLs. An EXE-only update is unsafe for an
    # onedir build. Keep EXE fallback for historical one-file releases.
    package_assets = [
        a for a in assets
        if Path(a.get("name", "")).suffix.lower() == ".zip"
        and "rccarslauncher" in a.get("name", "").lower()
        and not any(term in a.get("name", "").lower() for term in ("source", "src", "sourcecode"))
    ]
    preferred_package = next(
        (a for a in package_assets if any(term in a.get("name", "").lower() for term in ("portable", "package", "launcher"))),
        package_assets[0] if package_assets else None,
    )
    if preferred_package:
        preferred = preferred_package
    else:
        exe_assets = [a for a in assets if Path(a.get("name", "")).suffix.lower() == ".exe"]
        if not exe_assets:
            if any(Path(a.get("name", "")).suffix.lower() == ".zip" for a in assets):
                raise RuntimeError("Latest release has no RCCarsLauncher package ZIP or direct EXE. Attach RCCarsLauncher_Portable.zip for one-directory builds.")
            raise RuntimeError("Latest GitHub release has no launcher EXE or package ZIP asset")
        preferred = next((a for a in exe_assets if "rccarslauncher" in a.get("name", "").lower()), exe_assets[0])
    return {"tag": release.get("tag_name", "latest"), "name": release.get("name", ""),
            "url": release.get("html_url", f"https://github.com/{repo}/releases"),
            "asset_name": preferred.get("name"), "asset_url": preferred.get("browser_download_url"),
            "asset_size": preferred.get("size", 0)}


def prepare_self_update(asset_url: str, asset_name: str, progress=None) -> tuple[Path, Path]:
    """Stage a launcher EXE or a complete onedir package and create a Windows swap script."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Self-replacement is available only for the packaged launcher. In source mode, download the release manually.")
    exe_path = Path(sys.executable).resolve()
    payload = download_bytes(asset_url, progress, "Downloading launcher update")
    stage = user_data_dir() / "updates"
    stage.mkdir(parents=True, exist_ok=True)
    safe_name = Path(asset_name).name

    if safe_name.lower().endswith(".zip"):
        from io import BytesIO
        stage_payload = stage / "payload"
        if stage_payload.exists():
            shutil.rmtree(stage_payload)
        stage_payload.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                members = [m for m in archive.infolist() if not m.is_dir()]
                normalized: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
                for member in members:
                    raw_name = member.filename.replace("\\", "/")
                    relative = PurePosixPath(raw_name)
                    if relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
                        raise RuntimeError(f"Unsafe path in launcher update package: {member.filename}")
                    normalized.append((member, relative))
                # Support both archive-root files and an optional one-folder wrapper.
                prefix: tuple[str, ...] = ()
                if not any(tuple(p.parts) == ("RCCarsLauncher.exe",) for _, p in normalized):
                    candidates = [p.parts for _, p in normalized if p.name.lower() == "rccarslauncher.exe" and len(p.parts) >= 2]
                    if candidates and all(parts[0] == candidates[0][0] for parts in candidates):
                        prefix = (candidates[0][0],)
                extracted_runtime = False
                extracted_exe: Optional[Path] = None
                for member, relative in normalized:
                    parts = relative.parts
                    if prefix:
                        if parts[:1] != prefix:
                            continue
                        parts = parts[1:]
                    if not parts:
                        continue
                    rel = PurePosixPath(*parts)
                    # Only extract the launcher binary and its private PyInstaller runtime.
                    if not (rel.as_posix() == "RCCarsLauncher.exe" or rel.parts[0] == "_runtime"):
                        continue
                    dest = stage_payload.joinpath(*rel.parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member, "r") as src, dest.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if rel.as_posix() == "RCCarsLauncher.exe":
                        extracted_exe = dest
                    elif rel.parts[0] == "_runtime":
                        extracted_runtime = True
                if extracted_exe is None or not extracted_exe.is_file() or not extracted_exe.read_bytes()[:2] == b"MZ":
                    raise RuntimeError("Launcher package ZIP does not contain a valid root RCCarsLauncher.exe")
                if not extracted_runtime or not (stage_payload / "_runtime").is_dir():
                    raise RuntimeError("Launcher package ZIP does not contain the _runtime directory. Build and upload RCCarsLauncher_Portable.zip.")
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Downloaded launcher package is not a valid ZIP archive") from exc
        staged_exe = stage_payload / "RCCarsLauncher.exe"
        script = stage / "apply_launcher_package_update.cmd"
        target_dir = str(exe_path.parent)
        source_dir = str(stage_payload)
        script_text = (
            "@echo off\r\nsetlocal EnableExtensions\r\n"
            f'set "TARGET_DIR={target_dir}"\r\nset "SOURCE_DIR={source_dir}"\r\n'
            ":waitloop\r\ntimeout /t 1 /nobreak >nul\r\n"
            r'if not exist "%SOURCE_DIR%\RCCarsLauncher.exe" goto :waitloop' + "\r\n"

            r'if not exist "%SOURCE_DIR%\_runtime" goto :waitloop' + "\r\n"

            r'if exist "%TARGET_DIR%\_runtime.new" rmdir /s /q "%TARGET_DIR%\_runtime.new"' + "\r\n"

            r'xcopy "%SOURCE_DIR%\_runtime\*" "%TARGET_DIR%\_runtime.new" /E /I /H /K /Y >nul' + "\r\n"

            r'if errorlevel 1 goto :waitloop' + "\r\n"

            r'if exist "%TARGET_DIR%\_runtime.old" rmdir /s /q "%TARGET_DIR%\_runtime.old"' + "\r\n"

            r'if exist "%TARGET_DIR%\_runtime" ren "%TARGET_DIR%\_runtime" "_runtime.old"' + "\r\n"

            r'ren "%TARGET_DIR%\_runtime.new" "_runtime" >nul 2>&1' + "\r\n"

            r'if errorlevel 1 goto :rollback' + "\r\n"

            r'copy /y "%SOURCE_DIR%\RCCarsLauncher.exe" "%TARGET_DIR%\RCCarsLauncher.exe" >nul' + "\r\n"

            r'if errorlevel 1 goto :rollback' + "\r\n"

            r'if exist "%TARGET_DIR%\_runtime.old" rmdir /s /q "%TARGET_DIR%\_runtime.old"' + "\r\n"

            r'start "" "%TARGET_DIR%\RCCarsLauncher.exe"' + "\r\n"

            r'rmdir /s /q "%SOURCE_DIR%" >nul 2>&1' + "\r\n"

            r'del "%~f0" >nul 2>&1' + "\r\n"

            'exit /b 0\r\n'
            ':rollback\r\n'
            r'if exist "%TARGET_DIR%\_runtime" rmdir /s /q "%TARGET_DIR%\_runtime"' + "\r\n"

            r'if exist "%TARGET_DIR%\_runtime.old" ren "%TARGET_DIR%\_runtime.old" "_runtime"' + "\r\n"

            'goto :waitloop\r\n'
            'endlocal\r\n'
        )
        script.write_text(script_text, encoding="utf-8")
        if progress:
            progress(100, "Launcher package staged")
        return staged_exe, script

    if not payload.startswith(b"MZ"):
        raise RuntimeError("Release asset is neither a Windows executable nor a supported launcher package ZIP")
    staged_exe = stage / Path(safe_name).name
    staged_exe.write_bytes(payload)
    bat = stage / "apply_launcher_update.cmd"
    target = str(exe_path)
    source = str(staged_exe)
    bat.write_text(
        "@echo off\r\nsetlocal\r\n"
        f'set "TARGET={target}"\r\nset "SOURCE={source}"\r\n'
        ":waitloop\r\ntimeout /t 1 /nobreak >nul\r\n"
        'copy /y "%SOURCE%" "%TARGET%" >nul 2>&1\r\n'
        'if errorlevel 1 goto waitloop\r\n'
        'start "" "%TARGET%"\r\n'
        'del "%SOURCE%" >nul 2>&1\r\n'
        'del "%~f0" >nul 2>&1\r\n'
        "endlocal\r\n", encoding="utf-8"
    )
    if progress:
        progress(100, "Launcher EXE staged")
    return staged_exe, bat


def apply_app_update(batch_path: Path) -> None:
    subprocess.Popen(["cmd.exe", "/c", "start", "", str(batch_path)], cwd=str(batch_path.parent), close_fds=True)


def available_resolutions() -> list[tuple[int, int]]:
    values: set[tuple[int, int]] = set()
    if os.name == "nt":
        try:
            class DEVMODEW(ctypes.Structure):
                _fields_ = [
                    ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
                    ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
                    ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
                    ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                    ("dmDisplayOrientation", ctypes.c_ulong), ("dmDisplayFixedOutput", ctypes.c_ulong),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
                    ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
                    ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
                    ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
                    ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
                    ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
                    ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong),
                ]
            index = 0
            while index < 512:
                dm = DEVMODEW()
                dm.dmSize = ctypes.sizeof(DEVMODEW)
                if not ctypes.windll.user32.EnumDisplaySettingsW(None, index, ctypes.byref(dm)):
                    break
                if dm.dmPelsWidth >= 640 and dm.dmPelsHeight >= 480:
                    values.add((int(dm.dmPelsWidth), int(dm.dmPelsHeight)))
                index += 1
        except Exception:
            pass
    values.update({(640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 800),
                   (1366, 768), (1440, 900), (1600, 900), (1680, 1050), (1920, 1080),
                   (1920, 1200), (2560, 1080), (2560, 1440), (3440, 1440), (3840, 2160)})
    # Put common/resolutions-increasing order; the UI selects the current desktop first.
    return sorted(values, key=lambda wh: (wh[0] * wh[1], wh[0]))


def current_display_resolution() -> tuple[int, int]:
    if os.name == "nt":
        try:
            from ctypes import wintypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]
            hmon = ctypes.windll.user32.MonitorFromWindow(ctypes.windll.user32.GetDesktopWindow(), 2)
            info = MONITORINFO(); info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                return info.rcMonitor.right - info.rcMonitor.left, info.rcMonitor.bottom - info.rcMonitor.top
        except Exception:
            pass
    return 1920, 1080
