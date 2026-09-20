import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install-rocky.sh").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
INIT = (ROOT / "pgintel" / "__init__.py").read_text(encoding="utf-8")


class InstallerHotfixTests(unittest.TestCase):
    def test_application_version_has_dedicated_variable(self):
        self.assertIn('PGINTEL_VERSION="0.1.7"', INSTALLER)
        self.assertIsNone(re.search(r"(?m)^VERSION=", INSTALLER))
        self.assertIn('version = "0.1.7"', PYPROJECT)
        self.assertIn('__version__ = "0.1.7"', INIT)

    def test_os_release_is_not_sourced_into_installer_shell(self):
        self.assertNotIn("\n  . /etc/os-release\n", INSTALLER)
        self.assertIn('OS_ID="$(. /etc/os-release;', INSTALLER)
        self.assertIn('OS_VERSION_ID="$(. /etc/os-release;', INSTALLER)

    def test_source_tree_fallback_bootstraps_build_backend(self):
        self.assertIn('"setuptools>=68" wheel', INSTALLER)
        self.assertIn("-c 'import setuptools'", INSTALLER)
        self.assertIn("--no-build-isolation", INSTALLER)


if __name__ == "__main__":
    unittest.main()
