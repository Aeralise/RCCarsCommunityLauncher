from io import BytesIO
from typing import BinaryIO, Optional
from pathlib import Path

from .models import PatchChunks, PatchStruct, PTCHPack, FLSTPack, DESCPack
from .exceptions import PatchWrongFileError, PatchCorruptedFileError, PatchWrongChunkError
from .utils import convert_version_hex_2_str
from ....rccarspy.handlers.tiohb_handler import tiohbReadWord, tiohbReadDWord, tiohbReadFloat, tiohbReadString, tiohbWriteDWord


class PatchParser:
    def __init__(self, path):
        self.file_path = path
        self.fb: Optional[BinaryIO] = None
        self.struct: Optional[PatchStruct] = None

    def parse_file(self):
        try:
            self.fb = open(self.file_path, "rb")
            self.struct = PatchStruct()
            self._parse_headers()
            self._parse_data()
            return self.struct
        except Exception as ex:
            raise ex
        finally:
            self.fb.close()

    def _parse_headers(self):
        magic_string = self.fb.read(0x10)
        if magic_string != b"RCCARS MOD PATCH":
            raise PatchWrongFileError()
        # FILE
        file_chunk = tiohbReadDWord(self.fb)
        if file_chunk != PatchChunks.FILE_CHUNK:
            raise PatchCorruptedFileError()
        self.struct.file_version = tiohbReadFloat(self.fb)
        self.struct.file_patch_version = tiohbReadDWord(self.fb)
        self.struct.file_launcher_version = tiohbReadDWord(self.fb)
        self.struct.file_name = tiohbReadString(self.fb)
        self.fb.seek(0x40)
        # PTCH
        patch_chunk = tiohbReadDWord(self.fb)
        if patch_chunk != PatchChunks.PATCH_CHUNK:
            raise PatchCorruptedFileError()
        self.struct.patch_count = tiohbReadDWord(self.fb)
        self.struct.patch_addr_start = tiohbReadDWord(self.fb)
        self.struct.patch_addr_end = tiohbReadDWord(self.fb)
        # FLST
        flst_chunk = tiohbReadDWord(self.fb)
        if flst_chunk != PatchChunks.FLST_CHUNK:
            raise PatchCorruptedFileError()
        self.struct.f_list_count = tiohbReadDWord(self.fb)
        self.struct.f_list_addr_start = tiohbReadDWord(self.fb)
        self.struct.f_list_addr_end = tiohbReadDWord(self.fb)
        # DESC
        desc_chunk = tiohbReadDWord(self.fb)
        if desc_chunk != PatchChunks.DESC_CHUNK:
            raise PatchCorruptedFileError()
        self.struct.desc_count = tiohbReadDWord(self.fb)
        self.struct.desc_addr_start = tiohbReadDWord(self.fb)
        self.struct.desc_addr_end = tiohbReadDWord(self.fb)

    def _parse_data(self):
        # PTCH
        if self.struct.patch_count > 0:
            self.fb.seek(self.struct.patch_addr_start)
            for _ in range(self.struct.patch_count):
                chunk = tiohbReadWord(self.fb)
                if chunk == PatchChunks.PATCH_INIT_CHUNK:
                    ptch = PTCHPack()
                    ptch.address = tiohbReadDWord(self.fb)
                    ptch.byte_len = tiohbReadDWord(self.fb)
                    ptch.data = self.fb.read(ptch.byte_len)
                    self.struct.patch_list.append(ptch)
                    continue
                raise PatchWrongChunkError(chunk, PatchChunks.PATCH_INIT_CHUNK)
            if self.fb.tell() != self.struct.patch_addr_end:
                raise PatchCorruptedFileError()
        # FLST
        if self.struct.f_list_count > 0:
            self.fb.seek(self.struct.f_list_addr_start)
            for _ in range(self.struct.f_list_count):
                chunk = tiohbReadWord(self.fb)
                if chunk == PatchChunks.FLST_NEW_FILE_CHUNK:
                    flst = FLSTPack()
                    flst.game_path = tiohbReadString(self.fb)
                    chunk = tiohbReadWord(self.fb)
                    if chunk == PatchChunks.FLST_FILE_BYTES_CHUNK:
                        flst.file_size = tiohbReadDWord(self.fb)
                        flst.data = self.fb.read(flst.file_size)
                        self.struct.f_list_list.append(flst)
                        continue
                    raise PatchWrongChunkError(chunk, PatchChunks.FLST_FILE_BYTES_CHUNK)
                raise PatchWrongChunkError(chunk, PatchChunks.FLST_NEW_FILE_CHUNK)
            if self.fb.tell() != self.struct.f_list_addr_end:
                raise PatchCorruptedFileError()
        # DESC
        if self.struct.desc_count > 0:
            self.fb.seek(self.struct.desc_addr_start)
            for _ in range(self.struct.desc_count):
                chunk = tiohbReadWord(self.fb)
                if chunk == PatchChunks.DESC_NEW_DESCRIPTIONS_CHUNK:
                    desc = DESCPack()
                    desc.language_code = tiohbReadString(self.fb)
                    chunk = tiohbReadWord(self.fb)
                    if chunk == PatchChunks.DESC_TEXT_CHUNK:
                        desc.file_size = tiohbReadDWord(self.fb)
                        desc.data = self.fb.read(desc.file_size)
                        self.struct.desc_list.append(desc)
                        continue
                    raise PatchWrongChunkError(chunk, PatchChunks.DESC_TEXT_CHUNK)
                raise PatchWrongChunkError(chunk, PatchChunks.DESC_NEW_DESCRIPTIONS_CHUNK)
            if self.fb.tell() != self.struct.desc_addr_end:
                raise PatchCorruptedFileError()


def install_patch(patch_data: PatchStruct, origin_exe_path: Path, backup_exe_path: Path, root_path: Path):
    try:
        new_exe: Optional[BinaryIO] = None
        # 1. Откроем бэкап и сохраним его копию в new_exe
        with backup_exe_path.open("rb") as fb:
            new_exe = BytesIO(fb.read())
        # 2. Добавим в пустой участок EXE информацию о патче.
        new_exe.seek(0x300)
        magic_string = b"RCCARS MOD PATCH"
        version_string = b"VERSION " + f"{convert_version_hex_2_str(patch_data.file_patch_version)}".encode("ascii")
        new_exe.write(magic_string)
        new_exe.write(version_string)
        new_exe.seek(0x320)
        tiohbWriteDWord(new_exe, patch_data.file_patch_version)
        # 3. Патчим exe
        if patch_data.patch_count > 0:
            for patch in patch_data.patch_list:
                new_exe.seek(patch.address)
                new_exe.write(patch.data)

        # 4. Добавим файлы в папки
        if patch_data.f_list_count > 0:
            for file in patch_data.f_list_list:
                # 4.1. Создадим путь к файлу
                file_path = root_path / file.game_path
                # 4.2. Заполним папками
                file_path.parent.mkdir(parents=True, exist_ok=True)
                # 4.3.Сохраним файл
                with file_path.open("wb") as fb:
                    fb.write(file.data)
        # 5. Сохраним новый exe после сохранения новых файлов
        with origin_exe_path.open("wb") as fb:
            new_exe.seek(0)
            fb.write(new_exe.read())
    except Exception as ex:
        raise ex
    finally:
        new_exe.close()
