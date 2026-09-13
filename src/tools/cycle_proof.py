"""Explicit packaging and provisioning for the isolated AWS cycle evidence."""

from pathlib import Path
from shutil import copytree, ignore_patterns
from zipfile import ZIP_DEFLATED, ZipFile

from src.config import Settings
from src.domain.demo_cafe import build_demo_profile
from src.tools import alert_ledger, audit, inventory
from src.tools.escalation_queue import ensure_escalation_table
from src.tools.surface_files import write_replay_feed


def package_cycle(folder: Path, archive: Path) -> None:
    """Add project code/public fixtures to a Linux dependency directory and zip it."""
    root = Path(__file__).resolve().parents[2]
    copytree(
        root / "src",
        folder / "src",
        dirs_exist_ok=True,
        ignore=ignore_patterns("__pycache__", "*.pyc"),
    )
    (folder / "fixtures").mkdir(exist_ok=True)
    write_replay_feed(folder / "fixtures" / "cycle.json")
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                output.write(path, path.relative_to(folder).as_posix())


def provision_cycle(prefix: str) -> Settings:
    """Create only explicitly named proof tables, then seed the fictional café."""
    if not prefix.startswith("allerguard-cycle-proof-") or not prefix.replace("-", "").isalnum():
        raise ValueError("Use an isolated allerguard-cycle-proof- prefix.")
    settings = Settings(
        aws_region="eu-west-2",
        bedrock_model_id="injected-replay",
        cycle_proposal_mode="injected",
        notification_mode="disabled",
        dynamodb_table_businesses=prefix + "-business",
        dynamodb_table_alerts_seen=prefix + "-ledger",
        dynamodb_table_audit=prefix + "-audit",
        dynamodb_table_escalations=prefix + "-queue",
    )
    inventory.ensure_business_table(settings)
    alert_ledger.ensure_alerts_seen_table(settings)
    audit.ensure_audit_table(settings)
    ensure_escalation_table(settings)
    if inventory.read_business("demo-cafe", settings) is None:
        inventory.write_business(build_demo_profile(), settings)
    return settings
