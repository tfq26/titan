from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Iterable


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


@dataclass(frozen=True)
class QueuePaths:
    repo_root: Path

    @property
    def vault_root(self) -> Path:
        return self.repo_root / "docs" / "vault"

    @property
    def queue_root(self) -> Path:
        return self.vault_root / "queue-tasks"

    @property
    def open_dir(self) -> Path:
        return self.queue_root / "open"

    @property
    def claimed_dir(self) -> Path:
        return self.queue_root / "claimed"

    @property
    def review_needed_dir(self) -> Path:
        return self.queue_root / "review-needed"

    @property
    def blocked_dir(self) -> Path:
        return self.queue_root / "blocked"

    @property
    def completed_dir(self) -> Path:
        return self.queue_root / "completed"

    @property
    def reports_dir(self) -> Path:
        return self.repo_root / "docs" / "reports" / "subagents"

    @property
    def master_log(self) -> Path:
        return self.reports_dir / "subagent-master-log.md"


def ensure_queue_dirs(paths: QueuePaths) -> None:
    for directory in (
        paths.open_dir,
        paths.claimed_dir,
        paths.review_needed_dir,
        paths.blocked_dir,
        paths.completed_dir,
        paths.reports_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def list_tasks(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix == ".md" and path.name != "README.md"
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def split_frontmatter(text: str) -> tuple[str | None, str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, "", text
    return "---\n", match.group(1), text[match.end():]


def parse_frontmatter(frontmatter: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current_key: str | None = None
    current_value_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_value_lines
        if current_key is not None:
            result[current_key] = "\n".join(current_value_lines).rstrip()
        current_key = None
        current_value_lines = []

    for raw_line in frontmatter.splitlines():
        if raw_line.startswith(" ") or raw_line.startswith("\t"):
            if current_key is not None:
                current_value_lines.append(raw_line)
            continue
        if ":" in raw_line:
            flush()
            key, value = raw_line.split(":", 1)
            current_key = key.strip()
            current_value_lines = [value.lstrip()]
            continue
    flush()
    return result


def render_frontmatter(fields: dict[str, str]) -> str:
    lines: list[str] = []
    for key, value in fields.items():
        if "\n" in value:
            lines.append(f"{key}: |")
            lines.extend(f"  {line}" for line in value.splitlines())
        elif value == "":
            lines.append(f"{key}:")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def update_frontmatter_field(path: Path, key: str, value: str) -> None:
    text = read_text(path)
    fm_prefix, fm_body, rest = split_frontmatter(text)
    if fm_prefix is None:
        raise ValueError(f"{path} is missing frontmatter")

    lines = fm_body.splitlines()
    replacement = f"{key}: {value}" if value else f"{key}:"
    updated = False
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:\s*", line):
            lines[index] = replacement
            updated = True
            break
    if not updated:
        lines.append(replacement)

    cleaned_rest = rest.lstrip("\n")
    new_text = f"---\n" + "\n".join(lines) + f"\n---\n{cleaned_rest}"
    write_text(path, new_text)


def set_status(path: Path, status: str) -> None:
    update_frontmatter_field(path, "status", status)


def move_task(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))
    return dst


def current_report_link(task_path: Path) -> str | None:
    text = read_text(task_path)
    _, fm_body, _ = split_frontmatter(text)
    if not fm_body:
        return None
    fields = parse_frontmatter(fm_body)
    report = fields.get("report", "").strip()
    return report or None


def current_review_link(task_path: Path) -> str | None:
    text = read_text(task_path)
    _, fm_body, _ = split_frontmatter(text)
    if not fm_body:
        return None
    fields = parse_frontmatter(fm_body)
    review = fields.get("review", "").strip()
    return review or None


def resolve_task_reference(task_path: Path, reference: str | None) -> Path | None:
    if not reference:
        return None
    candidate = Path(reference)
    if candidate.is_absolute():
        return candidate
    return (task_path.parent / candidate).resolve()


def revision_count(task_path: Path) -> int:
    text = read_text(task_path)
    _, fm_body, _ = split_frontmatter(text)
    if not fm_body:
        return 0
    fields = parse_frontmatter(fm_body)
    try:
        return int(fields.get("revision", "0") or "0")
    except ValueError:
        return 0


def set_revision(task_path: Path, revision: int) -> None:
    update_frontmatter_field(task_path, "revision", str(revision))


def bump_revision(task_path: Path) -> None:
    set_revision(task_path, revision_count(task_path) + 1)


def ensure_text_contains(path: Path, needle: str) -> bool:
    return needle in read_text(path)
