"""Interface de terminal: listar, exportar WAV e gerar CPK com mapa JSON."""
from pathlib import Path
import argparse
import json
import sys

from .engine import DEFAULT_KEY, Project, Replacement, decoded_wav, generate, parse_key
from .groups import EXPORT_FORMATS, export_groups, groups_for_project
from .bulk import same_audio_replacements


def main():
    parser = argparse.ArgumentParser(description="Editor de Áudio CPK — modo de terminal")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("listar", help="Listar bancos ou áudios de um banco")
    listing.add_argument("cpk", type=Path)
    listing.add_argument("--banco")
    listing.add_argument("--busca", default="")
    listing.add_argument("--grupo", help="Mostrar somente uma parte, como 10_PLAYER_2")
    groups_cmd = sub.add_parser("grupos", help="Listar as partes com contagens e IDs")
    groups_cmd.add_argument("cpk", type=Path)
    zips = sub.add_parser("exportar-zips", help="Exportar uma parte ou todas como ZIPs independentes")
    zips.add_argument("cpk", type=Path)
    zips.add_argument("pasta", type=Path)
    zips.add_argument("--grupo", default="todos")
    zips.add_argument("--formato", choices=list(EXPORT_FORMATS), default="mp3_hca")
    zips.add_argument("--chave", default=str(DEFAULT_KEY))
    export = sub.add_parser("exportar", help="Exportar um HCA como WAV")
    export.add_argument("cpk", type=Path)
    export.add_argument("banco")
    export.add_argument("id", type=int)
    export.add_argument("saida", type=Path)
    export.add_argument("--chave", default=str(DEFAULT_KEY))
    build = sub.add_parser("gerar", help="Gerar CPK usando uma lista JSON salva na interface")
    build.add_argument("cpk", type=Path)
    build.add_argument("mapa", type=Path)
    build.add_argument("saida", type=Path)
    build.add_argument("--chave", default=None)
    build.add_argument("--nova-duracao", action="store_true", help="Usar a duração dos áudios substitutos")
    repeat = sub.add_parser("repetir-audio", help="Repetir um áudio escolhido em todas as falas ou em um grupo")
    repeat.add_argument("cpk", type=Path)
    repeat.add_argument("audio", type=Path)
    repeat.add_argument("saida", type=Path)
    repeat.add_argument("--grupo", default=None)
    repeat.add_argument("--nova-duracao", action="store_true")
    repeat.add_argument("--chave", default=str(DEFAULT_KEY))
    args = parser.parse_args()
    try:
        project = Project(args.cpk)
        if args.command == "repetir-audio":
            changes = same_audio_replacements(project, args.audio, args.grupo)
            report = generate(project, changes, args.saida, parse_key(args.chave), not args.nova_duracao,
                              progress=lambda p, m: print(f"{p:5.1f}% {m}", flush=True))
            print(f"Concluído: {len(changes)} falas; {report['codificacoes_hca']} codificações HCA necessárias.")
        elif args.command == "grupos":
            for group in groups_for_project(project):
                print(f"{group.name}.zip\t{len(group.ids)} áudios\tIDs {group.ids[0]}–{group.ids[-1]}")
        elif args.command == "exportar-zips":
            groups = groups_for_project(project)
            if args.grupo != "todos":
                groups = [group for group in groups if group.name == args.grupo]
                if not groups:
                    raise ValueError(f"Grupo inexistente: {args.grupo}")
            results = export_groups(project, groups, args.pasta, args.formato, parse_key(args.chave),
                                    progress=lambda p, m: print(f"{p:5.1f}% {m}", flush=True))
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.command == "listar":
            if args.grupo:
                groups = {group.name: group for group in groups_for_project(project)}
                if args.grupo not in groups:
                    raise ValueError(f"Grupo inexistente: {args.grupo}")
                group = groups[args.grupo]
                bank = project.bank(group.bank)
                for ident in group.ids:
                    item = bank.audios[ident]
                    if args.busca.casefold() in f"{item.id} {item.name}".casefold():
                        print(f"ID{item.id:06d}\t{item.duration:.3f}s\t{item.name}")
                return
            if not args.banco:
                for name in project.bank_names:
                    print(f"{name}\t{len(project.bank(name).audios)} áudios")
            else:
                for item in project.bank(args.banco).audios.values():
                    if args.busca.casefold() in f"{item.id} {item.name}".casefold():
                        print(f"ID{item.id:06d}\t{item.duration:.3f}s\t{item.name}")
        elif args.command == "exportar":
            raw = decoded_wav(project.bank(args.banco), args.id, parse_key(args.chave))
            with args.saida.open("xb") as f:
                f.write(raw)
            print(f"WAV exportado: {args.saida}")
        else:
            data = json.loads(args.mapa.read_text(encoding="utf-8"))
            replacements = []
            for row in data["substituicoes"]:
                path = Path(row["arquivo"])
                if not path.is_absolute():
                    path = args.mapa.resolve().parent / path
                replacements.append(Replacement(row["banco"], int(row["id"]), path))
            keep = False if args.nova_duracao else data.get("manter_duracao", True)
            report = generate(project, replacements, args.saida, parse_key(args.chave or data.get("chave", DEFAULT_KEY)), keep,
                              progress=lambda p, m: print(f"{p:5.1f}% {m}", flush=True))
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("Cancelado. O arquivo original foi preservado.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
