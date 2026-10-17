"""Contract tests for the isolated file-MCP acceptance fixture."""
from pathlib import Path
import tempfile
import unittest

import check


def file_case(name, *, denied=False):
    result = {
        "name": name,
        "call": {"name": "file_tool", "arguments": {"path": "sample.txt"}},
    }
    if denied:
        result["denied_contains"] = "permission denied"
    else:
        result["expected"] = [{"path": ["content", 0, "text"], "equals": "safe"}]
    return result


class FileBoundaryContractTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / ".mcp-hub-acceptance").write_text("isolated-test-environment", encoding="utf-8")
        allowed = root / "allowed"
        allowed.mkdir()
        cfg = {
            "isolated": True,
            "sandbox_root": str(root),
            "file_allowed_root": str(allowed),
            "file_allowed": file_case("allowed"),
            "file_denied": file_case("outside", denied=True),
            "file_traversal": file_case("traversal", denied=True),
            "file_symlink": file_case("symlink", denied=True),
        }
        return temp, root, cfg

    def test_complete_fixture_is_accepted(self):
        temp, _, cfg = self.fixture()
        self.addCleanup(temp.cleanup)
        check.validate_file_fixture(cfg)

    def test_fixture_requires_isolation_marker_and_all_negative_cases(self):
        temp, root, cfg = self.fixture()
        self.addCleanup(temp.cleanup)
        (root / ".mcp-hub-acceptance").unlink()
        with self.assertRaises(check.SetupError):
            check.validate_file_fixture(cfg)

        temp, _, cfg = self.fixture()
        self.addCleanup(temp.cleanup)
        del cfg["file_symlink"]
        with self.assertRaises(check.SetupError):
            check.validate_file_fixture(cfg)

    def test_allowed_root_must_be_inside_sandbox(self):
        temp, root, cfg = self.fixture()
        self.addCleanup(temp.cleanup)
        outside = root.parent / "not-an-allowed-root"
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        cfg["file_allowed_root"] = str(outside)
        with self.assertRaises(check.SetupError):
            check.validate_file_fixture(cfg)

    def test_denied_cases_require_explicit_denial_assertions(self):
        temp, _, cfg = self.fixture()
        self.addCleanup(temp.cleanup)
        del cfg["file_traversal"]["denied_contains"]
        with self.assertRaises(check.SetupError):
            check.validate_file_fixture(cfg)


if __name__ == "__main__":
    unittest.main()
