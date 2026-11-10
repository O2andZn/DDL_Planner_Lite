"""基于任务截止时间生成一次性应用内提醒。"""

from datetime import datetime, time, timedelta
from pathlib import Path

from src import database


_REMINDER_THRESHOLDS = (
    ("24h", timedelta(hours=24)),
    ("12h", timedelta(hours=12)),
    ("3h", timedelta(hours=3)),
)


def _local_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now().astimezone()
    return current.astimezone() if current.tzinfo is None else current.astimezone()


def _deadline_for(task: dict) -> datetime:
    deadline_date = datetime.strptime(task["due_date"], "%Y-%m-%d").date()
    deadline_time = time.fromisoformat(task.get("due_time") or "23:59")
    return datetime.combine(deadline_date, deadline_time).astimezone()


def get_due_reminders(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> list[dict]:
    """原子登记本次新到达的提醒阶段，刷新或重启后不重复返回。"""
    current = _local_now(now)
    tasks = database.list_tasks(status="待完成", db_path=db_path)
    candidates: list[tuple[int, str, str, str]] = []
    remaining_by_candidate: dict[tuple[int, str], int] = {}

    for task in tasks:
        if not task.get("due_date"):
            continue
        deadline = _deadline_for(task)
        remaining_seconds = int((deadline - current).total_seconds())
        if remaining_seconds <= 0:
            reminder_types = ("overdue",)
        else:
            reminder_types = tuple(
                reminder_type
                for reminder_type, threshold in _REMINDER_THRESHOLDS
                if remaining_seconds <= threshold.total_seconds()
            )
        for reminder_type in reminder_types:
            candidate = (
                task["id"],
                reminder_type,
                task["due_date"],
                task.get("due_time") or "23:59",
            )
            candidates.append(candidate)
            remaining_by_candidate[(task["id"], reminder_type)] = remaining_seconds

    if not candidates:
        return []

    claimed = database.claim_task_reminders(
        candidates,
        reminded_at=current.isoformat(),
        db_path=db_path,
    )
    for reminder in claimed:
        reminder["remaining_seconds"] = remaining_by_candidate[
            (reminder["id"], reminder["reminder_type"])
        ]
    return claimed


def format_remaining_time(remaining_seconds: int) -> str:
    if remaining_seconds <= 0:
        overdue_seconds = abs(remaining_seconds)
        hours, remainder = divmod(overdue_seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"已逾期 {hours} 小时 {minutes} 分钟"
        return f"已逾期 {minutes} 分钟"

    hours, remainder = divmod(remaining_seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"还剩 {hours} 小时 {minutes} 分钟"
    minutes, seconds = divmod(remaining_seconds, 60)
    return f"还剩 {minutes} 分钟 {seconds} 秒"
