"""Tests for SPI capabilities integrated into AppProfile (Wave 0).

Per Task 2 acceptance criteria: AppProfile has 8 spi_*_available fields.
"""
import pytest
from cua_overlay.profile.classifier import AppProfile


def test_app_profile_has_spi_fields():
    """AppProfile dataclass has all 8 spi_*_available fields."""
    # Check that the fields exist in the model schema
    assert hasattr(AppProfile, "__fields__") or hasattr(AppProfile, "model_fields")

    # For Pydantic v2
    if hasattr(AppProfile, "model_fields"):
        fields = AppProfile.model_fields
    else:
        fields = AppProfile.__fields__

    spi_fields = [
        "spi_skylight_available",
        "spi_ax_remote_available",
        "spi_cgs_display_space_available",
        "spi_endpoint_security_available",
        "spi_dtrace_available",
        "spi_dyld_inject_available",
        "spi_webkit_inspector_available",
        "spi_imu_available",
    ]

    for field_name in spi_fields:
        assert field_name in fields, f"Missing field: {field_name}"


def test_app_profile_spi_fields_are_bool():
    """All SPI capability fields are bool type."""
    # This just checks the type hints via inspection
    from typing import get_type_hints

    hints = get_type_hints(AppProfile)
    spi_fields = [
        "spi_skylight_available",
        "spi_ax_remote_available",
        "spi_cgs_display_space_available",
        "spi_endpoint_security_available",
        "spi_dtrace_available",
        "spi_dyld_inject_available",
        "spi_webkit_inspector_available",
        "spi_imu_available",
    ]

    for field_name in spi_fields:
        assert hints[field_name] == bool, f"Field {field_name} is not bool type"


def test_app_profile_spi_defaults_to_false():
    """All SPI capability fields default to False."""
    from datetime import datetime, timezone

    profile = AppProfile(
        bundle_id="com.test.app",
        probed_at=datetime.now(timezone.utc),
        probe_latency_ms=0,
    )

    # Check all SPI fields default to False
    assert profile.spi_skylight_available is False
    assert profile.spi_ax_remote_available is False
    assert profile.spi_cgs_display_space_available is False
    assert profile.spi_endpoint_security_available is False
    assert profile.spi_dtrace_available is False
    assert profile.spi_dyld_inject_available is False
    assert profile.spi_webkit_inspector_available is False
    assert profile.spi_imu_available is False
