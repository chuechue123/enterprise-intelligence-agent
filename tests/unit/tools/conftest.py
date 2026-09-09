"""Shared fixtures for deterministic analytics tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from bizinsight.data.generator import generate_dataset, write_dataset


@pytest.fixture(scope="session")
def generated_database_path(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    root = tmp_path_factory.mktemp("business-data")
    return write_dataset(generate_dataset(), root).database_path
