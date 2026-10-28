from typing import BinaryIO
from struct import unpack, pack


def tiohbReadByte(fb: BinaryIO):
    data = fb.read(1)
    if data == b'' or len(data) != 1:
        return None
    return unpack("B", data)[0]


def tiohbReadWord(fb: BinaryIO):
    data = fb.read(2)
    if data == b'' or len(data) != 2:
        return None
    return unpack("H", data)[0]


def tiohbReadDWord(fb: BinaryIO):
    data = fb.read(4)
    if data == b'' or len(data) != 4:
        return None
    return unpack("I", data)[0]


def tiohbReadFloat(fb: BinaryIO):
    data = fb.read(4)
    if data == b'' or len(data) != 4:
        return None
    return unpack("f", data)[0]


def tiohbReadString(fb: BinaryIO):
    _str = b''
    while True:
        c = fb.read(1)
        if c == b'\0' or c == b'':
            return _str.decode('cp437')
        else:
            _str += c


def tiohbWriteByte(fb: BinaryIO, data):
    fb.write(pack("B", data))


def tiohbWriteWord(fb: BinaryIO, data):
    fb.write(pack("H", data))


def tiohbWriteDWord(fb: BinaryIO, data):
    fb.write(pack("I", data))


def tiohbWriteFloat(fb: BinaryIO, _float):
    fb.write(pack("f", _float))


def tiohbWriteString(fb: BinaryIO, string: str):
    # Записываем строку как байты
    # fb.write(data.encode('ascii'))
    # Записываем нулевой терминатор
    # fb.write(b'\x00')
    str_len = len(string)
    for i in range(str_len + 1):
        if i < str_len:
            _char = ord(string[i])
        else:
            _char = 0
        tiohbWriteByte(fb, _char)


# ДАЛЬНЕЙШИЕ ФУНКЦИИ ПРЕДНАЗНАЧЕНЫ ДЛЯ ЗАПИСИ ДАННЫХ В ФАЙЛЫ
class ChunkUpdaterState:
    """
    Класс используется при записи данных в файлы
    """
    def __init__(self):
        # edi
        self.chunk: int = 0
        # [edi + 4] = start_address
        self.start_address: int = 0
        # [edi + 8] = value
        self.value: int = 0


def tiohbWriteChunk_S(fb: BinaryIO, chunk: int, data_len: int):
    """
    Рассчитывает указатель на конец данных с учетом длины данных, чанка, указателя, длины строки
    Затем записывает чанк и указатель.
    :param fb:
    :param chunk:
    :param str_len:
    :return:
    """
    cursor = fb.tell()
    address = cursor + 6 + data_len
    tiohbWriteWord(fb, chunk)
    tiohbWriteDWord(fb, address)


def tiohbWriteChunk(fb: BinaryIO, chunk_state: ChunkUpdaterState, chunk: int, value: int = -1):
    # получим текущую позицию
    cursor = fb.tell()
    # обновим состояние чанка
    chunk_state.chunk = chunk
    chunk_state.start_address = cursor
    chunk_state.value = value
    tiohbWriteWord(fb, chunk)
    tiohbWriteDWord(fb, cursor)
    if (chunk & 0x400) != 0 or (chunk & 0xF000) == 0x9000:
        if value != -1:
            tiohbWriteDWord(fb, value)


def tiohbChWriteString(fb: BinaryIO, chunk: int, string: str):
    """
    Записывает чанк, адрес, строку.
    :param fb:
    :param chunk:
    :param string:
    :return:
    """
    str_len = len(string) + 1
    tiohbWriteChunk_S(fb, chunk, str_len)
    tiohbWriteString(fb, string)


def tiohbChWriteDWord(fb: BinaryIO, chunk: int, data: int):
    tiohbWriteChunk_S(fb, chunk, 4)
    tiohbWriteDWord(fb, data)


def tiohbChWriteBPrizm(fb: BinaryIO, chunk: int, coord_list: int):
    tiohbWriteChunk_S(fb, chunk, 0x28)
    for _float in coord_list:
        tiohbWriteFloat(fb, _float)

def tiohbChWritePoint(fb: BinaryIO, chunk: int, point3d: list):
    tiohbWriteChunk_S(fb, chunk, 0xC)
    [tiohbWriteFloat(fb, _float) for _float in point3d]


def tiohbUpdateChunk(fb: BinaryIO, chunk_state: ChunkUpdaterState):
    # 1. Получим текущее положение курсора
    cur_cursor = fb.tell()
    # 2. Перейдем на уже записанный чанк
    fb.seek(chunk_state.start_address)
    # 3. Обновим значения, т.к. длина данных была изменена
    tiohbWriteWord(fb, chunk_state.chunk)
    tiohbWriteDWord(fb, cur_cursor)
    # 4. Сохраним новый указатель
    chunk_state.start_address = cur_cursor
    # 5. Вернемся обранто к данным
    fb.seek(cur_cursor)



