"""Testes de integração opcionais: CPK_TEST_FILE=/caminho/original.cpk pytest -q.

O CPK e os áudios de teste não são distribuídos no projeto.
"""
from array import array
from pathlib import Path
import hashlib
import io
import math
import os
import struct
import threading
import wave

import pytest

from editor_cpk.engine import (Cancelled, DEFAULT_KEY, FormatError, Project, Replacement,
                               decoded_wav, generate, match_folder, parse_key)

EXPECTED_SHA = "053c5f60f74b10c4e86b8fb206d926fa712927bfd932e4e113e8bd04a560a636"


@pytest.fixture(scope="module")
def original():
    path = os.environ.get("CPK_TEST_FILE")
    if not path:
        pytest.skip("Defina CPK_TEST_FILE com o CPK original para executar a integração real.")
    project = Project(path)
    assert hashlib.file_digest(project.archive.path.open("rb"), "sha256").hexdigest() == EXPECTED_SHA
    return project


def tone(path, duration, rate=44100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = bytearray()
        for i in range(round(rate * duration)):
            value = round(15000 * math.sin(2 * math.pi * 440 * i / rate))
            data.extend(struct.pack("<hh", value, value))
        w.writeframes(data)
    return path


def pcm(raw):
    with wave.open(io.BytesIO(raw), "rb") as w:
        assert w.getframerate() == 48000
        assert w.getnchannels() == 1
        values = array("h", w.readframes(w.getnframes()))
    if os.sys.byteorder != "little":
        values.byteswap()
    return values


def assert_tone(values):
    # Conteúdo acústico, além do cabeçalho: o sinal recuperado deve ter 440 Hz.
    section = values[1000:10000]
    crossings = sum(a <= 0 < b for a, b in zip(section, section[1:]))
    frequency = crossings * 48000 / len(section)
    assert 432 <= frequency <= 448
    rms = math.sqrt(sum(x*x for x in section) / len(section))
    assert 8000 < rms < 14000


def test_key_input():
    assert parse_key("0xD77A01") == parse_key("14121473") == DEFAULT_KEY
    for invalid in ("x", "-1", str(2**64)):
        with pytest.raises(FormatError):
            parse_key(invalid)


def test_real_bank_counts(original):
    counts = {n: len(original.bank(n).audios) for n in original.bank_names}
    assert counts == {"00_TEAM": 3976, "10_PLAYER": 41176, "20_MAIN": 6134, "30_MAIN": 3269, "40_MAIN": 278}
    assert sum(counts.values()) == 54833


def test_invalid_targets_and_duplicate_ids(original, tmp_path):
    audio = tone(tmp_path / "tone.wav", .25)
    change = Replacement("00_TEAM", 0, audio)
    with pytest.raises(FormatError, match="arquivo novo"):
        generate(original, [change], original.archive.path)
    existing = tmp_path / "existing.cpk"
    existing.write_bytes(b"preservar")
    with pytest.raises(FormatError):
        generate(original, [change], existing)
    assert existing.read_bytes() == b"preservar"
    with pytest.raises(FormatError, match="duplicados"):
        generate(original, [change, change], tmp_path / "duplicate.cpk")
    with pytest.raises(FormatError, match="pelo menos"):
        generate(original, [], tmp_path / "empty.cpk")


def test_folder_names_ids_and_ambiguity(original, tmp_path):
    for name in ("ID000000__BR_A1_T0_F0102.wav", "ID000000__BR_A1_T0_F0102.mp3",
                 "ID000001__OUTRO_NOME.wav", "ID999999.wav", "BR_A1_T0_F0104.wav",
                 "10_PLAYER__ID000002.wav", "desconhecido.wav"):
        (tmp_path / name).touch()
    results = {item.path.name: item for item in match_folder(original, "00_TEAM", tmp_path)}
    assert "Mais de um" in results["ID000000__BR_A1_T0_F0102.wav"].status
    assert "Mais de um" in results["ID000000__BR_A1_T0_F0102.mp3"].status
    assert "não corresponde" in results["ID000001__OUTRO_NOME.wav"].status
    assert "inexistente" in results["ID999999.wav"].status
    assert results["BR_A1_T0_F0104.wav"].audio_id == 2
    assert results["BR_A1_T0_F0104.wav"].status == "Pronto"
    assert "Banco diferente" in results["10_PLAYER__ID000002.wav"].status
    assert results["desconhecido.wav"].status == "Sem correspondência"
    foreign = tmp_path / "10_PLAYER"
    foreign.mkdir()
    (foreign / "ID000000.wav").touch()
    assert "Banco diferente" in match_folder(original, "00_TEAM", foreign)[0].status


def test_cancel_removes_temporary_files(original, tmp_path):
    audio = tone(tmp_path / "tone.wav", .25)
    change = Replacement("00_TEAM", 0, audio)
    output = tmp_path / "cancelled.cpk"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        generate(original, [change], output, cancel=cancel)
    cancel.clear()
    def progress(p, message):
        if message.startswith("Montando CPK:"):
            cancel.set()
    with pytest.raises(Cancelled):
        generate(original, [change], output, cancel=cancel, progress=progress)
    assert not output.exists()
    assert not list(tmp_path.glob("editor_cpk_*"))
    original.archive.check_unchanged()


def test_bad_audio_has_no_output(original, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"nao e audio")
    output = tmp_path / "bad.cpk"
    with pytest.raises(FormatError, match="FFmpeg"):
        generate(original, [Replacement("00_TEAM", 0, bad)], output)
    assert not output.exists()
    assert not list(tmp_path.glob("editor_cpk_*"))


def test_replace_all_five_banks_new_duration(original, tmp_path):
    audio = tone(tmp_path / "new.wav", 1.37)
    changes = [Replacement(n, original.bank(n).awb.ids[-1], audio) for n in original.bank_names]
    output = tmp_path / "five_banks.cpk"
    percentages = []
    report = generate(original, changes, output, keep_duration=False, progress=lambda p, m: percentages.append(p))
    assert percentages == sorted(percentages)
    assert report["validacao_estrutural"] == "aprovada"
    assert len(report["substituicoes"]) == 5
    rebuilt = Project(output)
    for change in changes:
        bank = rebuilt.bank(change.bank)
        assert bank.audios[change.audio_id].samples == 65760
        assert_tone(pcm(decoded_wav(bank, change.audio_id, DEFAULT_KEY)))
    # Leitor independente do empacotamento, fornecido pelo CriCodecs.
    from cricodecs import awb
    entry = rebuilt.archive.by_name["bra/sound/awb/40_MAIN.awb"]
    independent = awb.load(rebuilt.archive.read(entry))
    own_awb = rebuilt.bank("40_MAIN").awb
    assert independent.file_count == own_awb.count
    assert independent.alignment == own_awb.alignment
    for independent_entry, ident, (start, size) in zip(independent.entries, own_awb.ids, own_awb.spans):
        assert independent_entry.wave_id == ident
        assert independent_entry.offset == start - own_awb.base
        assert independent_entry.size == size
    assert report["sha256_original"] == EXPECTED_SHA


def test_keep_duration_cuts_and_pads(original, tmp_path):
    long_audio = tone(tmp_path / "long.wav", 1.37)
    short_audio = tone(tmp_path / "short.wav", .25)
    output = tmp_path / "fit.cpk"
    generate(original, [Replacement("00_TEAM", 0, long_audio), Replacement("00_TEAM", 1, short_audio)], output, keep_duration=True)
    bank = Project(output).bank("00_TEAM")
    for ident in (0, 1):
        assert bank.audios[ident].samples == original.bank("00_TEAM").audios[ident].samples
    assert_tone(pcm(decoded_wav(bank, 0, DEFAULT_KEY)))
    short = pcm(decoded_wav(bank, 1, DEFAULT_KEY))
    assert_tone(short)
    tail = short[-10000:]
    assert math.sqrt(sum(v*v for v in tail) / len(tail)) < 5
