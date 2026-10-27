"""Teste da interface com janela real; exige DISPLAY em Linux.

python tests/gui_smoke.py --cpk /caminho/original.cpk [--captura imagem.png]
"""
from pathlib import Path
import argparse
import json
import math
import struct
import tempfile
import time
import wave
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor_cpk.gui import App, filedialog, messagebox


def run(cpk, screenshot=None):
    errors, notices = [], []
    messagebox.showerror = lambda title, text, **kw: errors.append(text)
    messagebox.showinfo = lambda title, text, **kw: notices.append(text)
    messagebox.askyesno = lambda *a, **kw: True
    app = App()
    def wait():
        deadline = time.monotonic() + 60
        while app.busy and time.monotonic() < deadline:
            app.update()
            time.sleep(.015)
        app.update()
        assert not app.busy, "A interface não terminou a tarefa."
        assert not errors, errors
    def search(text):
        app.search_var.set(text)
        if app.search_after:
            app.after_cancel(app.search_after)
            app.search_after = None
        app.refresh_audio()
        app.update()
    with tempfile.TemporaryDirectory(prefix="cpk_gui_test_") as folder:
        folder = Path(folder)
        audio = folder / "voice.wav"
        with wave.open(str(audio), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(b"".join(struct.pack("<h", round(15000 * math.sin(2*math.pi*440*i/48000))) for i in range(24000)))
        try:
            app.open_cpk(cpk)
            wait()
            assert app.bank.name == "00_TEAM"
            assert len(app.groups) == 9
            assert len(app.group.ids) == 3976
            filedialog.askopenfilename = lambda **kw: str(audio)
            app.repeat_audio()
            bulk_dialog = next(w for w in app.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Repetir um áudio escolhido")
            def bulk_descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from bulk_descendants(child)
            next(w for w in bulk_descendants(bulk_dialog) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Escolher áudio…").invoke()
            app.update()
            apply_button = next(w for w in bulk_descendants(bulk_dialog) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Aplicar à lista")
            assert apply_button.winfo_rooty() + apply_button.winfo_height() <= bulk_dialog.winfo_rooty() + bulk_dialog.winfo_height()
            if screenshot:
                from PIL import ImageGrab
                ImageGrab.grab(xdisplay=app.winfo_screen()).save(str(Path(screenshot).with_name("escolher_audio_1_2.png")))
            next(w for w in bulk_descendants(bulk_dialog) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Aplicar à lista").invoke()
            wait()
            assert len(app.replacements) == 54833
            assert len(app.queue_tree.get_children()) == 54833
            assert {c.path for c in app.replacements.values()} == {audio.resolve()}
            app.clear_queue()
            assert not app.replacements
            search("ID000000")
            assert app.audio_tree.get_children() == ("0",)
            app.audio_tree.selection_set("0")
            filedialog.askopenfilename = lambda **kw: str(audio)
            app.add_audio()
            assert len(app.replacements) == 1
            exported = folder / "original.wav"
            search("ID000000")
            app.audio_tree.selection_set("0")
            filedialog.asksaveasfilename = lambda **kw: str(exported)
            app.export_wav()
            wait()
            assert exported.read_bytes()[:4] == b"RIFF"
            saved = folder / "map.json"
            filedialog.asksaveasfilename = lambda **kw: str(saved)
            app.save_project()
            app.queue_tree.selection_set("00_TEAM:0")
            app.remove_audio()
            assert not app.replacements
            filedialog.askopenfilename = lambda **kw: str(saved)
            app.load_project()
            wait()
            assert len(app.replacements) == 1
            app.bank_var.set("10_PLAYER_4")
            app.change_bank()
            wait()
            search("ID041175")
            assert app.audio_tree.get_children() == ("41175",)
            assert app.group.name == "10_PLAYER_4"
            search("ID000000")
            assert not app.audio_tree.get_children()
            app.bank_var.set("00_TEAM")
            app.change_bank()
            wait()
            imports = folder / "importar"
            imports.mkdir()
            (imports / "ID000002__BR_A1_T0_F0104.wav").write_bytes(audio.read_bytes())
            filedialog.askdirectory = lambda **kw: str(imports)
            app.import_folder()
            wait()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            accept = next(w for w in descendants(app) if w.winfo_class() == "TButton" and str(w.cget("text")).startswith("Adicionar 1"))
            accept.invoke()
            assert len(app.replacements) == 2
            app.bank_var.set("40_MAIN")
            app.change_bank()
            wait()
            zip_folder = folder / "zips"
            zip_folder.mkdir()
            filedialog.askdirectory = lambda **kw: str(zip_folder)
            app.export_zips()
            export_dialog = next(w for w in app.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Exportar grupos em ZIPs")
            for widget in descendants(export_dialog):
                if widget.winfo_class() == "TCombobox" and "HCA original" in widget.cget("values"):
                    widget.set("HCA original")
            next(w for w in descendants(export_dialog) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Escolher pasta…").invoke()
            next(w for w in descendants(export_dialog) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Exportar ZIPs").invoke()
            wait()
            import zipfile
            with zipfile.ZipFile(zip_folder / "40_MAIN.zip") as archive:
                assert sum(name.endswith(".hca") for name in archive.namelist()) == 278
                assert archive.testzip() is None
            app.bank_var.set("00_TEAM")
            app.change_bank()
            wait()
            if screenshot:
                from PIL import ImageGrab
                app.update()
                ImageGrab.grab(xdisplay=app.winfo_screen()).save(screenshot)
            output = folder / "result.cpk"
            app.output_var.set(str(output))
            app.build()
            wait()
            assert output.is_file()
            report = json.loads(output.with_suffix(".relatorio.json").read_text())
            assert len(report["substituicoes"]) == 2
            assert "Concluído" in app.status_var.get()
            print("GUI OK: 9 grupos, filtros por parte, buscar, associar, exportar WAV/ZIP, salvar/carregar lista, importar com revisão e gerar CPK.")
        finally:
            app.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpk", required=True)
    parser.add_argument("--captura")
    args = parser.parse_args()
    run(args.cpk, args.captura)
