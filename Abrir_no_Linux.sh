#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
if [[ -f programa_linux/EditorCPKAudio ]]; then
    chmod u+x programa_linux/EditorCPKAudio
    for CONVERTER in programa_linux/_internal/imageio_ffmpeg/binaries/ffmpeg-*; do
        if [[ -f "$CONVERTER" ]]; then chmod u+x "$CONVERTER"; fi
    done
    exec programa_linux/EditorCPKAudio "$@"
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Instale Python 3.12 para usar o código-fonte."
    exit 1
fi
if ! python3 -c 'import tkinter' 2>/dev/null; then
    echo "Instale o Tkinter e o suporte a ambientes virtuais:"
    echo "sudo apt install python3-tk python3-venv"
    exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv || {
        echo "Instale o suporte: sudo apt install python3-venv"
        exit 1
    }
fi
if ! .venv/bin/python -c 'import cricodecs, imageio_ffmpeg' 2>/dev/null; then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python iniciar.py "$@"
