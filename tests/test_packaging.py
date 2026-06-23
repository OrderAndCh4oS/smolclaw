import tomllib
from pathlib import Path


def test_setuptools_packages_have_source_directories():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    packages = pyproject["tool"]["setuptools"]["packages"]

    for package in packages:
        package_dir = repo_root.joinpath(*package.split("."))
        assert (package_dir / "__init__.py").is_file(), (
            f"pyproject.toml lists package {package!r}, "
            f"but {package_dir} is not a source package"
        )
