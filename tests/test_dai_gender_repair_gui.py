"""Exercise the desktop app's handlers on disposable copies, without dialogs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
(Path(__file__).resolve().parent / "output").mkdir(exist_ok=True)
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from dai_gender_repair import read_save
from dai_gender_repair_gui import App
from test_dai_gender_repair import fixture


class GuiTests(unittest.TestCase):
    def setUp(self):
        local = tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output')
        self.addCleanup(local.cleanup)
        env = patch.dict('os.environ', {'LOCALAPPDATA': local.name})
        env.start()
        self.addCleanup(env.stop)

    def test_repair_undo_restore_and_layout(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture(7)
            path.write_bytes(original)
            root = tk.Tk()
            try:
                app = App(root)
                with patch('dai_gender_repair_gui.messagebox.showinfo'), patch('dai_gender_repair_gui.messagebox.showerror') as error:
                    app.load(path)
                    root.update()
                    self.assertEqual(str(app.repair_button['state']), 'normal')
                    # The complete content must fit, including the Hawke limitation.
                    main, = root.winfo_children()
                    self.assertLessEqual(main.winfo_reqheight(), root.winfo_height())
                    app.repair()
                    self.assertEqual(read_save(path).gender('warden'), (0, True, False))
                    self.assertEqual(read_save(path).gender('hawke'), (1, False, True))
                    self.assertEqual(str(app.repair_button['state']), 'disabled')
                    self.assertEqual(str(app.undo_button['state']), 'normal')
                    backup = app.last[1]
                    self.assertEqual(backup.read_bytes(), original)
                    app.undo()
                    self.assertEqual(path.read_bytes(), original)
                    # Restore after restart: a newly constructed app knows no undo state.
                    app.repair()
                    app.last = None
                    with patch('dai_gender_repair_gui.filedialog.askopenfilename', return_value=str(backup)):
                        app.restore()
                    self.assertEqual(path.read_bytes(), original)
                    # A backup from another slot cannot replace this one.
                    other = Path(folder) / 'other.DAS.gender-backup-123.bak'
                    other.write_bytes(original)
                    with patch('dai_gender_repair_gui.filedialog.askopenfilename', return_value=str(other)):
                        app.restore()
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(error.call_count, 1)
                    legacy = path.with_name(path.name + '.gender-backup-0123456789ab.bak')
                    legacy.write_bytes(original)
                    app.move_old_backups()
                    self.assertFalse(legacy.exists())
                    self.assertIn('Moved 1 old backup', app.status.get())
                    with patch('dai_gender_repair_gui.os.startfile') as opened:
                        app.open_backups()
                    opened.assert_called_once()
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
