"""番茄钟状态转换和专注记录统计。"""

from datetime import date, datetime, timedelta
from math import ceil
from pathlib import Path

from src import database


POMODORO_SECONDS = 25 * 60


class FocusTimerError(ValueError):
    """专注计时状态或操作不符合要求。"""


def validate_countdown_minutes(minutes: int) -> int:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
        raise FocusTimerError("倒计时时长必须为 1 到 180 分钟。")
    return minutes * 60


def _local_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now().astimezone()
    return current.astimezone() if current.tzinfo is None else current.astimezone()


def _timestamp(value: datetime) -> str:
    return _local_now(value).isoformat()


def _remaining_seconds(record: dict, now: datetime) -> int:
    if record["status"] != "running":
        return int(record["remaining_seconds"])
    deadline = datetime.fromisoformat(record["deadline_at"])
    seconds = (deadline - now).total_seconds()
    return max(0, ceil(seconds))


def _elapsed_duration(record: dict, now: datetime) -> int:
    if record["status"] != "running":
        return int(record["duration"])
    if record.get("mode") == "count_up":
        segment_started_at = record.get("segment_started_at")
        if not segment_started_at:
            return int(record["duration"])
        segment_start = datetime.fromisoformat(segment_started_at)
        return int(record["duration"]) + max(
            0, int((now - segment_start).total_seconds())
        )
    remaining = _remaining_seconds(record, now)
    elapsed_in_segment = max(0, int(record["remaining_seconds"]) - remaining)
    return int(record["duration"]) + elapsed_in_segment


