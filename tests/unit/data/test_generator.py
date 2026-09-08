"""Tests for deterministic synthetic business data generation."""

from __future__ import annotations

import json
import sqlite3

from bizinsight.data.generator import (
    DEFAULT_SEED,
    TABLE_ROW_TARGETS,
    calculate_core_metrics,
    dataset_fingerprint,
    generate_dataset,
    write_dataset,
)


def test_generator_produces_expected_tables_and_row_counts() -> None:
    dataset = generate_dataset(DEFAULT_SEED)

    assert set(dataset.tables) == set(TABLE_ROW_TARGETS)
    assert {
        name: len(frame) for name, frame in dataset.tables.items()
    } == TABLE_ROW_TARGETS


def test_same_seed_produces_same_fingerprint_and_metrics() -> None:
    first = generate_dataset(DEFAULT_SEED)
    second = generate_dataset(DEFAULT_SEED)

    assert dataset_fingerprint(first) == dataset_fingerprint(second)
    assert calculate_core_metrics(first.tables) == calculate_core_metrics(
        second.tables,
    )


def test_different_seed_changes_data_without_changing_scenario_targets() -> None:
    first = generate_dataset(DEFAULT_SEED)
    second = generate_dataset(DEFAULT_SEED + 1)

    assert dataset_fingerprint(first) != dataset_fingerprint(second)
    assert first.ground_truth["scenario_targets"] == second.ground_truth[
        "scenario_targets"
    ]


def test_foreign_keys_are_complete() -> None:
    dataset = generate_dataset(DEFAULT_SEED)

    assert dataset.quality_summary["foreign_key_integrity"] == 1.0
    assert all(
        value == 0
        for value in dataset.quality_summary["orphan_counts"].values()
    )


def test_core_metrics_match_design_ranges() -> None:
    metrics = calculate_core_metrics(generate_dataset(DEFAULT_SEED).tables)

    assert 18_500_000 <= metrics["2026-Q1"]["revenue"] <= 18_900_000
    assert 16_200_000 <= metrics["2026-Q2"]["revenue"] <= 16_600_000
    assert 0.45 <= metrics["2026-Q1"]["gross_margin"] <= 0.49
    assert 0.37 <= metrics["2026-Q2"]["gross_margin"] <= 0.41
    assert 0.83 <= metrics["2026-Q1"]["renewal_rate"] <= 0.86
    assert 0.71 <= metrics["2026-Q2"]["renewal_rate"] <= 0.74
    assert 0.84 <= metrics["2026-Q1"]["on_time_acceptance_rate"] <= 0.88
    assert 0.62 <= metrics["2026-Q2"]["on_time_acceptance_rate"] <= 0.66
    assert 0.30 <= metrics["2026-Q1"]["win_rate"] <= 0.32
    assert 0.21 <= metrics["2026-Q2"]["win_rate"] <= 0.23


def test_writer_outputs_csv_sqlite_quality_and_separated_ground_truth(
    tmp_path,
) -> None:
    dataset = generate_dataset(DEFAULT_SEED)
    paths = write_dataset(dataset, tmp_path)

    for table_name, expected_count in TABLE_ROW_TARGETS.items():
        assert (paths.raw_dir / f"{table_name}.csv").is_file()
        with sqlite3.connect(paths.database_path) as connection:
            actual_count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"',
            ).fetchone()[0]
        assert actual_count == expected_count

    assert paths.quality_summary_path.is_file()
    assert paths.ground_truth_path.is_file()
    runtime_manifest = json.loads(
        paths.runtime_manifest_path.read_text(encoding="utf-8"),
    )
    assert "ground_truth" not in json.dumps(runtime_manifest)
    assert paths.ground_truth_path not in paths.runtime_inputs
