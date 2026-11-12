"""
Ground Truth Evaluation Module for PlantOps.

Reads isolated `data/ground_truth/ground_truth.json` (or `.csv`) ONLY during
evaluation to compare actual detector outputs against expected anomaly labels
and compute TP, FP, TN, FN, Precision, Recall, and F1 Score.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.validators.anomaly_detector import (
    detect_schedule_anomalies,
    evaluate_isolated_scenarios,
)


def load_ground_truth(gt_path: Path | None = None) -> list[dict[str, Any]]:
    path = gt_path or (PROJECT_ROOT / "data" / "ground_truth" / "ground_truth.json")
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_against_ground_truth(
    db: Session,
    gt_path: Path | None = None,
    scenarios_path: Path | None = None,
) -> dict[str, Any]:
    """
    Compare actual detected anomalies (baseline schedules + isolated scenarios)
    against isolated ground truth labels.
    """
    ground_truth_rows = load_ground_truth(gt_path)

    # Run actual detector (never receives ground_truth as input)
    baseline_detected = detect_schedule_anomalies(db)
    scenario_detected = evaluate_isolated_scenarios(db, scenarios_path=scenarios_path)
    all_detected = baseline_detected + scenario_detected

    detected_keys = {
        (item["issue_type"], item["entity_type"], str(item["entity_id"]))
        for item in all_detected
    }

    tp = 0
    fp = 0
    tn = 0
    fn = 0
    details: list[dict[str, Any]] = []

    matched_detected_keys: set[tuple[str, str, str]] = set()
    for gt in ground_truth_rows:
        expected_anom = bool(gt["expected_is_anomaly"])
        key = (gt["issue_type"], gt["entity_type"], str(gt["entity_id"]))

        if expected_anom:
            is_detected = key in detected_keys
            if is_detected:
                tp += 1
                matched_detected_keys.add(key)
                outcome = "TP"
            else:
                fn += 1
                outcome = "FN"
        else:
            # Negative ground truth row (clean baseline schedule)
            any_for_entity = any(
                d["entity_type"] == gt["entity_type"] and str(d["entity_id"]) == str(gt["entity_id"])
                for d in baseline_detected
            )
            if any_for_entity:
                fp += 1
                outcome = "FP"
            else:
                tn += 1
                outcome = "TN"

        details.append(
            {
                "gt_id": gt["gt_id"],
                "scenario_name": gt["scenario_name"],
                "issue_type": gt["issue_type"],
                "entity_type": gt["entity_type"],
                "entity_id": gt["entity_id"],
                "expected_is_anomaly": expected_anom,
                "actual_detected": outcome in ("TP", "FP"),
                "outcome": outcome,
            }
        )

    # Any unexpected baseline detections not in ground truth count as False Positives
    for det in baseline_detected:
        k = (det["issue_type"], det["entity_type"], str(det["entity_id"]))
        if k not in matched_detected_keys:
            # Avoid double counting if already counted via negative GT row
            if not any(
                g["entity_type"] == det["entity_type"]
                and str(g["entity_id"]) == str(det["entity_id"])
                and not bool(g["expected_is_anomaly"])
                for g in ground_truth_rows
            ):
                fp += 1

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1_score = (
        round((2 * precision * recall) / (precision + recall), 4)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "total_ground_truth_records": len(ground_truth_rows),
        "baseline_anomalies_detected": len(baseline_detected),
        "scenario_anomalies_detected": len(scenario_detected),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "comparisons": details,
    }

