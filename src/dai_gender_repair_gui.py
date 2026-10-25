"""Portable desktop companion for repairing existing PC Inquisition saves."""
from pathlib import Path
import argparse
import ctypes
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dai_gender_repair import (VERSION, HEROES, RepairError, apply, backup_directory,
    digest, is_backup_for, move_legacy_backups, read_save, replace_with_backup, undo)


def default_save_folder():
    docs = Path.home() / 'Documents'
    if sys.platform == 'win32':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
            docs = Path(buffer.value)
    return docs / 'BioWare' / 'Dragon Age Inquisition' / 'Save'


class App:
    def __init__(self, root):
        self.root = root
        self.path = self.save = self.last = None
        root.title('Thedas Save Repair — preview')
        root.geometry('780x790')
        root.minsize(740, 760)
        root.configure(bg='#f4f2ed')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#f4f2ed', foreground='#242c35')
        style.configure('TButton', padding=(12, 8))
        style.configure('Accent.TButton', background='#305b61', foreground='white')
        style.map('Accent.TButton', background=[('active', '#24484d'), ('disabled', '#b4b6b3')])
        style.configure('Title.TLabel', font=('Segoe UI Semibold', 23))
        style.configure('Sub.TLabel', foreground='#53636a')
        style.configure('Hero.TLabelframe.Label', font=('Segoe UI Semibold', 12))
        main = ttk.Frame(root, padding=26)
        main.pack(fill='both', expand=True)
        ttk.Label(main, text='Thedas Save Repair', style='Title.TLabel').pack(anchor='w')
        ttk.Label(main, text='Warden dialogue & Hawke gender flags  ·  PC Inquisition', style='Sub.TLabel').pack(anchor='w', pady=(3, 18))
        ttk.Label(main, text='1   Close Inquisition, then choose the save you want to repair.').pack(anchor='w')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=(10, 8))
        ttk.Button(row, text='Choose save…', command=self.choose).pack(side='left')
        ttk.Button(row, text='Open saves folder', command=self.open_saves).pack(side='left', padx=8)
        self.filename = tk.StringVar(value='No save selected')
        ttk.Label(main, textvariable=self.filename, wraplength=675, style='Sub.TLabel').pack(anchor='w')
        self.character = tk.StringVar(value='Your save stays on your computer.')
        ttk.Label(main, textvariable=self.character, wraplength=675).pack(anchor='w', pady=(3, 14))
        ttk.Label(main, text='2   Check the intended genders. Saved selections are filled in below.').pack(anchor='w')
        self.gender = {}
        self.enabled = {}
        self.states = {}
        for hero, title in (('warden', 'The Warden'), ('hawke', 'Hawke')):
            frame = ttk.LabelFrame(main, text=title, padding=(14, 8), style='Hero.TLabelframe')
            frame.pack(fill='x', pady=(10, 0))
            line = ttk.Frame(frame)
            line.pack(fill='x')
            enabled = tk.BooleanVar(value=True)
            gender = tk.IntVar(value=-1)
            self.enabled[hero], self.gender[hero] = enabled, gender
            ttk.Checkbutton(line, text='Repair', variable=enabled, command=self.preview).pack(side='left', padx=(0, 28))
            for value, label in enumerate(('Male', 'Female')):
                ttk.Radiobutton(line, text=label, variable=gender, value=value, command=self.preview).pack(side='left', padx=(0, 24))
            state = tk.StringVar(value='Choose a save to inspect these flags.')
            self.states[hero] = state
            ttk.Label(frame, textvariable=state, wraplength=620, style='Sub.TLabel').pack(anchor='w', pady=(5, 0))
        ttk.Label(main, text='3   Apply the repair. Backups stay outside the game’s save folder.', wraplength=665).pack(anchor='w', pady=(18, 8))
        row = ttk.Frame(main)
        row.pack(fill='x')
        self.repair_button = ttk.Button(row, text='Back up & repair save', style='Accent.TButton', command=self.repair, state='disabled')
        self.repair_button.pack(side='left')
        self.undo_button = ttk.Button(row, text='Undo last repair', command=self.undo, state='disabled')
        self.undo_button.pack(side='left', padx=8)
        self.restore_button = ttk.Button(row, text='Restore backup…', command=self.restore, state='disabled')
        self.restore_button.pack(side='left')
        backup_row = ttk.Frame(main)
        backup_row.pack(fill='x', pady=(6, 0))
        self.backups_button = ttk.Button(backup_row, text='Open backups folder', command=self.open_backups, state='disabled')
        self.backups_button.pack(side='left')
        self.move_backups_button = ttk.Button(backup_row, text='Move old backups out of Save…', command=self.move_old_backups, state='disabled')
        self.move_backups_button.pack(side='left', padx=8)
        self.status = tk.StringVar(value='Preview build — in-game success reported by a tester; broader testing remains ongoing.')
        ttk.Label(main, textvariable=self.status, wraplength=675, style='Sub.TLabel').pack(anchor='w', pady=(12, 8))
        ttk.Separator(main).pack(fill='x', pady=(5, 10))
        ttk.Label(main, text='For Hawke’s character creation, use a save from before it begins. This tool does not rebuild an existing face or body, replay dialogue, or change your Inquisitor.',
                  wraplength=675, style='Sub.TLabel').pack(anchor='w')

    def choose(self):
        folder = self.path.parent if self.path else default_save_folder()
        path = filedialog.askopenfilename(title='Choose an Inquisition save', initialdir=str(folder),
                                          filetypes=[('Inquisition saves', '*.DAS'), ('All files', '*.*')])
        if path:
            self.load(Path(path))

    def load(self, path):
        try:
            save = read_save(path)
            if path.suffix.lower() != '.das':
                raise RepairError('Choose the .DAS save itself.')
        except (OSError, RepairError) as exc:
            messagebox.showerror('Cannot open save', str(exc), parent=self.root)
            return
        self.path, self.save = path, save
        self.restore_button.configure(state='normal')
        self.backups_button.configure(state='normal')
        self.move_backups_button.configure(state='normal')
        self.undo_button.configure(state='normal' if self.last and self.last[0].resolve() == path.resolve() else 'disabled')
        self.filename.set(str(path))
        self.character.set(save.label)
        for hero in HEROES:
            self.enabled[hero].set(True)
            self.gender[hero].set(save.gender(hero)[0])
        self.preview()

    def preview(self):
        if not self.save:
            return
        changed = 0
        for hero in HEROES:
            enum, male, female = self.save.gender(hero)
            synchronized = (male, female) == (enum == 0, enum == 1)
            desired = self.gender[hero].get()
            enabled = self.enabled[hero].get()
            needs_change = enabled and (enum, male, female) != (desired, desired == 0, desired == 1)
            changed += needs_change
            original = 'Male' if enum == 0 else 'Female'
            detail = 'flags agree' if synchronized else 'gender flags disagree'
            action = (' → synchronize as ' + ('Male' if desired == 0 else 'Female')) if needs_change else (' · leave unchanged' if not enabled else '')
            self.states[hero].set('Saved gender: ' + original + ' · ' + detail + action)
        self.repair_button.configure(state='normal' if changed else 'disabled')
        self.status.set(f'{changed} hero setting(s) will be synchronized. Other save data is preserved.' if changed else
                        'The selected gender flags already agree. No repair is needed.')

    def repair(self):
        try:
            choices = {hero: self.gender[hero].get() for hero in HEROES if self.enabled[hero].get()}
            backup, repaired_hash = apply(self.path, self.save, choices)
            self.last = self.path, backup, repaired_hash
            self.undo_button.configure(state='normal')
            self.load(self.path)
            self.status.set('Repair verified. Backup stored outside the game’s Save folder.')
            messagebox.showinfo('Save repaired', 'The selected gender flags are now synchronized.\n\nLoad this save in Inquisition.\n\nBackup:\n' + str(backup), parent=self.root)
        except (OSError, RepairError) as exc:
            messagebox.showerror('Repair stopped', str(exc), parent=self.root)

    def undo(self):
        if not self.last:
            return
        path, backup, repaired_hash = self.last
        try:
            undo(path, backup, repaired_hash)
            self.last = None
            self.undo_button.configure(state='disabled')
            self.load(path)
            self.status.set('Original save restored. Both versions remain backed up.')
        except (OSError, RepairError) as exc:
            messagebox.showerror('Undo stopped', str(exc), parent=self.root)

    def open_saves(self):
        folder = self.path.parent if self.path else default_save_folder()
        if folder.is_dir():
            os.startfile(folder)
        else:
            messagebox.showinfo('Saves folder', 'Use Choose save to locate your Inquisition .DAS file.', parent=self.root)

    def restore(self):
        if not self.save:
            return
        name = filedialog.askopenfilename(title='Restore a backup of ' + self.path.name,
            initialdir=str(backup_directory(self.path)), filetypes=[('Backups of this save', self.path.name + '.*-backup-*.bak')])
        if not name:
            return
        try:
            backup = Path(name)
            if not is_backup_for(backup, self.path):
                raise RepairError('Choose a backup created for this save, from its backups folder or the old save folder.')
            original = read_save(backup)
            preserved = replace_with_backup(self.path, self.save.raw, original.raw)
            self.last = self.path, preserved, digest(original.raw)
            self.undo_button.configure(state='normal')
            self.load(self.path)
            self.status.set('Backup restored. The version it replaced was also backed up.')
        except (OSError, RepairError) as exc:
            messagebox.showerror('Restore stopped', str(exc), parent=self.root)

    def open_backups(self):
        if self.path:
            try:
                folder = backup_directory(self.path)
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(folder)
            except (OSError, RepairError) as exc:
                messagebox.showerror('Cannot open backups', str(exc), parent=self.root)

    def move_old_backups(self):
        if not self.path:
            return
        try:
            moved = move_legacy_backups(self.path)
            self.status.set(f'Moved {len(moved)} old backup(s) for this save outside the game’s Save folder.')
            messagebox.showinfo('Backups moved', f'{len(moved)} old backup(s) for this save were moved and verified.\n\n'
                'Close and reopen the game’s Load menu to refresh its list.\n\nBackups folder:\n' + str(backup_directory(self.path)), parent=self.root)
        except (OSError, RepairError) as exc:
            messagebox.showerror('Moving backups stopped', str(exc), parent=self.root)


def main():
    parser = argparse.ArgumentParser(description='Thedas Save Repair')
    parser.add_argument('save', type=Path, nargs='?', help='Optional .DAS to open; also supports dragging a save onto the executable')
    parser.add_argument('--inspect', type=Path, help='Read-only inspection, JSON on stdout')
    parser.add_argument('--self-test', type=Path, help='Write a runtime health report, without opening or editing saves')
    args = parser.parse_args()
    if args.inspect:
        save = read_save(args.inspect)
        print(json.dumps(dict(version=VERSION, character=save.label, sha256=digest(save.raw),
                              flags={h: save.gender(h) for h in HEROES})))
        return
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    app = App(root)
    if args.save:
        app.load(args.save)
    if args.self_test:
        root.update()
        args.self_test.write_text(json.dumps(dict(version=VERSION, tkinter=root.tk.call('info', 'patchlevel'),
                                                 window_created=True, save_loaded=app.save is not None)), encoding='utf-8')
        root.destroy()
        return
    root.mainloop()


if __name__ == '__main__':
    main()
