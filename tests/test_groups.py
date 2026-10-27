"""Particionamento compatível com os ZIPs antigos e exportação real."""
from pathlib import Path
import hashlib
import io
import json
import os
import threading
import wave
import zipfile

import pytest

from editor_cpk.engine import Cancelled, FormatError, Project, match_folder
from editor_cpk.groups import AudioGroup, export_groups, groups_for_project


@pytest.fixture(scope="module")
def project():
    path = os.environ.get("CPK_TEST_FILE")
    if not path:
        pytest.skip("Defina CPK_TEST_FILE para usar o arquivo real.")
    return Project(path)


def test_parts_cover_every_id_once(project):
    groups = groups_for_project(project)
    assert [(g.name, len(g.ids), g.ids[0], g.ids[-1]) for g in groups] == [
        ("00_TEAM", 3976, 0, 3975), ("10_PLAYER_1", 1074, 0, 1073),
        ("10_PLAYER_2", 15585, 1074, 16658), ("10_PLAYER_3", 20551, 16659, 37209),
        ("10_PLAYER_4", 3966, 37210, 41175), ("20_MAIN_1", 5352, 0, 5351),
        ("20_MAIN_2", 782, 5352, 6133), ("30_MAIN", 3269, 0, 3268), ("40_MAIN", 278, 0, 277)]
    assigned = [(g.bank, ident) for g in groups for ident in g.ids]
    assert len(assigned) == len(set(assigned)) == 54833
    for bank in project.bank_names:
        expected = set(project.bank(bank).awb.ids)
        assert {ident for name, ident in assigned if name == bank} == expected


@pytest.mark.parametrize("audio_format", ["hca", "wav", "mp3", "mp3_hca"])
def test_export_real_audio_and_reimport_names(project, tmp_path, audio_format):
    group = AudioGroup("00_TEAM", "00_TEAM", (0, 1))
    reports = export_groups(project, [group], tmp_path, audio_format)
    assert len(reports) == 1 and reports[0]["audios"] == 2
    output = tmp_path / "00_TEAM.zip"
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        records = [json.loads(line) for line in z.read("INDICE_DESTA_PARTE.jsonl").splitlines()]
        assert [r["id_awb"] for r in records] == [0, 1]
        for record in records:
            if "hca" in record:
                assert hashlib.sha256(z.read(record["hca"])).digest() == hashlib.sha256(project.bank("00_TEAM").awb.audio(record["id_awb"])).digest()
            if "wav" in record:
                with wave.open(io.BytesIO(z.read(record["wav"])), "rb") as wav:
                    assert wav.getnframes() == record["amostras"]
            if "mp3" in record:
                assert len(z.read(record["mp3"])) > 1000
        z.extractall(tmp_path / "reimport")
    if audio_format != "hca":
        matched = match_folder(project, "00_TEAM", tmp_path / "reimport")
        assert {r.audio_id for r in matched if r.status == "Pronto"} == {0, 1}
    before = output.read_bytes()
    with pytest.raises(FormatError, match="já existe"):
        export_groups(project, [group], tmp_path, audio_format)
    assert output.read_bytes() == before


def test_export_cancel_keeps_finished_and_removes_partial(project, tmp_path):
    cancel = threading.Event()
    groups = [AudioGroup("00_TEAM_a", "00_TEAM", (0,)), AudioGroup("00_TEAM_b", "00_TEAM", (1, 2))]
    def progress(percent, message):
        if "00_TEAM_b: 1/2" in message:
            cancel.set()
    with pytest.raises(Cancelled):
        export_groups(project, groups, tmp_path, "hca", cancel=cancel, progress=progress)
    assert (tmp_path / "00_TEAM_a.zip").is_file()
    assert not (tmp_path / "00_TEAM_b.zip").exists()
    assert not list(tmp_path.glob("cpk_export_*"))


def test_part_folder_indicates_underlying_bank(project, tmp_path):
    path = tmp_path / "10_PLAYER_1"
    path.mkdir()
    (path / "ID000000.wav").touch()
    assert match_folder(project, "10_PLAYER", path)[0].status == "Pronto"
    assert "Banco diferente" in match_folder(project, "00_TEAM", path)[0].status
