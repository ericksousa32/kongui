"""The integration document must cover the public API and every pending item."""

import inspect
import unittest
from pathlib import Path

from kongui.core import (
    NOT_IMPLEMENTED_OPERATIONS,
    READ_ONLY_FLAGS,
    CliRunner,
    ConfigService,
    KonsaveEngine,
    ProfileService,
)

DOC = Path(__file__).resolve().parent.parent / "docs" / "INTEGRATION.md"


def public_members(cls):
    """Names of the public callables and properties of a class."""
    return {
        name
        for name, _ in inspect.getmembers(cls)
        if not name.startswith("_") and name not in {"engine", "config"}
    }


class IntegrationDocTests(unittest.TestCase):
    """Keeps the documentation from drifting away from the code."""

    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")

    def test_every_not_implemented_operation_is_documented(self):
        for name in NOT_IMPLEMENTED_OPERATIONS:
            with self.subTest(operation=name):
                self.assertIn(f"`{name}`", self.text)

    def test_every_public_member_is_documented(self):
        for cls in (KonsaveEngine, ConfigService, ProfileService, CliRunner):
            for name in public_members(cls):
                with self.subTest(member=f"{cls.__name__}.{name}"):
                    self.assertIn(name, self.text)

    def test_every_read_only_flag_is_documented(self):
        for flag in READ_ONLY_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(f"`{flag}`", self.text)

    def test_required_sections_exist(self):
        for heading in (
            "## 2. APIs do Konsave confirmadas",
            "## 7. Como validar cada serviço",
            "## 8. Operações não implementadas",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_every_test_module_is_mentioned(self):
        folder = Path(__file__).resolve().parent
        docs = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(DOC.parent.glob("*.md"))
        )
        for path in sorted(folder.glob("test_*.py")):
            if path.stem == "test_zz_real_home_guard":
                continue
            with self.subTest(module=path.stem):
                self.assertIn(f"tests.{path.stem}", docs)


if __name__ == "__main__":
    unittest.main()
