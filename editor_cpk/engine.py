"""Conversão, montagem por streaming e validação do resultado."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import errno
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave

from .formats import Archive, Awb, Blob, FormatError, UtfTable, align, read_exact

DEFAULT_KEY = 14121473
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma"}
CHUNK = 1024 * 1024
MAX_PCM_BYTES = 64 * 1024 * 1024
Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


def check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Operação cancelada. O CPK original foi preservado.")


def parse_key(text: str | int) -> int:
    try:
        key = int(str(text).strip(), 16 if str(text).strip().lower().startswith("0x") else 10)
    except ValueError as exc:
        raise FormatError("Chave inválida. Use um número decimal ou hexadecimal com 0x.") from exc
    if not 0 <= key < 2**64:
        raise FormatError("A chave deve ser um inteiro de 64 bits sem sinal.")
    return key


def codec():
    try:
        from cricodecs import hca
        return hca
    except ImportError as exc:
        raise FormatError("CriCodecs não está instalado. Execute o instalador do programa.") from exc


def ffmpeg_executable() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise FormatError("FFmpeg não encontrado. Execute o instalador ou instale o FFmpeg.") from exc


def process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def copy_span(source, dest, offset: int, size: int, cancel=None):
    source.seek(offset)
    while size:
        check_cancel(cancel)
        data = source.read(min(CHUNK, size))
        if not data:
            raise FormatError("O arquivo de origem foi truncado durante a leitura.")
        dest.write(data)
        size -= len(data)


def span_digest(stream, offset: int, size: int, algorithm="sha256", cancel=None) -> bytes:
    digest = hashlib.new(algorithm)
    stream.seek(offset)
    while size:
        check_cancel(cancel)
        data = stream.read(min(CHUNK, size))
        if not data:
            raise FormatError("Arquivo truncado durante a validação.")
        digest.update(data)
        size -= len(data)
    return digest.digest()


def file_digest(path: Path, algorithm="sha256", cancel=None) -> bytes:
    with path.open("rb") as f:
        return span_digest(f, 0, path.stat().st_size, algorithm, cancel)


@dataclass
class Audio:
    id: int
    samples: int
    rate: int
    channels: int
    names: list[str] = field(default_factory=list)
    waveform_rows: list[int] = field(default_factory=list)
    cue_rows: list[int] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.names[0] if self.names else f"ID{self.id:06d}"

    @property
    def duration(self) -> float:
        return self.samples / self.rate


class Bank:
    def __init__(self, archive: Archive, name: str):
        self.name = name
        self.acb_entry = archive.by_name[f"bra/sound/acb/{name}.acb"]
        self.awb_entry = archive.by_name[f"bra/sound/awb/{name}.awb"]
        self.acb = UtfTable(archive.read(self.acb_entry))
        if len(self.acb.rows) != 1:
            raise FormatError("Cabeçalho ACB com várias linhas não suportado.")
        self.waveforms = UtfTable(self.acb.blob("WaveformTable"))
        self.cues = UtfTable(self.acb.blob("CueTable"))
        self.cue_names = UtfTable(self.acb.blob("CueNameTable"))
        self.awb = Awb(archive.path, self.awb_entry.offset, self.awb_entry.size)
        self.audios: dict[int, Audio] = {}
        waveform_ids = {}
        for i, row in enumerate(self.waveforms.rows):
            if row.get("EncodeType") != 2 or row.get("Streaming") != 1 or row.get("StreamAwbPortNo", 0) != 0:
                raise FormatError("Este banco precisa de HCA externo com uma única porta AWB.")
            ident = int(row["StreamAwbId"])
            if ident not in self.awb.index:
                raise FormatError("Waveform referencia ID inexistente no AWB.")
            values = int(row["NumSamples"]), int(row["SamplingRate"]), int(row["NumChannels"])
            if values[0] <= 0 or values[1] != 48000 or values[2] != 1:
                raise FormatError("Este editor suporta o perfil de narração mono a 48000 Hz.")
            if ident not in self.audios:
                self.audios[ident] = Audio(ident, *values)
            item = self.audios[ident]
            if (item.samples, item.rate, item.channels) != values:
                raise FormatError("Waveforms compartilhadas têm formatos diferentes.")
            item.waveform_rows.append(i)
            waveform_ids[i] = ident
        if set(self.audios) != set(self.awb.ids):
            raise FormatError("O banco contém IDs sem waveform; variante não suportada.")
        cue_ids = {}
        for i, row in enumerate(self.cues.rows):
            if row.get("ReferenceType") != 1 or row.get("ReferenceIndex") not in waveform_ids:
                raise FormatError("Cues complexas não são suportadas por esta versão do editor.")
            ident = waveform_ids[row["ReferenceIndex"]]
            cue_ids[i] = ident
            self.audios[ident].cue_rows.append(i)
        for row in self.cue_names.rows:
            if row.get("CueIndex") not in cue_ids:
                raise FormatError("Nome de cue aponta para uma cue inexistente.")
            item = self.audios[cue_ids[row["CueIndex"]]]
            name_value = str(row["CueName"])
            if name_value not in item.names:
                item.names.append(name_value)
        self.hash_table = UtfTable(self.acb.blob("StreamAwbHash"))
        self.header_table = UtfTable(self.acb.blob("StreamAwbAfs2Header"))
        if len(self.hash_table.rows) != 1 or len(self.header_table.rows) != 1:
            raise FormatError("Bancos com múltiplos AWBs não são suportados.")
        if len(self.hash_table.blob("Hash")) != 16:
            raise FormatError("Hash AWB incompatível.")
        embedded = self.header_table.blob("Header")
        if not self.awb.header_size <= len(embedded) <= align(self.awb.offsets[0], self.awb.alignment):
            raise FormatError("Cabeçalho AWB embutido tem tamanho inesperado.")
        with archive.path.open("rb") as f:
            f.seek(self.awb.base)
            if read_exact(f, len(embedded)) != embedded:
                raise FormatError("O cabeçalho AWB não corresponde ao ACB.")


class Project:
    def __init__(self, path: str | Path):
        self.archive = Archive(path)
        self.bank_names = sorted(
            Path(e.name).stem for e in self.archive.entries
            if e.name.startswith("bra/sound/acb/") and e.name.endswith(".acb")
            and f"bra/sound/awb/{Path(e.name).stem}.awb" in self.archive.by_name)
        if not self.bank_names:
            raise FormatError("Nenhum par ACB/AWB de narração foi encontrado neste CPK.")
        self._banks: dict[str, Bank] = {}

    def bank(self, name: str) -> Bank:
        if name not in self.bank_names:
            raise FormatError(f"Banco inexistente: {name}.")
        if name not in self._banks:
            self.archive.check_unchanged()
            self._banks[name] = Bank(self.archive, name)
        return self._banks[name]


@dataclass(frozen=True)
class Replacement:
    bank: str
    audio_id: int
    path: Path


@dataclass
class Match:
    path: Path
    bank: str
    audio_id: int | None
    name: str
    status: str


def match_folder(project: Project, bank_name: str, folder: Path, cancel=None) -> list[Match]:
    from .groups import base_bank_name
    bank = project.bank(bank_name)
    by_name: dict[str, set[int]] = defaultdict(set)
    for item in bank.audios.values():
        for name in item.names:
            by_name[name.casefold()].add(item.id)
    results = []
    for path in sorted(folder.rglob("*")):
        check_cancel(cancel)
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if len(results) >= 100000:
            raise FormatError("A pasta contém mais de 100 mil arquivos de áudio.")
        stem = path.stem
        folders = (*path.relative_to(folder).parts[:-1], folder.name, folder.parent.name)
        indicated = {folder_bank for part in folders if (folder_bank := base_bank_name(part, project.bank_names))}
        indicated.update(n for n in project.bank_names if stem.upper().startswith(n.upper() + "__"))
        if "__ID" in stem.upper():
            prefix = re.split(r"__ID", stem, maxsplit=1, flags=re.I)[0]
            if detected := base_bank_name(prefix, project.bank_names):
                indicated.add(detected)
        match = re.search(r"(?:^|__)ID(\d+)(?:__|$)", stem, re.I)
        ids = {int(match.group(1))} if match else by_name.get(stem.casefold(), set())
        ident = next(iter(ids)) if len(ids) == 1 else None
        if indicated and indicated != {bank_name}:
            status = "Banco diferente do selecionado"
        elif ident is None:
            status = "Nome ambíguo" if ids else "Sem correspondência"
        elif ident not in bank.audios:
            status = "ID inexistente neste banco"
        else:
            suffix = re.split(r"(?:^|__)ID\d+__", stem, flags=re.I)[-1] if match and "__" in stem[match.start():] else ""
            if suffix and suffix.casefold() not in {n.casefold() for n in bank.audios[ident].names}:
                status = "Nome não corresponde ao ID"
            else:
                status = "Pronto"
        results.append(Match(path.resolve(), bank_name, ident,
                             bank.audios[ident].name if ident in bank.audios else "", status))
    grouped: dict[int, list[Match]] = defaultdict(list)
    for item in results:
        if item.status == "Pronto":
            grouped[item.audio_id].append(item)
    for items in grouped.values():
        if len(items) > 1:
            for item in items:
                item.status = "Mais de um arquivo para este ID"
    return results


def decoded_wav(bank: Bank, ident: int, key: int) -> bytes:
    return codec().decode(bank.awb.audio(ident), keycode=key, subkey=bank.awb.subkey)


def wave_samples(raw: bytes) -> tuple[int, int, int]:
    with wave.open(io.BytesIO(raw), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise FormatError("O áudio PCM precisa ter 16 bits.")
        return wav.getnframes(), wav.getframerate(), wav.getnchannels()


def original_header(bank: Bank, ident: int):
    item = bank.audios[ident]
    header = codec().load(bank.awb.audio(ident)).header()
    if (header.fmt.sample_rate, header.fmt.channel_count, header.sample_count()) != (item.rate, item.channels, item.samples):
        raise FormatError("O perfil do HCA original não corresponde aos metadados ACB.")
    if header.file.version != 0x0200 or header.cipher.type not in (0, 56) or header.loop.enabled:
        raise FormatError("Versão HCA, criptografia ou loop não suportado neste áudio.")
    return header


def prepare_pcm(path: Path, pcm_path: Path, samples: int | None = None, cancel=None):
    """Converte uma entrada para PCM mono/48 kHz; reutilizável na troca em massa."""
    check_cancel(cancel)
    log_path = pcm_path.with_suffix(".ffmpeg.log")
    cmd = [ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn"]
    if samples is not None:
        cmd += ["-af", f"aresample=48000,apad,atrim=end_sample={samples}"]
    cmd += ["-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", str(pcm_path)]
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log, **process_options())
            try:
                while True:
                    try:
                        status = process.wait(timeout=0.15)
                        break
                    except subprocess.TimeoutExpired:
                        check_cancel(cancel)
                        if pcm_path.exists() and pcm_path.stat().st_size > MAX_PCM_BYTES:
                            raise FormatError("Áudio convertido ultrapassa 64 MiB. Use um trecho menor.")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if status:
            error = log_path.read_text(errors="replace")[-3000:]
            raise FormatError(f"FFmpeg não conseguiu converter {path.name}:\n{error}")
        if pcm_path.stat().st_size > MAX_PCM_BYTES:
            raise FormatError("Áudio convertido ultrapassa 64 MiB. Use um trecho menor.")
    finally:
        log_path.unlink(missing_ok=True)


def fitted_pcm(path: Path, samples: int | None) -> bytes:
    with wave.open(str(path), "rb") as source:
        count = source.getnframes() if samples is None else samples
        if count <= 0 or count * 2 > MAX_PCM_BYTES:
            raise FormatError("O áudio ajustado ultrapassa o limite de 64 MiB em PCM.")
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 48000):
            raise FormatError("O áudio preparado tem um perfil PCM inesperado.")
        pcm = source.readframes(count)
    pcm += b"\0" * (count * 2 - len(pcm))
    out = io.BytesIO()
    with wave.open(out, "wb") as dest:
        dest.setparams((1, 2, 48000, count, "NONE", "not compressed"))
        dest.writeframes(pcm)
    return out.getvalue()


def convert_audio(bank: Bank, ident: int, path: Path, directory: Path,
                  key: int, keep_duration: bool, cancel=None, *, prepared_wav: Path | None = None,
                  header=None) -> tuple[bytes, int]:
    check_cancel(cancel)
    item, hca = bank.audios[ident], codec()
    header = original_header(bank, ident) if header is None else header
    pcm_path = directory / f"{bank.name}_{ident}.wav"
    try:
        if prepared_wav is None:
            decoded_wav(bank, ident, key)
            prepare_pcm(path, pcm_path, item.samples if keep_duration else None, cancel)
            raw = pcm_path.read_bytes()
        else:
            raw = fitted_pcm(prepared_wav, item.samples if keep_duration else None)
        samples, rate, channels = wave_samples(raw)
        if not samples or (keep_duration and samples != item.samples):
            raise FormatError("A conversão não produziu a duração esperada.")
        config = hca.HcaEncodeConfig()
        config.sample_rate, config.channel_count = rate, channels
        config.version = header.file.version
        config.bitrate = header.codec.frame_size * rate * 8 // 1024
        config.quality = hca.HcaQuality.HIGH
        encoded = hca.encode(raw, config)
        check_cancel(cancel)
        encrypted = hca.encrypt(encoded, cipher_type=header.cipher.type, keycode=key, subkey=bank.awb.subkey)
        new_header = hca.load(encrypted).header()
        if new_header.sample_count() != samples or new_header.codec.frame_size != header.codec.frame_size:
            raise FormatError("O HCA gerado não manteve o perfil ou a duração solicitados.")
        if wave_samples(hca.decode(encrypted, keycode=key, subkey=bank.awb.subkey)) != (samples, rate, channels):
            raise FormatError("A verificação do HCA recém-codificado falhou.")
        return encrypted, samples
    finally:
        pcm_path.unlink(missing_ok=True)


def rebuild_bank(bank: Bank, encoded: dict[int, tuple[Path, int]], directory: Path,
                 cancel=None) -> tuple[Path, bytes]:
    original_awb = bank.awb
    output = directory / (bank.name + ".awb")
    head = bytearray(original_awb.header)
    offsets = [original_awb.offsets[0]]
    with original_awb.path.open("rb") as source:
        if span_digest(source, original_awb.base, original_awb.size, "md5", cancel) != bank.hash_table.blob("Hash"):
            raise FormatError(f"O hash do AWB {bank.name} não confere com seu ACB.")
        with output.open("w+b") as dest:
            dest.write(head)
            for index, ident in enumerate(original_awb.ids):
                check_cancel(cancel)
                target = align(offsets[-1], original_awb.alignment)
                dest.write(b"\0" * (target - dest.tell()))
                if ident in encoded:
                    replacement_path = encoded[ident][0]
                    with replacement_path.open("rb") as replacement:
                        copy_span(replacement, dest, 0, replacement_path.stat().st_size, cancel)
                else:
                    start, size = original_awb.spans[index]
                    copy_span(source, dest, start, size, cancel)
                offsets.append(dest.tell())
            for i, value in enumerate(offsets):
                if value >= 1 << (8 * original_awb.offset_width):
                    raise FormatError("O AWB reconstruído ultrapassou a capacidade de seus offsets.")
                start = original_awb.offset_table + i * original_awb.offset_width
                head[start:start + original_awb.offset_width] = value.to_bytes(original_awb.offset_width, "little")
            dest.seek(0)
            dest.write(head)
    acb = UtfTable(bank.acb.save())
    waveforms, cues = UtfTable(bank.waveforms.save()), UtfTable(bank.cues.save())
    for ident, (_, samples) in encoded.items():
        item = bank.audios[ident]
        for row in item.waveform_rows:
            waveforms.set(row, "NumSamples", samples)
        for row in item.cue_rows:
            cues.set(row, "Length", samples * 1000 // item.rate)
    acb.patch_blob("WaveformTable", waveforms.save())
    acb.patch_blob("CueTable", cues.save())
    hash_table, header_table = UtfTable(bank.hash_table.save()), UtfTable(bank.header_table.save())
    hash_table.patch_blob("Hash", file_digest(output, "md5", cancel))
    with output.open("rb") as f:
        header_table.patch_blob("Header", read_exact(f, len(header_table.blob("Header"))))
    acb.patch_blob("StreamAwbHash", hash_table.save())
    acb.patch_blob("StreamAwbAfs2Header", header_table.save())
    return output, acb.save()


def validate_result(original: Project, output: Path, changes: dict[tuple[str, int], tuple[Path, int]],
                    touched: set[str], key: int, cancel=None, progress: Progress = lambda p, m: None):
    rebuilt = Project(output)
    old, new = original.archive, rebuilt.archive
    if [e.name for e in old.entries] != [e.name for e in new.entries]:
        raise FormatError("A lista de entradas mudou após a reconstrução.")
    modified_names = {f"bra/sound/{kind}/{name}.{kind}" for name in touched for kind in ("acb", "awb")}
    expected_hashes, decoded_formats = {}, {}
    with old.path.open("rb") as src, output.open("rb") as dst:
        for index, entry in enumerate(old.entries):
            check_cancel(cancel)
            other = new.by_name[entry.name]
            if other.offset % new.alignment:
                raise FormatError("Entrada CPK desalinhada após a reconstrução.")
            if entry.name not in modified_names:
                if entry.size != other.size or span_digest(src, entry.offset, entry.size, cancel=cancel) != span_digest(dst, other.offset, other.size, cancel=cancel):
                    raise FormatError(f"Uma entrada não alterada mudou: {entry.name}.")
            progress(76 + 8 * (index + 1) / len(old.entries), "Conferindo arquivos preservados…")
        for bank_index, name in enumerate(sorted(touched)):
            old_bank, new_bank = original.bank(name), rebuilt.bank(name)
            if old_bank.awb.ids != new_bank.awb.ids:
                raise FormatError("Os IDs do banco reconstruído mudaram.")
            if span_digest(dst, new_bank.awb.base, new_bank.awb.size, "md5", cancel) != new_bank.hash_table.blob("Hash"):
                raise FormatError("Hash do AWB reconstruído inválido.")
            for index, ident in enumerate(old_bank.awb.ids):
                check_cancel(cancel)
                a, b = old_bank.audios[ident], new_bank.audios[ident]
                changed = changes.get((name, ident))
                if a.names != b.names or a.waveform_rows != b.waveform_rows or a.cue_rows != b.cue_rows:
                    raise FormatError("Uma associação de cue mudou.")
                if changed:
                    expected, samples = changed
                    raw = new_bank.awb.audio(ident)
                    if expected not in expected_hashes:
                        expected_hashes[expected] = file_digest(expected, cancel=cancel)
                    digest = hashlib.sha256(raw).digest()
                    if digest != expected_hashes[expected]:
                        raise FormatError("O HCA substituído não foi recuperado corretamente do CPK final.")
                    decode_key = digest, new_bank.awb.subkey
                    if decode_key not in decoded_formats:
                        decoded_formats[decode_key] = wave_samples(decoded_wav(new_bank, ident, key))
                    if b.samples != samples or decoded_formats[decode_key] != (samples, b.rate, b.channels):
                        raise FormatError("A duração do áudio reconstruído não confere.")
                    for row in b.cue_rows:
                        if new_bank.cues.rows[row]["Length"] != samples * 1000 // b.rate:
                            raise FormatError("A duração da cue reconstruída não confere.")
                else:
                    old_span, new_span = old_bank.awb.spans[index], new_bank.awb.spans[index]
                    if a.samples != b.samples or old_span[1] != new_span[1] or span_digest(src, *old_span, cancel=cancel) != span_digest(dst, *new_span, cancel=cancel):
                        raise FormatError(f"Um HCA não alterado mudou: {name} / {ident}.")
                if index % 500 == 0:
                    progress(84 + 10 * (bank_index + index / old_bank.awb.count) / len(touched), f"Validando {name}: {index + 1}/{old_bank.awb.count}")
    return rebuilt


def publish_file(temp: Path, output: Path, cancel=None):
    check_cancel(cancel)
    try:
        os.link(temp, output)  # Publicação atômica, sem sobrescrever um destino existente.
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise FormatError("O arquivo de destino já existe. Escolha outro nome.") from exc
        if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV, errno.EACCES):
            raise
        created = False
        try:
            with output.open("xb") as dest, temp.open("rb") as source:
                created = True
                copy_span(source, dest, 0, temp.stat().st_size, cancel)
                dest.flush()
                os.fsync(dest.fileno())
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    temp.unlink()


def generate(project: Project, replacements: list[Replacement], output: Path,
             key: int = DEFAULT_KEY, keep_duration: bool = True, cancel=None,
             progress: Progress = lambda p, m: None) -> dict:
    output = Path(output).expanduser().resolve()
    archive = project.archive
    key = parse_key(key)
    if not replacements:
        raise FormatError("Adicione pelo menos um áudio substituto.")
    if output == archive.path or output.exists():
        raise FormatError("Escolha um arquivo novo. O original e arquivos existentes nunca são sobrescritos.")
    if output.suffix.lower() != ".cpk":
        raise FormatError("O arquivo de saída precisa ter a extensão .cpk.")
    if not output.parent.is_dir():
        raise FormatError("A pasta de destino não existe.")
    archive.check_unchanged()
    grouped: dict[str, list[Replacement]] = defaultdict(list)
    seen = set()
    identities = {}
    for item in replacements:
        check_cancel(cancel)
        path = Path(item.path).resolve()
        ident = (item.bank, item.audio_id)
        if ident in seen or item.audio_id not in project.bank(item.bank).audios:
            raise FormatError("Há IDs duplicados ou inexistentes na lista de substituições.")
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS or path == output:
            raise FormatError(f"Arquivo substituto inválido: {path}.")
        seen.add(ident)
        stat = path.stat()
        identities[path] = stat.st_size, stat.st_mtime_ns, stat.st_ino
        grouped[item.bank].append(Replacement(item.bank, item.audio_id, path))
    # AWBs temporários + CPK temporário; margem para conversões e destino em FAT/exFAT.
    needed = archive.size * 2 + sum(project.bank(n).awb_entry.size for n in grouped) + 256 * 1024 * 1024
    if shutil.disk_usage(output.parent).free < needed:
        raise FormatError(f"Espaço livre insuficiente. Reserve cerca de {needed / 1024**3:.1f} GiB na pasta de destino.")
    progress(1, "Conferindo o CPK original…")
    original_sha = file_digest(archive.path, cancel=cancel).hex()
    with tempfile.TemporaryDirectory(prefix="editor_cpk_", dir=output.parent) as temp_dir:
        directory = Path(temp_dir)
        changes: dict[tuple[str, int], tuple[Path, int]] = {}
        new_files: dict[str, Path | bytes] = {}
        encodings = {}
        report_changes = []
        processed = 0
        repetitions = Counter(item.path for items in grouped.values() for item in items)
        prepared_source, prepared_path = None, directory / "entrada_reutilizada.wav"
        encoded_cache = {}
        conversion_count = 0
        for name, items in grouped.items():
            bank = project.bank(name)
            encoded = {}
            for item in items:
                check_cancel(cancel)
                progress(3 + 35 * processed / len(replacements), f"Convertendo {name} / ID{item.audio_id:06d}: {item.path.name}")
                stat = item.path.stat()
                if identities[item.path] != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
                    raise FormatError(f"O áudio de entrada mudou durante a operação: {item.path.name}.")
                header = original_header(bank, item.audio_id)
                signature = (item.path, bank.audios[item.audio_id].samples if keep_duration else None,
                             header.file.version, header.codec.frame_size, header.cipher.type,
                             header.fmt.sample_rate, header.fmt.channel_count, bank.awb.subkey, key)
                if repetitions[item.path] > 1 and signature in encoded_cache:
                    hca_path, samples, encoded_sha = encoded_cache[signature]
                else:
                    prepared_wav = None
                    if repetitions[item.path] > 1:
                        if prepared_source != item.path:
                            prepare_pcm(item.path, prepared_path, cancel=cancel)
                            prepared_source = item.path
                        prepared_wav = prepared_path
                    raw, samples = convert_audio(bank, item.audio_id, item.path, directory, key, keep_duration,
                                                 cancel, prepared_wav=prepared_wav, header=header)
                    hca_path = directory / f"{name}_{item.audio_id}.hca"
                    hca_path.write_bytes(raw)
                    conversion_count += 1
                    encoded_sha = hashlib.sha256(raw).hexdigest()
                    if repetitions[item.path] > 1:
                        encoded_cache[signature] = hca_path, samples, encoded_sha
                encoded[item.audio_id] = hca_path, samples
                changes[name, item.audio_id] = hca_path, samples
                report_changes.append({"banco": name, "id": item.audio_id, "nome": bank.audios[item.audio_id].name,
                                       "entrada": str(item.path), "amostras_antes": bank.audios[item.audio_id].samples,
                                       "amostras_depois": samples, "taxa": bank.audios[item.audio_id].rate,
                                       "sha256_hca": encoded_sha})
                processed += 1
            encodings[name] = encoded
        # Repetir uma gravação longa em milhares de posições pode ampliar muito a saída.
        sizes = {}
        for name, encoded in encodings.items():
            bank = project.bank(name)
            size = bank.awb.offsets[0]
            for index, ident in enumerate(bank.awb.ids):
                size = align(size, bank.awb.alignment) + (encoded[ident][0].stat().st_size if ident in encoded else bank.awb.spans[index][1])
            sizes[bank.awb_entry.name] = size
        estimated_cpk = archive.content_offset
        for entry in archive.entries:
            estimated_cpk = align(estimated_cpk, archive.alignment) + sizes.get(entry.name, entry.size)
        remaining_space = sum(sizes.values()) + estimated_cpk * 2 + 256 * 1024 * 1024
        if shutil.disk_usage(output.parent).free < remaining_space:
            raise FormatError(f"O áudio escolhido produziria um CPK de aproximadamente {estimated_cpk/1024**3:.1f} GiB. "
                              f"Reserve {remaining_space/1024**3:.1f} GiB livres ou use uma gravação mais curta.")
        for bank_index, (name, encoded) in enumerate(encodings.items()):
            bank = project.bank(name)
            progress(38 + 5 * bank_index / len(encodings), f"Reconstruindo banco {name}…")
            awb_path, acb_bytes = rebuild_bank(bank, encoded, directory, cancel)
            new_files[bank.awb_entry.name], new_files[bank.acb_entry.name] = awb_path, acb_bytes
        header, toc = UtfTable(archive.header.save()), UtfTable(archive.toc.save())
        result_path = directory / "resultado.cpk"
        packed_size = 0
        with archive.path.open("rb") as source, result_path.open("w+b") as dest:
            dest.write(archive.prefix)
            for index, entry in enumerate(archive.entries):
                check_cancel(cancel)
                position = align(dest.tell(), archive.alignment)
                dest.write(b"\0" * (position - dest.tell()))
                replacement = new_files.get(entry.name)
                if isinstance(replacement, bytes):
                    dest.write(replacement)
                elif isinstance(replacement, Path):
                    with replacement.open("rb") as data:
                        copy_span(data, dest, 0, replacement.stat().st_size, cancel)
                else:
                    copy_span(source, dest, entry.offset, entry.size, cancel)
                size = dest.tell() - position
                packed_size += size
                toc.set(entry.row, "FileOffset", position - archive.base)
                toc.set(entry.row, "FileSize", size)
                toc.set(entry.row, "ExtractSize", size)
                progress(43 + 32 * (index + 1) / len(archive.entries), f"Montando CPK: {entry.name}")
            final_size = dest.tell()
            updates = {"ContentSize": align(final_size, archive.alignment) - archive.content_offset,
                       "EnabledPackedSize": packed_size, "EnabledDataSize": packed_size}
            if header.rows[0].get("FileSize", 0):
                updates["FileSize"] = final_size
            for field_name, value in updates.items():
                header.set(0, field_name, value)
            dest.seek(16)
            dest.write(header.save())
            dest.seek(archive.toc_offset + 16)
            dest.write(toc.save())
            dest.flush()
            os.fsync(dest.fileno())
        progress(76, "Reabrindo e validando o CPK gerado…")
        validate_result(project, result_path, changes, set(grouped), key, cancel, progress)
        progress(95, "Confirmando que o CPK original permaneceu intacto…")
        archive.check_unchanged()
        if file_digest(archive.path, cancel=cancel).hex() != original_sha:
            raise FormatError("O arquivo original mudou durante a operação. A saída não será finalizada.")
        for path, identity in identities.items():
            stat = path.stat()
            if identity != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
                raise FormatError(f"O áudio de entrada mudou durante a operação: {path.name}.")
        from . import __version__
        report = {"programa": f"Editor de Áudio CPK {__version__}", "original": str(archive.path), "saida": str(output),
                  "sha256_original": original_sha, "sha256_saida": file_digest(result_path, cancel=cancel).hex(),
                  "tamanho_saida": final_size, "manter_duracao": keep_duration,
                  "codificacoes_hca": conversion_count,
                  "substituicoes": report_changes, "validacao_estrutural": "aprovada",
                  "arquivos_e_hcas_nao_alterados": "hashes conferidos", "teste_no_jogo": "não realizado"}
        progress(99, "Finalizando o novo arquivo…")
        publish_file(result_path, output, cancel)
    # O relatório é opcional: sua falha não transforma um CPK já validado em erro.
    try:
        report_path = output.with_suffix(".relatorio.json")
        with report_path.open("x", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        report["relatorio"] = str(report_path)
    except OSError as exc:
        report["aviso_relatorio"] = str(exc)
    progress(100, "CPK gerado e validado com sucesso.")
    return report
