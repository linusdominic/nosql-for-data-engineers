"""The explorer (docs/explorer/) must agree with the guide.

Every recorded lab number the explorer shows quotes a line of the guide; these tests fail
if that line or value is no longer there, or if data.js is stale.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "guide"


def _load_builder() -> ModuleType:
    path = ROOT / "tools" / "build_explorer_data.py"
    spec = importlib.util.spec_from_file_location("build_explorer_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


@pytest.mark.parametrize("entry", builder.RECORDED, ids=lambda e: e["id"])
def test_recorded_line_and_values_are_in_the_guide(entry: dict[str, object]) -> None:
    chapter = GUIDE / str(entry["chapter"])
    assert chapter.exists(), f"{entry['id']}: no chapter {chapter.name}"
    context = str(entry["context"])
    assert context in chapter.read_text(), f"{entry['id']}: line not found in {chapter.name}: {context!r}"
    values = entry["values"]
    assert isinstance(values, dict) and values, f"{entry['id']}: no values"
    for name, value in values.items():
        assert str(value) in context, f"{entry['id']}: {name}={value!r} is not in its line"


def test_recorded_ids_are_unique() -> None:
    ids = [e["id"] for e in builder.RECORDED]
    assert len(ids) == len(set(ids))


def test_guide_links_point_at_real_headings() -> None:
    links = builder.guide_links()
    assert all(url.startswith(builder.REPO) for url in links.values())


def test_data_js_is_up_to_date() -> None:
    """data.js is generated; regenerate it with `make explorer-data` when this fails."""
    expected = builder.render(builder.build())
    assert builder.OUT.read_text() == expected
