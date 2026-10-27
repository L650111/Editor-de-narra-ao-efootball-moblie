"""Leitura limitada e edição conservadora de UTF, CPK e AFS2.

As tabelas mantêm sua representação original. Apenas campos de tamanho fixo
são editados; campos desconhecidos permanecem byte a byte.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import struct


class FormatError(ValueError):
    pass


def align(value: int, boundary: int) -> int:
    return ((value + boundary - 1) // boundary) * boundary


def xor_utf(raw: bytes) -> bytes:
    state = 0x655F
    out = bytearray(len(raw))
    for i, byte in enumerate(raw):
        out[i] = byte ^ (state & 255)
        state = (state * 0x4115) & 0xFFFFFFFF
    return bytes(out)


_TYPES = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i",
          6: ">Q", 7: ">q", 8: ">f", 9: ">d", 10: ">I", 11: ">II"}


@dataclass(frozen=True)
class Blob:
    start: int
    size: int


class UtfTable:
    def __init__(self, raw: bytes):
        self.encrypted = raw[:4] != b"@UTF"
        self.data = bytearray(xor_utf(raw) if self.encrypted else raw)
        b = self.data
        if len(b) < 32 or b[:4] != b"@UTF":
            raise FormatError("Tabela @UTF inválida ou não suportada.")
        size, self.version, rowoff, stroff, dataoff, nameoff, cols, rowlen, rows = struct.unpack_from(
            ">IHHIIIHHI", b, 4)
        if self.version not in (0, 1) or size + 8 > len(b):
            raise FormatError("Versão ou tamanho UTF não suportado.")
        self.end = size + 8
        self.rows_start, self.strings_start, self.blobs_start = rowoff + 8, stroff + 8, dataoff + 8
        if not (32 <= self.rows_start <= self.strings_start <= self.blobs_start <= self.end):
            raise FormatError("Offsets UTF inválidos.")
        if rows > 1_000_000 or self.rows_start + rowlen * rows > self.strings_start:
            raise FormatError("Linhas UTF ultrapassam a área de dados.")
        self.name = self._string(nameoff)
        self.rows: list[dict] = [dict() for _ in range(rows)]
        self.cells: dict[tuple[int, str], tuple[int | None, int, int]] = {}
        pos, row_cursor = 32, 0
        for _ in range(cols):
            if pos + 5 > self.rows_start:
                raise FormatError("Descritor de coluna UTF truncado.")
            flags = b[pos]
            name = self._string(struct.unpack_from(">I", b, pos + 1)[0])
            kind, storage = flags & 15, flags & 0xF0
            if kind not in _TYPES or storage not in (0x10, 0x30, 0x50):
                raise FormatError(f"Coluna UTF não suportada: {name} ({flags:#x}).")
            width = struct.calcsize(_TYPES[kind])
            pos += 5
            for row in range(rows):
                cell = pos if storage == 0x30 else self.rows_start + row * rowlen + row_cursor
                if storage == 0x10:
                    value, location = (Blob(self.blobs_start, 0) if kind == 11 else "" if kind == 10 else 0), None
                else:
                    if cell + width > len(b):
                        raise FormatError("Célula UTF truncada.")
                    parts = struct.unpack_from(_TYPES[kind], b, cell)
                    value = self._string(parts[0]) if kind == 10 else (
                        Blob(self.blobs_start + parts[0], parts[1]) if kind == 11 else parts[0])
                    location = cell
                    if isinstance(value, Blob) and (value.start < self.blobs_start or value.start + value.size > self.end):
                        raise FormatError("Blob UTF fora dos limites.")
                if name in self.rows[row]:
                    raise FormatError("Nome de coluna UTF duplicado.")
                self.rows[row][name] = value
                self.cells[row, name] = location, kind, storage
            if storage == 0x30:
                pos += width
            elif storage == 0x50:
                row_cursor += width
        if pos > self.rows_start or row_cursor > rowlen:
            raise FormatError("Esquema UTF inconsistente.")

    def _string(self, offset: int) -> str:
        start = self.strings_start + offset
        if not self.strings_start <= start < self.blobs_start:
            raise FormatError("String UTF fora dos limites.")
        end = self.data.find(0, start, self.blobs_start)
        if end < 0:
            raise FormatError("String UTF sem terminador.")
        return bytes(self.data[start:end]).decode("utf-8", errors="replace")

    def blob(self, name: str, row: int = 0) -> bytes:
        val = self.rows[row].get(name)
        if not isinstance(val, Blob):
            raise FormatError(f"Blob ausente: {name}.")
        return bytes(self.data[val.start:val.start + val.size])

    def patch_blob(self, name: str, new: bytes, row: int = 0):
        val = self.rows[row].get(name)
        if not isinstance(val, Blob) or len(new) != val.size:
            raise FormatError(f"O tamanho do blob {name} mudou; variante não suportada.")
        self.data[val.start:val.start + val.size] = new

    def set(self, row: int, name: str, value: int):
        if self.rows[row].get(name) == value:
            return
        if (row, name) not in self.cells:
            raise FormatError(f"Campo UTF ausente: {name}.")
        location, kind, storage = self.cells[row, name]
        if location is None or kind >= 8 or (storage == 0x30 and len(self.rows) > 1):
            raise FormatError(f"Não é possível alterar o campo compartilhado {name}.")
        try:
            struct.pack_into(_TYPES[kind], self.data, location, value)
        except struct.error as exc:
            raise FormatError(f"Valor fora do limite do campo {name}.") from exc
        self.rows[row][name] = value

    def save(self) -> bytes:
        raw = bytes(self.data)
        return xor_utf(raw) if self.encrypted else raw


def read_exact(stream, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise FormatError("Arquivo truncado.")
    return data


def read_packet(stream, offset: int, magic: bytes) -> tuple[bytes, UtfTable]:
    stream.seek(offset)
    head = read_exact(stream, 16)
    length = struct.unpack_from("<Q", head, 8)[0]
    if head[:4] != magic or not 32 <= length <= 64 * 1024 * 1024:
        raise FormatError(f"Pacote {magic.decode(errors='replace')} inválido.")
    return head, UtfTable(read_exact(stream, length))


@dataclass(frozen=True)
class Entry:
    row: int
    name: str
    offset: int
    size: int


class Archive:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        stat = self.path.stat()
        self.size = stat.st_size
        self.identity = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
        with self.path.open("rb") as f:
            self.header_packet, self.header = read_packet(f, 0, b"CPK ")
            if len(self.header.rows) != 1:
                raise FormatError("Cabeçalho CPK com número de linhas inesperado.")
            h = self.header.rows[0]
            self.toc_offset = int(h.get("TocOffset", 0))
            self.content_offset = int(h.get("ContentOffset", 0))
            self.alignment = int(h.get("Align", 0))
            if not (16 <= self.toc_offset < self.content_offset <= 16 * 1024 * 1024):
                raise FormatError("Layout CPK não suportado (é necessário TOC antes do conteúdo).")
            if not 1 <= self.alignment <= 1_048_576 or self.alignment & (self.alignment - 1):
                raise FormatError("Alinhamento CPK inválido.")
            for key, val in h.items():
                if key.endswith("Offset") and key not in ("TocOffset", "ContentOffset") and isinstance(val, int) and val:
                    raise FormatError(f"CPK com tabela adicional {key}; variante não suportada.")
            if any(h.get(k, 0) for k in ("EnableCrc", "CrcMode", "Codec", "EnableTocCrc", "EnableFileCrc", "TocCrc", "ItocCrc", "AlignHighBit")):
                raise FormatError("CPK comprimido ou com CRC externo não suportado.")
            self.toc_packet, self.toc = read_packet(f, self.toc_offset, b"TOC ")
            if self.toc_offset + 16 + len(self.toc.data) > self.content_offset:
                raise FormatError("A TOC se sobrepõe ao conteúdo.")
            f.seek(0)
            self.prefix = read_exact(f, self.content_offset)
        self.base = min(self.toc_offset, self.content_offset)
        self.entries: list[Entry] = []
        self.by_name: dict[str, Entry] = {}
        for i, row in enumerate(self.toc.rows):
            name = (str(row.get("DirName", "")).strip("/") + "/" + str(row.get("FileName", ""))).lstrip("/")
            if not name or ".." in name.split("/") or "\\" in name or name in self.by_name:
                raise FormatError("Nome de entrada CPK inválido ou duplicado.")
            if int(row.get("FileSize", -1)) != int(row.get("ExtractSize", -2)):
                raise FormatError("Entrada CPK comprimida não suportada.")
            item = Entry(i, name, self.base + int(row["FileOffset"]), int(row["FileSize"]))
            if item.offset < self.content_offset or item.size < 0 or item.offset + item.size > self.size:
                raise FormatError(f"Entrada fora dos limites do CPK: {name}.")
            self.entries.append(item)
            self.by_name[name] = item
        end = self.content_offset
        for item in sorted(self.entries, key=lambda e: e.offset):
            if item.offset < end:
                raise FormatError("Entradas CPK sobrepostas.")
            end = item.offset + item.size
        if int(h.get("Files", len(self.entries))) != len(self.entries):
            raise FormatError("A contagem de arquivos CPK não confere.")

    def check_unchanged(self):
        s = self.path.stat()
        if (s.st_size, s.st_mtime_ns, s.st_ino) != self.identity:
            raise FormatError("O CPK original mudou. Abra-o novamente antes de continuar.")

    def read(self, entry: Entry, limit: int = 64 * 1024 * 1024) -> bytes:
        if entry.size > limit:
            raise FormatError("Entrada grande demais para leitura direta.")
        with self.path.open("rb") as f:
            f.seek(entry.offset)
            return read_exact(f, entry.size)


class Awb:
    def __init__(self, path: str | Path, offset: int = 0, size: int | None = None):
        self.path, self.base = Path(path), offset
        self.size = self.path.stat().st_size - offset if size is None else size
        with self.path.open("rb") as f:
            f.seek(offset)
            head = read_exact(f, 16)
            if head[:4] != b"AFS2":
                raise FormatError("O banco não usa AWB AFS2.")
            self.version, self.offset_width = head[4], head[5]
            self.id_width, self.count, self.alignment, self.subkey = struct.unpack_from("<HIHH", head, 6)
            if self.version not in (1, 2) or self.offset_width not in (2, 4, 8) or self.id_width not in (2, 4):
                raise FormatError("Versão AFS2 não suportada.")
            if not 0 < self.count <= 1_000_000 or not 1 <= self.alignment <= 65535:
                raise FormatError("Contagem ou alinhamento AFS2 inválido.")
            self.offset_table = 16 + self.count * self.id_width
            self.header_size = self.offset_table + (self.count + 1) * self.offset_width
            if self.header_size > self.size:
                raise FormatError("Tabelas AWB truncadas.")
            self.header = head + read_exact(f, self.header_size - 16)
        self.ids = [int.from_bytes(self.header[16+i*self.id_width:16+(i+1)*self.id_width], "little") for i in range(self.count)]
        self.offsets = [int.from_bytes(self.header[self.offset_table+i*self.offset_width:self.offset_table+(i+1)*self.offset_width], "little") for i in range(self.count+1)]
        if len(set(self.ids)) != self.count or self.offsets[0] < self.header_size or self.offsets[-1] != self.size:
            raise FormatError("IDs ou limites do AWB inconsistentes.")
        self.index = {value: i for i, value in enumerate(self.ids)}
        self.spans: list[tuple[int, int]] = []
        for i in range(self.count):
            start, end = align(self.offsets[i], self.alignment), self.offsets[i+1]
            if not self.header_size <= start < end <= self.size:
                raise FormatError("Offset de áudio AWB inválido.")
            self.spans.append((self.base + start, end - start))

    def audio(self, audio_id: int, limit: int = 64 * 1024 * 1024) -> bytes:
        start, size = self.spans[self.index[audio_id]]
        if size > limit:
            raise FormatError("Áudio individual grande demais (limite: 64 MiB).")
        with self.path.open("rb") as f:
            f.seek(start)
            return read_exact(f, size)
