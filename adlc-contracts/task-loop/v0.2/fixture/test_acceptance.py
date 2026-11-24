import unittest
from pathlib import Path

from math_utils import add


class Acceptance(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-2, 3), 1)

    def test_documentation(self):
        self.assertIn("add(a, b)", Path("README.md").read_text())

    def test_legacy_removed(self):
        self.assertFalse(Path("legacy.txt").exists())
