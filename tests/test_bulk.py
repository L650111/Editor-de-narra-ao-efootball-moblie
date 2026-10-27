from pathlib import Path
import os
import threading

import pytest

from editor_cpk import engine
from editor_cpk.bulk import same_audio_replacements
from editor_cpk.engine import Cancelled, FormatError, Project, Replacement, decoded_wav, generate
from test_real_cpk import tone, pcm, assert_tone


@pytest.fixture(scope="module")
def project():
    path = os.environ.get("CPK_TEST_FILE")
    if not path:
        pytest.skip("Defina CPK_TEST_FILE para o teste com o arquivo real.")
    return Project(path)


def test_chosen_file_applies_to_all_or_one_group(project, tmp_path):
    audio = tone(tmp_path / "minha_escolha.wav", .18)
    all_changes = same_audio_replacements(project, audio)
    assert len(all_changes) == 54833
    assert len({(c.bank, c.audio_id) for c in all_changes}) == 54833
    assert {c.path for c in all_changes} == {audio.resolve()}
    group = same_audio_replacements(project, audio, "10_PLAYER_4")
    assert len(group) == 3966
    assert group[0].audio_id == 37210 and group[-1].audio_id == 41175
    with pytest.raises(FormatError):
        same_audio_replacements(project, audio, "inexistente")
    cancel = threading.Event(); cancel.set()
    with pytest.raises(Cancelled):
        same_audio_replacements(project, audio, cancel=cancel)


def test_one_audio_replaces_every_real_entry(project, tmp_path, monkeypatch):
    audio = tone(tmp_path / "minha_gravacao.wav", .18)
    calls = []
    prepare = engine.prepare_pcm
    def count_preparations(*args, **kwargs):
        calls.append(args[0])
        return prepare(*args, **kwargs)
    monkeypatch.setattr(engine, "prepare_pcm", count_preparations)
    output = tmp_path / "todos.cpk"
    report = generate(project, same_audio_replacements(project, audio), output, keep_duration=False)
    assert len(report["substituicoes"]) == 54833
    assert report["codificacoes_hca"] == 1
    assert calls == [audio.resolve()]
    assert len({c["sha256_hca"] for c in report["substituicoes"]}) == 1
    new = Project(output)
    for name in new.bank_names:
        bank = new.bank(name)
        assert {item.samples for item in bank.audios.values()} == {8640}
        for ident in (bank.awb.ids[0], bank.awb.ids[len(bank.awb.ids)//2], bank.awb.ids[-1]):
            assert_tone(pcm(decoded_wav(bank, ident, engine.DEFAULT_KEY)))
    assert report["validacao_estrutural"] == "aprovada"


def test_same_file_preserves_each_original_duration(project, tmp_path, monkeypatch):
    audio = tone(tmp_path / "repetir.wav", 1.37)
    calls = []
    prepare = engine.prepare_pcm
    def count_preparations(*args, **kwargs):
        calls.append(args[0])
        return prepare(*args, **kwargs)
    monkeypatch.setattr(engine, "prepare_pcm", count_preparations)
    changes = [Replacement("00_TEAM", 0, audio), Replacement("00_TEAM", 1, audio), Replacement("10_PLAYER", 0, audio)]
    output = tmp_path / "duracoes.cpk"
    report = generate(project, changes, output, keep_duration=True)
    assert len(calls) == 1
    new = Project(output)
    for change in changes:
        item = new.bank(change.bank).audios[change.audio_id]
        assert item.samples == project.bank(change.bank).audios[change.audio_id].samples
        values = pcm(decoded_wav(new.bank(change.bank), change.audio_id, engine.DEFAULT_KEY))
        assert_tone(values)
        if item.duration > 1.5:
            assert max(abs(v) for v in values[-3000:]) < 5


def test_changing_input_during_generation_is_rejected(project, tmp_path):
    audio = tone(tmp_path / "mudando.wav", .25)
    output = tmp_path / "nao_finalizar.cpk"
    def progress(percent, message):
        if percent > 3 and message.startswith("Convertendo"):
            stat = audio.stat()
            os.utime(audio, ns=(stat.st_atime_ns, stat.st_mtime_ns+1_000_000))
    with pytest.raises(FormatError, match="entrada mudou"):
        generate(project, [Replacement("00_TEAM", 0, audio), Replacement("00_TEAM", 1, audio)], output, progress=progress)
    assert not output.exists()
    assert not list(tmp_path.glob("editor_cpk_*"))
