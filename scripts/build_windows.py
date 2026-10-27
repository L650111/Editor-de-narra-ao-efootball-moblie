"""Compila, verifica e empacota a versão portátil para Windows x64."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from editor_cpk import __version__


def build():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Execute este script com Python de 64 bits no Windows.")
    os.chdir(ROOT)
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    executable = ROOT / "dist" / "EditorCPKAudio.exe"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", "EditorCPKAudio", "--onefile", "--windowed",
        "--collect-all", "cricodecs", "--collect-all", "imageio_ffmpeg",
        "--copy-metadata", "cricodecs", "--copy-metadata", "imageio-ffmpeg",
        "--add-data", f"{ROOT / 'licencas'}{os.pathsep}licencas",
        "--add-data", f"{ROOT / 'LICENSE'}{os.pathsep}.",
        "--add-data", f"{ROOT / 'LICENCAS_TERCEIROS.md'}{os.pathsep}.",
        "iniciar.py",
    ], check=True)
    # O executável precisa funcionar fora do código-fonte e sem FFmpeg no PATH.
    with tempfile.TemporaryDirectory(prefix="Editor CPK áç ") as temporary:
        directory = Path(temporary)
        isolated_exe = directory / executable.name
        shutil.copy2(executable, isolated_exe)
        report_path = directory / "verificacao.json"
        environment = os.environ.copy()
        environment["PATH"] = ""
        for key in ("PYTHONHOME", "PYTHONPATH", "IMAGEIO_FFMPEG_EXE"):
            environment.pop(key, None)
        result = subprocess.run([str(isolated_exe), "--autoteste", str(report_path)],
                                cwd=directory, env=environment, timeout=180)
        if not report_path.is_file():
            raise RuntimeError(f"O executável não produziu o relatório (código {result.returncode}).")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if result.returncode or report.get("resultado") != "aprovado":
            raise RuntimeError("A verificação do executável Windows falhou.")
        report["python_compilacao"] = platform.python_version()
        report["commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        report["dependencias"] = {
            name: importlib.metadata.version(name)
            for name in ("cricodecs", "imageio-ffmpeg", "pyinstaller")
        }
        (release / "VERIFICACAO_WINDOWS.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="cpk_windows_package_") as temporary:
        package = Path(temporary) / "EditorCPKAudio-Windows-x64"
        package.mkdir()
        shutil.copy2(executable, package / executable.name)
        for name in ("README.md", "LEIA_PRIMEIRO_WINDOWS.txt", "LICENSE", "LICENCAS_TERCEIROS.md"):
            shutil.copy2(ROOT / name, package / name)
        shutil.copytree(ROOT / "licencas", package / "licencas")
        # Inclui também as licenças das versões efetivamente instaladas no Windows.
        for name in ("cricodecs", "imageio-ffmpeg", "pyinstaller"):
            distribution = importlib.metadata.distribution(name)
            for item in distribution.files or ():
                if item.name.lower().startswith(("license", "copying", "notice")):
                    original = Path(distribution.locate_file(item))
                    if original.is_file():
                        destination = package / "licencas" / name / Path(*item.parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(original, destination)
        shutil.copy2(release / "VERIFICACAO_WINDOWS.json", package / "VERIFICACAO_WINDOWS.json")
        with zipfile.ZipFile(release / "EditorCPKAudio-Windows-x64.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package.parent))
    shutil.copy2(executable, release / executable.name)
    assets = [release / name for name in (
        "EditorCPKAudio.exe", "EditorCPKAudio-Windows-x64.zip", "VERIFICACAO_WINDOWS.json")]
    (release / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()}  {path.name}\n"
        for path in assets
    ), encoding="utf-8")
    notes = f"""Editor de Áudio CPK {__version__} — Windows x64

Baixe **EditorCPKAudio-Windows-x64.zip**, extraia e abra **EditorCPKAudio.exe**.
O arquivo **EditorCPKAudio.exe** também está disponível como download separado.
Não é necessário instalar Python, CriCodecs ou FFmpeg.

Compatível com Windows 10/11 de 64 bits. O CPK original e os áudios do jogo não estão incluídos.

O executável foi testado no Windows, fora do código-fonte, em uma pasta com espaços e acentos,
com PATH vazio: abertura da interface Tkinter, conversão FFmpeg e codificação, criptografia e
decodificação HCA de um sinal conhecido. Consulte **VERIFICACAO_WINDOWS.json** e **SHA256SUMS.txt**.
O funcionamento do CPK modificado dentro do jogo ainda depende de teste no próprio jogo.
"""
    (release / "NOTAS_RELEASE.md").write_text(notes, encoding="utf-8")
    print(f"Pacote Windows {__version__} pronto em {release}")


if __name__ == "__main__":
    build()
