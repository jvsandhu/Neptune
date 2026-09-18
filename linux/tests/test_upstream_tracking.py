"""Offline checks for fork versus original-project update tracking."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'check_upstream', Path(__file__).resolve().parents[1] / 'check_upstream.py'
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class UpstreamTrackingTests(unittest.TestCase):
    def test_fork_prefers_original_project(self):
        self.assertEqual(checker.select_target(['origin', 'upstream']),
                         ('upstream', 'upstream/main'))

    def test_direct_clone_keeps_origin_fallback(self):
        self.assertEqual(checker.select_target(['origin']), ('origin', 'origin/main'))

    def test_explicit_ref_selects_its_remote(self):
        self.assertEqual(checker.select_target(['origin', 'upstream'], ref='origin/main'),
                         ('origin', 'origin/main'))

    def test_explicit_remote_and_ref(self):
        self.assertEqual(checker.select_target(['source'], 'source', 'v1.1.5'),
                         ('source', 'v1.1.5'))

    def test_missing_remote_is_actionable(self):
        with self.assertRaisesRegex(ValueError, 'Configure it or pass --remote'):
            checker.select_target(['origin'], 'missing')
