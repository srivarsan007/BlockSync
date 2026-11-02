"""
tests/test_snapshot_drift.py

Verifies that the committed offline snapshot in frontend/src/data/snapshot.json
matches a fresh optimization run on the sample dataset.

Per Step 1c requirements:
- generated_at is NOT asserted (timestamps differ across runs).
- exact start minutes, downtime minutes, and per-task windows are NOT asserted.
- Compares only solver invariants:
    1. Solver status (e.g. OPTIMAL)
    2. Objective value
    3. Number of blocks used (metrics.total_blocks_used)
    4. Number of bundled pairs (metrics.bundled_task_pairs)
    5. Number of tasks scheduled (metrics.total_tasks_scheduled)
    6. Dataset SHA-256 hash
"""

import json
from pathlib import Path
import pytest

from scripts.export_snapshot import generate_snapshot, compute_dataset_hash


def test_snapshot_exists_and_valid():
    repo_root = Path(__file__).resolve().parent.parent
    snapshot_path = repo_root / "frontend" / "src" / "data" / "snapshot.json"
    assert snapshot_path.exists(), f"Snapshot file not found at {snapshot_path}"

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Core metadata present
    assert "generated_at" in data
    assert "dataset_hash" in data
    assert "status" in data
    assert "objective_value" in data
    assert "tasks" in data and len(data["tasks"]) == 9
    assert "windows" in data and len(data["windows"]) == 3
    assert "schedule" in data and len(data["schedule"]) > 0
    assert "baseline_schedule" in data and len(data["baseline_schedule"]) > 0
    assert "metrics" in data
    assert "baseline_metrics" in data
    assert "explanations" in data
    assert "conflicts" in data
    assert "synergies" in data
    assert "ml_metadata" in data
    assert "ml_explanations" in data


def test_snapshot_invariants_no_drift():
    repo_root = Path(__file__).resolve().parent.parent
    snapshot_path = repo_root / "frontend" / "src" / "data" / "snapshot.json"
    tasks_path = repo_root / "data" / "sample_dataset.csv"
    windows_path = repo_root / "data" / "maintenance_windows.csv"

    with open(snapshot_path, "r", encoding="utf-8") as f:
        committed = json.load(f)

    # Fresh run against dataset files
    fresh = generate_snapshot(tasks_path, windows_path)

    # 1. Dataset hash invariant
    expected_hash = compute_dataset_hash(tasks_path, windows_path)
    assert committed["dataset_hash"] == expected_hash, "Committed snapshot dataset_hash does not match current raw dataset"
    assert fresh["dataset_hash"] == committed["dataset_hash"]

    # 2. Solver status invariant
    assert committed["status"] == fresh["status"], f"Status drift: {committed['status']} vs fresh {fresh['status']}"
    assert committed["status"] in ("OPTIMAL", "FEASIBLE")

    # 3. Objective value invariant
    assert committed["objective_value"] == pytest.approx(fresh["objective_value"], rel=1e-4), (
        f"Objective value drift: {committed['objective_value']} vs fresh {fresh['objective_value']}"
    )

    # 4. Total tasks scheduled invariant
    assert committed["metrics"]["total_tasks_scheduled"] == fresh["metrics"]["total_tasks_scheduled"]

    # 5. Number of blocks used invariant
    assert committed["metrics"]["total_blocks_used"] == fresh["metrics"]["total_blocks_used"]

    # 6. Number of bundled task pairs invariant
    assert committed["metrics"]["bundled_task_pairs"] == fresh["metrics"]["bundled_task_pairs"]
