"""Grupos compatíveis com os ZIPs antigos e exportação de áudio em partes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import subprocess
import tempfile
import zipfile

from .formats import Awb, FormatError

# Limites exclusivos conferidos nos índices dos ZIPs exportados anteriormente.
LEGACY_CUTS = {"10_PLAYER": (1074, 16659, 37210), "20_MAIN": (5352,)}
EXPORT_FORMATS = {"mp3_hca": "MP3 + HCA original", "mp3": "MP3", "wav": "WAV", "hca": "HCA original"}


@dataclass(frozen=True)
class AudioGroup:
    name: str
    bank: str
    ids: tuple[int, ...]


def base_bank_name(name: str, bank_names) -> str | None:
    text = name.casefold()
    for bank in bank_names:
        if text == bank.casefold() or re.fullmatch(re.escape(bank.casefold()) + r"_[1-9][0-9]*", text):
            return bank
    return None


def groups_for_project(project) -> list[AudioGroup]:
    groups = []
    for bank in project.bank_names:
        entry = project.archive.by_name[f"bra/sound/awb/{bank}.awb"]
        awb = Awb(project.archive.path, entry.offset, entry.size)
        ids = sorted(awb.ids)
        cuts = [value for value in LEGACY_CUTS.get(bank, ()) if value < len(ids)]
        if not cuts:
            groups.append(AudioGroup(bank, bank, tuple(ids)))
            continue
        bounds = [0, *cuts, len(ids)]
        for index, (start, stop) in enumerate(zip(bounds, bounds[1:]), 1):
            groups.append(AudioGroup(f"{bank}_{index}", bank, tuple(ids[start:stop])))
    return groups


def group_for_audio(groups: list[AudioGroup], bank: str, ident: int) -> str:
    for group in groups:
        if group.bank == bank and ident in group.ids:
            return group.name
    return bank


def safe_audio_name(ident: int, name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")[:160]
    return f"ID{ident:06d}__{name}" if name else f"ID{ident:06d}"


def _mp3(wav_path: Path, output: Path, cancel):
    from .engine import check_cancel, ffmpeg_executable, process_options
    log = output.with_suffix(".log")
    cmd = [ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
           "-vn", "-ar", "48000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "96k", str(output)]
    with log.open("wb") as error_file:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=error_file, **process_options())
        try:
            while True:
                try:
                    status = process.wait(timeout=.15)
                    break
                except subprocess.TimeoutExpired:
                    check_cancel(cancel)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if status:
        raise FormatError("Não foi possível exportar MP3:\n" + log.read_text(errors="replace")[-2500:])


def export_groups(project, groups: list[AudioGroup], destination: Path, audio_format="mp3_hca",
                  key=14121473, cancel=None, progress=lambda p, m: None) -> list[dict]:
    """Um ZIP independente por grupo; nunca sobrescreve saídas existentes.

    No cancelamento, ZIPs completos são mantidos e o ZIP em construção é removido.
    """
    from .engine import (CHUNK, MAX_PCM_BYTES, Cancelled, check_cancel, decoded_wav,
                         parse_key, publish_file, wave_samples)
    destination = Path(destination).expanduser().resolve()
    if audio_format not in EXPORT_FORMATS or not groups:
        raise FormatError("Escolha pelo menos um grupo e um formato válido.")
    if not destination.is_dir():
        raise FormatError("A pasta de destino não existe.")
    names = set()
    total = sum(len(group.ids) for group in groups)
    for group in groups:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", group.name) or group.name in names or not group.ids:
            raise FormatError("Há grupos inválidos, vazios ou duplicados na exportação.")
        names.add(group.name)
        if (destination / f"{group.name}.zip").exists():
            raise FormatError(f"{group.name}.zip já existe. Escolha outra pasta para preservar o arquivo.")
        bank = project.bank(group.bank)
        if len(set(group.ids)) != len(group.ids) or any(ident not in bank.audios for ident in group.ids):
            raise FormatError("O grupo contém IDs duplicados ou inexistentes.")
    key = parse_key(key)
    completed, processed = [], 0
    try:
        with tempfile.TemporaryDirectory(prefix="cpk_export_", dir=destination) as temp:
            temp = Path(temp)
            for group in groups:
                check_cancel(cancel)
                project.archive.check_unchanged()
                bank = project.bank(group.bank)
                temporary_zip = temp / f"{group.name}.zip"
                index = []
                with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
                    for position, ident in enumerate(group.ids, 1):
                        check_cancel(cancel)
                        item = bank.audios[ident]
                        stem = safe_audio_name(ident, item.name)
                        message = f"Exportando {group.name}: {position}/{len(group.ids)} · ID{ident:06d}"
                        progress(100 * processed / total, message)
                        files = {}
                        if audio_format in ("hca", "mp3_hca"):
                            path = f"{group.name}/hca/{stem}.hca"
                            archive.writestr(path, bank.awb.audio(ident))
                            files["hca"] = path
                        if audio_format != "hca":
                            if item.samples * item.channels * 2 > MAX_PCM_BYTES:
                                raise FormatError("O áudio individual ultrapassa o limite de 64 MiB em PCM.")
                            raw = decoded_wav(bank, ident, key)
                            if wave_samples(raw) != (item.samples, item.rate, item.channels):
                                raise FormatError(f"A duração decodificada não confere: {group.bank} / {ident}.")
                            if audio_format == "wav":
                                path = f"{group.name}/wav/{stem}.wav"
                                archive.writestr(path, raw)
                                files["wav"] = path
                            else:
                                wav_path, mp3_path = temp / "atual.wav", temp / "atual.mp3"
                                wav_path.write_bytes(raw)
                                _mp3(wav_path, mp3_path, cancel)
                                path = f"{group.name}/mp3/{stem}.mp3"
                                archive.write(mp3_path, path)
                                files["mp3"] = path
                                wav_path.unlink(missing_ok=True)
                                mp3_path.unlink(missing_ok=True)
                                mp3_path.with_suffix(".log").unlink(missing_ok=True)
                        index.append({"banco": group.bank, "grupo": group.name, "id_awb": ident,
                                      "nomes_internos": item.names, "amostras": item.samples,
                                      "taxa": item.rate, "duracao_segundos": item.duration, **files})
                        processed += 1
                    archive.writestr("INDICE_DESTA_PARTE.jsonl", "\n".join(json.dumps(row, ensure_ascii=False) for row in index) + "\n")
                    archive.writestr("LEIA_ME.txt", f"Grupo: {group.name}\nBanco no CPK: {group.bank}\nÁudios: {len(group.ids)}\n"
                                      f"Formato: {EXPORT_FORMATS[audio_format]}\nMantenha os nomes e IDs para importar os áudios editados.\n"
                                      "HCA original preserva os bytes criptografados do jogo. MP3 é uma cópia para ouvir/editar.\n"
                                      "Na reimportação, use o grupo correspondente e a pasta com seus WAVs/MP3s editados.\n")
                progress(100 * processed / total, f"Conferindo {group.name}.zip…")
                # Ler até o fim de cada entrada verifica também seu CRC sem guardar o ZIP inteiro na RAM.
                with zipfile.ZipFile(temporary_zip) as archive:
                    for item in archive.infolist():
                        check_cancel(cancel)
                        with archive.open(item) as stream:
                            while stream.read(CHUNK):
                                check_cancel(cancel)
                project.archive.check_unchanged()
                output = destination / f"{group.name}.zip"
                publish_file(temporary_zip, output, cancel)
                completed.append({"grupo": group.name, "banco": group.bank, "audios": len(group.ids),
                                  "arquivo": str(output), "bytes": output.stat().st_size})
    except Cancelled as exc:
        raise Cancelled(f"Exportação cancelada. {len(completed)} ZIP(s) concluído(s) foram mantidos; o ZIP incompleto foi removido.") from exc
    progress(100, f"Exportação concluída: {len(completed)} ZIP(s).")
    return completed
