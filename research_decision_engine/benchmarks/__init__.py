"""Deterministic benchmark suite for Research Decision Engine Core."""

from research_decision_engine.benchmarks.worlds import (
    BENCHMARK_VERSION,
    BenchmarkDesign,
    BenchmarkWorldConfig,
    all_benchmark_world_ids,
    benchmark_world_ids,
    benchmark_worlds,
    lookahead_benchmark_world_ids,
    paired_evaluation_worlds,
)

__all__ = [
    "BENCHMARK_VERSION",
    "BenchmarkDesign",
    "BenchmarkWorldConfig",
    "all_benchmark_world_ids",
    "benchmark_world_ids",
    "benchmark_worlds",
    "lookahead_benchmark_world_ids",
    "paired_evaluation_worlds",
]
