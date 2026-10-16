from __future__ import annotations

import hashlib
import json
import os
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
    state = read_json(_state_path(instance_id), {"mods": {}, "managed_files": [], "original_files": [], "managed_sources": {}})
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
    state = previous_state or read_json(_state_path(instance_id), {"mods": {}, "managed_files": [], "original_files": [], "managed_sources": {}})
    existing = state.setdefault("mods", {})
    # Preserve metadata for archives that aren't currently visible (e.g. temporarily moved out).
    for index, record in enumerate(records):
        existing[_archive_key(record.archive)] = {"enabled": bool(record.enabled), "order": index}
    state["managed_files"] = list(state.get("managed_files", []))
    state["original_files"] = list(state.get("original_files", []))
    state.setdefault("managed_sources", {})
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


def _archive_signature(path: Path) -> dict[str, Any]:
    """Fast cache fingerprint: stat metadata plus ZIP central-directory checksums.

    The ZIP central directory contains each member's CRC and sizes, so checking it is
    substantially cheaper than decompressing all files. For 7z, size and high-resolution
    mtime are used to avoid reading the entire potentially large archive on each apply.
    """
    stat = path.stat()
    signature: dict[str, Any] = {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "suffix": path.suffix.casefold(),
    }
    if path.suffix.casefold() == ".zip":
        digest = hashlib.sha256()
        with zipfile.ZipFile(path, "r") as archive:
            for info in archive.infolist():
                fields = (
                    info.filename,
                    str(info.CRC),
                    str(info.file_size),
                    str(info.compress_size),
                    str(info.external_attr),
                    "1" if info.is_dir() else "0",
                )
                digest.update("\0".join(fields).encode("utf-8", errors="surrogatepass"))
                digest.update(b"\n")
        signature["directory_sha256"] = digest.hexdigest()
    return signature


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _validate_extracted_tree(root: Path) -> list[str]:
    files: list[str] = []
    root_resolved = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink extracted from mod archive: {path}")
        try:
            path.resolve().relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"Unsafe path extracted from mod archive: {path}") from exc
        if path.is_file():
            rel = safe_archive_relative_path(path.relative_to(root).as_posix())
            if rel.name == ".rccarsmod.json":
                path.unlink(missing_ok=True)
                continue
            files.append(rel.as_posix())
    return sorted(files, key=str.casefold)


def _extract_one(record: ModRecord, staging_root: Path,
                 progress: Optional[Callable[[int, str], None]] = None) -> Path:
    """Extract once per archive revision and reuse a validated staging cache thereafter."""
    staging_root.mkdir(parents=True, exist_ok=True)
    key = _cache_key(record.archive)
    target_root = staging_root / key
    marker_path = staging_root / f"{key}.cache.json"
    signature = _archive_signature(record.archive)
    marker = read_json(marker_path, {})
    if not isinstance(marker, dict):
        marker = {}
    cached_files = marker.get("files", [])
    if marker.get("schema") == 1 and marker.get("signature") == signature and target_root.is_dir():
        # Detect incomplete/deleted cache output cheaply before trusting it.
        if all((target_root / Path(p)).is_file() for p in cached_files):
            if progress:
                progress(100, f"Using cached files: {record.name}")
            return target_root

    temp_root = staging_root / f".{key}.tmp"
    old_root = staging_root / f".{key}.old"
    _remove_tree(temp_root)
    _remove_tree(old_root)
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        if record.archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(record.archive, "r") as archive:
                infos = archive.infolist()
                file_infos = [info for info in infos if not info.is_dir()]
                for info in infos:
                    safe_archive_relative_path(info.filename)
                last_percent = -1
                for index, info in enumerate(file_infos, 1):
                    # Ignore symbolic-link entries; mods should contain regular game files.
                    unix_mode = (info.external_attr >> 16) & 0xF000
                    if unix_mode == 0xA000:
                        raise ValueError(f"Symlink in mod archive is not allowed: {info.filename}")
                    rel = safe_archive_relative_path(info.filename)
                    if rel.name == ".rccarsmod.json":
                        continue
                    dest = temp_root / rel
                    try:
                        dest.resolve().relative_to(temp_root.resolve())
                    except ValueError as exc:
                        raise ValueError(f"Unsafe path in mod archive: {info.filename}") from exc
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # Stream entries instead of reading each whole member into RAM.
                    with archive.open(info, "r") as source, dest.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if progress:
                        percent = round(index * 100 / max(1, len(file_infos)))
                        if percent != last_percent or index == len(file_infos):
                            progress(percent, f"Extracting {record.name}: {rel.as_posix()}")
                            last_percent = percent
        elif record.archive.suffix.lower() == ".7z":
            try:
                import py7zr
            except ImportError as exc:
                raise RuntimeError("7z mod archives require py7zr. Install it with: py -3 -m pip install py7zr") from exc
            with py7zr.SevenZipFile(record.archive, mode="r") as archive:
                names = archive.getnames()
                for name in names:
                    safe_archive_relative_path(name)
                archive.extractall(path=temp_root)
        else:
            raise ValueError(f"Unsupported mod archive type: {record.archive.suffix}")

        manifest_files = _validate_extracted_tree(temp_root)
        if target_root.exists():
            os.replace(target_root, old_root)
        try:
            os.replace(temp_root, target_root)
        except Exception:
            if old_root.exists() and not target_root.exists():
                os.replace(old_root, target_root)
            raise
        _remove_tree(old_root)
        write_json(marker_path, {"schema": 1, "signature": signature, "files": manifest_files})
        return target_root
    except Exception:
        _remove_tree(temp_root)
        raise


