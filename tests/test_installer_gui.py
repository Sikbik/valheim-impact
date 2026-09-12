"""Opt-in display test: VALHEIM_INSTALLER_GUI_TESTS=1 with Python+Tk."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('VALHEIM_INSTALLER_GUI_TESTS') == '1', 'requires an explicitly enabled graphical display test')
class InstallerGuiTests(unittest.TestCase):
    def test_preview_enables_apply_and_input_changes_invalidate_it(self):
        import tkinter as tk
        from installer.ui import InstallerWindow
        from test_installer import package
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / 'Valheim'
            (game / 'valheim_Data').mkdir(parents=True)
            (game / 'valheim_Data/globalgamemanagers').write_bytes(b'fixture Unity marker')
            (game / 'valheim.x86_64').write_bytes(b'fixture executable')
            (game / 'BepInEx/core').mkdir(parents=True)
            (game / 'BepInEx/core/BepInEx.dll').write_bytes(b'fixture prerequisite')
            archive = package(Path(temporary) / 'probe.zip')
            root = tk.Tk()
            try:
                with patch('installer.ui.steam_games', return_value=[]):
                    window = InstallerWindow(root)
                self.assertFalse(window.replacement.get())
                window.game.set(str(game))
                window.package.set(str(archive))
                self.assertEqual(str(window.apply_button['state']), 'disabled')
                window.preview_button.invoke()
                deadline = time.monotonic() + 10
                while window.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertFalse(window.busy)
                self.assertEqual(str(window.apply_button['state']), 'normal')
                self.assertEqual(len(window.tree.get_children()), 2)
                self.assertFalse((game / 'BepInEx/plugins/ValheimImpact').exists())
                window.replacement.set(True)
                self.assertEqual(str(window.apply_button['state']), 'disabled')
                self.assertIsNone(window.plan)
            finally:
                root.destroy()
