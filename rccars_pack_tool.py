#!/usr/bin/env python3
"""Extractor for CREAT Studio Pack 1.0 archives used by RC Cars (2003).

Usage:
    python rccars_pack_tool.py list RCCars.pack
    python rccars_pack_tool.py extract RCCars.pack --out RCCars_unpacked
    python rccars_pack_tool.py verify-fragment "RCCars - Выделение 0x1F07A.bin" car_antenna_Car1_H2F.data

The full archive has not been bundled with this tool. The cipher was checked
against the supplied 512-byte archive fragment and loose file.
"""
from __future__ import annotations

import argparse
import mmap
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT_CHUNK = 0x5210
DIRECTORY_CHUNK = 0x0613
DATA_SECTION_CHUNK = 0x0630
ENTRY_CHUNK = 0x0220
DATA_CHUNK = 0x1431


@dataclass(frozen=True)
class Chunk:
    chunk_id: int
    end: int                 # absolute, exclusive end position
    data_start: int
    extra: Optional[int] = None  # extended chunk's extra DWORD, e.g. data length


@dataclass
class PackEntry:
    path: str = ""
    size: Optional[int] = None
    data_offset: Optional[int] = None
    flags: int = 0


def read_chunk(buf, offset: int) -> Chunk:
    """Read the engine's chunk header at an absolute file offset."""
    if offset < 0 or offset + 6 > len(buf):
        raise ValueError(f"Chunk header outside file at 0x{offset:X}")
    chunk_id, end = struct.unpack_from("<HI", buf, offset)
    pos = offset + 6
    extra = None
    # tiohbReadChunk reads an extra DWORD for IDs with bit 0x0400 set or 0x9xxx.
    if (chunk_id & 0x0400) != 0 or (chunk_id & 0xF000) == 0x9000:
        if pos + 4 > len(buf):
            raise ValueError(f"Truncated extended chunk header at 0x{offset:X}")
        extra = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
    if end < pos:
        raise ValueError(
            f"Invalid chunk end 0x{end:X} for chunk 0x{chunk_id:04X} at 0x{offset:X}"
        )
    if end > len(buf):
        raise ValueError(
            f"Chunk 0x{chunk_id:04X} at 0x{offset:X} ends at 0x{end:X}, "
            f"beyond file size 0x{len(buf):X}; is this the complete pack?"
        )
    return Chunk(chunk_id, end, pos, extra)


def read_c_string(buf, start: int, limit: int) -> str:
    if start < 0 or limit < start or limit > len(buf):
        raise ValueError("Invalid string bounds")
    nul = buf.find(b"\0", start, limit)
    if nul < 0:
        raise ValueError(f"Unterminated string at 0x{start:X}")
    return bytes(buf[start:nul]).decode("cp1252", errors="replace")


def xor_transform(data: bytearray, key: bytes) -> None:
    """In-place equivalent of the game's FUN_00421190.

    This is not a simple repeating XOR. After reading a key byte, the function
    checks whether the *next* byte in the current key buffer is zero. If so,
    every original key byte is advanced with (byte * 3 + 1) modulo 256 and the
    key index resets. Bytes that become zero can therefore shorten later cycles.
    """
    if not key:
        raise ValueError("Empty CREAT Studio data key")
    key_len = len(key)
    state = bytearray(key) + bytearray(1)  # trailing NUL used by the original code
    key_pos = 0
    for i in range(len(data)):
        next_is_nul = state[key_pos + 1] == 0
        data[i] ^= state[key_pos]
        key_pos += 1
        if next_is_nul:
            for j in range(key_len):
                state[j] = (state[j] * 3 + 1) & 0xFF
            key_pos = 0


