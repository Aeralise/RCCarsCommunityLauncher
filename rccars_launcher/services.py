from __future__ import annotations

import configparser
import ctypes
import json
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


def _resolution_key_positions(data: bytes, primary: bytes, alternate: bytes) -> list[int]:
    primary_hits = _find_all(data, primary)
    if len(primary_hits) == 2:
        return primary_hits
    alternate_hits = _find_all(data, alternate)
    all_hits = sorted(set(primary_hits + alternate_hits))
    return all_hits


def patch_crs_resolutions(data: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Patch the two 16-bit LE resolution values following each CRS setting record.

    Expected record signature around a value: key + variable metadata + 01 00 04 00 + u16 + ...
    No write is returned unless there are exactly two valid records for each axis.
    """
    if not (1 <= width <= 65535 and 1 <= height <= 65535):
        raise ValueError("Resolution must fit in an unsigned 16-bit integer")
    mutable = bytearray(data)
    marker = b"\x01\x00\x04\x00"
    jobs: list[tuple[int, int, str]] = []
    for label, keys, value in (
        ("X", (b"XResolution", b"XResoultion"), width),
        ("Y", (b"YResolution", b"YResoultion"), height),
    ):
        all_key_hits: list[int] = []
        for key in keys:
            all_key_hits.extend(_find_all(data, key))
        all_key_hits = sorted(set(all_key_hits))
        # Prefer the spelling which occurs exactly twice; otherwise accept exactly two combined hits.
        exact = next((_find_all(data, key) for key in keys if len(_find_all(data, key)) == 2), None)
        if exact is not None:
            all_key_hits = exact
        if len(all_key_hits) != 2:
            raise ValueError(f"RCCars.crs: expected 2 {label}Resolution records, found {len(all_key_hits)}. File was not modified.")
        for key_pos in all_key_hits:
            scan_start = key_pos + 4
            scan_end = min(len(data), key_pos + 160)
            record_marker = data.find(marker, scan_start, scan_end)
            if record_marker < 0 or record_marker + 6 > len(data):
                raise ValueError(f"RCCars.crs: could not locate the {label}Resolution value field near 0x{key_pos:X}. File was not modified.")
            value_offset = record_marker + 4
            jobs.append((value_offset, value, label))
    for offset, value, _label in jobs:
        struct.pack_into("<H", mutable, offset, value)
    return bytes(mutable), 2, 2


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
                           progress: Optional[Callable[[int, str], None]] = None) -> str:
    api_url = f"https://api.github.com/repos/{WSF_REPO}/releases/latest"
    if progress:
        progress(1, "Checking the latest RC Cars WidescreenFix release…")
    release = github_json(api_url)
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


def install_compatibility_components(game_root: Path, backup_root: Path,
                                     progress: Optional[Callable[[int, str], None]] = None) -> str:
    """Install both Win32 Ultimate ASI Loader and the latest RC Cars WidescreenFix."""
    def loader_progress(value: int, message: str) -> None:
        if progress:
            progress(max(0, min(45, round(value * 0.45))), f"ASI Loader: {message}")

    def fix_progress(value: int, message: str) -> None:
        if progress:
            progress(max(45, min(100, 45 + round(value * 0.55))), f"WidescreenFix: {message}")

    loader_message = install_asi_loader(game_root, backup_root, loader_progress)
    try:
        fix_message = install_widescreen_fix(game_root, backup_root, fix_progress)
    except Exception as exc:
        raise RuntimeError(
            "ASI Loader was installed, but WidescreenFix installation failed. "
            f"Details: {exc}"
        ) from exc
    if progress:
        progress(100, "ASI Loader and WidescreenFix installed")
    return loader_message + "\n" + fix_message


def check_launcher_update(repo: str) -> Optional[dict[str, Any]]:
    repo = repo.strip().strip("/")
    if not repo or "/" not in repo or any(part in repo for part in ("..", "?", "#")):
        raise ValueError("Set launcher_update_repo in launcher_config.json to 'owner/repository' first.")
    release = github_json(f"https://api.github.com/repos/{repo}/releases/latest")
    assets = release.get("assets", [])
    exe_assets = [a for a in assets if Path(a.get("name", "")).suffix.lower() == ".exe"]
    if not exe_assets:
        zip_assets = [a for a in assets if Path(a.get("name", "")).suffix.lower() == ".zip"]
        if zip_assets:
            raise RuntimeError("Latest release has ZIP assets but no direct EXE asset. Publish RCCarsLauncher.exe as a release asset to enable in-app updates.")
        raise RuntimeError("Latest GitHub release has no .exe asset")
    preferred = next((a for a in exe_assets if "rccarslauncher" in a.get("name", "").lower()), exe_assets[0])
    return {"tag": release.get("tag_name", "latest"), "name": release.get("name", ""),
            "url": release.get("html_url", f"https://github.com/{repo}/releases"),
            "asset_name": preferred.get("name"), "asset_url": preferred.get("browser_download_url"),
            "asset_size": preferred.get("size", 0)}


def prepare_self_update(asset_url: str, asset_name: str, progress=None) -> tuple[Path, Path]:
    """Download and stage a new EXE plus a Windows cmd script that swaps it after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Self-replacement is available only for the packaged EXE. In source mode, download the release manually.")
    exe_path = Path(sys.executable).resolve()
    payload = download_bytes(asset_url, progress, "Downloading launcher update")
    if not payload.startswith(b"MZ"):
        raise RuntimeError("Release asset is not a Windows executable")
    stage = user_data_dir() / "updates"
    stage.mkdir(parents=True, exist_ok=True)
    staged_exe = stage / Path(asset_name).name
    staged_exe.write_bytes(payload)
    bat = stage / "apply_launcher_update.cmd"
    target = str(exe_path)
    source = str(staged_exe)
    bat.write_text(
        "@echo off\r\nsetlocal\r\n"
        f'set "TARGET={target}"\r\nset "SOURCE={source}"\r\n'
        ":waitloop\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        'copy /y "%SOURCE%" "%TARGET%" >nul 2>&1\r\n'
        'if errorlevel 1 goto waitloop\r\n'
        'start "" "%TARGET%"\r\n'
        'del "%SOURCE%" >nul 2>&1\r\n'
        'del "%~f0" >nul 2>&1\r\n'
        "endlocal\r\n", encoding="utf-8"
    )
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
