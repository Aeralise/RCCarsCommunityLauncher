from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .services import read_json, safe_archive_relative_path, user_data_dir, write_json


@dataclass
class ModRecord:
    archive: Path
    name: str
    enabled: bool = False
    order: int = 0
    kind: str = "ZIP"


def _state_path(instance_id: str) -> Path:
    return user_data_dir() / "mod_profiles" / instance_id / "mod_state.json"


def _profile_dir(instance_id: str) -> Path:
    path = user_data_dir() / "mod_profiles" / instance_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _archive_key(path: Path) -> str:
    return path.name.casefold()


def scan_mods(game_root: Path, instance_id: str) -> tuple[list[ModRecord], dict[str, Any]]:
    mods_dir = game_root / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    state = read_json(_state_path(instance_id), {"mods": {}, "managed_files": [], "original_files": []})
    mod_state = state.setdefault("mods", {})
    archive_paths = sorted(
        [p for p in mods_dir.iterdir() if p.is_file() and p.suffix.lower() in (".zip", ".7z")],
        key=lambda p: p.name.casefold(),
    )
    records: list[ModRecord] = []
    for default_order, path in enumerate(archive_paths):
        key = _archive_key(path)
        data = mod_state.get(key, {})
        records.append(ModRecord(
            archive=path,
            name=path.stem,
            enabled=bool(data.get("enabled", False)),
            order=int(data.get("order", default_order)),
            kind=path.suffix[1:].upper(),
        ))
    records.sort(key=lambda m: (m.order, m.name.casefold()))
    normalize_order(records)
    return records, state


def normalize_order(records: list[ModRecord]) -> None:
    for index, record in enumerate(records):
        record.order = index


def save_mod_settings(instance_id: str, records: list[ModRecord], previous_state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    state = previous_state or read_json(_state_path(instance_id), {"mods": {}, "managed_files": [], "original_files": []})
    existing = state.setdefault("mods", {})
    # Preserve metadata for archives that aren't currently visible (e.g. temporarily moved out).
    for index, record in enumerate(records):
        existing[_archive_key(record.archive)] = {"enabled": bool(record.enabled), "order": index}
    state["managed_files"] = list(state.get("managed_files", []))
    state["original_files"] = list(state.get("original_files", []))
    write_json(_state_path(instance_id), state)
    return state


def import_mod_archives(paths: list[Path], game_root: Path) -> list[Path]:
    mods_dir = game_root / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    imported: list[Path] = []
    for src in paths:
        if not src.is_file() or src.suffix.lower() not in (".zip", ".7z"):
            continue
        dest = mods_dir / src.name
        if src.resolve() == dest.resolve():
            imported.append(dest)
            continue
        if dest.exists():
            stem, suffix = src.stem, src.suffix
            number = 2
            while (mods_dir / f"{stem} ({number}){suffix}").exists():
                number += 1
            dest = mods_dir / f"{stem} ({number}){suffix}"
        shutil.copy2(src, dest)
        imported.append(dest)
    return imported


def _cache_key(path: Path) -> str:
    return hashlib.sha256(path.name.casefold().encode("utf-8")).hexdigest()[:20]


def _extract_one(record: ModRecord, staging_root: Path, progress: Optional[Callable[[int, str], None]] = None) -> Path:
    target_root = staging_root / _cache_key(record.archive)
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    if record.archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(record.archive) as archive:
            infos = [i for i in archive.infolist() if not i.is_dir()]
            for index, info in enumerate(infos, 1):
                # Ignore symbolic-link entries; mods should contain regular game files.
                unix_mode = (info.external_attr >> 16) & 0xF000
                if unix_mode == 0xA000:
                    raise ValueError(f"Symlink in mod archive is not allowed: {info.filename}")
                rel = safe_archive_relative_path(info.filename)
                if rel.name == ".rccarsmod.json":
                    continue
                dest = target_root / rel
                try:
                    dest.resolve().relative_to(target_root.resolve())
                except ValueError as exc:
                    raise ValueError(f"Unsafe path in mod archive: {info.filename}") from exc
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(info))
                if progress:
                    progress(round(index * 100 / max(1, len(infos))), f"Extracting {record.name}: {rel.as_posix()}")
    elif record.archive.suffix.lower() == ".7z":
        try:
            import py7zr
        except ImportError as exc:
            raise RuntimeError("7z mod archives require py7zr. Install it with: py -3 -m pip install py7zr") from exc
        with py7zr.SevenZipFile(record.archive, mode="r") as archive:
            names = archive.getnames()
            for name in names:
                safe_archive_relative_path(name)
            archive.extractall(path=target_root)
        # Verify extracted paths after the library extraction.
        for p in target_root.rglob("*"):
            if p.is_symlink():
                raise ValueError(f"Symlink extracted from {record.archive.name}: {p}")
            try:
                p.resolve().relative_to(target_root.resolve())
            except ValueError as exc:
                raise ValueError(f"Unsafe path from {record.archive.name}: {p}") from exc
    return target_root


