"""Smoke test: the manifest and the module declaration are coherent."""

from pathlib import Path

from novvus_sdk.manifest import Manifest


def test_manifest_is_valid() -> None:
    manifest = Manifest.load(Path(__file__).resolve().parents[1] / "novvus.toml")
    assert manifest.module.id == "automatizacion"
