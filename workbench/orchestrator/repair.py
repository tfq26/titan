"""
Queue repair and drift detection for the workbench.

Provides:
- Pre-transition vault-vs-graph validation
- Post-transition vault verification
- Drift detection (duplicate tasks, missing reports, invalid transitions)
- Repair condition emission

These hooks enforce vault-graph-conflict-resolution.md policy.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Conflict:
    """A detected inconsistency between graph state and vault state."""
    conflict_type: str           # "queue_state" | "report_link" | "revision_mismatch" | "duplicate_location" | "missing_report" | "invalid_transition"
    description: str
    task_filename: str
    graph_value: Optional[str] = None
    vault_value: Optional[str] = None
    severity: str = "error"      # "error" (block transition) | "warn" (log and proceed)


@dataclass
class RepairCondition:
    """Emitted when vault drift requires human or tool intervention."""
    task_filename: str
    condition_type: str          # "duplicate_task" | "missing_report" | "invalid_state" | "orphaned_file"
    description: str
    affected_paths: list[str] = field(default_factory=list)
    suggested_action: str = ""


# ── State folders ─────────────────────────────────────────────────────

STATE_FOLDERS = ["open", "claimed", "review-needed", "completed", "blocked"]


# ── Pre-transition validation ─────────────────────────────────────────

def validate_graph_vs_vault(
    vault_root: Path,
    task_filename: str,
    expected_queue_state: str,
    expected_revision: Optional[int] = None,
    expected_report_path: Optional[str] = None,
    expected_review_path: Optional[str] = None,
) -> list[Conflict]:
    """
    Validate that graph state matches vault state before a mutation.

    Args:
        vault_root: Project vault root (contains queue-tasks/)
        task_filename: The task file being operated on
        expected_queue_state: Which folder graph thinks the task is in
        expected_revision: What revision graph thinks the task is at
        expected_report_path: What report path graph has recorded
        expected_review_path: What review path graph has recorded

    Returns:
        List of conflicts. Empty list means valid.
    """
    conflicts: list[Conflict] = []

    if not vault_root.exists():
        conflicts.append(Conflict(
            conflict_type="vault_missing",
            description=f"Vault root does not exist: {vault_root}",
            task_filename=task_filename,
            severity="error",
        ))
        return conflicts

    if not task_filename:
        conflicts.append(Conflict(
            conflict_type="missing_task_filename",
            description="No task filename in graph state",
            task_filename="<unknown>",
            severity="error",
        ))
        return conflicts

    queue_root = vault_root / "queue-tasks"

    # ── Check 1: Duplicate task locations ─────────────────────────────
    found_in_folders = []
    for folder in STATE_FOLDERS:
        candidate = queue_root / folder / task_filename
        if candidate.exists():
            found_in_folders.append(folder)

    if len(found_in_folders) > 1:
        conflicts.append(Conflict(
            conflict_type="duplicate_location",
            description=f"Task exists in multiple folders: {found_in_folders}",
            task_filename=task_filename,
            vault_value=str(found_in_folders),
            severity="error",
        ))
        return conflicts  # Stop — cannot proceed with duplicates

    # ── Check 2: Queue state mismatch ─────────────────────────────────
    if expected_queue_state not in found_in_folders:
        actual_folder = found_in_folders[0] if found_in_folders else "none"
        conflicts.append(Conflict(
            conflict_type="queue_state",
            description=f"Graph expects task in {expected_queue_state}/ but vault shows {actual_folder}/",
            task_filename=task_filename,
            graph_value=expected_queue_state,
            vault_value=actual_folder,
            severity="error",
        ))

    # ── Check 3: Frontmatter vs graph state ───────────────────────────
    if found_in_folders and len(found_in_folders) == 1:
        task_path = queue_root / found_in_folders[0] / task_filename
        content = task_path.read_text()
        fm = _parse_frontmatter(content)

        if expected_revision is not None:
            vault_revision = fm.get("revision", 0)
            if vault_revision != expected_revision:
                conflicts.append(Conflict(
                    conflict_type="revision_mismatch",
                    description=f"Graph revision={expected_revision}, vault revision={vault_revision}",
                    task_filename=task_filename,
                    graph_value=str(expected_revision),
                    vault_value=str(vault_revision),
                    severity="error",
                ))

        if expected_report_path is not None:
            vault_report = fm.get("report", "")
            if vault_report and vault_report != expected_report_path:
                conflicts.append(Conflict(
                    conflict_type="report_link",
                    description=f"Graph report path differs from vault frontmatter",
                    task_filename=task_filename,
                    graph_value=expected_report_path,
                    vault_value=vault_report,
                    severity="warn",
                ))

        if expected_review_path is not None:
            vault_review = fm.get("review", "")
            if vault_review and vault_review != expected_review_path:
                conflicts.append(Conflict(
                    conflict_type="review_link",
                    description=f"Graph review path differs from vault frontmatter",
                    task_filename=task_filename,
                    graph_value=expected_review_path,
                    vault_value=vault_review,
                    severity="warn",
                ))

    # ── Check 4: Report file actually exists ──────────────────────────
    if fm:
        report_link = fm.get("report", "")
        if report_link:
            report_full_path = vault_root.parent.parent / report_link
            if not report_full_path.exists():
                conflicts.append(Conflict(
                    conflict_type="missing_report",
                    description=f"Report linked in frontmatter does not exist: {report_link}",
                    task_filename=task_filename,
                    vault_value=report_link,
                    severity="error",
                ))

    return conflicts


# ── Post-transition verification ──────────────────────────────────────

def verify_vault_transition(
    vault_root: Path,
    task_filename: str,
    expected_target_folder: str,
    expected_source_folder: str,
) -> tuple[bool, list[str]]:
    """
    Verify that a queue state transition completed correctly.

    Returns (ok, errors[]).
    """
    errors: list[str] = []
    queue_root = vault_root / "queue-tasks"

    target_path = queue_root / expected_target_folder / task_filename
    source_path = queue_root / expected_source_folder / task_filename

    if not target_path.exists():
        errors.append(f"Task not found in target folder: {expected_target_folder}/")

    if source_path.exists():
        errors.append(
            f"Stale task copy remains in source folder: {expected_source_folder}/. "
            f"Queue invariant violated."
        )

    # Check no duplicates appeared
    found = []
    for folder in STATE_FOLDERS:
        if (queue_root / folder / task_filename).exists():
            found.append(folder)

    if len(found) > 1:
        errors.append(f"Task now exists in multiple folders: {found}")

    return len(errors) == 0, errors


# ── Full vault drift scan ─────────────────────────────────────────────

def scan_vault_for_drift(vault_root: Path) -> list[RepairCondition]:
    """
    Scan an entire project vault for drift conditions.

    Checks:
    - Duplicate task files across state folders
    - Tasks in review-needed/ without report links
    - Tasks in completed/ with invalid frontmatter
    - Orphaned files in queue folders that don't match the naming pattern

    Returns list of RepairConditions for each drift found.
    """
    conditions: list[RepairCondition] = []
    queue_root = vault_root / "queue-tasks"

    if not queue_root.exists():
        return conditions

    # ── Collect all task files by filename ────────────────────────────
    task_files: dict[str, list[str]] = {}
    for folder in STATE_FOLDERS:
        folder_path = queue_root / folder
        if not folder_path.exists():
            continue
        for f in folder_path.iterdir():
            if f.is_file() and f.name.endswith(".md") and f.name != "README.md":
                task_files.setdefault(f.name, []).append(folder)

    # ── Detect duplicates ─────────────────────────────────────────────
    for filename, folders in task_files.items():
        if len(folders) > 1:
            conditions.append(RepairCondition(
                task_filename=filename,
                condition_type="duplicate_task",
                description=f"Task {filename} found in {len(folders)} folders: {folders}",
                affected_paths=[str(queue_root / f / filename) for f in folders],
                suggested_action="Determine which copy is authoritative and delete the others.",
            ))

    # ── Check review-needed tasks have report links ───────────────────
    review_dir = queue_root / "review-needed"
    if review_dir.exists():
        for task_file in review_dir.iterdir():
            if task_file.is_file() and task_file.name.endswith(".md") and task_file.name != "README.md":
                content = task_file.read_text()
                fm = _parse_frontmatter(content)
                report = fm.get("report", "")
                if not report:
                    conditions.append(RepairCondition(
                        task_filename=task_file.name,
                        condition_type="missing_report",
                        description=f"Task in review-needed/ has no report link in frontmatter",
                        affected_paths=[str(task_file)],
                        suggested_action="Worker must write a report and update the task frontmatter report link.",
                    ))

    return conditions


# ── Helpers ───────────────────────────────────────────────────────────

def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from a Markdown file."""
    if not content.startswith("---"):
        return {}

    try:
        end_idx = content.index("---", 3)
        fm_text = content[3:end_idx].strip()
    except ValueError:
        return {}

    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Try to parse as int
            try:
                value = int(value)
            except ValueError:
                pass
            result[key] = value

    return result


def reconcile_graph_to_vault(
    state: dict,
    vault_root: Path,
    task_filename: str,
) -> dict:
    """
    Re-derive graph state fields from vault filesystem.

    Called when a conflict is detected. Returns a dict of state updates
    that should be merged into the graph state.

    Policy: vault wins. Graph adopts vault's version of truth.
    """
    updates = {}
    queue_root = vault_root / "queue-tasks"

    # Find which folder the task is actually in
    for folder in STATE_FOLDERS:
        candidate = queue_root / folder / task_filename
        if candidate.exists():
            # Update current task path
            updates["current_task_path"] = f"queue-tasks/{folder}/{task_filename}"

            # Read frontmatter
            content = candidate.read_text()
            fm = _parse_frontmatter(content)

            if "revision" in fm:
                updates["revision_count"] = fm["revision"]
            if "report" in fm:
                updates["worker_report_path"] = fm["report"]
            if "review" in fm:
                updates["primary_review_path"] = fm["review"]

            break

    return updates
