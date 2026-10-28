class PatchWrongFileError(Exception):
    def __init__(self, message="Wrong file! The file is not a patcher file."):
        # Притворяемся встроенным исключением, чтобы скрыть путь пакета
        __module__ = 'builtins'
        super().__init__(message)


class PatchCorruptedFileError(Exception):
    def __init__(self, message="The file is corrupted!"):
        # Притворяемся встроенным исключением, чтобы скрыть путь пакета
        __module__ = 'builtins'
        super().__init__(message)


class PatchWrongChunkError(Exception):
    def __init__(self, chunk: int, current_chunk: int):
        # Притворяемся встроенным исключением, чтобы скрыть путь пакета
        __module__ = 'builtins'
        message = f"The file is corrupted! Wrong data chunk. Need 0x{current_chunk:04X}. Get 0x{chunk:04X}."
        super().__init__(message)
