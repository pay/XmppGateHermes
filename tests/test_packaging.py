"""Dependency and setup metadata contracts for local plugin installations."""

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_slixmpp_includes_http_upload_dependencies(self):
        with (ROOT / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
        requirements = [
            requirement
            for requirement in project["dependencies"]
            if requirement.startswith("slixmpp")
        ]
        self.assertEqual(len(requirements), 1)
        extras = requirements[0].partition("[")[2].partition("]")[0].split(",")
        self.assertIn("xep-0363", [extra.strip() for extra in extras])

    def test_editable_progress_prompt_does_not_offer_force(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        description = manifest.split("  - name: XMPP_EDITABLE_PROGRESS\n", 1)[1]
        description = description.split("  - name:", 1)[0]
        self.assertIn("known", description)
        self.assertIn("disabled", description)
        self.assertNotIn("force", description)


if __name__ == "__main__":
    unittest.main()