def parse_pack(buf) -> tuple[str, bytes, list[PackEntry], Chunk]:
    root = read_chunk(buf, 0)
    if root.chunk_id != ROOT_CHUNK:
        raise ValueError(
            f"Not a CREAT Studio Pack archive: root ID is 0x{root.chunk_id:04X}, "
            f"expected 0x{ROOT_CHUNK:04X}"
        )
    if root.data_start + 4 > root.end:
        raise ValueError("Root chunk is too short")

    # The root starts with a raw 32-bit float (version 1.0), followed by typed chunks.
    pos = root.data_start + 4
    title = ""
    key = b""
    entries: list[PackEntry] = []
    saw_directory = False

    while pos < root.end:
        chunk = read_chunk(buf, pos)
        if chunk.end <= pos:
            raise ValueError(f"Non-advancing chunk at 0x{pos:X}")

        if chunk.chunk_id == 0x4011:
            title = read_c_string(buf, chunk.data_start, chunk.end)
        elif chunk.chunk_id == 0x4014:
            key_text = read_c_string(buf, chunk.data_start, chunk.end)
            key = key_text.encode("cp1252", errors="replace")
        elif chunk.chunk_id == DIRECTORY_CHUNK:
            if saw_directory:
                raise ValueError("Duplicate file directory chunk")
            # 0x0613 is an extended chunk: the engine stores the entry count
            # in the extra DWORD of its 10-byte chunk header, not in the body.
            if chunk.extra is None:
                raise ValueError("Directory chunk is missing its entry count")
            count = chunk.extra
            item_pos = chunk.data_start
            for index in range(count):
                entry_chunk = read_chunk(buf, item_pos)
                if entry_chunk.chunk_id != ENTRY_CHUNK:
                    raise ValueError(
                        f"Directory entry {index} at 0x{item_pos:X} has ID "
                        f"0x{entry_chunk.chunk_id:04X}, expected 0x{ENTRY_CHUNK:04X}"
                    )
                entry = PackEntry()
                field_pos = entry_chunk.data_start
                while field_pos < entry_chunk.end:
                    field = read_chunk(buf, field_pos)
                    if field.chunk_id == 0x4021:
                        entry.path = read_c_string(buf, field.data_start, field.end)
                    elif field.chunk_id in (0x3022, 0x3023, 0x3024):
                        if field.data_start + 4 > field.end:
                            raise ValueError(
                                f"Short DWORD field 0x{field.chunk_id:04X} "
                                f"in entry {index}"
                            )
                        value = struct.unpack_from("<I", buf, field.data_start)[0]
                        if field.chunk_id == 0x3022:
                            entry.size = value
                        elif field.chunk_id == 0x3023:
                            entry.data_offset = value
                        else:
                            entry.flags = value
                    field_pos = field.end
                if not entry.path:
                    raise ValueError(f"Entry {index} has no path")
                if entry.size is None or entry.data_offset is None:
                    raise ValueError(f"Entry {index} ({entry.path}) lacks size/offset")
                entries.append(entry)
                item_pos = entry_chunk.end
            if item_pos != chunk.end:
                raise ValueError(
                    f"Directory count says {count} entries, but parsed through "
                    f"0x{item_pos:X}; directory ends at 0x{chunk.end:X}"
                )
            saw_directory = True
        pos = chunk.end

    if not saw_directory or not entries:
        raise ValueError("No file directory found")
    if not key:
        raise ValueError("Encryption-key chunk 0x4014 not found")

    # The separate data section begins immediately after the root/directory chunk.
    data_section = read_chunk(buf, root.end)
    if data_section.chunk_id != DATA_SECTION_CHUNK:
        raise ValueError(
            f"Expected data-section chunk 0x{DATA_SECTION_CHUNK:04X} at "
            f"0x{root.end:X}, got 0x{data_section.chunk_id:04X}"
        )
    # 0x0630 also stores its file count in the extra DWORD of the extended header.
    if data_section.extra is None:
        raise ValueError("Data-section chunk is missing its entry count")
    data_count = data_section.extra
    if data_count != len(entries):
        raise ValueError(
            f"Directory has {len(entries)} files, data section says {data_count}"
        )

    return title, key, entries, data_section


