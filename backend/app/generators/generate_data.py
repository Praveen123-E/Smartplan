"""
Deterministic Synthetic Data Generator for PlantOps (Fixed Seed: 20261022).

Generates reproducible starter or full-scale manufacturing datasets following
the exact 16-step dependency order so all parent records exist before children.

Usage:
    python -m app.generators.generate_data --scale starter --seed 20261022
    python -m app.generators.generate_data --scale full --seed 20261022
    python -m app.generators.generate_data --scale full --seed 20261022 --load-db
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import random
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import PROJECT_ROOT
from app.utils.id_generator import (
    format_anomaly_id,
    format_machine_id,
    format_material_id,
    format_order_id,
    format_order_operation_id,
    format_product_id,
    format_routing_id,
    format_run_id,
    format_schedule_id,
    format_tooling_id,
)


# Fixed reference timeline so repeated runs produce identical timestamps & checksums
BASE_TIMESTAMP = datetime(2026, 11, 16, 8, 0, 0)
BASE_DATE = date(2026, 11, 16)
DEFAULT_SEED = 20261022

SCALE_CONFIG = {
    "starter": {
        "num_products": 10,
        "num_machines": 8,
        "num_orders": 30,
        "ops_per_order": 4,
        "num_materials": 25,
        "horizon_days": 10,
        "baseline_scheduled_orders": 6,
    },
    "full": {
        "num_products": 100,
        "num_machines": 40,
        "num_orders": 500,
        "ops_per_order": 4,  # 500 * 4 = 2,000 operations
        "num_materials": 200,
        "horizon_days": 14,
        "baseline_scheduled_orders": 20,
    },
}

PRODUCT_CATEGORIES = [
    "Powertrain",
    "Hydraulic Assembly",
    "Precision Fasteners",
    "Chassis Components",
    "Thermal Modules",
]

MACHINE_SPECS = [
    ("Laser Cutter", "Cutting", "WC-CUTTING"),
    ("CNC Lathe", "Machining", "WC-MACHINING"),
    ("CNC Mill", "Machining", "WC-MACHINING"),
    ("Radial Drill", "Drilling", "WC-DRILLING"),
    ("Surface Grinder", "Grinding", "WC-FINISHING"),
    ("Welding Cell", "Welding", "WC-JOINING"),
    ("Assembly Station", "Assembly", "WC-ASSEMBLY"),
    ("CMM Tester", "Inspection", "WC-QUALITY"),
]

MASTER_OPERATIONS = [
    ("OP-STD-001", "Laser Blank Cutting", "Cutting", 10, 1.5, 1, "TOOL-001"),
    ("OP-STD-002", "CNC Precision Turning", "Machining", 15, 2.5, 1, "TOOL-002"),
    ("OP-STD-003", "CNC Multi-Axis Milling", "Machining", 20, 3.0, 1, "TOOL-003"),
    ("OP-STD-004", "Precision Drilling", "Drilling", 10, 1.5, 1, None),
    ("OP-STD-005", "Surface Grinding", "Grinding", 15, 2.0, 1, None),
    ("OP-STD-006", "Robotic Welding", "Welding", 15, 2.2, 2, "TOOL-004"),
    ("OP-STD-007", "Sub-Assembly", "Assembly", 10, 2.0, 2, "TOOL-005"),
    ("OP-STD-008", "CMM Quality Inspection", "Inspection", 5, 1.0, 1, "TOOL-006"),
]

MATERIAL_CATEGORIES = [
    ("Raw Metal", "kg"),
    ("Fastener", "pcs"),
    ("Electronic", "pcs"),
    ("Polymer", "kg"),
    ("Coating", "liters"),
]


def _iso_dt(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


def _iso_date(value: date | None) -> str | None:
    return value.strftime("%Y-%m-%d") if value is not None else None


def _iso_time(value: time | None) -> str | None:
    return value.strftime("%H:%M:%S") if value is not None else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_dataset(scale: str = "full", seed: int = DEFAULT_SEED) -> dict[str, list[dict[str, Any]]]:
    """
    Generate the complete synthetic PlantOps dataset in memory as ordered tables.

    Uses fixed `random.Random(seed)` and `np.random.default_rng(seed)` so repeated
    invocations with the same `(scale, seed)` return identical records.
    """
    if scale not in SCALE_CONFIG:
        raise ValueError(f"Unsupported scale '{scale}'. Choose from {list(SCALE_CONFIG.keys())}.")

    cfg = SCALE_CONFIG[scale]
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    ts_str = _iso_dt(BASE_TIMESTAMP)

    # ------------------------------------------------------------------
    # Step 1: Generate Products
    # ------------------------------------------------------------------
    products: list[dict[str, Any]] = []
    for i in range(1, cfg["num_products"] + 1):
        prod_id = format_product_id(i, 2026)
        sku = f"SKU-{i:04d}"
        cat = PRODUCT_CATEGORIES[(i - 1) % len(PRODUCT_CATEGORIES)]
        products.append(
            {
                "product_id": prod_id,
                "sku": sku,
                "name": f"{cat.split()[0]} Unit Model {i:03d}",
                "category": cat,
                "unit_of_measure": "pcs",
                "standard_batch_size": int(rng.choice([10, 20, 25, 50])),
                "description": f"Synthetic manufactured SKU {sku} in {cat}.",
                "status": "Active",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # ------------------------------------------------------------------
    # Step 2: Generate Routings (1 active routing per product)
    # ------------------------------------------------------------------
    routings: list[dict[str, Any]] = []
    for prod in products:
        routings.append(
            {
                "routing_id": format_routing_id(prod["sku"], "01"),
                "product_id": prod["product_id"],
                "version": "01",
                "name": f"Standard Routing for {prod['sku']}",
                "is_active": True,
                "effective_from": "2026-01-01",
                "effective_to": None,
                "status": "Active",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # ------------------------------------------------------------------
    # Step 3: Shared Tooling, Master Operations & Routing Operations
    # ------------------------------------------------------------------
    shared_tooling: list[dict[str, Any]] = []
    for t_idx in range(1, 7):
        shared_tooling.append(
            {
                "tooling_id": format_tooling_id(t_idx),
                "name": f"Precision Fixture Set {t_idx:02d}",
                "tool_type": rng.choice(["Fixture", "Die", "Jig", "Calibration Gauge"]),
                "total_quantity": 3 if t_idx <= 4 else 2,
                "available_quantity": 3 if t_idx <= 4 else 2,
                "status": "Available",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    operations: list[dict[str, Any]] = []
    for code, name, op_type, setup_m, run_m, labor_cnt, tool_id in MASTER_OPERATIONS:
        operations.append(
            {
                "operation_code": code,
                "name": name,
                "operation_type": op_type,
                "description": f"Standard {op_type.lower()} step: {name}",
                "default_setup_minutes": setup_m,
                "default_run_minutes_per_unit": run_m,
                "required_labor_count": labor_cnt,
                "tooling_id": tool_id,
                "status": "Active",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # Each routing gets 4 sequential steps:
    # Step 1: Cutting -> Step 2: Turning or Milling -> Step 3: Drilling/Grinding/Welding/Assembly -> Step 4: Inspection
    routing_operations: list[dict[str, Any]] = []
    ro_id = 1
    for idx, routing in enumerate(routings):
        step_codes = [
            "OP-STD-001",
            "OP-STD-002" if idx % 2 == 0 else "OP-STD-003",
            rng.choice(["OP-STD-004", "OP-STD-005", "OP-STD-006", "OP-STD-007"]),
            "OP-STD-008",
        ]
        for seq, op_code in enumerate(step_codes, start=1):
            op_meta = next(o for o in operations if o["operation_code"] == op_code)
            routing_operations.append(
                {
                    "id": ro_id,
                    "routing_id": routing["routing_id"],
                    "operation_code": op_code,
                    "sequence_number": seq,
                    "duration_per_unit_minutes": round(
                        op_meta["default_run_minutes_per_unit"] * float(np_rng.uniform(0.9, 1.2)), 2
                    ),
                    "setup_minutes": op_meta["default_setup_minutes"],
                    "labor_required": op_meta["required_labor_count"],
                    "tooling_id": op_meta["tooling_id"],
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            ro_id += 1

    # ------------------------------------------------------------------
    # Step 4: Generate Machines
    # ------------------------------------------------------------------
    machines: list[dict[str, Any]] = []
    for m_idx in range(1, cfg["num_machines"] + 1):
        m_type, op_type_cap, wc = MACHINE_SPECS[(m_idx - 1) % len(MACHINE_SPECS)]
        # Only mark the last machine as Maintenance if another machine shares its capability
        has_backup = cfg["num_machines"] > len(MACHINE_SPECS)
        status = "Maintenance" if (m_idx == cfg["num_machines"] and has_backup) else "Available"
        machines.append(
            {
                "machine_id": format_machine_id(m_idx),
                "name": f"{m_type} #{m_idx:02d}",
                "machine_type": m_type,
                "work_center": wc,
                "capacity_per_hour": round(float(rng.uniform(10.0, 25.0)), 1),
                "concurrent_job_capacity": 1,
                "capabilities": op_type_cap,
                "hourly_operating_cost": round(float(rng.uniform(40.0, 110.0)), 2),
                "status": status,
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # ------------------------------------------------------------------
    # Step 5: Generate Machine Eligibility
    # ------------------------------------------------------------------
    operation_machine_eligibility: list[dict[str, Any]] = []
    elig_id = 1
    for op in operations:
        matching_machines = [m for m in machines if m["capabilities"] == op["operation_type"]]
        for m_pos, mach in enumerate(matching_machines):
            operation_machine_eligibility.append(
                {
                    "id": elig_id,
                    "operation_code": op["operation_code"],
                    "machine_id": mach["machine_id"],
                    "efficiency_factor": round(float(rng.choice([0.95, 1.0, 1.05, 1.1])), 2),
                    "is_preferred": m_pos == 0,
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            elig_id += 1

    # ------------------------------------------------------------------
    # Step 6: Generate Machine Calendars & Planned Downtime
    # ------------------------------------------------------------------
    machine_calendars: list[dict[str, Any]] = []
    cal_id = 1
    holiday_date = BASE_DATE + timedelta(days=6)  # Plant maintenance/public holiday
    for mach in machines:
        for d_offset in range(cfg["horizon_days"]):
            cal_date = BASE_DATE + timedelta(days=d_offset)
            day_name = cal_date.strftime("%A")
            is_holiday = cal_date == holiday_date
            is_sunday = day_name == "Sunday"
            is_working = not (is_holiday or is_sunday)
            avail_mins = 450 if is_working else 0  # 08:00-16:00 (480) minus 30m break (12:00-12:30)
            machine_calendars.append(
                {
                    "calendar_id": cal_id,
                    "machine_id": mach["machine_id"],
                    "calendar_date": _iso_date(cal_date),
                    "day_of_week": day_name,
                    "is_working_day": is_working,
                    "is_holiday": is_holiday,
                    "shift_name": "Day Shift",
                    "shift_start_time": "08:00:00",
                    "shift_end_time": "16:00:00",
                    "break_start_time": "12:00:00",
                    "break_end_time": "12:30:00",
                    "available_minutes": avail_mins,
                    "notes": "Plant Holiday" if is_holiday else ("Weekend" if is_sunday else "Regular Shift"),
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            cal_id += 1

    machine_downtime: list[dict[str, Any]] = []
    for dt_idx in range(1, min(6, len(machines)) + 1):
        mach = machines[dt_idx]  # MACH-002 .. MACH-006
        dt_day = BASE_DATE + timedelta(days=dt_idx % 4 + 1)
        start_dt = datetime.combine(dt_day, time(13, 0))
        end_dt = datetime.combine(dt_day, time(15, 0))
        machine_downtime.append(
            {
                "downtime_id": dt_idx,
                "machine_id": mach["machine_id"],
                "downtime_type": "Planned Maintenance" if dt_idx % 2 == 1 else "Calibration",
                "start_time": _iso_dt(start_dt),
                "end_time": _iso_dt(end_dt),
                "reason": "Preventive spindle & safety check",
                "reported_by": "maint_eng",
                "status": "Scheduled",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # ------------------------------------------------------------------
    # Step 7: Generate Labor Shifts & Labor Resources
    # ------------------------------------------------------------------
    labor_shifts: list[dict[str, Any]] = []
    shift_id = 1
    for d_offset in range(cfg["horizon_days"]):
        s_date = BASE_DATE + timedelta(days=d_offset)
        if s_date.strftime("%A") == "Sunday" or s_date == holiday_date:
            continue
        labor_shifts.append(
            {
                "shift_id": shift_id,
                "shift_name": "Day Shift",
                "shift_date": _iso_date(s_date),
                "start_time": "08:00:00",
                "end_time": "16:00:00",
                "break_minutes": 30,
                "total_headcount": max(12, cfg["num_machines"]),
                "available_headcount": max(10, cfg["num_machines"] - 2),
                "status": "Active",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )
        shift_id += 1

    labor_resources: list[dict[str, Any]] = []
    first_shift_id = labor_shifts[0]["shift_id"] if labor_shifts else 1
    for emp_idx in range(1, min(25, cfg["num_machines"]) + 1):
        labor_resources.append(
            {
                "labor_id": emp_idx,
                "employee_code": f"EMP-{emp_idx:03d}",
                "full_name": f"Operator {emp_idx:03d}",
                "skill_group": MACHINE_SPECS[(emp_idx - 1) % len(MACHINE_SPECS)][1],
                "shift_id": labor_shifts[(emp_idx - 1) % len(labor_shifts)]["shift_id"]
                if labor_shifts
                else first_shift_id,
                "is_available": True,
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

    # ------------------------------------------------------------------
    # Step 8 & 9: Generate Materials & Inventory Lots
    # ------------------------------------------------------------------
    materials: list[dict[str, Any]] = []
    inventory_lots: list[dict[str, Any]] = []
    lot_id = 1
    for mat_idx in range(1, cfg["num_materials"] + 1):
        mat_id = format_material_id(mat_idx, 2026)
        cat, unit = MATERIAL_CATEGORIES[(mat_idx - 1) % len(MATERIAL_CATEGORIES)]
        is_delayed_material = mat_idx % 20 == 0  # 5% delayed supplier deliveries
        materials.append(
            {
                "material_id": mat_id,
                "name": f"{cat} Grade-{mat_idx:03d}",
                "category": cat,
                "unit": unit,
                "unit_cost": round(float(rng.uniform(4.0, 85.0)), 2),
                "reorder_level": 100.0,
                "available_quantity": 0.0,   # Calculated in Step 14
                "reserved_quantity": 0.0,
                "consumed_quantity": 0.0,
                "stock_status": "In Stock",  # Calculated in Step 14
                "status": "Active",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

        # Create 2 inventory lots per material
        for sub_lot in (1, 2):
            qty = float(rng.choice([250.0, 400.0, 600.0, 900.0]))
            reserved = round(qty * 0.05, 2) if sub_lot == 1 else 0.0
            avail = round(qty - reserved, 2)
            delayed_flag = is_delayed_material and sub_lot == 2
            avail_date = (
                BASE_DATE + timedelta(days=5)
                if delayed_flag
                else BASE_DATE - timedelta(days=rng.randint(1, 10))
            )
            inventory_lots.append(
                {
                    "lot_id": lot_id,
                    "material_id": mat_id,
                    "lot_number": f"LOT-2026-{lot_id:06d}",
                    "initial_quantity": qty,
                    "available_quantity": avail,
                    "reserved_quantity": reserved,
                    "consumed_quantity": 0.0,
                    "availability_date": _iso_date(avail_date),
                    "expiry_date": _iso_date(BASE_DATE + timedelta(days=365)),
                    "supplier_name": f"Supplier-{(mat_idx % 8) + 1:02d}",
                    "is_delayed": delayed_flag,
                    "status": "Delayed" if delayed_flag else "Available",
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            lot_id += 1

    # ------------------------------------------------------------------
    # Step 10: Generate Material Requirements (BOM)
    # ------------------------------------------------------------------
    material_requirements: list[dict[str, Any]] = []
    mr_id = 1
    for p_idx, prod in enumerate(products):
        mat_a = materials[(p_idx * 2) % len(materials)]
        mat_b = materials[(p_idx * 2 + 1) % len(materials)]
        for chosen_mat, op_code in [(mat_a, "OP-STD-001"), (mat_b, "OP-STD-007")]:
            material_requirements.append(
                {
                    "id": mr_id,
                    "product_id": prod["product_id"],
                    "operation_code": op_code,
                    "material_id": chosen_mat["material_id"],
                    "quantity_per_unit": round(float(rng.uniform(0.5, 3.0)), 2),
                    "scrap_factor": 0.02,
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            mr_id += 1

    # ------------------------------------------------------------------
    # Step 11 & 12: Generate Production Orders & Order Operations
    # ------------------------------------------------------------------
    production_orders: list[dict[str, Any]] = []
    production_order_operations: list[dict[str, Any]] = []
    routing_ops_by_routing: dict[str, list[dict[str, Any]]] = {}
    for ro in routing_operations:
        routing_ops_by_routing.setdefault(ro["routing_id"], []).append(ro)

    for ord_idx in range(1, cfg["num_orders"] + 1):
        order_id = format_order_id(ord_idx, 2026)
        prod = products[(ord_idx - 1) % len(products)]
        routing = routings[(ord_idx - 1) % len(routings)]
        qty = int(rng.choice([10, 15, 20, 25, 30, 40]))
        priority = 1 if ord_idx % 10 == 1 else int(rng.choice([2, 3, 3, 4, 5]))
        is_urgent = priority == 1
        release_day = BASE_DATE + timedelta(days=(ord_idx - 1) % max(1, cfg["horizon_days"] - 5))
        release_dt = datetime.combine(release_day, time(8, 0))
        due_dt = release_dt + timedelta(days=rng.randint(2, 6), hours=8)

        if ord_idx <= cfg["baseline_scheduled_orders"]:
            status = "Scheduled"
        elif ord_idx % 12 == 0:
            status = "Draft"
        elif ord_idx % 7 == 0:
            status = "Planned"
        else:
            status = "Released"

        production_orders.append(
            {
                "order_id": order_id,
                "product_id": prod["product_id"],
                "routing_id": routing["routing_id"],
                "quantity": qty,
                "completed_quantity": 0,
                "priority": priority,
                "customer_name": f"Customer-{(ord_idx % 25) + 1:02d}",
                "release_date": _iso_dt(release_dt),
                "due_date": _iso_dt(due_dt),
                "is_urgent": is_urgent,
                "status": status,
                "notes": "Urgent customer expedite" if is_urgent else "Standard batch order",
                "created_at": ts_str,
                "updated_at": ts_str,
            }
        )

        # Expand order into its 4 sequential operations
        for ro in routing_ops_by_routing[routing["routing_id"]]:
            planned_dur = max(15, int(round(ro["duration_per_unit_minutes"] * qty)))
            production_order_operations.append(
                {
                    "operation_id": format_order_operation_id(order_id, ro["sequence_number"]),
                    "order_id": order_id,
                    "routing_operation_id": ro["id"],
                    "operation_code": ro["operation_code"],
                    "sequence_number": ro["sequence_number"],
                    "planned_duration_minutes": planned_dur,
                    "setup_minutes": ro["setup_minutes"],
                    "labor_required": ro["labor_required"],
                    "tooling_id": ro["tooling_id"],
                    "completed_quantity": 0,
                    "actual_start_time": None,
                    "actual_end_time": None,
                    "status": "Scheduled" if status == "Scheduled" else "Pending",
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )

    # ------------------------------------------------------------------
    # Step 13: Generate Sequence-Dependent Changeover Matrix
    # ------------------------------------------------------------------
    changeover_matrix: list[dict[str, Any]] = []
    co_id = 1
    for p_from in products:
        for p_to in products:
            if p_from["product_id"] == p_to["product_id"]:
                minutes = 0
                cleaning = False
            elif p_from["category"] == p_to["category"]:
                minutes = int(rng.choice([10, 15, 20]))
                cleaning = False
            else:
                minutes = int(rng.choice([25, 30, 35, 45]))
                cleaning = True
            changeover_matrix.append(
                {
                    "id": co_id,
                    "machine_id": None,  # Plant-wide default transition
                    "from_product_id": p_from["product_id"],
                    "to_product_id": p_to["product_id"],
                    "changeover_minutes": minutes,
                    "cleaning_required": cleaning,
                    "notes": "Same SKU" if minutes == 0 else "Sequence-dependent setup",
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            co_id += 1

    # Add machine-specific changeover overrides for first 3 machines
    for mach in machines[:3]:
        for idx_p in range(min(5, len(products))):
            p_from = products[idx_p]
            p_to = products[(idx_p + 1) % len(products)]
            changeover_matrix.append(
                {
                    "id": co_id,
                    "machine_id": mach["machine_id"],
                    "from_product_id": p_from["product_id"],
                    "to_product_id": p_to["product_id"],
                    "changeover_minutes": 18,
                    "cleaning_required": True,
                    "notes": f"Machine-specific setup on {mach['machine_id']}",
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )
            co_id += 1

    # ------------------------------------------------------------------
    # Step 14: Calculate Derived Values (Material Stock Totals & Status)
    # ------------------------------------------------------------------
    lots_by_mat: dict[str, list[dict[str, Any]]] = {}
    for lot in inventory_lots:
        lots_by_mat.setdefault(lot["material_id"], []).append(lot)

    for mat in materials:
        mat_lots = lots_by_mat.get(mat["material_id"], [])
        total_avail = round(sum(l["available_quantity"] for l in mat_lots), 2)
        total_res = round(sum(l["reserved_quantity"] for l in mat_lots), 2)
        total_cons = round(sum(l["consumed_quantity"] for l in mat_lots), 2)
        has_delay = any(l["is_delayed"] for l in mat_lots)

        mat["available_quantity"] = total_avail
        mat["reserved_quantity"] = total_res
        mat["consumed_quantity"] = total_cons
        if total_avail <= 0:
            mat["stock_status"] = "Out of Stock"
        elif has_delay:
            mat["stock_status"] = "Delayed"
        elif total_avail < mat["reorder_level"]:
            mat["stock_status"] = "Low Stock"
        else:
            mat["stock_status"] = "In Stock"

    # ------------------------------------------------------------------
    # Step 15: Generate Clean Baseline Scheduling Data + RBAC Users & Audit
    # ------------------------------------------------------------------
    baseline_run_id = format_run_id(1, 2026)
    scheduling_runs: list[dict[str, Any]] = []
    operation_schedules: list[dict[str, Any]] = []
    tooling_allocations: list[dict[str, Any]] = []

    # Map helpers for clean valid baseline placement
    elig_by_op: dict[str, list[str]] = {}
    for el in operation_machine_eligibility:
        elig_by_op.setdefault(el["operation_code"], []).append(el["machine_id"])

    co_lookup = {
        (row["from_product_id"], row["to_product_id"]): row["changeover_minutes"]
        for row in changeover_matrix
        if row["machine_id"] is None
    }
    downtime_by_machine: dict[str, list[tuple[datetime, datetime]]] = {}
    for dt_row in machine_downtime:
        s_dt = datetime.strptime(dt_row["start_time"], "%Y-%m-%d %H:%M:%S")
        e_dt = datetime.strptime(dt_row["end_time"], "%Y-%m-%d %H:%M:%S")
        downtime_by_machine.setdefault(dt_row["machine_id"], []).append((s_dt, e_dt))

    machine_cursor: dict[str, datetime] = {
        m["machine_id"]: datetime.combine(BASE_DATE, time(8, 0)) for m in machines
    }
    machine_last_product: dict[str, str | None] = {m["machine_id"]: None for m in machines}
    ops_by_order: dict[str, list[dict[str, Any]]] = {}
    for op_row in production_order_operations:
        ops_by_order.setdefault(op_row["order_id"], []).append(op_row)

    sch_counter = 1
    alloc_counter = 1
    total_co_mins = 0
    total_lateness_mins = 0
    delayed_orders = 0
    latest_end = datetime.combine(BASE_DATE, time(8, 0))

    def _find_valid_slot(
        mach_id: str, earliest_start: datetime, duration_mins: int, changeover_mins: int
    ) -> tuple[datetime, datetime, datetime | None]:
        """Place an operation inside working days (08:00-12:00 or 12:30-16:00), avoiding downtime."""
        cursor = max(earliest_start, machine_cursor[mach_id])
        # Keep baseline operations concise inside shift windows
        block_dur = min(duration_mins, 180)
        total_needed = changeover_mins + block_dur

        for _ in range(40):
            # Advance past Sunday/Holiday
            while cursor.strftime("%A") == "Sunday" or cursor.date() == holiday_date:
                cursor = datetime.combine(cursor.date() + timedelta(days=1), time(8, 0))

            morning_start = datetime.combine(cursor.date(), time(8, 0))
            morning_end = datetime.combine(cursor.date(), time(12, 0))
            afternoon_start = datetime.combine(cursor.date(), time(12, 30))
            afternoon_end = datetime.combine(cursor.date(), time(16, 0))

            if cursor < morning_start:
                cursor = morning_start
            elif morning_end <= cursor < afternoon_start:
                cursor = afternoon_start
            elif cursor >= afternoon_end:
                cursor = datetime.combine(cursor.date() + timedelta(days=1), time(8, 0))
                continue

            window_end = morning_end if cursor < morning_end else afternoon_end
            candidate_end = cursor + timedelta(minutes=total_needed)
            if candidate_end > window_end:
                cursor = afternoon_start if cursor < morning_end else datetime.combine(
                    cursor.date() + timedelta(days=1), time(8, 0)
                )
                continue

            # Check downtime overlap
            overlaps_dt = False
            for dt_s, dt_e in downtime_by_machine.get(mach_id, []):
                if cursor < dt_e and candidate_end > dt_s:
                    cursor = dt_e
                    overlaps_dt = True
                    break
            if overlaps_dt:
                continue

            co_start = cursor if changeover_mins > 0 else None
            op_start = cursor + timedelta(minutes=changeover_mins)
            op_end = op_start + timedelta(minutes=block_dur)
            return op_start, op_end, co_start

        raise RuntimeError(f"Could not place baseline slot for {mach_id}")

    baseline_orders = production_orders[: cfg["baseline_scheduled_orders"]]
    for ord_row in baseline_orders:
        prev_op_end = datetime.strptime(ord_row["release_date"], "%Y-%m-%d %H:%M:%S")
        due_dt = datetime.strptime(ord_row["due_date"], "%Y-%m-%d %H:%M:%S")
        order_late = False
        order_lateness = 0

        for op_row in ops_by_order[ord_row["order_id"]]:
            eligible = [
                m_id for m_id in elig_by_op[op_row["operation_code"]]
                if next(m for m in machines if m["machine_id"] == m_id)["status"] == "Available"
            ]
            # Pick the eligible machine with the earliest cursor
            chosen_mach = min(eligible, key=lambda m_id: machine_cursor[m_id])
            prev_prod = machine_last_product[chosen_mach]
            co_mins = (
                co_lookup.get((prev_prod, ord_row["product_id"]), 15)
                if prev_prod is not None
                else 0
            )
            dur_mins = min(op_row["planned_duration_minutes"], 180)
            op_row["planned_duration_minutes"] = dur_mins

            op_start, op_end, co_start = _find_valid_slot(
                chosen_mach, prev_op_end, dur_mins, co_mins
            )

            machine_cursor[chosen_mach] = op_end
            machine_last_product[chosen_mach] = ord_row["product_id"]
            prev_op_end = op_end
            latest_end = max(latest_end, op_end)
            total_co_mins += co_mins

            lateness = max(0, int((op_end - due_dt).total_seconds() // 60))
            if lateness > 0:
                order_late = True
                order_lateness = max(order_lateness, lateness)

            sch_id = format_schedule_id(sch_counter, 2026)
            sch_counter += 1
            operation_schedules.append(
                {
                    "schedule_id": sch_id,
                    "run_id": baseline_run_id,
                    "order_id": ord_row["order_id"],
                    "order_operation_id": op_row["operation_id"],
                    "machine_id": chosen_mach,
                    "labor_shift_id": first_shift_id,
                    "start_time": _iso_dt(op_start),
                    "end_time": _iso_dt(op_end),
                    "duration_minutes": dur_mins,
                    "changeover_minutes": co_mins,
                    "changeover_start_time": _iso_dt(co_start),
                    "is_late": lateness > 0,
                    "lateness_minutes": lateness,
                    "status": "Scheduled",
                    "created_at": ts_str,
                    "updated_at": ts_str,
                }
            )

            if op_row["tooling_id"]:
                tooling_allocations.append(
                    {
                        "id": alloc_counter,
                        "schedule_id": sch_id,
                        "tooling_id": op_row["tooling_id"],
                        "allocated_quantity": 1,
                        "start_time": _iso_dt(op_start),
                        "end_time": _iso_dt(op_end),
                        "created_at": ts_str,
                        "updated_at": ts_str,
                    }
                )
                alloc_counter += 1

        if order_late:
            delayed_orders += 1
            total_lateness_mins += order_lateness

    makespan_mins = int((latest_end - datetime.combine(BASE_DATE, time(8, 0))).total_seconds() // 60)
    otd_pct = round(
        ((len(baseline_orders) - delayed_orders) / len(baseline_orders)) * 100.0, 2
    ) if baseline_orders else 100.0

    scheduling_runs.append(
        {
            "run_id": baseline_run_id,
            "run_name": f"Baseline Valid Schedule ({scale})",
            "solver_status": "Feasible",
            "objective_value": float(makespan_mins + total_lateness_mins * 3 + total_co_mins * 1.5),
            "best_bound": float(makespan_mins),
            "execution_duration_seconds": 0.42,
            "makespan_minutes": makespan_mins,
            "total_lateness_minutes": total_lateness_mins,
            "total_changeover_minutes": total_co_mins,
            "delayed_order_count": delayed_orders,
            "unscheduled_operation_count": 0,
            "on_time_delivery_pct": otd_pct,
            "avg_machine_utilization_pct": round(
                (sum(s["duration_minutes"] for s in operation_schedules) / max(1, len(machines) * 450)) * 100.0,
                2,
            ),
            "weight_makespan": 1.0,
            "weight_lateness": 3.0,
            "weight_changeover": 1.5,
            "solver_time_limit_seconds": 30,
            "infeasibility_reason": None,
            "triggered_by": "planner",
            "is_baseline": True,
            "started_at": ts_str,
            "completed_at": ts_str,
            "created_at": ts_str,
            "updated_at": ts_str,
        }
    )

    # Roles & Demo Users (password hash placeholder updated cleanly in Phase 11 auth seeder)
    roles = [
        {"role_id": 1, "name": "Admin", "description": "OT/IT Administrator", "created_at": ts_str, "updated_at": ts_str},
        {"role_id": 2, "name": "Production Planner", "description": "Production Planner", "created_at": ts_str, "updated_at": ts_str},
        {"role_id": 3, "name": "Plant Operator", "description": "Plant Operator", "created_at": ts_str, "updated_at": ts_str},
        {"role_id": 4, "name": "Maintenance/Quality Engineer", "description": "Maintenance/Quality Engineer", "created_at": ts_str, "updated_at": ts_str},
    ]
    # Pre-computed bcrypt hash for "PlantOps@2026" or deterministic placeholder replaced by security helper
    demo_users_spec = [
        ("USR-001", "admin", "admin@plantops.local", "OT/IT Admin", 1),
        ("USR-002", "planner", "planner@plantops.local", "Lead Production Planner", 2),
        ("USR-003", "operator", "operator@plantops.local", "Floor Plant Operator", 3),
        ("USR-004", "engineer", "engineer@plantops.local", "Maintenance & Quality Engineer", 4),
    ]
    # Pre-computed verified bcrypt hash of "PlantOps@2026" for deterministic demo login
    default_hash = "$2b$12$HrXZmeHHouSMY8.VNhPjc.lxb47odNAwtjfY901zVg8tv8v475Zx6"
    users = [
        {
            "user_id": uid,
            "username": uname,
            "email": email,
            "full_name": fname,
            "hashed_password": default_hash,
            "is_active": True,
            "last_login_at": None,
            "created_at": ts_str,
            "updated_at": ts_str,
        }
        for uid, uname, email, fname, _ in demo_users_spec
    ]
    user_roles = [
        {
            "id": idx,
            "user_id": uid,
            "role_id": rid,
            "created_at": ts_str,
            "updated_at": ts_str,
        }
        for idx, (uid, _, _, _, rid) in enumerate(demo_users_spec, start=1)
    ]

    state_change_events: list[dict[str, Any]] = []
    evt_id = 1
    for ord_row in production_orders[:20]:
        if ord_row["status"] == "Draft":
            continue
        state_change_events.append(
            {
                "id": evt_id,
                "entity_type": "ProductionOrder",
                "entity_id": ord_row["order_id"],
                "previous_state": "Draft",
                "new_state": "Released",
                "changed_by": "planner",
                "reason": "Order released for planning",
                "created_at": ts_str,
            }
        )
        evt_id += 1
        if ord_row["status"] in ("Planned", "Scheduled"):
            state_change_events.append(
                {
                    "id": evt_id,
                    "entity_type": "ProductionOrder",
                    "entity_id": ord_row["order_id"],
                    "previous_state": "Released",
                    "new_state": ord_row["status"],
                    "changed_by": "planner",
                    "reason": "Baseline planning transition",
                    "created_at": ts_str,
                }
            )
            evt_id += 1
    audit_logs = [
        {
            "id": 1,
            "user_id": "USR-002",
            "username": "planner",
            "action": "GENERATE_BASELINE_SCHEDULE",
            "entity_type": "SchedulingRun",
            "entity_id": baseline_run_id,
            "old_value": None,
            "new_value": f"Scheduled {len(baseline_orders)} baseline orders",
            "reason": f"Deterministic seed {seed} baseline",
            "ip_address": "127.0.0.1",
            "created_at": ts_str,
        }
    ]
    notifications = [
        {
            "id": 1,
            "user_id": "USR-002",
            "title": "Baseline Schedule Ready",
            "message": f"Baseline run {baseline_run_id} generated with {otd_pct}% OTD.",
            "severity": "Info",
            "is_read": False,
            "entity_type": "SchedulingRun",
            "entity_id": baseline_run_id,
            "created_at": ts_str,
        }
    ]

    return {
        "products": products,
        "routings": routings,
        "shared_tooling": shared_tooling,
        "operations": operations,
        "routing_operations": routing_operations,
        "machines": machines,
        "operation_machine_eligibility": operation_machine_eligibility,
        "machine_calendars": machine_calendars,
        "machine_downtime": machine_downtime,
        "labor_shifts": labor_shifts,
        "labor_resources": labor_resources,
        "materials": materials,
        "inventory_lots": inventory_lots,
        "material_requirements": material_requirements,
        "production_orders": production_orders,
        "production_order_operations": production_order_operations,
        "changeover_matrix": changeover_matrix,
        "scheduling_runs": scheduling_runs,
        "operation_schedules": operation_schedules,
        "tooling_allocations": tooling_allocations,
        "roles": roles,
        "users": users,
        "user_roles": user_roles,
        "state_change_events": state_change_events,
        "audit_logs": audit_logs,
        "notifications": notifications,
    }


def generate_anomaly_scenarios_and_ground_truth(
    dataset: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Step 16: Build separate labelled negative test scenarios (the 5 mandatory
    anomalies + extended scenarios) and isolated Ground Truth records.

    Baseline dataset records are NOT modified.
    """
    schedules = dataset["operation_schedules"]
    orders = dataset["production_orders"]
    lots = dataset["inventory_lots"]
    machines = dataset["machines"]

    first_sch = schedules[0]
    second_sch = schedules[1]
    delayed_lot = next((l for l in lots if l["is_delayed"]), lots[-1])
    downtime_row = dataset["machine_downtime"][0]

    scenarios: list[dict[str, Any]] = [
        # 5 Mandatory Negative Scenarios
        {
            "anomaly_id": format_anomaly_id(1, 2026),
            "scenario_name": "SCEN-01-MACHINE-OVERLAP",
            "issue_type": "MachineOverlap",
            "entity_type": "OperationSchedule",
            "entity_id": second_sch["schedule_id"],
            "machine_id": first_sch["machine_id"],
            "order_id": second_sch["order_id"],
            "order_operation_id": second_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": "Non-overlapping time intervals on same machine",
            "actual_result": f"Overlaps with {first_sch['schedule_id']} on {first_sch['machine_id']}",
            "simulated_start_time": first_sch["start_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Two operations scheduled concurrently on a single-capacity machine.",
        },
        {
            "anomaly_id": format_anomaly_id(2, 2026),
            "scenario_name": "SCEN-02-PRECEDENCE-VIOLATION",
            "issue_type": "PrecedenceViolation",
            "entity_type": "OperationSchedule",
            "entity_id": second_sch["schedule_id"],
            "machine_id": second_sch["machine_id"],
            "order_id": second_sch["order_id"],
            "order_operation_id": second_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": f"Step 2 starts >= Step 1 end ({first_sch['end_time']})",
            "actual_result": f"Step 2 starts before Step 1 ends ({first_sch['start_time']})",
            "simulated_start_time": first_sch["start_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Operation sequence order violated (Step 2 started before Step 1 finished).",
        },
        {
            "anomaly_id": format_anomaly_id(3, 2026),
            "scenario_name": "SCEN-03-MATERIAL-BEFORE-AVAILABILITY",
            "issue_type": "MaterialBeforeAvailability",
            "entity_type": "InventoryLot",
            "entity_id": delayed_lot["lot_number"],
            "machine_id": first_sch["machine_id"],
            "order_id": orders[0]["order_id"],
            "order_operation_id": first_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": f"Operation starts on/after material availability_date ({delayed_lot['availability_date']})",
            "actual_result": f"Operation scheduled on {first_sch['start_time'][:10]} before lot arrives",
            "simulated_start_time": first_sch["start_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Material consumed before inventory lot availability date.",
        },
        {
            "anomaly_id": format_anomaly_id(4, 2026),
            "scenario_name": "SCEN-04-OUTSIDE-SHIFT-CALENDAR",
            "issue_type": "OutsideShiftCalendar",
            "entity_type": "OperationSchedule",
            "entity_id": "SCH-SCEN-000004",
            "machine_id": first_sch["machine_id"],
            "order_id": orders[0]["order_id"],
            "order_operation_id": first_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": "Scheduled strictly inside 08:00-16:00 working shift",
            "actual_result": "Scheduled at 22:00-23:30 outside shift calendar",
            "simulated_start_time": f"{BASE_DATE.strftime('%Y-%m-%d')} 22:00:00",
            "simulated_end_time": f"{BASE_DATE.strftime('%Y-%m-%d')} 23:30:00",
            "explanation": "Operation placed outside machine working shift window.",
        },
        {
            "anomaly_id": format_anomaly_id(5, 2026),
            "scenario_name": "SCEN-05-CHANGEOVER-OMITTED",
            "issue_type": "ChangeoverOmitted",
            "entity_type": "OperationSchedule",
            "entity_id": "SCH-SCEN-000005",
            "machine_id": first_sch["machine_id"],
            "order_id": orders[1]["order_id"],
            "order_operation_id": schedules[min(4, len(schedules) - 1)]["order_operation_id"],
            "severity": "Warning",
            "expected_result": "Required changeover > 0 minutes between different SKUs",
            "actual_result": "Changeover recorded as 0 minutes between different SKUs",
            "simulated_start_time": first_sch["end_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Sequence-dependent changeover setup time was omitted.",
        },
        # Extended Negative Scenarios
        {
            "anomaly_id": format_anomaly_id(6, 2026),
            "scenario_name": "SCEN-06-DOWNTIME-CONFLICT",
            "issue_type": "MachineDowntimeConflict",
            "entity_type": "MachineDowntime",
            "entity_id": str(downtime_row["downtime_id"]),
            "machine_id": downtime_row["machine_id"],
            "order_id": orders[2]["order_id"],
            "order_operation_id": first_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": "No operations scheduled during maintenance window",
            "actual_result": f"Overlaps maintenance {downtime_row['start_time']} - {downtime_row['end_time']}",
            "simulated_start_time": downtime_row["start_time"],
            "simulated_end_time": downtime_row["end_time"],
            "explanation": "Operation overlaps planned machine maintenance downtime.",
        },
        {
            "anomaly_id": format_anomaly_id(7, 2026),
            "scenario_name": "SCEN-07-INELIGIBLE-MACHINE",
            "issue_type": "IneligibleMachine",
            "entity_type": "Machine",
            "entity_id": machines[-1]["machine_id"],
            "machine_id": machines[-1]["machine_id"],
            "order_id": orders[0]["order_id"],
            "order_operation_id": first_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": "Assigned machine must exist in OperationMachineEligibility",
            "actual_result": f"Operation assigned to ineligible machine {machines[-1]['machine_id']}",
            "simulated_start_time": first_sch["start_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Operation assigned to a machine lacking required capability.",
        },
        {
            "anomaly_id": format_anomaly_id(8, 2026),
            "scenario_name": "SCEN-08-NEGATIVE-INVENTORY",
            "issue_type": "InsufficientMaterial",
            "entity_type": "Material",
            "entity_id": dataset["materials"][0]["material_id"],
            "machine_id": first_sch["machine_id"],
            "order_id": orders[0]["order_id"],
            "order_operation_id": first_sch["order_operation_id"],
            "severity": "Critical",
            "expected_result": "Material balance >= 0",
            "actual_result": "Simulated consumption exceeds available quantity (-45.0 units)",
            "simulated_start_time": first_sch["start_time"],
            "simulated_end_time": first_sch["end_time"],
            "explanation": "Deliberate negative-inventory scenario for validation testing.",
        },
    ]

    ground_truth_rows: list[dict[str, Any]] = []
    for idx, scen in enumerate(scenarios, start=1):
        ground_truth_rows.append(
            {
                "gt_id": f"GT-{idx:03d}",
                "scenario_name": scen["scenario_name"],
                "issue_type": scen["issue_type"],
                "entity_type": scen["entity_type"],
                "entity_id": scen["entity_id"],
                "expected_is_anomaly": True,
                "expected_decision": f"Detect {scen['issue_type']}",
                "notes": scen["explanation"],
            }
        )

    # Add baseline True-Negative ground truth reference rows
    for tn_idx, base_sch in enumerate(schedules[:4], start=len(scenarios) + 1):
        ground_truth_rows.append(
            {
                "gt_id": f"GT-{tn_idx:03d}",
                "scenario_name": "BASELINE-VALID-SCHEDULE",
                "issue_type": "None",
                "entity_type": "OperationSchedule",
                "entity_id": base_sch["schedule_id"],
                "expected_is_anomaly": False,
                "expected_decision": "Valid Schedule (No Anomaly)",
                "notes": "Clean baseline schedule row verified against all hard constraints.",
            }
        )

    return scenarios, ground_truth_rows


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def export_dataset(
    dataset: dict[str, list[dict[str, Any]]],
    scenarios: list[dict[str, Any]],
    ground_truth_rows: list[dict[str, Any]],
    scale: str,
    seed: int,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """
    Export generated tables to CSV, JSON, SQL seed script, Ground Truth files,
    and `source_manifest.json` with SHA-256 checksums for reproducibility checks.
    """
    data_dir = output_root or (PROJECT_ROOT / "data")
    gen_dir = data_dir / "generated"
    csv_dir = gen_dir / "csv"
    json_dir = gen_dir / "json"
    gt_dir = data_dir / "ground_truth"

    for d in (csv_dir, json_dir, gt_dir):
        d.mkdir(parents=True, exist_ok=True)

    checksums: dict[str, str] = {}
    row_counts: dict[str, int] = {}

    # 1. Export all baseline tables to CSV & JSON using Pandas
    for table_name, rows in dataset.items():
        row_counts[table_name] = len(rows)
        df = pd.DataFrame(rows)

        csv_path = csv_dir / f"{table_name}.csv"
        df.to_csv(csv_path, index=False, lineterminator="\n")
        checksums[str(csv_path.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(csv_path)

        json_path = json_dir / f"{table_name}.json"
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        checksums[str(json_path.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(json_path)

    # 2. Export separate Anomaly Scenarios
    scen_csv = csv_dir / "anomaly_scenarios.csv"
    pd.DataFrame(scenarios).to_csv(scen_csv, index=False, lineterminator="\n")
    checksums[str(scen_csv.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(scen_csv)

    scen_json = gen_dir / "anomaly_scenarios.json"
    scen_json.write_text(json.dumps(scenarios, indent=2), encoding="utf-8")
    checksums[str(scen_json.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(scen_json)

    # 3. Export separate Ground Truth files (CSV + JSON)
    gt_csv = gt_dir / "ground_truth.csv"
    with gt_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(ground_truth_rows[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ground_truth_rows)
    checksums[str(gt_csv.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(gt_csv)

    gt_json = gt_dir / "ground_truth.json"
    gt_json.write_text(json.dumps(ground_truth_rows, indent=2), encoding="utf-8")
    checksums[str(gt_json.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(gt_json)

    # 4. Export SQL Seed Script (deterministic order)
    sql_path = gen_dir / "plantops_seed.sql"
    sql_lines = [
        "-- PlantOps Deterministic SQL Seed Script",
        f"-- Scale: {scale} | Seed: {seed}",
        "SET FOREIGN_KEY_CHECKS = 0;",
    ]
    for table_name, rows in dataset.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        col_list = ", ".join(f"`{c}`" for c in cols)
        for row in rows:
            vals = ", ".join(_sql_literal(row[c]) for c in cols)
            sql_lines.append(f"INSERT INTO `{table_name}` ({col_list}) VALUES ({vals});")
    sql_lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    sql_path.write_text("\n".join(sql_lines) + "\n", encoding="utf-8")
    checksums[str(sql_path.relative_to(data_dir)).replace("\\", "/")] = _sha256_file(sql_path)

    # 5. Export Source Manifest
    manifest = {
        "project": "PlantOps",
        "is_synthetic_only": True,
        "external_sources": [],
        "notes": "100% synthetic manufacturing dataset generated deterministically for PlantOps.",
        "scale": scale,
        "seed": seed,
        "reference_timestamp": _iso_dt(BASE_TIMESTAMP),
        "row_counts": row_counts,
        "anomaly_scenario_count": len(scenarios),
        "ground_truth_count": len(ground_truth_rows),
        "sha256_checksums": checksums,
    }
    manifest_path = gen_dir / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_dataset_to_db(dataset: dict[str, list[dict[str, Any]]], ground_truth_rows: list[dict[str, Any]], db_session) -> None:
    """
    Insert the generated dataset into a SQLAlchemy session in parent-before-child order.
    """
    from app.models import (
        AuditLog,
        ChangeoverMatrix,
        GroundTruth,
        InventoryLot,
        LaborResource,
        LaborShift,
        Machine,
        MachineCalendar,
        MachineDowntime,
        Material,
        MaterialRequirement,
        Notification,
        Operation,
        OperationMachineEligibility,
        OperationSchedule,
        Product,
        ProductionOrder,
        ProductionOrderOperation,
        Role,
        Routing,
        RoutingOperation,
        SchedulingRun,
        SharedTooling,
        StateChangeEvent,
        ToolingAllocation,
        User,
        UserRole,
    )

    table_to_model = [
        ("products", Product),
        ("routings", Routing),
        ("shared_tooling", SharedTooling),
        ("operations", Operation),
        ("routing_operations", RoutingOperation),
        ("machines", Machine),
        ("operation_machine_eligibility", OperationMachineEligibility),
        ("machine_calendars", MachineCalendar),
        ("machine_downtime", MachineDowntime),
        ("labor_shifts", LaborShift),
        ("labor_resources", LaborResource),
        ("materials", Material),
        ("inventory_lots", InventoryLot),
        ("material_requirements", MaterialRequirement),
        ("production_orders", ProductionOrder),
        ("production_order_operations", ProductionOrderOperation),
        ("changeover_matrix", ChangeoverMatrix),
        ("scheduling_runs", SchedulingRun),
        ("operation_schedules", OperationSchedule),
        ("tooling_allocations", ToolingAllocation),
        ("roles", Role),
        ("users", User),
        ("user_roles", UserRole),
        ("state_change_events", StateChangeEvent),
        ("audit_logs", AuditLog),
        ("notifications", Notification),
    ]

    # Parse ISO date/time strings back into Python objects for SQLAlchemy Date/DateTime/Time columns
    date_fields = {"effective_from", "effective_to", "calendar_date", "shift_date", "availability_date", "expiry_date"}
    time_fields = {"shift_start_time", "shift_end_time", "break_start_time", "break_end_time", "start_time", "end_time"}
    datetime_fields = {
        "created_at", "updated_at", "release_date", "due_date",
        "actual_start_time", "actual_end_time", "started_at", "completed_at",
        "changeover_start_time", "last_login_at",
    }

    for table_name, model_cls in table_to_model:
        rows = dataset.get(table_name, [])
        converted_rows = []
        for row in rows:
            item = dict(row)
            for k, v in list(item.items()):
                if v is None:
                    continue
                if k in date_fields and isinstance(v, str):
                    item[k] = date.fromisoformat(v)
                elif k in time_fields and isinstance(v, str) and len(v) == 8:
                    item[k] = time.fromisoformat(v)
                elif (k in datetime_fields or (k in time_fields and len(v) > 8)) and isinstance(v, str):
                    item[k] = datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
            converted_rows.append(model_cls(**item))
        db_session.bulk_save_objects(converted_rows)
        db_session.flush()

    gt_objs = [GroundTruth(**row) for row in ground_truth_rows]
    db_session.bulk_save_objects(gt_objs)
    db_session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="PlantOps Deterministic Synthetic Data Generator")
    parser.add_argument("--scale", choices=["starter", "full"], default="full", help="Dataset scale")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Fixed random seed")
    parser.add_argument("--load-db", action="store_true", help="Also insert generated data into configured DB")
    args = parser.parse_args()

    dataset = generate_dataset(scale=args.scale, seed=args.seed)
    scenarios, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)
    manifest = export_dataset(dataset, scenarios, gt_rows, scale=args.scale, seed=args.seed)

    if args.load_db:
        from app.database.connection import SessionLocal
        from app.database.init_db import create_tables

        create_tables()
        with SessionLocal() as session:
            load_dataset_to_db(dataset, gt_rows, session)

    print(
        f"Generated PlantOps dataset (scale={args.scale}, seed={args.seed}): "
        f"products={manifest['row_counts']['products']}, "
        f"machines={manifest['row_counts']['machines']}, "
        f"orders={manifest['row_counts']['production_orders']}, "
        f"operations={manifest['row_counts']['production_order_operations']}, "
        f"materials={manifest['row_counts']['materials']}"
    )


if __name__ == "__main__":
    main()

