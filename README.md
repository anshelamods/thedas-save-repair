# Thedas Save Repair

Repair the Warden and Hawke gender flags in existing **PC Dragon Age: Inquisition** saves. This standalone companion to Thedas World State Studio needs **no Java or Python installation**.

**[Download for Windows — 0.1.2 preview](downloads/Thedas-Save-Repair-0.1.2-preview-Windows-x64.zip?raw=true)**

Download the Windows ZIP linked above to use the app. The folders below contain its source code for development.

## How to use

1. Extract the **whole ZIP**. Keep `Thedas Save Repair.exe` beside the `_internal` folder.
2. Close Inquisition and run `Thedas Save Repair.exe`.
3. Choose your Inquisition `.DAS` save.
4. Check the Warden and Hawke genders. Uncheck **Repair** for either hero you want to leave unchanged.
5. Click **Back up & repair save**, then start the game and load that save.

The app keeps the save's filename and slot. It synchronizes each selected hero's main gender value and both male/female flags together. It validates the save and backup before replacement.

## Backups and undo

Backups are kept **outside the game's Save folder**, under:

```text
%LOCALAPPDATA%\ThedasWorldstateStudio\SaveBackups
```

- **Open backups folder** opens the selected slot's backup folder.
- **Undo last repair** restores the previous version, provided the game has not written newer progress to that slot.
- **Restore backup** works after restarting the tool. It also backs up the version it replaces. Restoring a backup restores the entire older save, including its progress.
- **Move old backups out of Save…** moves recognized backups made by earlier versions out of the game folder. Changing a backup's extension alone may leave it visible in the game's Load menu.

## Hawke character creation

Use a save from **before Hawke's character creation begins**. Changing these flags does not rebuild an appearance already created or replay completed dialogue and cutscenes. This is a focused gender-flag repair tool, not a general appearance or World State editor. Console saves are unsupported.

## Validation

- Two user-tested female-to-male Hawke changes worked in character creation. Independent comparisons against their backups found exactly the three intended Hawke values changed; all other 3,695 plot values and all encoded bits outside the plot table/checksum were unchanged in each pair.
- 16 focused automated tests cover repair, unrelated data preservation, backups, undo, restore, old-backup migration, invalid files and write failures.
- Earlier read-only checks covered 760 local saves: 758 supported saves passed 1,516 in-memory repair checks; two were refused for pre-existing checksum mismatches. This is file validation, not exhaustive gameplay testing.

See [the usage guide](docs/USAGE.txt) for more detail. Report problems through [Issues](https://github.com/anshelamods/thedas-save-repair/issues), including the app version and exact error text. Do not post personal save files unless you intend to share them publicly.

## Run or build from source

Development uses Python 3.12 with Tk. End users should use the Windows download above.

```powershell
python src/dai_gender_repair_gui.py
python -m unittest discover -s tests -p "test_*.py" -v
```

To build on Windows:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller build.spec
```

The result is `dist/Thedas Save Repair/`. Distribute that entire folder, including `_internal`. Folder packaging avoids the temporary runtime extraction used by the original 0.1.0 single-EXE preview. Source builds use a generic executable icon; the existing Windows download retains the Studio icon.

## Format references

The supplied World Editor's mapping files and storage layout were inspected as format evidence. No original JAR or Java runtime is included.

[Original FBCHUNKS format research](https://www.tapatalk.com/groups/daitools/fbchunks-files-profileoptions-and-save-games-t68.html)
