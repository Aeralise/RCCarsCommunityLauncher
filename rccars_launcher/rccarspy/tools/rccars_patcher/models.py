from dataclasses import dataclass, field
from enum import IntEnum
from typing import List


class PatchChunks(IntEnum):
    # FILE
    FILE_CHUNK = 0x454C4946
    # PATCH
    PATCH_CHUNK = 0x48435450
    PATCH_INIT_CHUNK = 0x0111
    # FILE_LIST
    FLST_CHUNK = 0x54534C46
    FLST_NEW_FILE_CHUNK = 0x0222
    FLST_FILE_BYTES_CHUNK = 0x0223
    # DESCRIPTIONS
    DESC_CHUNK = 0x43534544
    DESC_NEW_DESCRIPTIONS_CHUNK = 0x0444
    DESC_TEXT_CHUNK = 0x0445


@dataclass
class PTCHPack:
    address: int = 0
    byte_len: int = 0
    data: bytes = b""


@dataclass
class FLSTPack:
    game_path: str = ""
    file_path: str = ""
    file_size: int = 0
    data: bytes = b""


@dataclass
class DESCPack:
    language_code: str = ""
    file_path: str = ""
    file_size: int = 0
    data: bytes = b""


@dataclass
class PatchStruct:
    # FILE
    file_version: float = 0
    file_patch_version: int = 0
    file_launcher_version: int = 0
    file_name: str = ""
    # PTCH
    patch_count: int = 0
    patch_addr_start: int = 0
    patch_addr_end: int = 0
    patch_list: List[PTCHPack] = field(default_factory=list)
    # FLST
    f_list_count: int = 0
    f_list_addr_start: int = 0
    f_list_addr_end: int = 0
    f_list_list: List[FLSTPack] = field(default_factory=list)
    # DESC
    desc_count: int = 0
    desc_addr_start: int = 0
    desc_addr_end: int = 0
    desc_list: List[DESCPack] = field(default_factory=list)
