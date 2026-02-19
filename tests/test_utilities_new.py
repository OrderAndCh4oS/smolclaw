import os

import pytest

from app.utilities import safe_filename, ensure_dir


class TestSafeFilename:
    def test_safe_filename(self):
        assert safe_filename("foo:bar/baz qux") == "foo_bar_baz_qux"

    def test_safe_filename_preserves_normal(self):
        assert safe_filename("hello-world_123") == "hello-world_123"


class TestEnsureDir:
    def test_ensure_dir_creates(self, temp_dir):
        target = os.path.join(temp_dir, "nested", "dir")
        result = ensure_dir(target)
        assert os.path.isdir(target)
        assert result == target

    def test_ensure_dir_existing(self, temp_dir):
        result = ensure_dir(temp_dir)
        assert os.path.isdir(temp_dir)
        assert result == temp_dir
