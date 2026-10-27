"""Interface Tkinter. Trabalho de disco/codec fica fora da thread gráfica."""
from __future__ import annotations

from pathlib import Path
import datetime
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .engine import (AUDIO_EXTENSIONS, DEFAULT_KEY, Cancelled, FormatError, Project,
                     Replacement, decoded_wav, generate, match_folder, parse_key)
from .groups import EXPORT_FORMATS, export_groups, groups_for_project
from .bulk import same_audio_replacements

BG, PANEL, INPUT, FG, MUTED, ACCENT = "#101823", "#192535", "#233347", "#eaf0f7", "#a2b1c3", "#4ad5ba"
AUDIO_FILTER = [("Áudios", " ".join("*" + s for s in sorted(AUDIO_EXTENSIONS))), ("Todos os arquivos", "*")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Editor de Áudio CPK · {__version__}")
        self.geometry("1240x850")
        self.minsize(1020, 740)
        self.configure(bg=BG)
        self.project: Project | None = None
        self.bank = None
        self.group = None
        self.groups = {}
        self.audio_groups = {}
        self.replacements: dict[tuple[str, int], Replacement] = {}
        self.busy = False
        self.messages = queue.Queue()
        self.cancel_event = threading.Event()
        self.done_callback = None
        self.controls = []
        self.readonly_controls = []
        self.preview_dir = tempfile.TemporaryDirectory(prefix="cpk_preview_")
        self.original_var = tk.StringVar()
        self.bank_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.key_var = tk.StringVar(value=str(DEFAULT_KEY))
        self.output_var = tk.StringVar()
        self.duration_var = tk.StringVar(value="Manter a duração original")
        self.status_var = tk.StringVar(value="Abra o CPK original para começar.")
        self.count_var = tk.StringVar(value="Nenhum banco carregado")
        self.queue_var = tk.StringVar(value="0 substituições")
        self.selection_var = tk.StringVar(value="Selecione uma fala para associar seu novo áudio.")
        self._style()
        self._layout()
        self.search_after = None
        self.search_var.trace_add("write", self._search_changed)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._drain)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        font = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        style.configure(".", font=(font, 10))
        self.option_add("*TCombobox*Listbox.background", INPUT)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", "#315b68")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(font, 9))
        style.configure("Title.TLabel", font=(font, 24, "bold"))
        style.configure("Section.TLabel", font=(font, 11, "bold"))
        style.configure("TButton", background=INPUT, foreground=FG, borderwidth=0, padding=(12, 8))
        style.map("TButton", background=[("active", "#354c62"), ("disabled", "#1d2939")], foreground=[("disabled", "#63758a")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#092b26", font=(font, 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#77e8d1"), ("disabled", "#284b48")], foreground=[("disabled", "#9aa9ab")])
        style.configure("TEntry", fieldbackground=INPUT, foreground=FG, insertcolor=FG, padding=7, borderwidth=0)
        style.map("TEntry", fieldbackground=[("disabled", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("TCombobox", fieldbackground=INPUT, background=INPUT, foreground=FG, arrowcolor=ACCENT, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT)], selectbackground=[("readonly", INPUT)], selectforeground=[("readonly", FG)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=29, borderwidth=0, font=(font, 9))
        style.configure("Treeview.Heading", background=INPUT, foreground=MUTED, relief="flat", padding=(6, 9), font=(font, 9, "bold"))
        style.map("Treeview", background=[("selected", "#2c555e")], foreground=[("selected", "#ffffff")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=INPUT, borderwidth=0)
        style.configure("TPanedwindow", background=BG)
        style.configure("TScrollbar", background=INPUT, troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0)

    def _button(self, parent, text, command, accent=False, **kwargs):
        b = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton", **kwargs)
        self.controls.append(b)
        return b

    def _entry(self, parent, variable, **kwargs):
        e = ttk.Entry(parent, textvariable=variable, **kwargs)
        self.controls.append(e)
        return e

    @staticmethod
    def _tree(parent, columns, sizes):
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=[key for key, title in columns], show="headings", selectmode="browse")
        for (key, title), width in zip(columns, sizes):
            tree.heading(key, text=title, anchor="w")
            tree.column(key, width=width, minwidth=55, anchor="w", stretch=key in ("name", "file"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return frame, tree

    def _layout(self):
        shell = ttk.Frame(self, padding=24)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        ttk.Label(header, text="Editor de Áudio CPK", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Escolha a fala, associe seu áudio e gere um novo CPK.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        source = ttk.Frame(shell)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        source.columnconfigure(0, weight=1)
        ttk.Label(source, text="1   Arquivo original", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        original_entry = ttk.Entry(source, textvariable=self.original_var, state="readonly")
        self.readonly_controls.append(original_entry)
        original_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self._button(source, "Abrir CPK…", self.choose_cpk, True).grid(row=1, column=1)
        ttk.Label(source, text="O original é preservado. A saída será salva em outro arquivo.", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(5, 0))

        tools = ttk.Frame(shell)
        tools.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tools.columnconfigure(2, weight=1)
        ttk.Label(tools, text="2   Grupo de áudios e falas", style="Section.TLabel").grid(row=0, column=0, sticky="w", columnspan=3, pady=(0, 7))
        self._button(tools, "Exportar ZIPs…", self.export_zips).grid(row=0, column=3, sticky="e", pady=(0, 7))
        self.bank_combo = ttk.Combobox(tools, textvariable=self.bank_var, state="readonly", width=16)
        self.bank_combo.grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.bank_combo.bind("<<ComboboxSelected>>", lambda e: self.change_bank())
        self.readonly_controls.append(self.bank_combo)
        ttk.Label(tools, text="Buscar nome ou ID:", style="Muted.TLabel").grid(row=1, column=1, padx=(0, 6))
        self._entry(tools, self.search_var).grid(row=1, column=2, sticky="ew")
        ttk.Label(tools, textvariable=self.count_var, style="Muted.TLabel").grid(row=1, column=3, padx=(12, 0))

        panes = ttk.Panedwindow(shell, orient="horizontal")
        panes.grid(row=3, column=0, sticky="nsew")
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        table, self.audio_tree = self._tree(left, [("id", "ID"), ("name", "Nome da fala"), ("duration", "Duração"), ("state", "Troca")], [75, 300, 83, 70])
        table.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.audio_tree.tag_configure("queued", foreground=ACCENT)
        self.audio_tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.audio_tree.bind("<Double-1>", lambda e: self.add_audio())
        ttk.Label(left, textvariable=self.selection_var, style="Muted.TLabel", wraplength=560).grid(row=1, column=0, sticky="w", pady=(8, 5))
        actions = ttk.Frame(left)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        self._button(actions, "Associar áudio…", self.add_audio, True).pack(side="left", padx=(0, 6))
        self._button(actions, "Ouvir original", self.preview).pack(side="left", padx=(0, 6))
        self._button(actions, "Exportar WAV…", self.export_wav).pack(side="left")

        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        heading = ttk.Frame(right)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(heading, text="Substituições", style="Section.TLabel").pack(side="left")
        ttk.Label(heading, textvariable=self.queue_var, style="Muted.TLabel").pack(side="right")
        row = ttk.Frame(right)
        row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._button(row, "Importar pasta…", self.import_folder).pack(side="left")
        self._button(row, "Repetir áudio…", self.repeat_audio).pack(side="left", padx=(7, 0))
        table, self.queue_tree = self._tree(right, [("bank", "Grupo"), ("id", "ID"), ("file", "Novo áudio")], [115, 65, 190])
        table.grid(row=2, column=0, sticky="nsew")
        self.queue_tree.bind("<Delete>", lambda e: self.remove_audio())
        row = ttk.Frame(right)
        row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self._button(row, "Remover", self.remove_audio).pack(side="left", padx=(0, 5))
        self._button(row, "Salvar lista…", self.save_project).pack(side="left", padx=(0, 5))
        self._button(row, "Carregar…", self.load_project).pack(side="left")
        self._button(row, "Limpar", self.clear_queue).pack(side="left", padx=(5, 0))

        target = ttk.Frame(shell)
        target.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        target.columnconfigure(0, weight=1)
        ttk.Label(target, text="3   Novo arquivo CPK", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        self._entry(target, self.output_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self._button(target, "Escolher destino…", self.choose_output).grid(row=1, column=1)
        options = ttk.Frame(target)
        options.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(options, text="Duração:", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        duration = ttk.Combobox(options, textvariable=self.duration_var, values=["Manter a duração original", "Usar a duração do novo áudio"], state="readonly", width=29)
        duration.pack(side="left", padx=(0, 18))
        self.readonly_controls.append(duration)
        ttk.Label(options, text="Chave HCA:", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        self._entry(options, self.key_var, width=19).pack(side="left")
        ttk.Label(options, text="Pré-configurada para este CPK", style="Muted.TLabel").pack(side="left", padx=8)

        footer = ttk.Frame(shell)
        footer.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", wraplength=850).grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.progress_bar = ttk.Progressbar(footer, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=(0, 14))
        row = ttk.Frame(footer)
        row.grid(row=0, column=1, rowspan=2, sticky="e")
        self.cancel_button = ttk.Button(row, text="Cancelar", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="left", padx=(0, 7))
        self._button(row, "Gerar novo CPK", self.build, True).pack(side="left")
        self.log = tk.Text(shell, height=3, bg=PANEL, fg=MUTED, relief="flat", font=("DejaVu Sans Mono", 8), padx=10, pady=7, state="disabled", wrap="word")
        self.log.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        self._log("Pronto. Comece abrindo dt510_bra_mobile_all.cpk.")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.datetime.now():%H:%M:%S}  {text}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 500:
            self.log.delete("1.0", "2.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        for widget in self.controls:
            widget.configure(state="disabled" if busy else "normal")
        for widget in self.readonly_controls:
            widget.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _job(self, job, done):
        if self.busy:
            return
        self.cancel_event.clear()
        self.last_progress_time = 0
        self.done_callback = done
        self.progress_bar["value"] = 0
        self._set_busy(True)
        def run():
            try:
                result = job()
                self.messages.put(("done", result))
            except Cancelled as exc:
                self.messages.put(("cancelled", str(exc)))
            except Exception as exc:
                self.messages.put(("error", (str(exc), traceback.format_exc())))
        threading.Thread(target=run, daemon=True).start()

    def _progress(self, percent, message):
        now = time.monotonic()
        if percent >= 100 or now - self.last_progress_time >= .1:
            self.last_progress_time = now
            self.messages.put(("progress", (percent, message)))

    def _drain(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    percent, message = payload
                    self.progress_bar["value"] = percent
                    self.status_var.set(message)
                    if message != getattr(self, "last_message", None):
                        self._log(message)
                        self.last_message = message
                elif kind == "done":
                    self._set_busy(False)
                    callback, self.done_callback = self.done_callback, None
                    try:
                        callback(payload)
                    except Exception as exc:
                        self._show_error(str(exc), traceback.format_exc())
                elif kind == "error":
                    self._set_busy(False)
                    self.done_callback = None
                    self._show_error(*payload)
                elif kind == "cancelled":
                    self._set_busy(False)
                    self.done_callback = None
                    self.status_var.set(payload)
                    self._log(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _show_error(self, text, detail=""):
        self.status_var.set("Operação interrompida. Consulte a mensagem de erro.")
        self._log(text)
        if detail:
            try:
                location = Path.home() / ".editor_cpk_audio"
                location.mkdir(exist_ok=True)
                with (location / "erros.log").open("a", encoding="utf-8") as f:
                    f.write(f"\n{datetime.datetime.now().isoformat()}\n{detail}\n")
            except OSError:
                pass
        messagebox.showerror("Editor de Áudio CPK", text, parent=self)

    def report_callback_exception(self, exc_type, value, tb):
        self._show_error(str(value), "".join(traceback.format_exception(exc_type, value, tb)))

    def choose_cpk(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Abrir CPK original", filetypes=[("Arquivo CPK", "*.cpk"), ("Todos", "*")])
        if path:
            self.open_cpk(path)

    def open_cpk(self, path):
        if self.replacements and not messagebox.askyesno("Abrir outro CPK", "A lista atual será limpa. Continuar?", parent=self):
            return
        self.status_var.set("Lendo o CPK e o primeiro banco…")
        def load():
            project = Project(path)
            groups = groups_for_project(project)
            return project, project.bank(groups[0].bank), groups
        def done(result):
            self.project, self.bank, groups = result
            self.groups = {group.name: group for group in groups}
            self.group = groups[0]
            self.audio_groups = {(group.bank, ident): group.name for group in groups for ident in group.ids}
            self.replacements.clear()
            self.original_var.set(str(self.project.archive.path))
            self.bank_combo["values"] = tuple(self.groups)
            self.bank_var.set(self.group.name)
            self.search_var.set("")
            self.output_var.set(str(self.project.archive.path.with_name(self.project.archive.path.stem + "_modificado.cpk")))
            self.refresh_audio()
            self.refresh_queue()
            self.status_var.set("CPK carregado. Selecione uma fala para substituir.")
            self._log(f"CPK aberto: {self.project.archive.path.name} · {len(groups)} grupos de áudios")
        self._job(load, done)

    def change_bank(self):
        if self.busy or not self.project:
            return
        name = self.bank_var.get()
        group = self.groups[name]
        self.status_var.set(f"Carregando {name}…")
        def done(bank):
            self.bank = bank
            self.group = group
            self.search_var.set("")
            self.refresh_audio()
            self.status_var.set(f"Grupo {group.name}: {len(group.ids)} áudios · banco {bank.name}.")
        self._job(lambda: self.project.bank(group.bank), done)

    def _search_changed(self, *args):
        if self.search_after:
            self.after_cancel(self.search_after)
        self.search_after = self.after(250, self.refresh_audio)

    def refresh_audio(self):
        self.search_after = None
        self.audio_tree.delete(*self.audio_tree.get_children())
        if not self.bank:
            return
        query = self.search_var.get().strip().casefold()
        ids = self.group.ids if self.group else self.bank.awb.ids
        items = [self.bank.audios[ident] for ident in ids]
        items = [item for item in items if not query or query in f"{item.id} ID{item.id:06d} {' '.join(item.names)}".casefold()]
        for item in items[:1500]:
            queued = (self.bank.name, item.id) in self.replacements
            self.audio_tree.insert("", "end", iid=str(item.id), values=(f"{item.id:06d}", item.name, f"{item.duration:.2f} s", "Sim" if queued else ""), tags=("queued",) if queued else ())
        shown = min(1500, len(items))
        self.count_var.set(f"{len(ids):,} áudios neste grupo".replace(",", "."))
        if len(items) > shown:
            self.selection_var.set(f"Exibindo {shown} de {len(items)} resultados. Digite para refinar a busca.")
        else:
            self.selection_var.set(f"{len(items)} resultados. Selecione uma fala para associar seu áudio.")

    def selected(self):
        if self.busy:
            return None
        selection = self.audio_tree.selection()
        if not self.bank or not selection:
            messagebox.showinfo("Selecionar fala", "Abra o CPK e selecione uma fala na lista.", parent=self)
            return None
        return self.bank.audios[int(selection[0])]

    def _selection_changed(self, event=None):
        selection = self.audio_tree.selection()
        if self.bank and selection:
            item = self.bank.audios[int(selection[0])]
            self.selection_var.set(f"{item.name} · ID{item.id:06d} · {item.duration:.3f} s")

    def refresh_queue(self):
        self.queue_tree.delete(*self.queue_tree.get_children())
        for (bank, ident), item in sorted(self.replacements.items()):
            group_name = self.audio_groups.get((bank, ident), bank)
            self.queue_tree.insert("", "end", iid=f"{bank}:{ident}", values=(group_name, f"{ident:06d}", item.path.name))
        self.queue_var.set(f"{len(self.replacements):,} substituições".replace(",", "."))

    def add_audio(self):
        item = self.selected()
        if item is None:
            return
        path = filedialog.askopenfilename(parent=self, title=f"Novo áudio para {item.name}", filetypes=AUDIO_FILTER)
        if path:
            self.replacements[self.bank.name, item.id] = Replacement(self.bank.name, item.id, Path(path).resolve())
            self.refresh_queue()
            self.refresh_audio()
            self._log(f"Associado: {self.bank.name} / ID{item.id:06d} ← {Path(path).name}")

    def remove_audio(self):
        if self.busy:
            return
        selected = self.queue_tree.selection()
        for ident in selected:
            bank, audio_id = ident.rsplit(":", 1)
            self.replacements.pop((bank, int(audio_id)), None)
        self.refresh_queue()
        self.refresh_audio()

    def import_folder(self):
        if self.busy:
            return
        if not self.project or not self.bank:
            messagebox.showinfo("Abrir CPK", "Abra o CPK original primeiro.", parent=self)
            return
        folder = filedialog.askdirectory(parent=self, title=f"Pasta com substitutos para {self.group.name}")
        if not folder:
            return
        project, bank_name = self.project, self.bank.name
        self.status_var.set("Verificando nomes e IDs da pasta…")
        self._job(lambda: match_folder(project, bank_name, Path(folder), self.cancel_event), self._review_matches)

    def clear_queue(self):
        if self.busy or not self.replacements:
            return
        if messagebox.askyesno("Limpar lista", f"Remover as {len(self.replacements)} associações da lista?", parent=self):
            self.replacements.clear()
            self.refresh_queue()
            self.refresh_audio()
            self.status_var.set("Lista de substituições limpa.")

    def repeat_audio(self):
        if self.busy:
            return
        if not self.project or not self.group:
            messagebox.showinfo("Abrir CPK", "Abra o CPK original primeiro.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Repetir um áudio escolhido")
        dialog.geometry("690x470")
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        total = sum(len(group.ids) for group in self.groups.values())
        selected = tk.StringVar()
        all_label = f"Todo o CPK ({total:,} áudios)".replace(",", ".")
        group_label = f"Somente {self.group.name} ({len(self.group.ids):,} áudios)".replace(",", ".")
        scope = tk.StringVar(value=all_label)
        duration = tk.StringVar(value=self.duration_var.get())
        ttk.Label(frame, text="Escolha o áudio que será repetido", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Você escolhe a gravação. O mesmo arquivo será associado às falas do escopo abaixo.", style="Muted.TLabel", wraplength=640).grid(row=1, column=0, sticky="w", pady=(6, 12))
        row = ttk.Frame(frame)
        row.grid(row=2, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=selected, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 7))
        def choose():
            path = filedialog.askopenfilename(parent=dialog, title="Escolher áudio para repetir", filetypes=AUDIO_FILTER)
            if path:
                selected.set(path)
        ttk.Button(row, text="Escolher áudio…", command=choose).grid(row=0, column=1)
        ttk.Label(frame, text="Aplicar em:").grid(row=3, column=0, sticky="w", pady=(12, 4))
        ttk.Combobox(frame, textvariable=scope, values=[all_label, group_label], state="readonly").grid(row=4, column=0, sticky="ew")
        ttk.Label(frame, text="Duração:").grid(row=5, column=0, sticky="w", pady=(12, 4))
        ttk.Combobox(frame, textvariable=duration, values=["Manter a duração original", "Usar a duração do novo áudio"], state="readonly").grid(row=6, column=0, sticky="ew")
        ttk.Label(frame, text="As associações desse escopo serão substituídas. Depois, clique em Gerar novo CPK.\nA opção de manter a duração corta o excesso e completa trechos curtos com silêncio.", style="Muted.TLabel", wraplength=640).grid(row=7, column=0, sticky="w", pady=(12, 10))
        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, sticky="e")
        ttk.Button(actions, text="Fechar", command=dialog.destroy).pack(side="left", padx=7)
        def apply():
            if not selected.get():
                messagebox.showinfo("Escolher áudio", "Escolha o arquivo que você quer repetir.", parent=dialog)
                return
            path, project = Path(selected.get()), self.project
            group_name = None if scope.get() == all_label else self.group.name
            chosen_duration = duration.get()
            dialog.destroy()
            def done(items):
                for item in items:
                    self.replacements[item.bank, item.audio_id] = item
                self.duration_var.set(chosen_duration)
                self.refresh_queue()
                self.refresh_audio()
                count = f"{len(items):,}".replace(",", ".")
                self.status_var.set(f"{count} falas associadas a {path.name}. Escolha o destino e gere o novo CPK.")
                self._log(f"Mesmo áudio escolhido: {path} · {len(items)} associações.")
            self._job(lambda: same_audio_replacements(project, path, group_name, self.cancel_event), done)
        ttk.Button(actions, text="Aplicar à lista", command=apply, style="Accent.TButton").pack(side="left")

    def _review_matches(self, matches):
        ids = set(self.group.ids) if self.group else set(self.bank.audios)
        for item in matches:
            if item.status == "Pronto" and item.audio_id not in ids:
                other = self.audio_groups.get((item.bank, item.audio_id), item.bank)
                item.status = f"Pertence a outro grupo: {other}"
            if (item.bank, item.audio_id) in self.replacements and item.status == "Pronto":
                item.status = "Já existe na lista; remova antes de importar"
        good = [item for item in matches if item.status == "Pronto"]
        self.status_var.set(f"Pasta analisada: {len(good)} associações válidas de {len(matches)} arquivos.")
        dialog = tk.Toplevel(self)
        dialog.title("Revisar importação da pasta")
        dialog.geometry("1080x600")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(frame, text="Confira as associações antes de adicionar", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=f"{len(good)} válidas · {len(matches)-len(good)} precisam de revisão · Grupo: {self.group.name}", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 12))
        table, tree = self._tree(frame, [("file", "Arquivo"), ("id", "ID"), ("name", "Fala original"), ("status", "Situação")], [290, 70, 270, 290])
        table.grid(row=2, column=0, sticky="nsew")
        tree.tag_configure("good", foreground=ACCENT)
        tree.tag_configure("bad", foreground="#ffb77e")
        for item in matches:
            tree.insert("", "end", values=(item.path.name, "" if item.audio_id is None else f"{item.audio_id:06d}", item.name, item.status), tags=("good" if item.status == "Pronto" else "bad",))
        row = ttk.Frame(frame)
        row.grid(row=3, column=0, sticky="e", pady=(15, 0))
        ttk.Button(row, text="Fechar", command=dialog.destroy).pack(side="left", padx=8)
        def accept():
            for item in good:
                self.replacements[item.bank, item.audio_id] = Replacement(item.bank, item.audio_id, item.path)
            self.refresh_queue()
            self.refresh_audio()
            self._log(f"Importação: {len(good)} substituições adicionadas após revisão.")
            dialog.destroy()
        ttk.Button(row, text=f"Adicionar {len(good)} associações válidas", style="Accent.TButton", command=accept, state="normal" if good else "disabled").pack(side="left")

    def export_zips(self):
        if self.busy:
            return
        if not self.project or not self.group:
            messagebox.showinfo("Abrir CPK", "Abra o CPK original primeiro.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Exportar grupos em ZIPs")
        dialog.configure(bg=BG)
        dialog.geometry("650x395")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Exportar áudios por grupo", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Cada grupo vira um ZIP independente, com nomes e IDs para reimportar.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 15))
        scope = tk.StringVar(value=f"Somente {self.group.name}")
        audio_format = tk.StringVar(value=EXPORT_FORMATS["mp3_hca"])
        destination = tk.StringVar()
        ttk.Label(frame, text="Grupos:").grid(row=2, column=0, sticky="w")
        scope_widget = ttk.Combobox(frame, textvariable=scope, values=[f"Somente {self.group.name}", f"Todos os {len(self.groups)} grupos"], state="readonly")
        scope_widget.grid(row=3, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(frame, text="Formato dos áudios:").grid(row=4, column=0, sticky="w")
        format_widget = ttk.Combobox(frame, textvariable=audio_format, values=list(EXPORT_FORMATS.values()), state="readonly")
        format_widget.grid(row=5, column=0, sticky="ew", pady=(4, 10))
        row = ttk.Frame(frame)
        row.grid(row=6, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=destination, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 7))
        def choose():
            path = filedialog.askdirectory(parent=dialog, title="Pasta para salvar os ZIPs")
            if path:
                destination.set(path)
        ttk.Button(row, text="Escolher pasta…", command=choose).grid(row=0, column=1)
        ttk.Label(frame, text="Os tamanhos variam com a duração e o formato. WAV ocupa mais espaço.\nA exportação de muitos áudios pode demorar; você pode cancelar.", style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=(10, 12))
        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, sticky="e")
        ttk.Button(actions, text="Fechar", command=dialog.destroy).pack(side="left", padx=7)
        def start():
            if not destination.get():
                messagebox.showinfo("Escolher pasta", "Escolha a pasta onde os ZIPs serão salvos.", parent=dialog)
                return
            try:
                key = parse_key(self.key_var.get())
            except FormatError as exc:
                messagebox.showerror("Chave inválida", str(exc), parent=dialog)
                return
            groups = list(self.groups.values()) if scope.get().startswith("Todos") else [self.group]
            code = next(code for code, label in EXPORT_FORMATS.items() if label == audio_format.get())
            folder = Path(destination.get())
            project = self.project
            dialog.destroy()
            self.status_var.set("Preparando a exportação dos grupos…")
            def done(results):
                self.status_var.set(f"Exportação concluída: {len(results)} ZIP(s) em {folder}")
                detail = "\n".join(f"{Path(r['arquivo']).name}: {r['audios']} áudios · {r['bytes']/1_000_000:.1f} MB" for r in results)
                self._log(detail)
                messagebox.showinfo("ZIPs exportados", f"Arquivos salvos em:\n{folder}\n\n{detail}", parent=self)
            self._job(lambda: export_groups(project, groups, folder, code, key, self.cancel_event, self._progress), done)
        ttk.Button(actions, text="Exportar ZIPs", style="Accent.TButton", command=start).pack(side="left")

    def _audio_to_wav(self, item, destination, on_done):
        try:
            key = parse_key(self.key_var.get())
        except FormatError as exc:
            self._show_error(str(exc))
            return
        bank = self.bank
        self.status_var.set("Decodificando o áudio original…")
        def work():
            raw = decoded_wav(bank, item.id, key)
            if self.cancel_event.is_set():
                raise Cancelled("Exportação cancelada.")
            with Path(destination).open("xb") as f:
                f.write(raw)
            return Path(destination)
        self._job(work, on_done)

    def preview(self):
        item = self.selected()
        if item is None:
            return
        destination = Path(self.preview_dir.name) / f"{self.bank.name}_ID{item.id:06d}_{threading.get_ident()}_{datetime.datetime.now():%H%M%S%f}.wav"
        def done(path):
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.status_var.set("Áudio aberto no reprodutor do computador.")
        self._audio_to_wav(item, destination, done)

    def export_wav(self):
        item = self.selected()
        if item is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Exportar áudio original", initialfile=f"ID{item.id:06d}__{item.name}.wav", defaultextension=".wav", filetypes=[("WAV", "*.wav")])
        if path:
            if Path(path).exists():
                self._show_error("Escolha um nome novo para exportar o áudio.")
                return
            def done(output):
                self.status_var.set(f"WAV exportado: {output.name}")
                self._log(f"Áudio exportado: {output}")
            self._audio_to_wav(item, path, done)

    def choose_output(self):
        if self.busy:
            return
        initial = Path(self.output_var.get()).name if self.output_var.get() else "narracao_modificada.cpk"
        path = filedialog.asksaveasfilename(parent=self, title="Salvar novo CPK", initialfile=initial, defaultextension=".cpk", filetypes=[("Arquivo CPK", "*.cpk")])
        if path:
            self.output_var.set(path)

    def save_project(self):
        if self.busy or not self.project:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Salvar lista de substituições", initialfile="substituicoes.json", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = {"versao": 1, "cpk": str(self.project.archive.path), "tamanho_cpk": self.project.archive.size,
                "chave": self.key_var.get(), "manter_duracao": self.duration_var.get() == "Manter a duração original",
                "substituicoes": [{"banco": item.bank, "id": item.audio_id, "arquivo": str(item.path)} for item in self.replacements.values()]}
        with Path(path).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._log(f"Lista salva: {Path(path).name}")

    def load_project(self):
        if self.busy:
            return
        if not self.project:
            messagebox.showinfo("Abrir CPK", "Abra primeiro o CPK usado na lista salva.", parent=self)
            return
        path = filedialog.askopenfilename(parent=self, title="Carregar lista de substituições", filetypes=[("JSON", "*.json")])
        if not path:
            return
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("versao") != 1 or data.get("tamanho_cpk") != self.project.archive.size:
            raise FormatError("A lista foi salva para outro CPK ou tem uma versão não suportada.")
        if self.replacements and not messagebox.askyesno("Carregar lista", "Substituir a lista de trocas atual pela lista salva?", parent=self):
            return
        parse_key(data.get("chave", DEFAULT_KEY))
        def work():
            result = {}
            for row in data["substituicoes"]:
                if self.cancel_event.is_set():
                    raise Cancelled("Carregamento cancelado.")
                bank_name, ident, file = str(row["banco"]), int(row["id"]), Path(row["arquivo"])
                if not file.is_absolute():
                    file = Path(path).parent / file
                key = bank_name, ident
                if key in result or ident not in self.project.bank(bank_name).audios or not file.is_file() or file.suffix.lower() not in AUDIO_EXTENSIONS:
                    raise FormatError(f"Substituição inválida ou arquivo ausente: {file}.")
                result[key] = Replacement(bank_name, ident, file.resolve())
            return result
        def done(result):
            self.replacements = result
            self.key_var.set(str(data.get("chave", DEFAULT_KEY)))
            self.duration_var.set("Manter a duração original" if data.get("manter_duracao", True) else "Usar a duração do novo áudio")
            self.refresh_audio()
            self.refresh_queue()
            self.status_var.set("Lista de substituições carregada.")
        self._job(work, done)

    def build(self):
        if self.busy:
            return
        if not self.project or not self.replacements:
            messagebox.showinfo("Adicionar substituições", "Abra um CPK e associe pelo menos um áudio substituto.", parent=self)
            return
        try:
            key = parse_key(self.key_var.get())
        except FormatError as exc:
            self._show_error(str(exc))
            return
        if not self.output_var.get().strip():
            self.choose_output()
            if not self.output_var.get().strip():
                return
        keep = self.duration_var.get() == "Manter a duração original"
        output = Path(self.output_var.get().strip())
        project, changes = self.project, list(self.replacements.values())
        def done(report):
            self.status_var.set(f"Concluído: {output.name} · {len(changes)} áudios substituídos.")
            self._log(f"Saída validada: {output}")
            message = f"Novo CPK gerado e validado:\n\n{output}\n\nÁudios substituídos: {len(changes)}\nOriginal preservado.\n\nO funcionamento dentro do jogo ainda precisa ser testado."
            if report.get("aviso_relatorio"):
                message += "\n\nO relatório adicional não pôde ser salvo."
            messagebox.showinfo("CPK concluído", message, parent=self)
        self._job(lambda: generate(project, changes, output, key, keep, self.cancel_event, self._progress), done)

    def _close(self):
        if self.busy:
            self.cancel_event.set()
            messagebox.showinfo("Cancelando", "Aguarde a operação terminar de cancelar e feche a janela novamente.", parent=self)
            return
        self.preview_dir.cleanup()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
