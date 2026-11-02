#!/usr/bin/env python3
"""
scripts/export_snapshot.py

Runs the complete BlockSync optimization pipeline (ML priority scoring,
task graph analysis, baseline scheduler, CP-SAT solver, metrics engine,
and explainability generator) on data/sample_dataset.csv and
data/maintenance_windows.csv.

Exports the verified schedule and metrics snapshot into
frontend/src/data/snapshot.json with dataset hash, timestamp, and solver invariants.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from optimizer.baseline import schedule_greedy
from optimizer.explain import ExplainabilityEngine
from optimizer.graph import TaskGraphBuilder
from optimizer.metrics import compute_schedule_metrics
from optimizer.ml_priority import get_ml_priority_model
from optimizer.solver import BlockOptimizerSolver


def compute_dataset_hash(tasks_path: Path, windows_path: Path) -> str:
    """Computes SHA-256 hash across both raw dataset files."""
    hasher = hashlib.sha256()
    with open(tasks_path, "rb") as f:
        hasher.update(f.read())
    with open(windows_path, "rb") as f:
        hasher.update(f.read())
    return f"sha256:{hasher.hexdigest()}"


def generate_snapshot(
    tasks_path: Path = Path("data/sample_dataset.csv"),
    windows_path: Path = Path("data/maintenance_windows.csv"),
) -> Dict[str, Any]:
    """Executes the pipeline and returns the snapshot dictionary."""
    if not tasks_path.exists() or not windows_path.exists():
        raise FileNotFoundError(f"Missing dataset files: {tasks_path} or {windows_path}")

    dataset_hash = compute_dataset_hash(tasks_path, windows_path)

    # 1. Load data
    tasks_df = pd.read_csv(tasks_path)
    raw_windows_df = pd.read_csv(windows_path)

    # Ensure windows_df has expected column names for solver
    windows_df = pd.DataFrame([
        {
            "id": row["id"],
            "section_id": row["section_id"],
            "start_minute": int(row.get("start_minute", row.get("start_time"))),
            "end_minute": int(row.get("end_minute", row.get("end_time"))),
            "available_duration_minutes": int(row.get("available_duration_minutes", int(row.get("end_minute", row.get("end_time"))) - int(row.get("start_minute", row.get("start_time"))))),
            "source": row.get("source", "derived_from_timetable"),
        }
        for _, row in raw_windows_df.iterrows()
    ])

    # 2. ML Priority Scoring
    ml_model = get_ml_priority_model()
    scored_tasks_df, ml_explanations = ml_model.score_tasks(tasks_df)
    ml_metadata = {
        "metrics": ml_model.metrics,
        "feature_importances": ml_model.feature_importances,
        "metadata": ml_model.training_metadata,
    }

    # 3. Graph Edge Detection
    graph_builder = TaskGraphBuilder(scored_tasks_df)
    conflicts_raw = graph_builder.get_conflicts()
    synergies_raw = graph_builder.get_synergies()

    conflicts = [
        {"task_id_1": u, "task_id_2": v, "reason": r}
        for u, v, r in conflicts_raw
    ]
    synergies = [
        {"task_id_1": u, "task_id_2": v, "reason": r}
        for u, v, r in synergies_raw
    ]

    # 4. Baseline Greedy Schedule & Metrics
    baseline_schedule = schedule_greedy(scored_tasks_df, windows_df)
    baseline_metrics = compute_schedule_metrics(baseline_schedule, scored_tasks_df, windows_df)

    # 5. CP-SAT Solver
    solver = BlockOptimizerSolver(scored_tasks_df, windows_df)
    schedule, status, infeasible_reasons, trace = solver.solve()
    objective_val = float(solver.solver.ObjectiveValue()) if status in ("OPTIMAL", "FEASIBLE") else None
    opt_metrics = compute_schedule_metrics(schedule, scored_tasks_df, windows_df)

    # 6. Explainability Engine
    explanations = []
    if schedule and status in ("OPTIMAL", "FEASIBLE"):
        explainer = ExplainabilityEngine(scored_tasks_df, windows_df)
        explanations = explainer.generate_explanations(schedule, trace)

    # 7. Convert tasks and windows to clean dicts
    tasks_list = []
    for _, row in scored_tasks_df.iterrows():
        tasks_list.append({
            "id": str(row["id"]),
            "department": str(row["department"]),
            "section_id": str(row["section_id"]),
            "duration_minutes": int(row["duration_minutes"]),
            "criticality": int(row["criticality"]),
            "due_date": str(row["due_date"]),
            "status": str(row.get("status", "pending")),
            "description": str(row.get("description", "")),
            "ml_priority_score": float(row.get("ml_priority_score", 0.0)),
            "effective_priority": int(row.get("effective_priority", row["criticality"])),
        })

    windows_list = []
    for _, row in raw_windows_df.iterrows():
        windows_list.append({
            "id": str(row["id"]),
            "section_id": str(row["section_id"]),
            "start_time": int(row.get("start_time", row.get("start_minute"))),
            "end_time": int(row.get("end_time", row.get("end_minute"))),
            "source": str(row.get("source", "derived_from_timetable")),
        })

    schedule_list = [s.model_dump() if hasattr(s, "model_dump") else s for s in schedule]
    baseline_list = [b.model_dump() if hasattr(b, "model_dump") else b for b in baseline_schedule]

    metrics_dict = opt_metrics.model_dump() if hasattr(opt_metrics, "model_dump") else opt_metrics
    baseline_metrics_dict = baseline_metrics.model_dump() if hasattr(baseline_metrics, "model_dump") else baseline_metrics

    snapshot = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_hash": dataset_hash,
        "status": status,
        "objective_value": objective_val,
        "tasks": tasks_list,
        "windows": windows_list,
        "schedule": schedule_list,
        "baseline_schedule": baseline_list,
        "metrics": metrics_dict,
        "baseline_metrics": baseline_metrics_dict,
        "explanations": [e.model_dump() if hasattr(e, "model_dump") else e for e in explanations],
        "conflicts": conflicts,
        "synergies": synergies,
        "ml_metadata": ml_metadata,
        "ml_explanations": ml_explanations,
    }
    return snapshot


def main():
    repo_root = Path(__file__).resolve().parent.parent
    tasks_path = repo_root / "data" / "sample_dataset.csv"
    windows_path = repo_root / "data" / "maintenance_windows.csv"
    output_path = repo_root / "frontend" / "src" / "data" / "snapshot.json"

    print(f"Exporting snapshot from {tasks_path} and {windows_path}...")
    snapshot = generate_snapshot(tasks_path, windows_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Verified snapshot successfully written to {output_path}")
    print(f"  Solver Status:    {snapshot['status']}")
    print(f"  Objective Value:  {snapshot['objective_value']}")
    print(f"  Tasks Scheduled:  {snapshot['metrics']['total_tasks_scheduled']}")
    print(f"  Blocks Used:      {snapshot['metrics']['total_blocks_used']}")
    print(f"  Bundled Pairs:    {snapshot['metrics']['bundled_task_pairs']}")
    print(f"  Dataset Hash:     {snapshot['dataset_hash']}")


if __name__ == "__main__":
    main()