def apply_mods(game_root: Path, instance_id: str, records: list[ModRecord], backup_root: Path,
               progress: Optional[Callable[[int, str], None]] = None) -> tuple[int, int]:
    """Build ordered mod overlay in <game>/update and restore files when mods are disabled.

    Files that existed in update before the manager took ownership are backed up to the
    portable launcher data folder and restored when the last enabled mod stops providing that path.
    """
    update_root = game_root / "update"
    update_root.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(instance_id)
    state = read_json(state_path, {"mods": {}, "managed_files": [], "original_files": []})
    old_managed = {str(p).replace("\\", "/") for p in state.get("managed_files", [])}
    original_files = {str(p).replace("\\", "/") for p in state.get("original_files", [])}
    backup_files_root = backup_root / "update-originals"
    staging_root = _profile_dir(instance_id) / "staging"

    # Extract enabled mods and make a final virtual overlay: later entries win conflicts.
    enabled = sorted([m for m in records if m.enabled], key=lambda m: m.order)
    overlay: dict[str, tuple[Path, str]] = {}
    for idx, record in enumerate(enabled, 1):
        if progress:
            progress(int((idx - 1) * 80 / max(1, len(enabled))), f"Preparing mod {idx}/{len(enabled)}: {record.name}")
        staged = _extract_one(record, staging_root)
        for file_path in staged.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(staged)
            rel_posix = rel.as_posix()
            safe_rel = safe_archive_relative_path(rel_posix)
            key = safe_rel.as_posix().casefold()
            overlay[key] = (file_path, safe_rel.as_posix())

    # Retire managed paths no longer provided by any enabled mod and restore their baseline.
    new_managed = {actual for _src, actual in overlay.values()}
    old_index = {p.casefold(): p for p in old_managed}
    new_index = {p.casefold(): p for p in new_managed}
    for old_key, old_rel in old_index.items():
        if old_key in new_index:
            continue
        target = update_root / Path(old_rel)
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            # Do not recursively remove directories: unrelated files may share them.
            try:
                target.rmdir()
            except OSError:
                pass
        if old_rel in original_files:
            backup = backup_files_root / Path(old_rel)
            if backup.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            original_files.discard(old_rel)

    # Put enabled mods into update in requested order. Preserve each pre-existing update file once.
    total = max(1, len(overlay))
    for index, (key, (src, rel_posix)) in enumerate(overlay.items(), 1):
        target = update_root / Path(rel_posix)
        try:
            target.resolve().relative_to(update_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Refusing path outside update/: {rel_posix}") from exc
        canonical = rel_posix.casefold()
        is_already_managed = canonical in old_index
        if not is_already_managed and target.exists() and target.is_file() and rel_posix not in original_files:
            backup = backup_files_root / Path(rel_posix)
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            original_files.add(rel_posix)
        if target.exists() and target.is_dir():
            raise ValueError(f"A directory already exists where a mod file must be written: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        if progress:
            progress(80 + int(index * 19 / total), f"Applying update/: {rel_posix}")

    state["managed_files"] = sorted(new_managed, key=str.casefold)
    state["original_files"] = sorted(original_files, key=str.casefold)
    state.setdefault("mods", {})
    for index, record in enumerate(records):
        state["mods"][_archive_key(record.archive)] = {"enabled": bool(record.enabled), "order": index}
    write_json(state_path, state)
    if progress:
        progress(100, "Mod overlay applied")
    return len(enabled), len(new_managed)
