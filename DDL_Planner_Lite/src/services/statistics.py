"""任务和专注统计数据计算。"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src import database


def _local_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().date()


def get_statistics(
    *,
    today: date | None = None,
    db_path: Path | str | None = None,
) -> dict:
    current_date = today or date.today()
    task_data = database.get_task_statistics(db_path)
    task_rows = task_data["tasks"]
    week_dates = [current_date - timedelta(days=offset) for offset in range(6, -1, -1)]
    week_keys = {day.isoformat() for day in week_dates}
    new_tasks = {key: 0 for key in week_keys}
    completed_tasks = {key: 0 for key in week_keys}

    for task in task_rows:
        created_day = _local_date(task["created_at"])
        if created_day is not None and created_day.isoformat() in new_tasks:
            new_tasks[created_day.isoformat()] += 1

        completed_day = _local_date(task.get("completed_at"))
        if (
            task["status"] == "已完成"
            and completed_day is not None
            and completed_day.isoformat() in completed_tasks
        ):
            completed_tasks[completed_day.isoformat()] += 1

    focus_records = database.list_focus_records(db_path=db_path)
    completed_records = [
        record for record in focus_records if record["status"] == "completed"
    ]
    completed_pomodoros = [
        record
        for record in completed_records
        if record.get("mode") != "count_up"
    ]
    count_up_sessions = [
        record
        for record in completed_records
        if record.get("mode") == "count_up"
    ]
    focus_by_day = {key: 0 for key in week_keys}
    for record in completed_records:
        completed_at = _local_date(record.get("completed_at"))
        if completed_at is not None and completed_at.isoformat() in focus_by_day:
            focus_by_day[completed_at.isoformat()] += int(record["duration"])

    recent_completed = completed_records[:10]
    return {
        **{key: value for key, value in task_data.items() if key != "tasks"},
        "week_dates": week_dates,
        "weekly_created": [new_tasks[day.isoformat()] for day in week_dates],
        "weekly_completed": [
            completed_tasks[day.isoformat()] for day in week_dates
        ],
        "weekly_focus_seconds": [
            focus_by_day[day.isoformat()] for day in week_dates
        ],
        "total_focus_seconds": sum(int(record["duration"]) for record in completed_records),
        "completed_pomodoros": len(completed_pomodoros),
        "count_up_sessions": len(count_up_sessions),
        "recent_focus_records": recent_completed,
    }
