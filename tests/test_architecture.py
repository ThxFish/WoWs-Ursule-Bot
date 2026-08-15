import ast
import tomllib
from pathlib import Path

import ursule_bot


ROOT = Path(__file__).resolve().parents[1] / "ursule_bot"


def test_package_version_matches_project_metadata():
    pyproject = ROOT.parent / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]

    assert ursule_bot.__version__ == project["version"]


def _imports(path: Path) -> list[ast.ImportFrom | ast.Import]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]


def test_centers_do_not_import_each_other():
    center_root = ROOT / "centers"
    for center in ("planning", "stats", "information"):
        forbidden = {name for name in ("planning", "stats", "information") if name != center}
        for path in (center_root / center).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for other in forbidden:
                assert f"centers.{other}" not in source
                assert f"..{other}" not in source


def test_web_routes_do_not_call_collectors_directly():
    for path in (ROOT / "interfaces" / "web" / "routes").glob("*.py"):
        for node in _imports(path):
            if isinstance(node, ast.ImportFrom):
                assert "integrations.collectors" not in (node.module or "")
            else:
                assert all("integrations.collectors" not in alias.name for alias in node.names)
