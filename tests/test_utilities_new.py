import os

from app.utilities import ensure_dir


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
