"""Tests for bounded.resolve_in_root (synthetic fixture trial-002, Tester-owned).

Covers: root itself, child, normalized child, parent traversal,
sibling-prefix escape, absolute outside. Standard library only.
"""

import os
import tempfile
import unittest

from bounded import resolve_in_root


def norm(p):
    """Case- and form-insensitive path identity for comparison."""
    return os.path.normcase(os.path.realpath(os.fspath(p)))


class ResolveInRootTest(unittest.TestCase):
    def test_root_itself(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(norm(resolve_in_root(root, root)), norm(root))

    def test_child(self):
        with tempfile.TemporaryDirectory() as root:
            child = os.path.join(root, "child.txt")
            with open(child, "w", encoding="utf-8"):
                pass
            self.assertEqual(norm(resolve_in_root(root, child)), norm(child))

    def test_normalized_child(self):
        with tempfile.TemporaryDirectory() as root:
            child = os.path.join(root, "a", "b", "file.txt")
            os.makedirs(os.path.dirname(child))
            messy = os.path.join(root, ".", "a", "..", "a", "b", "file.txt")
            self.assertEqual(norm(resolve_in_root(root, messy)), norm(child))

    def test_parent_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            outside = os.path.join(root, "..", "escape.txt")
            with self.assertRaises(ValueError):
                resolve_in_root(root, outside)

    def test_sibling_prefix_escape(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "data")
            sibling = os.path.join(base, "data-evil")
            os.makedirs(root)
            os.makedirs(sibling)
            with self.assertRaises(ValueError):
                resolve_in_root(root, os.path.join(sibling, "secret.txt"))

    def test_absolute_outside(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as other:
            target = os.path.join(other, "outside.txt")
            with open(target, "w", encoding="utf-8"):
                pass
            with self.assertRaises(ValueError):
                resolve_in_root(root, target)


if __name__ == "__main__":
    unittest.main()
