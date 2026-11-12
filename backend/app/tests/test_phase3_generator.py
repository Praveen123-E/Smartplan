"""
Phase 3 Automated Tests: Verify deterministic synthetic data generation,
exact full-scale counts, business ID formats, SHA-256 reproducibility,
separate ground truth files, and foreign-key valid DB loading.
"""

from pathlib import Path
import re
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
import app.models  # noqa: F401
from app.generators.generate_data import (
    DEFAULT_SEED,
    export_dataset,
    generate_anomaly_scenarios_and_ground_truth,
    generate_dataset,
    load_dataset_to_db,
)
from app.models import (
    Machine,
    Material,
    OperationSchedule,
    Product,
    ProductionOrder,
    ProductionOrderOperation,
)


def test_full_dataset_required_counts() -> None:
    """Confirm full dataset matches exact prompt counts with seed 20261022."""
    dataset = generate_dataset(scale="full", seed=DEFAULT_SEED)

    assert len(dataset["products"]) == 100
    assert len(dataset["machines"]) == 40
    assert len(dataset["production_orders"]) == 500
    assert len(dataset["production_order_operations"]) == 2000
    assert len(dataset["materials"]) == 200
    assert len(dataset["routings"]) == 100
    assert len(dataset["operation_schedules"]) > 0


def test_starter_dataset_uses_same_generator() -> None:
    """Confirm starter scale generates valid smaller dataset."""
    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    assert len(dataset["products"]) == 10
    assert len(dataset["machines"]) == 8
    assert len(dataset["production_orders"]) == 30
    assert len(dataset["production_order_operations"]) == 120
    assert len(dataset["materials"]) == 25


def test_business_id_conventions() -> None:
    """Verify all generated business IDs match required PlantOps formats."""
    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    assert re.match(r"^PROD-2026-\d{6}$", dataset["products"][0]["product_id"])
    assert re.match(r"^ROUTE-SKU-\d{4}-01$", dataset["routings"][0]["routing_id"])
    assert re.match(r"^MACH-\d{3}$", dataset["machines"][0]["machine_id"])
    assert re.match(r"^MAT-2026-\d{6}$", dataset["materials"][0]["material_id"])
    assert re.match(r"^ORD-2026-\d{6}$", dataset["production_orders"][0]["order_id"])
    assert re.match(
        r"^OP-ORD-2026-\d{6}-\d{2}$",
        dataset["production_order_operations"][0]["operation_id"],
    )
    assert re.match(r"^SCH-2026-\d{6}$", dataset["operation_schedules"][0]["schedule_id"])


def test_reproducibility_checksums(tmp_path: Path) -> None:
    """Generate dataset twice and confirm identical row counts and SHA-256 checksums."""
    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"

    ds1 = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    sc1, gt1 = generate_anomaly_scenarios_and_ground_truth(ds1)
    manifest1 = export_dataset(ds1, sc1, gt1, scale="starter", seed=DEFAULT_SEED, output_root=run1_dir)

    ds2 = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    sc2, gt2 = generate_anomaly_scenarios_and_ground_truth(ds2)
    manifest2 = export_dataset(ds2, sc2, gt2, scale="starter", seed=DEFAULT_SEED, output_root=run2_dir)

    assert manifest1["row_counts"] == manifest2["row_counts"]
    assert manifest1["sha256_checksums"] == manifest2["sha256_checksums"]
    assert manifest1["is_synthetic_only"] is True
    assert (run1_dir / "ground_truth" / "ground_truth.csv").is_file()
    assert (run1_dir / "ground_truth" / "ground_truth.json").is_file()
    assert (run1_dir / "generated" / "plantops_seed.sql").is_file()


def test_mandatory_anomaly_scenarios_and_ground_truth() -> None:
    """Verify all 5 mandatory negative scenarios exist separately from baseline data."""
    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    scenarios, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)

    issue_types = {s["issue_type"] for s in scenarios}
    mandatory = {
        "MachineOverlap",
        "PrecedenceViolation",
        "MaterialBeforeAvailability",
        "OutsideShiftCalendar",
        "ChangeoverOmitted",
    }
    assert mandatory.issubset(issue_types)
    assert any(r["expected_is_anomaly"] is True for r in gt_rows)
    assert any(r["expected_is_anomaly"] is False for r in gt_rows)


def test_load_generated_dataset_into_fk_enforced_db() -> None:
    """Confirm parent-before-child DB loading satisfies all foreign-key constraints."""
    test_engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    _, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)

    with TestingSessionLocal() as session:
        load_dataset_to_db(dataset, gt_rows, session)
        assert session.query(Product).count() == 10
        assert session.query(Machine).count() == 8
        assert session.query(ProductionOrder).count() == 30
        assert session.query(ProductionOrderOperation).count() == 120
        assert session.query(Material).count() == 25
        assert session.query(OperationSchedule).count() == len(dataset["operation_schedules"])

    test_engine.dispose()

