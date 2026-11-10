"""数据管理、清理校验和备份服务。"""

from pathlib import Path

from src import database
from src.config import BACKUP_DIR


def get_summary(db_path: Path | str | None = None) -> dict:
    return database.get_data_management_summary(db_path)


def clear_focus_history(db_path: Path | str | None = None) -> int:
    before = get_summary(db_path)
    deleted = database.clear_focus_records(db_path)
    after = get_summary(db_path)
    if (
        after["focus_records"] != 0
        or after["completed_focus_seconds"] != 0
        or after["tasks_total"] != before["tasks_total"]
        or after["daily_plan_items"] != before["daily_plan_items"]
    ):
        raise database.DatabaseError("清理后数据复核失败，请检查数据库状态。")
    return deleted


def clear_completed_tasks(db_path: Path | str | None = None) -> dict[str, int]:
    before = get_summary(db_path)
    result = database.clear_completed_tasks(db_path)
    after = get_summary(db_path)
    if (
        after["tasks_completed"] != 0
        or after["tasks_pending"] != before["tasks_pending"]
        or after["tasks_total"] != before["tasks_total"] - result["tasks_deleted"]
        or after["daily_plan_items"]
        != before["daily_plan_items"] - result["daily_plan_items_deleted"]
        or after["focus_records"] != before["focus_records"]
        or after["completed_focus_seconds"] != before["completed_focus_seconds"]
    ):
        raise database.DatabaseError("清理后数据复核失败，请检查数据库状态。")
    return result


def reset_all_data(db_path: Path | str | None = None) -> dict[str, int]:
    result = database.reset_all_business_data(db_path)
    after = get_summary(db_path)
    if any(
        after[key]
        for key in (
            "tasks_total",
            "tasks_completed",
            "tasks_pending",
            "daily_plan_items",
            "focus_records",
            "completed_focus_seconds",
        )
    ):
        raise database.DatabaseError("重置后数据复核失败，请检查数据库状态。")
    return result


def create_backup(
    db_path: Path | str | None = None,
    backup_dir: Path | str | None = None,
) -> Path:
    return database.backup_database(
        BACKUP_DIR if backup_dir is None else backup_dir,
        db_path,
    )
