import unittest
from pathlib import Path
from unittest.mock import patch
from installer.discovery import running_valheim


class ProcessDiscoveryTests(unittest.TestCase):
    def test_exited_process_does_not_break_detection(self):
        with patch('installer.discovery.sys.platform', 'linux'), \
             patch.object(Path, 'is_dir', return_value=True), \
             patch.object(Path, 'iterdir', return_value=iter([Path('/proc/123'), Path('/proc/456')])), \
             patch.object(Path, 'read_text', side_effect=[ProcessLookupError(3, 'No such process'), 'valheim.x86_64\n']), \
             patch.object(Path, 'read_bytes', return_value=b'/game/valheim.x86_64\0'):
            self.assertEqual(running_valheim(), ['valheim.x86_64 (PID 456)'])

    def test_exit_during_permission_fallback_is_ignored(self):
        with patch('installer.discovery.sys.platform', 'linux'), \
             patch.object(Path, 'is_dir', return_value=True), \
             patch.object(Path, 'iterdir', return_value=iter([Path('/proc/123')])), \
             patch.object(Path, 'read_text', side_effect=[PermissionError(), ProcessLookupError()]):
            self.assertEqual(running_valheim(), [])
