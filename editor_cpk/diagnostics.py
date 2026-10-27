"""Verifica o pacote distribuído sem precisar dos arquivos do jogo."""
from pathlib import Path
import io
import json
import math
import os
import struct
import sys
import tempfile
import traceback
import wave

from . import __version__
from .engine import DEFAULT_KEY, codec, ffmpeg_executable, prepare_pcm, wave_samples


def verify_installation(report_path: str) -> int:
    report = {"versao": __version__, "plataforma": sys.platform,
              "executavel": bool(getattr(sys, "frozen", False)), "testes": {}}
    try:
        ffmpeg = Path(ffmpeg_executable()).resolve()
        if report["executavel"] and not ffmpeg.is_relative_to(Path(sys._MEIPASS).resolve()):
            raise RuntimeError("O FFmpeg não está sendo carregado do próprio pacote.")
        report["ffmpeg"] = ffmpeg.name
        with tempfile.TemporaryDirectory(prefix="cpk_autoteste_") as temporary:
            directory = Path(temporary)
            source, converted = directory / "entrada.wav", directory / "convertido.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
                wav.writeframes(b"".join(
                    struct.pack("<hh", value, value)
                    for i in range(11025)
                    for value in (round(15000 * math.sin(2 * math.pi * 440 * i / 44100)),)
                ))
            prepare_pcm(source, converted)
            raw = converted.read_bytes()
            if wave_samples(raw) != (12000, 48000, 1):
                raise RuntimeError("A conversão para PCM mono/48 kHz falhou.")
            report["testes"]["conversao_ffmpeg"] = "aprovado"

            hca = codec()
            config = hca.HcaEncodeConfig()
            config.sample_rate, config.channel_count = 48000, 1
            config.version, config.bitrate = 0x0200, 96000
            config.quality = hca.HcaQuality.HIGH
            encoded = hca.encrypt(hca.encode(raw, config), cipher_type=56,
                                  keycode=DEFAULT_KEY, subkey=0)
            decoded = hca.decode(encoded, keycode=DEFAULT_KEY, subkey=0)
            if wave_samples(decoded) != (12000, 48000, 1):
                raise RuntimeError("A codificação/decodificação HCA alterou o formato.")
            with wave.open(io.BytesIO(decoded), "rb") as wav:
                values = [v[0] for v in struct.iter_unpack("<h", wav.readframes(12000))][1000:10000]
            frequency = sum(a <= 0 < b for a, b in zip(values, values[1:])) * 48000 / len(values)
            rms = math.sqrt(sum(v * v for v in values) / len(values))
            if not 432 <= frequency <= 448 or not 8000 < rms < 14000:
                raise RuntimeError("O conteúdo do áudio não sobreviveu ao teste HCA.")
            report["testes"]["hca_codificar_criptografar_decodificar"] = "aprovado"

        from .gui import App
        app = App()
        try:
            app.update()
            if not app.winfo_exists() or __version__ not in app.title():
                raise RuntimeError("A janela principal não abriu corretamente.")
            report["tk"] = str(app.tk.call("info", "patchlevel"))
            report["testes"]["interface_tkinter"] = "aprovado"
        finally:
            app._close()
        report["resultado"] = "aprovado"
        status = 0
    except Exception:
        report["resultado"] = "falhou"
        report["erro"] = traceback.format_exc()
        status = 1
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return status