def _cached_file_list(staged_root: Path, staging_root: Path, record: ModRecord) -> list[Path]:
    marker = read_json(staging_root / f"{_cache_key(record.archive)}.cache.json", {})
    files = marker.get("files", []) if isinstance(marker, dict) else []
    result: list[Path] = []
    for rel_text in files:
        rel = safe_archive_relative_path(str(rel_text))
        path = staged_root / rel
        try:
            path.resolve().relative_to(staged_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Unsafe path in cached mod: {rel_text}") from exc
        if path.is_file():
            result.append(path)
    return result


def apply_mods(game_root: Path, instance_id: str, records: list[ModRecord], backup_root: Path,
               progress: Optional[Callable[[int, str], None]] = None) -> tuple[int, int]:
    """Synchronize enabled mods into <game>/update, removing stale files and restoring originals.

    Later enabled mods override earlier mods. Archives are cached after extraction, so applying
    the same mod profile again doesn't decompress unchanged archives. Only changed source files
    are copied into update/; disabling/removing a mod reconciles the overlay and removes files
    no longer supplied by any enabled mod.
    """
    update_root = game_root / "update"
    update_root.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(instance_id)
    state = read_json(state_path, {"mods": {}, "managed_files": [], "original_files": [], "managed_sources": {}})
    old_managed = {str(p).replace("\\", "/") for p in state.get("managed_files", [])}
    original_files = {str(p).replace("\\", "/") for p in state.get("original_files", [])}
    original_index = {p.casefold(): p for p in original_files}
    old_sources = {str(k).casefold(): str(v) for k, v in state.get("managed_sources", {}).items()}
    backup_files_root = backup_root / "update-originals"
    staging_root = _profile_dir(instance_id) / "staging"

    enabled = sorted([m for m in records if m.enabled], key=lambda m: m.order)
    # key -> (staged file, relative path as supplied by the last winning mod, source identity)
    overlay: dict[str, tuple[Path, str, str]] = {}
    for idx, record in enumerate(enabled, 1):
        if progress:
            progress(int((idx - 1) * 35 / max(1, len(enabled))), f"Preparing mod {idx}/{len(enabled)}: {record.name}")
        def extraction_progress(value: int, message: str, base_index: int = idx - 1) -> None:
            if progress:
                overall = int(((base_index + max(0, min(100, value)) / 100) * 35) / max(1, len(enabled)))
                progress(overall, message)

        staged = _extract_one(record, staging_root, extraction_progress if progress else None)
        cache_record = read_json(staging_root / f"{_cache_key(record.archive)}.cache.json", {})
        signature_json = json.dumps(cache_record.get("signature", {}), sort_keys=True, separators=(",", ":"))
        source_id = hashlib.sha256(signature_json.encode("utf-8")).hexdigest()[:20]
        for file_path in _cached_file_list(staged, staging_root, record):
            rel = safe_archive_relative_path(file_path.relative_to(staged).as_posix())
            rel_posix = rel.as_posix()
            overlay[rel_posix.casefold()] = (file_path, rel_posix, source_id)

    new_managed = {rel_posix for _src, rel_posix, _source_id in overlay.values()}
    old_index = {p.casefold(): p for p in old_managed}
    new_index = {p.casefold(): p for p in new_managed}
    managed_sources_next = {key: source_id for key, (_src, _rel, source_id) in overlay.items()}

    # Delete stale files and restore a pre-mod original only when no enabled mod still owns it.
    for old_key, old_rel in old_index.items():
        if old_key in new_index:
            continue
        target = update_root / Path(old_rel)
        try:
            target.resolve().relative_to(update_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Refusing to remove path outside update/: {old_rel}") from exc
        if target.is_file() or target.is_symlink():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            try:
                target.rmdir()
            except OSError:
                pass
        original_rel = original_index.get(old_key)
        if original_rel:
            backup = backup_files_root / Path(original_rel)
            if backup.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            original_files.discard(original_rel)
            original_index.pop(old_key, None)

    # Apply the final overlay, saving each baseline only once. Skip unchanged files.
    total = max(1, len(overlay))
    for index, (canonical, (src, rel_posix, source_id)) in enumerate(overlay.items(), 1):
        target = update_root / Path(rel_posix)
        try:
            target.resolve().relative_to(update_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Refusing path outside update/: {rel_posix}") from exc
        prior_managed = canonical in old_index
        if not prior_managed and target.exists() and target.is_file() and canonical not in original_index:
            backup = backup_files_root / Path(rel_posix)
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            original_files.add(rel_posix)
            original_index[canonical] = rel_posix
        if target.exists() and target.is_dir():
            raise ValueError(f"A directory already exists where a mod file must be written: {target}")

        # copy2 preserves the staged mtime. For a previously applied same source, matching
        # size+mtime means the destination is already the desired output.
        unchanged = False
        if target.is_file() and old_sources.get(canonical) == source_id:
            src_stat = src.stat()
            dst_stat = target.stat()
            unchanged = src_stat.st_size == dst_stat.st_size and src_stat.st_mtime_ns == dst_stat.st_mtime_ns
        if not unchanged:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        if progress:
            progress(35 + int(index * 64 / total), f"Applying update/: {rel_posix}")

    state["managed_files"] = sorted(new_managed, key=str.casefold)
    state["original_files"] = sorted(original_files, key=str.casefold)
    state["managed_sources"] = managed_sources_next
    state.setdefault("mods", {})
    for index, record in enumerate(records):
        state["mods"][_archive_key(record.archive)] = {"enabled": bool(record.enabled), "order": index}
    write_json(state_path, state)
    if progress:
        progress(100, "Mod overlay applied")
    return len(enabled), len(new_managed)