def start_focus(
    task_id: int | None = None,
    *,
    mode: str = "countdown",
    planned_duration_seconds: int | None = None,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> int:
    current = _local_now(now)
    if mode not in ("countdown", "count_up"):
        raise FocusTimerError("请选择有效的计时模式。")
    if mode == "countdown":
        planned_duration = (
            POMODORO_SECONDS
            if planned_duration_seconds is None
            else planned_duration_seconds
        )
        if (
            isinstance(planned_duration, bool)
            or not isinstance(planned_duration, int)
            or not 60 <= planned_duration <= 180 * 60
            or planned_duration % 60 != 0
        ):
            raise FocusTimerError("倒计时时长必须为 1 到 180 分钟。")
        deadline = current + timedelta(seconds=planned_duration)
        remaining_seconds = planned_duration
        segment_started_at = None
    else:
        if planned_duration_seconds is not None:
            raise FocusTimerError("正计时模式不需要设置目标时长。")
        planned_duration = None
        deadline = None
        remaining_seconds = 0
        segment_started_at = _timestamp(current)

    if database.get_active_focus_record(db_path) is not None:
        raise FocusTimerError("已有专注计时正在进行或暂停，请先继续或重置。")

    task_title = "自由专注"
    if task_id is not None:
        task = database.get_task(task_id, db_path)
        if task is None or task["status"] != "待完成":
            raise FocusTimerError("请选择一个仍待完成的有效任务，或使用自由专注。")
        task_title = task["title"]

    return database.create_focus_record(
        task_id=task_id,
        task_title=task_title,
        duration=remaining_seconds,
        started_at=_timestamp(current),
        deadline_at=_timestamp(deadline) if deadline is not None else None,
        mode=mode,
        planned_duration=planned_duration,
        segment_started_at=segment_started_at,
        db_path=db_path,
    )


def get_active_focus(db_path: Path | str | None = None) -> dict | None:
    return database.get_active_focus_record(db_path)


def get_remaining_seconds(
    record: dict, *, now: datetime | None = None
) -> int:
    return _remaining_seconds(record, _local_now(now))


def get_elapsed_seconds(
    record: dict, *, now: datetime | None = None
) -> int:
    return _elapsed_duration(record, _local_now(now))


def pause_focus(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> None:
    current = _local_now(now)
    record = database.get_active_focus_record(db_path)
    if record is None or record["status"] != "running":
        raise FocusTimerError("当前没有正在运行的专注计时可暂停。")

    if record.get("mode") == "count_up":
        elapsed = _elapsed_duration(record, current)
        remaining = 0
    else:
        remaining = _remaining_seconds(record, current)
        if remaining == 0:
            complete_expired_focus(now=current, db_path=db_path)
            return
        elapsed = _elapsed_duration(record, current)
    database.pause_focus_record(
        record["id"],
        duration=elapsed,
        remaining_seconds=remaining,
        db_path=db_path,
    )


def resume_focus(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> None:
    current = _local_now(now)
    record = database.get_active_focus_record(db_path)
    if record is None or record["status"] != "paused":
        raise FocusTimerError("当前没有已暂停的专注计时可继续。")

    is_count_up = record.get("mode") == "count_up"
    deadline = (
        None
        if is_count_up
        else current + timedelta(seconds=int(record["remaining_seconds"]))
    )
    database.resume_focus_record(
        record["id"],
        deadline_at=_timestamp(deadline) if deadline is not None else None,
        segment_started_at=_timestamp(current) if is_count_up else None,
        db_path=db_path,
    )


def reset_focus(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> int | None:
    """放弃当前计时并保存实际专注时长，不计入完成番茄钟。"""
    current = _local_now(now)
    record = database.get_active_focus_record(db_path)
    if record is None:
        return None

    if record.get("mode") == "count_up":
        remaining = 0
        elapsed = _elapsed_duration(record, current)
    else:
        remaining = _remaining_seconds(record, current)
        if remaining == 0:
            return complete_expired_focus(now=current, db_path=db_path)
        elapsed = _elapsed_duration(record, current)
    database.finish_focus_record(
        record["id"],
        duration=elapsed,
        completed_at=_timestamp(current),
        status="abandoned",
        remaining_seconds=remaining,
        db_path=db_path,
    )
    return record["id"]


def finish_count_up_focus(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> int | None:
    """结束并保存正计时；重复调用不会重复创建专注记录。"""
    current = _local_now(now)
    record = database.get_active_focus_record(db_path)
    if record is None or record.get("mode") != "count_up":
        return None

    database.finish_focus_record(
        record["id"],
        duration=_elapsed_duration(record, current),
        completed_at=_timestamp(current),
        status="completed",
        remaining_seconds=0,
        db_path=db_path,
    )
    return record["id"]


def complete_expired_focus(
    *,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> int | None:
    """截止时间到达后完成记录；返回新完成的记录编号。"""
    current = _local_now(now)
    record = database.get_active_focus_record(db_path)
    if (
        record is None
        or record["status"] != "running"
        or record.get("mode") == "count_up"
    ):
        return None
    if _remaining_seconds(record, current) > 0:
        return None

    database.finish_focus_record(
        record["id"],
        duration=int(record["duration"]) + int(record["remaining_seconds"]),
        completed_at=_timestamp(current),
        status="completed",
        remaining_seconds=0,
        db_path=db_path,
    )
    return record["id"]


def get_today_focus_stats(
    *,
    today: date | None = None,
    now: datetime | None = None,
    db_path: Path | str | None = None,
) -> dict:
    current = _local_now(now)
    current_date = today or current.date()
    records = database.list_focus_records(
        started_on=current_date.isoformat(),
        db_path=db_path,
    )

    valid_records = [
        record
        for record in records
        if record["status"] in ("running", "paused", "completed")
    ]
    total_seconds = 0
    task_totals: dict[tuple[int | None, str], dict[str, int | str | None]] = {}
    for record in valid_records:
        actual_duration = _elapsed_duration(record, current)
        total_seconds += actual_duration
        title = record["task_title"]
        task_key = (record["task_id"], title)
        task_total = task_totals.setdefault(
            task_key,
            {
                "task_id": record["task_id"],
                "task_title": title,
                "duration": 0,
                "completed_pomodoros": 0,
                "count_up_sessions": 0,
            },
        )
        task_total["duration"] = int(task_total["duration"]) + actual_duration
        if (
            record["status"] == "completed"
            and record.get("mode") != "count_up"
        ):
            task_total["completed_pomodoros"] = (
                int(task_total["completed_pomodoros"]) + 1
            )
        elif record["status"] == "completed":
            task_total["count_up_sessions"] = (
                int(task_total["count_up_sessions"]) + 1
            )

    completed_count = sum(
        record["status"] == "completed" and record.get("mode") != "count_up"
        for record in records
    )
    count_up_sessions = sum(
        record["status"] == "completed" and record.get("mode") == "count_up"
        for record in records
    )
    recent_record = dict(records[0]) if records else None
    if recent_record is not None:
        recent_record["actual_duration"] = _elapsed_duration(
            recent_record, current
        )

    return {
        "total_seconds": total_seconds,
        "completed_pomodoros": completed_count,
        "count_up_sessions": count_up_sessions,
        "task_totals": sorted(
            task_totals.values(),
            key=lambda item: (-int(item["duration"]), str(item["task_title"])),
        ),
        "recent_record": recent_record,
        "records": records,
    }
