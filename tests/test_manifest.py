from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_bluetooth_dependency() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "fitorb" / "manifest.json").read_text()
    )

    assert manifest["domain"] == "fitorb"
    assert manifest["name"] == "Fitorb Smart Ring"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert "bluetooth" in manifest["dependencies"]
    assert manifest["bluetooth"][0]["connectable"] is True


def test_manifest_version_is_history_release() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "fitorb" / "manifest.json").read_text()
    )

    assert manifest["version"] == "0.2.0"


def test_hacs_metadata_points_to_integration() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "Fitorb Smart Ring"
    assert hacs["render_readme"] is True
