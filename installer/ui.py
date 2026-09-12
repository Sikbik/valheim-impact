"""Approachable Tk UI. Work stays off the UI thread; all mutations require a preview."""
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import core
from .discovery import steam_games

PROFILE_COPY = {
    'Compact': 'Lower memory use, with more frequent texture reloads.',
    'Balanced': 'Default target: 6 GB VRAM, 16 GB RAM, 1080p.',
    'High': 'Preserves a larger texture working set for high-resolution and 4K evaluation.',
}


class InstallerWindow:
    def __init__(self, root):
        self.root, self.events, self.plan, self.busy = root, queue.Queue(), None, False
        root.title('Valheim Impact | Local installer')
        root.geometry('1000x850')
        root.minsize(640, 760)
        root.configure(background='#101b23')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('DejaVu Sans', 10), background='#101b23', foreground='#e6eee9')
        style.configure('TFrame', background='#101b23')
        style.configure('TLabel', background='#101b23', foreground='#e6eee9')
        style.configure('Muted.TLabel', foreground='#a8b9bf')
        style.configure('Title.TLabel', font=('DejaVu Sans', 26, 'bold'), foreground='#f0d395')
        style.configure('Badge.TLabel', foreground='#f0d395', font=('DejaVu Sans', 10, 'bold'))
        style.configure('TButton', padding=(12, 9), background='#29414c', foreground='#f4f7f6')
        style.map('TButton', background=[('active', '#3a5a65'), ('disabled', '#1d2b33')])
        style.configure('Accent.TButton', background='#d8bd80', foreground='#15232b', font=('DejaVu Sans', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#edd49d'), ('disabled', '#526366')])
        style.configure('TEntry', fieldbackground='#21333e', foreground='#f4f7f6', padding=7)
        style.configure('TCombobox', fieldbackground='#21333e', foreground='#f4f7f6', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#21333e')], foreground=[('readonly', '#f4f7f6')])
        style.configure('Treeview', background='#172832', fieldbackground='#172832', foreground='#e6eee9', rowheight=29)
        style.configure('Treeview.Heading', background='#29414c', foreground='#e6eee9', padding=8)
        style.configure('Horizontal.TProgressbar', background='#d8bd80', troughcolor='#21333e')
        self.game, self.package, self.profile = tk.StringVar(), tk.StringVar(), tk.StringVar(value='Balanced')
        self.replacement = tk.BooleanVar(value=False)
        self.operation = tk.StringVar(value='Install / update')
        self.status = tk.StringVar(value='Choose a game folder and package, then preview the changes.')
        self.details = tk.StringVar(value=PROFILE_COPY['Balanced'])
        self.package_status = tk.StringVar(value='No package verified yet')
        outer = ttk.Frame(root, padding=26)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='VALHEIM IMPACT', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='EXPERIMENTAL PROBE  /  LOCAL INSTALLER', style='Badge.TLabel').pack(anchor='w', pady=(4, 10))
        ttk.Label(outer, text='A foundation for an original Viking anime world. This build contains diagnostics and authored texture probes.\nIt is not the finished visual overhaul. Enable experimental replacements below when testing a compatible package.', wraplength=920, style='Muted.TLabel').pack(anchor='w', pady=(0, 18))
        self.controls = []
        self.folder_row(outer, '1  Valheim game folder', self.game, self.choose_game, 'Browse folder')
        self.folder_row(outer, '2  Verified package ZIP', self.package, self.choose_package, 'Choose package')
        ttk.Label(outer, textvariable=self.package_status, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        settings = ttk.Frame(outer)
        settings.pack(fill='x', pady=(0, 8))
        ttk.Label(settings, text='3  Quality profile').pack(side='left', padx=(0, 14))
        profile = ttk.Combobox(settings, textvariable=self.profile, values=list(core.PROFILES), state='readonly', width=14)
        profile.pack(side='left')
        self.controls.append((profile, 'readonly'))
        ttk.Label(settings, text='Action').pack(side='left', padx=(30, 12))
        operation = ttk.Combobox(settings, textvariable=self.operation, values=['Install / update', 'Uninstall', 'Rollback last change', 'Recover interrupted change'], state='readonly', width=26)
        operation.pack(side='left')
        self.controls.append((operation, 'readonly'))
        ttk.Label(outer, textvariable=self.details, wraplength=920, style='Muted.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Profiles bound the replacement texture cache. Hardware targets and 4K quality still need measurement.', style='Muted.TLabel', wraplength=920).pack(anchor='w', pady=(3, 12))
        toggle = ttk.Checkbutton(outer, text='Enable experimental game texture replacements', variable=self.replacement)
        toggle.pack(anchor='w', pady=(0, 10))
        self.controls.append((toggle, 'normal'))
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, 10))
        self.preview_button = self.button(bar, 'Preview exact changes', self.preview, 'Accent.TButton')
        self.button(bar, 'Verify installation', self.verify)
        self.button(bar, 'Find Steam folder', self.detect)
        self.apply_button = self.button(bar, 'Apply reviewed changes', self.apply, 'Accent.TButton')
        self.apply_button.configure(state='disabled')
        for button in bar.winfo_children():
            button.pack_forget()
        for index, button in enumerate(bar.winfo_children()):
            button.grid(row=index // 2, column=index % 2, sticky='ew', padx=(0, 8), pady=(0, 6))
        bar.columnconfigure(0, weight=1)
        bar.columnconfigure(1, weight=1)
        footer = ttk.Frame(outer)
        footer.pack(side='bottom', fill='x')
        ttk.Label(footer, text='Installer metadata and rollback copies stay in ValheimImpact/.installer. Unowned content is preserved.', style='Muted.TLabel', wraplength=920).pack(anchor='w', pady=(8, 6))
        self.progress = ttk.Progressbar(footer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(2, 8))
        ttk.Label(footer, textvariable=self.status, wraplength=920).pack(anchor='w')
        table = ttk.Frame(outer)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('action', 'path', 'bytes', 'hash'), show='headings', selectmode='browse', height=8)
        for name, label, width in [('action', 'Change', 85), ('path', 'Path inside ValheimImpact', 420), ('bytes', 'Bytes before / after', 155), ('hash', 'New SHA256 (short)', 155)]:
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=70, stretch=(name == 'path'))
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        for variable in (self.game, self.package, self.profile, self.operation, self.replacement):
            variable.trace_add('write', self.invalidate)
        outer.bind('<Configure>', lambda event: self.wrap_labels(outer, max(300, event.width - 52)))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        self.detect()

    def wrap_labels(self, parent, width):
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Label):
                widget.configure(wraplength=width)
            elif isinstance(widget, ttk.Frame):
                self.wrap_labels(widget, width)

    def folder_row(self, parent, title, variable, command, label):
        ttk.Label(parent, text=title).pack(anchor='w', pady=(0, 4))
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 8))
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
        self.controls.append((entry, 'normal'))
        self.button(row, label, command)

    def button(self, parent, text, command, style='TButton'):
        button = ttk.Button(parent, text=text, command=command, style=style)
        button.pack(side='left', padx=(0, 8))
        self.controls.append((button, 'normal'))
        return button

    def invalidate(self, *_):
        self.plan = None
        self.apply_button.configure(state='disabled')
        self.details.set(PROFILE_COPY[self.profile.get()])
        self.package_status.set('Preview verifies the selected package, hashes, game folder and owned files')
        self.tree.delete(*self.tree.get_children())

    def choose_game(self):
        path = filedialog.askdirectory(title='Select the folder containing the Valheim executable', parent=self.root)
        if path:
            self.game.set(path)

    def choose_package(self):
        path = filedialog.askopenfilename(title='Select a trusted Valheim Impact experimental package', filetypes=[('Valheim Impact ZIP', '*.zip')], parent=self.root)
        if path:
            self.package.set(path)

    def detect(self):
        games = steam_games()
        if games and not self.game.get():
            self.game.set(games[0])
        self.status.set('Steam folder found. Confirm the selected location.' if games else 'Steam folder not found. Use Browse folder to select Valheim manually.')

    def task(self, work, done):
        self.busy = True
        for control, _ in self.controls:
            control.configure(state='disabled')
        self.progress.start(12)
        def worker():
            try:
                self.events.put(('done', done, work()))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                item = self.events.get_nowait()
                if item[0] == 'progress':
                    self.status.set(item[1])
                    continue
                self.busy = False
                self.progress.stop()
                for control, state in self.controls:
                    control.configure(state=state)
                self.apply_button.configure(state='disabled')
                if item[0] == 'error':
                    self.plan = None
                    self.status.set(item[1])
                    messagebox.showerror('Changes stopped', item[1], parent=self.root)
                else:
                    item[1](item[2])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def preview(self):
        operation = {'Install / update': 'install', 'Uninstall': 'uninstall', 'Rollback last change': 'rollback', 'Recover interrupted change': 'recover'}[self.operation.get()]
        game, package, profile = self.game.get(), self.package.get() or None, self.profile.get()
        enable_replacement = self.replacement.get()
        self.plan = None
        self.status.set('Verifying package and preparing the exact change preview...')
        self.task(lambda: core.preview(game, package, operation=operation, profile=profile, enable_replacement=enable_replacement), self.show_plan)

    def show_plan(self, plan):
        self.plan = plan
        self.tree.delete(*self.tree.get_children())
        for change in plan.changes:
            size = f"{change.before['size'] if change.before else 0:,} / {change.after['size'] if change.after else 0:,}"
            self.tree.insert('', 'end', values=(change.action.upper(), change.path, size, change.after['sha256'][:16] if change.after else ''))
        count = sum(c.action in ('add', 'remove', 'replace') for c in plan.changes)
        self.package_status.set(f'Verified experimental {plan.version or "local rollback"} | {plan.profile}' + (f' | SHA256 {plan.package_digest[:24]}...' if plan.package_digest else ''))
        self.status.set(f'{count} file changes ready for review. Close Valheim before applying. Destination: {plan.game / core.OWNED}')
        self.apply_button.configure(state='normal')

    def apply(self):
        if not self.plan:
            return
        plan = self.plan
        if not messagebox.askokcancel('Apply these reviewed changes?', f'Apply {plan.operation} to:\n{plan.game / core.OWNED}\n\nThe listed files will change and a local rollback backup will be saved. Valheim must remain closed.\n\nThis is an experimental diagnostic/probe build.', parent=self.root):
            return
        self.status.set('Checking that Valheim is closed and the preview is still current...')
        self.task(lambda: core.apply(plan, reviewed_token=plan.token, progress=lambda msg: self.events.put(('progress', msg))), self.finished)

    def finished(self, result):
        self.plan = None
        self.status.set('Complete. Your local backup is available through Rollback last change. Experimental replacements follow the installed profile and runtime setting.')
        messagebox.showinfo('Local changes complete', self.status.get(), parent=self.root)

    def verify(self):
        game = self.game.get()
        self.status.set('Checking installed owned files...')
        self.task(lambda: core.verify(game), self.show_verify)

    def show_verify(self, result):
        self.plan = None
        text = 'All owned files match the installation receipt.' if result['ok'] and result['installed'] else 'No owned installation is present.' if result['ok'] else '\n'.join(result['issues'])
        self.status.set(text)
        (messagebox.showinfo if result['ok'] else messagebox.showwarning)('Installation verification', text, parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation in progress', 'Wait for the current operation to finish before closing the installer.', parent=self.root)
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    InstallerWindow(root)
    root.mainloop()
    return 0
