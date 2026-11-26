"""Progress and health engine (pure functions; business.py feeds it rows).

Progress never counts the same work twice: a task with subtasks takes the
weighted mean of its subtasks (its own `progress` is ignored), and the project
strategies only look at *leaf* tasks (`tasks`), at phases that have leaf tasks
(`weighted`) or at milestones (`milestones`). Cancelled tasks and milestones
leave every denominator. Formulas (modules/projects/README.md):

    leaf progress        = 100 if done else task.progress (0-100)
    parent progress      = Σ(weight x child progress) / Σ(weight) over non-cancelled children
    phase progress       = Σ(weight x leaf progress) / Σ(weight) over its non-cancelled leaves
    strategy "tasks"     = done leaves / non-cancelled leaves x 100
    strategy "weighted"  = Σ(phase.weight x phase progress) / Σ(phase.weight) over phases with
                           leaves; leaves without a phase form one extra bucket of weight 1
    strategy "milestones"= reached milestones / non-cancelled milestones x 100
    planned progress     = clamp((today - start) / (due - start)) x 100 when both dates exist

Health is separate from progress and from status:
    blocked   = an open task is blocked
    delayed   = project past its due date, or an open task/pending milestone past its date
    at_risk   = an open risk with score >= 6 or a materialized risk
    on_track  = otherwise (and always for draft/completed/cancelled/archived projects)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

HUNDRED = Decimal("100")
PCT = Decimal("0.01")
RISK_SCORES = {"low": 1, "medium": 2, "high": 3}
RISK_ALERT = 6


def pct(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(HUNDRED, value)).quantize(PCT, rounding=ROUND_HALF_UP)


@dataclass
class TaskRow:
    id: UUID
    parent_id: UUID | None
    phase_id: UUID | None
    status: str
    progress: int
    weight: Decimal
    due: date | None = None
    blocked: bool = False
    children: list[TaskRow] = field(default_factory=list)


def build_tree(tasks: Iterable[TaskRow]) -> list[TaskRow]:
    by_id = {t.id: t for t in tasks}
    roots: list[TaskRow] = []
    for task in by_id.values():
        task.children = []
    for task in by_id.values():
        parent = by_id.get(task.parent_id) if task.parent_id else None
        if parent is not None and parent is not task:
            parent.children.append(task)
        else:
            roots.append(task)

    # A subtask without a phase of its own belongs to its nearest ancestor's phase.
    def inherit(task: TaskRow, phase_id: UUID | None) -> None:
        if task.phase_id is None:
            task.phase_id = phase_id
        for child in task.children:
            inherit(child, task.phase_id)

    for root in roots:
        inherit(root, root.phase_id)
    return roots


def _weight(value: Decimal | None) -> Decimal:
    return value if value is not None and value > 0 else Decimal("0")


def task_progress(task: TaskRow) -> Decimal:
    """Effective progress of a task: subtasks roll up; a leaf uses its own figure."""
    live = [c for c in task.children if c.status != "cancelled"]
    if live:
        total = sum((_weight(c.weight) for c in live), Decimal("0"))
        if total <= 0:
            return pct(sum((task_progress(c) for c in live), Decimal("0")) / len(live))
        return pct(sum((_weight(c.weight) * task_progress(c) for c in live), Decimal("0")) / total)
    if task.status == "done":
        return HUNDRED
    if task.status == "cancelled":
        return Decimal("0")
    return pct(Decimal(max(0, min(100, int(task.progress)))))


def leaves(roots: Iterable[TaskRow]) -> list[TaskRow]:
    out: list[TaskRow] = []

    def walk(task: TaskRow) -> None:
        live = [c for c in task.children if c.status != "cancelled"]
        if live:
            for child in live:
                walk(child)
        elif task.status != "cancelled":
            out.append(task)

    for root in roots:
        if root.status != "cancelled":
            walk(root)
    return out


def weighted_mean(pairs: Iterable[tuple[Decimal, Decimal]]) -> Decimal | None:
    """Σ(weight x value) / Σ(weight); None when there is nothing to average."""
    items = [(w, v) for w, v in pairs]
    if not items:
        return None
    total = sum((w for w, _v in items), Decimal("0"))
    if total <= 0:
        return pct(sum((v for _w, v in items), Decimal("0")) / len(items))
    return pct(sum((w * v for w, v in items), Decimal("0")) / total)


def phase_progress(phase_id: UUID | None, leaf_tasks: Iterable[TaskRow]) -> Decimal | None:
    return weighted_mean(
        (_weight(t.weight), task_progress(t)) for t in leaf_tasks if t.phase_id == phase_id
    )


def project_progress(
    strategy: str,
    roots: list[TaskRow],
    phase_weights: dict[UUID, Decimal],
    milestone_statuses: Iterable[str],
) -> Decimal:
    leaf_tasks = leaves(roots)
    if strategy == "milestones":
        statuses = [s for s in milestone_statuses if s != "cancelled"]
        if not statuses:
            return Decimal("0.00")
        return pct(Decimal(sum(1 for s in statuses if s == "reached")) / len(statuses) * HUNDRED)
    if strategy == "weighted":
        buckets: list[tuple[Decimal, Decimal]] = []
        for phase_id, weight in phase_weights.items():
            value = phase_progress(phase_id, leaf_tasks)
            if value is not None:
                buckets.append((_weight(weight), value))
        orphan = phase_progress(None, leaf_tasks)
        if orphan is not None:
            buckets.append((Decimal("1"), orphan))
        return weighted_mean(buckets) or Decimal("0.00")
    # "tasks": completed leaves over non-cancelled leaves
    if not leaf_tasks:
        return Decimal("0.00")
    done = sum(1 for t in leaf_tasks if t.status == "done")
    return pct(Decimal(done) / len(leaf_tasks) * HUNDRED)


def planned_progress(start: date | None, due: date | None, today: date) -> Decimal | None:
    if start is None or due is None or due <= start:
        return None
    return pct(Decimal((today - start).days) / Decimal((due - start).days) * HUNDRED)


def risk_score(probability: str, impact: str) -> int:
    return RISK_SCORES.get(probability, 2) * RISK_SCORES.get(impact, 2)


def health(
    status: str,
    due: date | None,
    today: date,
    roots: list[TaskRow],
    milestones: Iterable[tuple[str, date | None]],
    risks: Iterable[tuple[str, int]],
) -> str:
    """`risks` are (status, score) pairs; `milestones` are (status, due_date) pairs."""
    if status not in ("active", "paused"):
        return "on_track"
    open_tasks = [t for t in _all(roots) if t.status not in ("done", "cancelled")]
    if any(t.blocked for t in open_tasks):
        return "blocked"
    if due is not None and due < today:
        return "delayed"
    if any(t.due is not None and t.due < today for t in open_tasks):
        return "delayed"
    if any(s == "pending" and d is not None and d < today for s, d in milestones):
        return "delayed"
    if any(
        s == "materialized" or (s in ("open", "mitigating") and score >= RISK_ALERT)
        for s, score in risks
    ):
        return "at_risk"
    return "on_track"


def _all(roots: Iterable[TaskRow]) -> list[TaskRow]:
    out: list[TaskRow] = []

    def walk(task: TaskRow) -> None:
        out.append(task)
        for child in task.children:
            walk(child)

    for root in roots:
        walk(root)
    return out


def would_cycle(edges: dict[UUID, set[UUID]], predecessor: UUID, successor: UUID) -> bool:
    """True if adding predecessor → successor creates a cycle (successor already reaches
    predecessor)."""
    if predecessor == successor:
        return True
    stack = [successor]
    seen: set[UUID] = set()
    while stack:
        node = stack.pop()
        if node == predecessor:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
    return False
