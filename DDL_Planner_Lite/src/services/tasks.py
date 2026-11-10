"""任务管理业务逻辑和输入校验。"""

from datetime import date, datetime, time, timedelta
from pathlib import Path

from src import database


PRIORITIES = ("高", "中", "低")
PRESET_CATEGORIES = ("课程作业", "考试复习", "实验报告", "竞赛", "科研项目")
CUSTOM_CATEGORY_OPTION = "其他（自定义）"
CATEGORY_OPTIONS = (*PRESET_CATEGORIES, CUSTOM_CATEGORY_OPTION)
STATUSES = ("待完成", "已完成")


class TaskValidationError(ValueError):
    """任务输入不符合要求。"""


def resolve_category(category: str, custom_category: str = "") -> str:
    """将分类选择解析为保存到数据库的最终分类名称。"""
    if category == CUSTOM_CATEGORY_OPTION:
        normalized_category = custom_category.strip()
    else:
        normalized_category = category.strip()

    if not normalized_category:
        raise TaskValidationError("自定义分类名称不能为空。")
    return normalized_category


def _normalize_task(
    *,
    title: str,
    description: str,
    due_date: date | datetime | str,
    due_time: time | str,
    priority: str,
    category: str,
    custom_category: str,
) -> tuple[str, str, str, str, str, str]:
    normalized_title = title.strip()
    if not normalized_title:
        raise TaskValidationError("任务名称不能为空。")

    if isinstance(due_date, datetime):
        normalized_due_date = due_date.date().isoformat()
    elif isinstance(due_date, date):
        normalized_due_date = due_date.isoformat()
    else:
        try:
            normalized_due_date = date.fromisoformat(due_date).isoformat()
        except (TypeError, ValueError) as error:
            raise TaskValidationError("请选择有效的截止日期。") from error

    if isinstance(due_time, time):
        normalized_due_time = due_time.strftime("%H:%M")
    else:
        try:
            normalized_due_time = time.fromisoformat(due_time).strftime("%H:%M")
        except (TypeError, ValueError) as error:
            raise TaskValidationError("请选择有效的截止时间。") from error

    if priority not in PRIORITIES:
        raise TaskValidationError("请选择有效的优先级。")
    normalized_category = resolve_category(category, custom_category)

    return (
        normalized_title,
        description.strip(),
        normalized_due_date,
        normalized_due_time,
        priority,
        normalized_category,
    )


def add_task(
    *,
    title: str,
    description: str = "",
    due_date: date | datetime | str,
    due_time: time | str = "23:59",
    priority: str = "中",
    category: str = "其他",
    custom_category: str = "",
    db_path: Path | str | None = None,
) -> int:
    values = _normalize_task(
        title=title,
        description=description,
        due_date=due_date,
        due_time=due_time,
        priority=priority,
        category=category,
        custom_category=custom_category,
    )
    return database.create_task(
        title=values[0],
        description=values[1],
        due_date=values[2],
        due_time=values[3],
        priority=values[4],
        category=values[5],
        db_path=db_path,
    )


def edit_task(
    task_id: int,
    *,
    title: str,
    description: str = "",
    due_date: date | datetime | str,
    due_time: time | str = "23:59",
    priority: str = "中",
    category: str = "其他",
    custom_category: str = "",
    db_path: Path | str | None = None,
) -> None:
    values = _normalize_task(
        title=title,
        description=description,
        due_date=due_date,
        due_time=due_time,
        priority=priority,
        category=category,
        custom_category=custom_category,
    )
    database.update_task(
        task_id,
        title=values[0],
        description=values[1],
        due_date=values[2],
        due_time=values[3],
        priority=values[4],
        category=values[5],
        db_path=db_path,
    )


def get_tasks(
    *,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    keyword: str = "",
    db_path: Path | str | None = None,
) -> list[dict]:
    if status is not None and status not in STATUSES:
        raise TaskValidationError("请选择有效的任务状态筛选条件。")
    if priority is not None and priority not in PRIORITIES:
        raise TaskValidationError("请选择有效的优先级筛选条件。")
    if category is not None and not category.strip():
        raise TaskValidationError("分类筛选条件不能为空。")
    return database.list_tasks(
        status=status,
        priority=priority,
        category=category,
        keyword=keyword.strip(),
        db_path=db_path,
    )


def complete_task(task_id: int, db_path: Path | str | None = None) -> None:
    database.mark_task_completed(task_id, db_path=db_path)


def remove_task(task_id: int, db_path: Path | str | None = None) -> None:
    database.delete_task(task_id, db_path=db_path)


def get_dashboard_data(
    *, today: date | None = None, db_path: Path | str | None = None
) -> dict:
    """从任务数据生成首页统计、今日待办和截止提醒。"""
    current_date = today or date.today()
    current_date_text = current_date.isoformat()
    seven_days_later_text = (current_date + timedelta(days=7)).isoformat()
    all_tasks = database.list_tasks(db_path=db_path)
    pending_tasks = [task for task in all_tasks if task["status"] == "待完成"]
    completed_count = sum(task["status"] == "已完成" for task in all_tasks)
    overdue_tasks = [
        task
        for task in pending_tasks
        if task["due_date"] is not None and task["due_date"] < current_date_text
    ]
    today_tasks = [
        task for task in pending_tasks if task["due_date"] == current_date_text
    ]
    upcoming_tasks = [
        task
        for task in pending_tasks
        if task["due_date"] is not None
        and current_date_text <= task["due_date"] <= seven_days_later_text
    ]
    upcoming_tasks.sort(key=lambda task: (task["due_date"], task["id"]))
    overdue_tasks.sort(key=lambda task: (task["due_date"], task["id"]))

    total_count = len(all_tasks)
    return {
        "total": total_count,
        "pending": len(pending_tasks),
        "completed": completed_count,
        "overdue": len(overdue_tasks),
        "completion_rate": completed_count / total_count if total_count else 0.0,
        "today_tasks": today_tasks,
        "upcoming_tasks": upcoming_tasks,
        "overdue_tasks": overdue_tasks,
    }
