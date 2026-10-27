"""Associação explícita de um áudio escolhido a um grupo ou ao CPK inteiro."""
from pathlib import Path

from .engine import AUDIO_EXTENSIONS, FormatError, Replacement, check_cancel
from .groups import groups_for_project


def same_audio_replacements(project, path: Path, group_name: str | None = None, cancel=None) -> list[Replacement]:
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise FormatError("Escolha um arquivo de áudio válido, como WAV ou MP3.")
    groups = groups_for_project(project)
    if group_name is not None:
        groups = [group for group in groups if group.name == group_name]
        if not groups:
            raise FormatError(f"Grupo inexistente: {group_name}.")
    result = []
    for group in groups:
        for ident in group.ids:
            check_cancel(cancel)
            result.append(Replacement(group.bank, ident, path))
    return result
