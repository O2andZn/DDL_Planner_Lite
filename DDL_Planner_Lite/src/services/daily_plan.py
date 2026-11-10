"""每日计划任务业务逻辑。"""

from datetime import date
from pathlib import Path

from src import database


def get_planned_tasks(
    plan_date: date | str | None = None,
    db_path: Path | str | None = None,
) -> list[dict]:
    date_text = plan_date.isoformat() if isinstance(plan_date, date) else plan_date
    date_text = date_text or date.today().isoformat()
    return database.list_daily_plan_tasks(date_text, db_path)


def get_available_tasks(
    plan_date: date | str | None = None,
    db_path: Path | str | None = None,
) -> list[dict]:
    date_text = plan_date.isoformat() if isinstance(plan_date, date) else plan_date
    date_text = date_text or date.today().isoformat()
    return database.list_available_daily_plan_tasks(date_text, db_path)


def add_tasks(
    task_ids: list[int],
    plan_date: date | str | None = None,
    db_path: Path | str | None = None,
) -> int:
    date_text = plan_date.isoformat() if isinstance(plan_date, date) else plan_date
    date_text = date_text or date.today().isoformat()
    return database.add_daily_plan_items(task_ids, date_text, db_path)


def remove_task(
    plan_item_id: int,
    plan_date: date | str | None = None,
    db_path: Path | str | None = None,
) -> None:
    date_text = plan_date.isoformat() if isinstance(plan_date, date) else plan_date
    date_text = date_text or date.today().isoformat()
    database.remove_daily_plan_item(plan_item_id, date_text, db_path)
