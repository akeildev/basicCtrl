"""skills/loader unit tests — pin the catalog shape for cognition prompts."""
from __future__ import annotations

import pytest

from cua_overlay.skills import loader


@pytest.mark.unit
def test_list_bundles_returns_seeded_apps():
    """All seeded apps appear, sorted, with no __pycache__ noise."""
    bundles = loader.list_bundles()
    assert "com.apple.calculator" in bundles
    assert "com.google.Chrome" in bundles
    assert "com.tinyspeck.slackmacgap" in bundles
    assert all(not b.startswith("__") for b in bundles)
    assert bundles == sorted(bundles)


@pytest.mark.unit
def test_list_skills_for_known_bundle():
    topics = loader.list_skills("com.apple.calculator")
    assert "arithmetic" in topics


@pytest.mark.unit
def test_list_skills_for_missing_bundle_returns_empty():
    assert loader.list_skills("com.nonexistent.app") == []


@pytest.mark.unit
def test_read_skill_returns_markdown_or_none():
    body = loader.read_skill("com.apple.calculator", "arithmetic")
    assert body is not None
    assert "# Apple Calculator" in body  # heading from arithmetic.md

    assert loader.read_skill("com.apple.calculator", "missing-topic") is None
    assert loader.read_skill("com.nonexistent.app", "anything") is None


@pytest.mark.unit
def test_read_all_skills_concatenates_with_topic_headers():
    blob = loader.read_all_skills("com.apple.calculator")
    assert blob is not None
    assert blob.startswith("# Skills for com.apple.calculator")
    assert "## arithmetic" in blob


@pytest.mark.unit
def test_read_all_skills_returns_none_for_missing_bundle():
    assert loader.read_all_skills("com.nonexistent.app") is None
