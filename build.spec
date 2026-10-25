# Build a portable folder. Keep the EXE together with its _internal folder.
from pathlib import Path
root = Path(SPECPATH)
a = Analysis([str(root / 'src/dai_gender_repair_gui.py')],
    pathex=[str(root / 'src')], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['numpy', 'pandas', 'scipy', 'matplotlib', 'PIL', 'webview'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name='Thedas Save Repair', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon='NONE')
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                  name='Thedas Save Repair')
