"""The package metadata must stay installable: pipx refused 0.4.0 when a field landed in the wrong table."""

import pathlib
import tomllib

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_optional_dependencies_are_lists_and_project_fields_sit_in_project():
    data = tomllib.loads(PYPROJECT.read_text())
    project = data["project"]
    assert all(isinstance(v, list) for v in project.get("optional-dependencies", {}).values())
    assert "license" in project and project["scripts"]["phaneris"]
