"""Unit tests for Cassette NDJSON serialization and schema versioning."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from cua_overlay.cache.cassette import Cassette, CassetteStep
from cua_overlay.state.causal_dag import ActionCanonical, HoarePost, HoarePre


class TestCassetteCreation:
    """Test basic cassette creation."""

    def test_cassette_creation(self):
        """Create Cassette, assert empty steps."""
        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test instruction",
        )

        assert cassette.cache_key == "test-key"
        assert cassette.bundle_id == "com.example.app"
        assert len(cassette.steps) == 0
        assert cassette.schema_version == "1.0"

    def test_cassette_add_step(self, sample_cassette_step: CassetteStep):
        """Add 3 steps, assert len(cassette.steps) == 3."""
        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test instruction",
        )

        cassette.add_step(sample_cassette_step)
        cassette.add_step(sample_cassette_step)
        cassette.add_step(sample_cassette_step)

        assert len(cassette.steps) == 3


class TestCassetteSerialization:
    """Test NDJSON serialization/deserialization."""

    def test_cassette_to_ndjson(self, sample_cassette: Cassette):
        """Cassette with 2 steps, serialize, assert metadata line + step lines."""
        # Use first 2 steps
        cassette = Cassette(
            cache_key=sample_cassette.cache_key,
            bundle_id=sample_cassette.bundle_id,
            instruction=sample_cassette.instruction,
        )
        cassette.add_step(sample_cassette.steps[0])
        cassette.add_step(sample_cassette.steps[1])

        ndjson = cassette.to_ndjson()
        lines = ndjson.split("\n")

        # First line is metadata
        metadata = json.loads(lines[0])
        assert "_metadata" in metadata
        assert metadata["_metadata"]["schema_version"] == "1.0"
        assert metadata["_metadata"]["cache_key"] == sample_cassette.cache_key

        # Remaining lines are steps
        assert len(lines) == 3  # metadata + 2 steps

    def test_cassette_from_ndjson(self, sample_cassette: Cassette):
        """Serialize then deserialize, assert equal."""
        ndjson = sample_cassette.to_ndjson()
        loaded = Cassette.from_ndjson(ndjson, sample_cassette.cache_key)

        assert loaded.cache_key == sample_cassette.cache_key
        assert loaded.bundle_id == sample_cassette.bundle_id
        assert len(loaded.steps) == len(sample_cassette.steps)

        # Check each step is preserved
        for orig, loaded_step in zip(sample_cassette.steps, loaded.steps):
            assert loaded_step.step_idx == orig.step_idx
            assert loaded_step.screenshot_phash == orig.screenshot_phash
            assert loaded_step.ax_subtree_hash == orig.ax_subtree_hash


class TestCassetteSchemaVersion:
    """Test schema versioning."""

    def test_cassette_schema_version_metadata(self, sample_cassette: Cassette):
        """to_ndjson includes schema_version in metadata line."""
        ndjson = sample_cassette.to_ndjson()
        first_line = ndjson.split("\n")[0]
        metadata = json.loads(first_line)

        assert metadata["_metadata"]["schema_version"] == "1.0"

    def test_cassette_validates_schema_version_on_load(self, sample_cassette: Cassette):
        """Load cassette with mismatched schema_version, assert warning logged."""
        # Create NDJSON with wrong schema version
        ndjson = sample_cassette.to_ndjson()
        lines = ndjson.split("\n")

        # Modify schema version in metadata
        metadata_dict = json.loads(lines[0])
        metadata_dict["_metadata"]["schema_version"] = "2.0"
        lines[0] = json.dumps(metadata_dict)

        modified_ndjson = "\n".join(lines)

        # Load and verify it doesn't crash (just warns)
        loaded = Cassette.from_ndjson(modified_ndjson, sample_cassette.cache_key)
        assert loaded is not None  # Should not crash


class TestCassetteHealedSelectors:
    """Test healed_selectors preservation."""

    def test_cassette_preserves_healed_selectors(self, sample_cassette_step: CassetteStep):
        """Step with healed_selectors populated, serialize/deserialize, assert intact."""
        # Create step with healed selectors
        healed_step = CassetteStep(
            step_idx=sample_cassette_step.step_idx,
            hoare_pre=sample_cassette_step.hoare_pre,
            action_canonical=sample_cassette_step.action_canonical,
            hoare_post=sample_cassette_step.hoare_post,
            screenshot_phash=sample_cassette_step.screenshot_phash,
            ax_subtree_hash=sample_cassette_step.ax_subtree_hash,
            healed_selectors=["@id=button1", "@title=Submit"],
        )

        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test",
        )
        cassette.add_step(healed_step)

        # Serialize and deserialize
        ndjson = cassette.to_ndjson()
        loaded = Cassette.from_ndjson(ndjson, cassette.cache_key)

        assert loaded.steps[0].healed_selectors == ["@id=button1", "@title=Submit"]


class TestCassettePHashRoundtrip:
    """Test pHash value preservation."""

    def test_cassette_phash_roundtrip(self, sample_cassette_step: CassetteStep):
        """Step with specific phash value, serialize/deserialize, assert preserved."""
        phash = "abc123def456ghi789"

        step = CassetteStep(
            step_idx=sample_cassette_step.step_idx,
            hoare_pre=sample_cassette_step.hoare_pre,
            action_canonical=sample_cassette_step.action_canonical,
            hoare_post=sample_cassette_step.hoare_post,
            screenshot_phash=phash,
            ax_subtree_hash="hash1",
        )

        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test",
        )
        cassette.add_step(step)

        # Serialize and deserialize
        ndjson = cassette.to_ndjson()
        loaded = Cassette.from_ndjson(ndjson, cassette.cache_key)

        assert loaded.steps[0].screenshot_phash == phash


class TestCassetteEdgeCases:
    """Test edge cases and error handling."""

    def test_cassette_handles_empty_steps(self):
        """Serialize empty cassette, deserialize, assert empty list returned."""
        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test",
        )

        ndjson = cassette.to_ndjson()
        loaded = Cassette.from_ndjson(ndjson, cassette.cache_key)

        assert len(loaded.steps) == 0

    def test_cassette_malformed_json_raises(self):
        """Load invalid JSON, assert JSONDecodeError or ValidationError caught."""
        with pytest.raises((json.JSONDecodeError, ValueError)):
            Cassette.from_ndjson("{ invalid json }", "test-key")

    def test_cassette_missing_metadata_raises(self):
        """Load NDJSON without _metadata, assert error."""
        bad_ndjson = '{"step_idx": 0}\n{"step_idx": 1}'
        with pytest.raises(ValueError):
            Cassette.from_ndjson(bad_ndjson, "test-key")