def safe_output_path(output_root: Path, archive_path: str) -> Path:
    normalized = archive_path.replace("\\", "/")
    # Reject rooted paths, drive-qualified paths, and traversal components.
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ValueError(f"Refusing absolute archive path: {archive_path!r}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError(f"Unsafe archive path: {archive_path!r}")
    root = output_root.resolve()
    dest = root.joinpath(*parts).resolve()
    try:
        dest.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Archive path escapes output directory: {archive_path!r}") from exc
    return dest


def list_pack(pack_path: Path) -> int:
    with pack_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            title, key, entries, _ = parse_pack(buf)
            print(f"Title: {title or '(none)'}")
            print(f"Key: {key.decode('cp1252', errors='replace')!r}")
            print(f"Files: {len(entries)}")
            for e in entries:
                flag = "XOR" if e.flags & 0x20 else "raw"
                print(f"{e.size:>10}  {e.data_offset:08X}  {e.flags:08X}  {flag:>3}  {e.path}")
    return 0


def extract_pack(pack_path: Path, output_root: Path, progress: bool = True) -> int:
    output_root.mkdir(parents=True, exist_ok=True)
    with pack_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            title, key, entries, _ = parse_pack(buf)
            print(f"Archive: {title or pack_path.name} ({len(entries)} files)")
            for index, entry in enumerate(entries, 1):
                assert entry.size is not None and entry.data_offset is not None
                chunk = read_chunk(buf, entry.data_offset)
                if chunk.chunk_id != DATA_CHUNK:
                    raise ValueError(
                        f"{entry.path}: expected data chunk 0x{DATA_CHUNK:04X} at "
                        f"0x{entry.data_offset:X}, got 0x{chunk.chunk_id:04X}"
                    )
                if chunk.extra != entry.size:
                    raise ValueError(
                        f"{entry.path}: directory size 0x{entry.size:X} differs from "
                        f"data chunk size 0x{(chunk.extra or 0):X}"
                    )
                if chunk.data_start + entry.size != chunk.end:
                    raise ValueError(
                        f"{entry.path}: chunk end/size mismatch at 0x{entry.data_offset:X}"
                    )
                payload = bytearray(buf[chunk.data_start:chunk.end])
                if entry.flags & 0x20:
                    xor_transform(payload, key)
                dest = safe_output_path(output_root, entry.path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
                if progress:
                    print(f"[{index:4}/{len(entries)}] {entry.path}")
    print(f"Extracted to: {output_root.resolve()}")
    return 0


def verify_fragment(fragment_path: Path, original_path: Path) -> int:
    fragment = fragment_path.read_bytes()
    original = original_path.read_bytes()
    # Fragment starts at archive offset 0x1F07A: 6-byte 0x0630 header + count,
    # then a 10-byte 0x1431 header. Payload therefore starts at fragment + 0x14.
    if len(fragment) < 20:
        raise ValueError("Fragment is too short for the section and data headers")
    payload = bytearray(fragment[20:])
    xor_transform(payload, b"CREATSTUDIOGames")
    compare_len = min(len(payload), len(original))
    mismatch = next((i for i in range(compare_len) if payload[i] != original[i]), None)
    if mismatch is not None:
        print(f"Mismatch at offset 0x{mismatch:X}: decoded={payload[mismatch]:02X}, original={original[mismatch]:02X}")
        return 1
    print(f"OK: decoded {compare_len} bytes exactly match {original_path.name}")
    if compare_len < len(original):
        print(f"Note: fragment contains {compare_len} payload bytes; original is {len(original)} bytes")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="list entries without extracting")
    p_list.add_argument("pack", type=Path)
    p_extract = sub.add_parser("extract", help="extract the complete archive")
    p_extract.add_argument("pack", type=Path)
    p_extract.add_argument("--out", type=Path, default=Path("RCCars_unpacked"))
    p_verify = sub.add_parser("verify-fragment", help="verify the cipher against the supplied sample")
    p_verify.add_argument("fragment", type=Path)
    p_verify.add_argument("original", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            return list_pack(args.pack)
        if args.command == "extract":
            return extract_pack(args.pack, args.out)
        if args.command == "verify-fragment":
            return verify_fragment(args.fragment, args.original)
    except (OSError, ValueError, struct.error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
