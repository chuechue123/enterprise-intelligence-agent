"""Synthetic and runtime data support for BizInsight Agent."""

from bizinsight.data.generator import (
    DEFAULT_SEED,
    TABLE_ROW_TARGETS,
    GeneratedPaths,
    SyntheticDataset,
    calculate_core_metrics,
    dataset_fingerprint,
    generate_dataset,
    write_dataset,
)

__all__ = [
    "DEFAULT_SEED",
    "TABLE_ROW_TARGETS",
    "GeneratedPaths",
    "SyntheticDataset",
    "calculate_core_metrics",
    "dataset_fingerprint",
    "generate_dataset",
    "write_dataset",
]
