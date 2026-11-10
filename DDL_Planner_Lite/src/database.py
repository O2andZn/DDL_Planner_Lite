"""SQLite 数据库初始化和任务数据访问。"""

from contextlib import closing, contextmanager
from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Generator
from uuid import uuid4

from src.config import DATABASE_PATH


STATUSES = ("待完成", "已完成")
PRIORITIES = ("高", "中", "低")
_TASK_COLUMNS = {
    "id",
    "title",
    "description",
    "due_date",
    "priority",
    "category",
    "status",
    "created_at",
    "updated_at",
    "completed_at",
    "due_time",
}


class DatabaseError(RuntimeError):
    """数据库读写失败。"""


class TaskNotFoundError(LookupError):
    """指定任务不存在。"""


class FocusRecordNotFoundError(LookupError):
    """指定专注记录不存在或不处于预期状态。"""


class ActiveFocusError(RuntimeError):
    """存在进行中或暂停的专注计时，不能单独清空专注记录。"""


@contextmanager
def _connection(
    db_path: Path | str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    path = Path(db_path) if db_path is not None else DATABASE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        raise DatabaseError(f"数据库操作失败：{error}") from error


def _create_tasks_table(
    connection: sqlite3.Connection, *, due_date_required: bool = True
) -> None:
    due_date_constraint = "NOT NULL" if due_date_required else ""
    connection.execute(
        f"""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            due_date TEXT {due_date_constraint},
            due_time TEXT NOT NULL DEFAULT '23:59',
            priority TEXT NOT NULL DEFAULT '中'
                CHECK (priority IN ('高', '中', '低')),
            category TEXT NOT NULL DEFAULT '其他',
            status TEXT NOT NULL DEFAULT '待完成'
                CHECK (status IN ('待完成', '已完成')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
        """
    )


def _migrate_tasks_table(
    connection: sqlite3.Connection, columns: set[str]
) -> None:
    """将初始化版本的 is_completed/英文优先级结构升级并保留已有记录。"""
    cursor = connection.execute("SELECT * FROM tasks")
    cursor.row_factory = sqlite3.Row
    rows = cursor.fetchall()
    due_date_required = not any(
        row["due_date"] is None for row in rows if "due_date" in columns
    )

    legacy_table = f"tasks_legacy_{uuid4().hex}"
    connection.execute(f'ALTER TABLE tasks RENAME TO "{legacy_table}"')
    _create_tasks_table(connection, due_date_required=due_date_required)

    priority_map = {
        "high": "高",
        "medium": "中",
        "low": "低",
        "高": "高",
        "中": "中",
        "低": "低",
    }
    for row in rows:
        old_status = row["status"] if "status" in columns else None
        if old_status in STATUSES:
            status = old_status
        else:
            is_completed = row["is_completed"] if "is_completed" in columns else 0
            status = "已完成" if is_completed else "待完成"

        old_priority = row["priority"] if "priority" in columns else "中"
        priority = priority_map.get(old_priority, "中")
        connection.execute(
            """
            INSERT INTO tasks (
                id, title, description, due_date, priority, category, status,
                created_at, updated_at, completed_at, due_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["title"],
                row["description"] or "",
                row["due_date"] if "due_date" in columns else None,
                priority,
                row["category"] or "其他",
                status,
                row["created_at"] if "created_at" in columns else None,
                row["updated_at"] if "updated_at" in columns else None,
                row["completed_at"] if "completed_at" in columns else None,
                row["due_time"] if "due_time" in columns else "23:59",
            ),
        )

    connection.execute(f'DROP TABLE "{legacy_table}"')


def initialize_database(db_path: Path | str | None = None) -> None:
    """创建任务表，或在保留任务数据的前提下升级旧结构。"""
    with _connection(db_path) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
        ).fetchone()
        if table_exists is None:
            _create_tasks_table(connection)
        else:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if columns <= _TASK_COLUMNS:
                if "completed_at" not in columns:
                    connection.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
                if "due_time" not in columns:
                    connection.execute(
                        "ALTER TABLE tasks ADD COLUMN due_time TEXT NOT NULL "
                        "DEFAULT '23:59'"
                    )
            if columns - _TASK_COLUMNS:
                connection.execute("BEGIN IMMEDIATE")
                _migrate_tasks_table(connection, columns)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS focus_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                task_title TEXT NOT NULL,
                duration INTEGER NOT NULL DEFAULT 0 CHECK (duration >= 0),
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL
                    CHECK (status IN ('running', 'paused', 'completed', 'abandoned')),
                remaining_seconds INTEGER NOT NULL DEFAULT 0
                    CHECK (remaining_seconds >= 0),
                deadline_at TEXT,
                mode TEXT CHECK (mode IN ('countdown', 'count_up')),
                planned_duration INTEGER CHECK (
                    planned_duration IS NULL OR planned_duration > 0
                ),
                segment_started_at TEXT
            )
            """
        )
        focus_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(focus_records)")
        }
        if "mode" not in focus_columns:
            connection.execute(
                "ALTER TABLE focus_records ADD COLUMN mode TEXT "
                "CHECK (mode IN ('countdown', 'count_up'))"
            )
        if "planned_duration" not in focus_columns:
            connection.execute(
                "ALTER TABLE focus_records ADD COLUMN planned_duration INTEGER "
                "CHECK (planned_duration IS NULL OR planned_duration > 0)"
            )
        if "segment_started_at" not in focus_columns:
            connection.execute(
                "ALTER TABLE focus_records ADD COLUMN segment_started_at TEXT"
            )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_focus_record
            ON focus_records ((1))
            WHERE status IN ('running', 'paused')
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS focus_records_started_at "
            "ON focus_records (started_at DESC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                plan_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (task_id, plan_date)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS daily_plan_items_date "
            "ON daily_plan_items (plan_date, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                reminder_type TEXT NOT NULL CHECK (
                    reminder_type IN ('24h', '12h', '3h', 'overdue')
                ),
                reminded_at TEXT NOT NULL,
                UNIQUE (task_id, reminder_type)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_management_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL CHECK (
                    action IN (
                        'clear_focus_records',
                        'clear_completed_tasks',
                        'reset_all_data'
                    )
                ),
                tasks_deleted INTEGER NOT NULL DEFAULT 0,
                daily_plan_items_deleted INTEGER NOT NULL DEFAULT 0,
                focus_records_deleted INTEGER NOT NULL DEFAULT 0,
                focus_records_preserved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def create_task(
    *,
    title: str,
    description: str,
    due_date: str,
    due_time: str = "23:59",
    priority: str,
    category: str,
    db_path: Path | str | None = None,
) -> int:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO tasks (
                title, description, due_date, due_time, priority, category
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, description, due_date, due_time, priority, category),
        )
        return int(cursor.lastrowid)


def get_task(task_id: int, db_path: Path | str | None = None) -> dict | None:
    with _connection(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row is not None else None


def list_tasks(
    *,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    keyword: str = "",
    db_path: Path | str | None = None,
) -> list[dict]:
    conditions: list[str] = []
    parameters: list[str] = []
    if status is not None:
        conditions.append("status = ?")
        parameters.append(status)
    if priority is not None:
        conditions.append("priority = ?")
        parameters.append(priority)
    if category is not None:
        conditions.append("category = ?")
        parameters.append(category)
    if keyword:
        conditions.append("title LIKE ?")
        parameters.append(f"%{keyword}%")

    query = "SELECT * FROM tasks"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += (
        " ORDER BY CASE status WHEN '待完成' THEN 0 ELSE 1 END, "
        "due_date IS NULL, due_date, created_at DESC, id DESC"
    )

    with _connection(db_path) as connection:
        return [
            dict(row)
            for row in connection.execute(query, parameters).fetchall()
        ]


def claim_task_reminders(
    candidates: list[tuple[int, str, str, str]],
    *,
    reminded_at: str,
    db_path: Path | str | None = None,
) -> list[dict]:
    """原子地登记符合当前截止时间的提醒阶段，只返回首次登记成功的项目。"""
    created: list[dict] = []
    with _connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for task_id, reminder_type, due_date, due_time in candidates:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_reminders (
                    task_id, reminder_type, reminded_at
                )
                SELECT id, ?, ?
                FROM tasks
                WHERE id = ? AND status = '待完成'
                    AND due_date = ? AND due_time = ?
                """,
                (reminder_type, reminded_at, task_id, due_date, due_time),
            )
            if cursor.rowcount == 0:
                continue
            row = connection.execute(
                """
                SELECT t.id, t.title, t.due_date, t.due_time,
                       t.priority, t.category, r.reminder_type, r.reminded_at
                FROM task_reminders AS r
                JOIN tasks AS t ON t.id = r.task_id
                WHERE t.id = ? AND r.reminder_type = ?
                """,
                (task_id, reminder_type),
            ).fetchone()
            if row is not None:
                created.append(dict(row))
    return created


def update_task(
    task_id: int,
    *,
    title: str,
    description: str,
    due_date: str,
    due_time: str = "23:59",
    priority: str,
    category: str,
    db_path: Path | str | None = None,
) -> None:
    with _connection(db_path) as connection:
        old_deadline = connection.execute(
            "SELECT due_date, due_time FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if old_deadline is None:
            raise TaskNotFoundError(f"找不到编号为 {task_id} 的任务。")
        connection.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, due_date = ?, due_time = ?,
                priority = ?, category = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, description, due_date, due_time, priority, category, task_id),
        )
        if (
            old_deadline["due_date"] != due_date
            or old_deadline["due_time"] != due_time
        ):
            connection.execute(
                "DELETE FROM task_reminders WHERE task_id = ?", (task_id,)
            )


def mark_task_completed(
    task_id: int, db_path: Path | str | None = None
) -> None:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE tasks
            SET status = '已完成', updated_at = CURRENT_TIMESTAMP,
                completed_at = COALESCE(completed_at, ?)
            WHERE id = ?
            """,
            (datetime.now().astimezone().isoformat(), task_id),
        )
        if cursor.rowcount == 0:
            raise TaskNotFoundError(f"找不到编号为 {task_id} 的任务。")


def list_daily_plan_tasks(
    plan_date: str, db_path: Path | str | None = None
) -> list[dict]:
    with _connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT p.id AS plan_item_id, p.plan_date, p.created_at AS planned_at,
                   t.id, t.title, t.description, t.due_date, t.priority,
                   t.category, t.status, t.created_at, t.updated_at,
                   t.completed_at
            FROM daily_plan_items AS p
            JOIN tasks AS t ON t.id = p.task_id
            WHERE p.plan_date = ?
            ORDER BY CASE t.status WHEN '待完成' THEN 0 ELSE 1 END,
                     t.due_date, t.id
            """,
            (plan_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_available_daily_plan_tasks(
    plan_date: str, db_path: Path | str | None = None
) -> list[dict]:
    with _connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT t.*
            FROM tasks AS t
            WHERE t.status = '待完成'
              AND NOT EXISTS (
                  SELECT 1
                  FROM daily_plan_items AS p
                  WHERE p.task_id = t.id AND p.plan_date = ?
              )
            ORDER BY t.due_date IS NULL, t.due_date, t.id
            """,
            (plan_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def add_daily_plan_items(
    task_ids: list[int],
    plan_date: str,
    db_path: Path | str | None = None,
) -> int:
    if not task_ids:
        return 0
    with _connection(db_path) as connection:
        placeholders = ", ".join("?" for _ in task_ids)
        tasks_found = connection.execute(
            f"""
            SELECT id FROM tasks
            WHERE status = '待完成' AND id IN ({placeholders})
            """,
            task_ids,
        ).fetchall()
        found_ids = {row["id"] for row in tasks_found}
        invalid_ids = set(task_ids) - found_ids
        if invalid_ids:
            raise TaskNotFoundError(
                "部分任务不存在或已完成，无法加入今日计划。"
            )
        cursor = connection.executemany(
            """
            INSERT INTO daily_plan_items (task_id, plan_date)
            VALUES (?, ?)
            ON CONFLICT (task_id, plan_date) DO NOTHING
            """,
            [(task_id, plan_date) for task_id in dict.fromkeys(task_ids)],
        )
        return cursor.rowcount


def remove_daily_plan_item(
    plan_item_id: int,
    plan_date: str,
    db_path: Path | str | None = None,
) -> None:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM daily_plan_items WHERE id = ? AND plan_date = ?",
            (plan_item_id, plan_date),
        )
        if cursor.rowcount == 0:
            raise TaskNotFoundError("今日计划中找不到指定任务。")


def get_task_statistics(db_path: Path | str | None = None) -> dict:
    with _connection(db_path) as connection:
        rows = connection.execute("SELECT * FROM tasks").fetchall()
        tasks = [dict(row) for row in rows]
        total = len(tasks)
        completed = sum(task["status"] == "已完成" for task in tasks)
        today = date.today().isoformat()
        return {
            "tasks": tasks,
            "total": total,
            "completed": completed,
            "pending": total - completed,
            "overdue": sum(
                task["status"] == "待完成"
                and task["due_date"] is not None
                and task["due_date"] < today
                for task in tasks
            ),
            "completion_rate": completed / total if total else 0.0,
            "categories": _count_field(tasks, "category"),
            "priorities": _count_field(tasks, "priority"),
        }


def get_data_management_summary(db_path: Path | str | None = None) -> dict:
    """读取数据管理页面所需的业务记录数量和有效专注时长。"""
    with _connection(db_path) as connection:
        task_counts = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = '待完成' THEN 1 ELSE 0 END) AS pending
            FROM tasks
            """
        ).fetchone()
        focus_summary = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status = 'completed' THEN duration ELSE 0 END), 0)
                       AS completed_seconds,
                   SUM(CASE WHEN status IN ('running', 'paused') THEN 1 ELSE 0 END)
                       AS active
            FROM focus_records
            """
        ).fetchone()
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM daily_plan_items"
        ).fetchone()[0]
        return {
            "tasks_total": int(task_counts["total"]),
            "tasks_completed": int(task_counts["completed"] or 0),
            "tasks_pending": int(task_counts["pending"] or 0),
            "daily_plan_items": int(plan_count),
            "focus_records": int(focus_summary["total"]),
            "completed_focus_seconds": int(focus_summary["completed_seconds"]),
            "active_focus": bool(focus_summary["active"]),
        }


def clear_focus_records(db_path: Path | str | None = None) -> int:
    """清空专注历史；若计时器仍运行或暂停，则拒绝执行。"""
    with _connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute(
            "SELECT 1 FROM focus_records "
            "WHERE status IN ('running', 'paused') LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ActiveFocusError("当前有进行中或已暂停的番茄钟，请先结束或重置计时。")

        cursor = connection.execute("DELETE FROM focus_records")
        deleted = cursor.rowcount
        remaining = connection.execute(
            "SELECT COUNT(*) FROM focus_records"
        ).fetchone()[0]
        if remaining:
            raise DatabaseError("清理专注记录后仍检测到未删除的记录。")
        connection.execute(
            """
            INSERT INTO data_management_logs (action, focus_records_deleted)
            VALUES ('clear_focus_records', ?)
            """,
            (deleted,),
        )
        return deleted


def clear_completed_tasks(db_path: Path | str | None = None) -> dict[str, int]:
    """删除已完成任务及级联的每日计划项，并保留专注历史。"""
    with _connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        plan_before = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM daily_plan_items AS p
                JOIN tasks AS t ON t.id = p.task_id
                WHERE t.status = '已完成'
                """
            ).fetchone()[0]
        )
        focus_before = int(
            connection.execute("SELECT COUNT(*) FROM focus_records").fetchone()[0]
        )
        cursor = connection.execute("DELETE FROM tasks WHERE status = '已完成'")
        deleted_tasks = cursor.rowcount
        remaining_completed = connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = '已完成'"
        ).fetchone()[0]
        plan_after = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM daily_plan_items AS p
                JOIN tasks AS t ON t.id = p.task_id
                WHERE t.status = '已完成'
                """
            ).fetchone()[0]
        )
        focus_after = int(
            connection.execute("SELECT COUNT(*) FROM focus_records").fetchone()[0]
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if remaining_completed or plan_after or focus_before != focus_after or violations:
            raise DatabaseError("清理已完成任务后的数据校验失败，操作已回滚。")
        connection.execute(
            """
            INSERT INTO data_management_logs (
                action, tasks_deleted, daily_plan_items_deleted,
                focus_records_preserved
            )
            VALUES ('clear_completed_tasks', ?, ?, ?)
            """,
            (deleted_tasks, plan_before, focus_after),
        )
        return {
            "tasks_deleted": deleted_tasks,
            "daily_plan_items_deleted": plan_before,
            "focus_records_preserved": focus_after,
        }


def reset_all_business_data(db_path: Path | str | None = None) -> dict[str, int]:
    """在单一事务中删除任务、每日计划和专注记录，保留数据库结构。"""
    with _connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        counts = {
            "tasks_deleted": int(
                connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            ),
            "daily_plan_items_deleted": int(
                connection.execute("SELECT COUNT(*) FROM daily_plan_items").fetchone()[0]
            ),
            "focus_records_deleted": int(
                connection.execute("SELECT COUNT(*) FROM focus_records").fetchone()[0]
            ),
        }
        connection.execute("DELETE FROM focus_records")
        connection.execute("DELETE FROM daily_plan_items")
        connection.execute("DELETE FROM tasks")

        remaining = (
            int(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM daily_plan_items").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM focus_records").fetchone()[0]),
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if any(remaining) or violations:
            raise DatabaseError("重置后的数据校验失败，操作已回滚。")
        connection.execute(
            """
            INSERT INTO data_management_logs (
                action, tasks_deleted, daily_plan_items_deleted,
                focus_records_deleted
            )
            VALUES ('reset_all_data', ?, ?, ?)
            """,
            (
                counts["tasks_deleted"],
                counts["daily_plan_items_deleted"],
                counts["focus_records_deleted"],
            ),
        )
        return counts


def backup_database(
    backup_dir: Path | str, db_path: Path | str | None = None
) -> Path:
    """使用 SQLite 在线备份 API 创建不会覆盖现有文件的数据库副本。"""
    source_path = Path(db_path) if db_path is not None else DATABASE_PATH
    target_dir = Path(backup_dir)
    target: Path | None = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"ddl_planner_backup_{stamp}"
        for suffix in range(1000):
            name = f"{base_name}_{suffix}" if suffix else base_name
            candidate = target_dir / f"{name}.db"
            try:
                with candidate.open("xb"):
                    pass
            except FileExistsError:
                continue
            target = candidate
            break
        if target is None:
            raise FileExistsError("无法为备份分配不重复的文件名。")

        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(target, timeout=10)) as destination:
                source.backup(destination)
                integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.DatabaseError(
                        f"备份完整性检查失败：{integrity}"
                    )
                destination.commit()
        return target
    except (OSError, sqlite3.Error) as error:
        cleanup_error = ""
        if target is not None and target.exists():
            try:
                target.unlink()
            except OSError as cleanup_exception:
                cleanup_error = f"；临时备份文件清理失败：{cleanup_exception}"
        raise DatabaseError(
            f"创建数据库备份失败：{error}{cleanup_error}"
        ) from error


def _count_field(tasks: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        value = task[field] or "未分类"
        counts[value] = counts.get(value, 0) + 1
    return counts


def delete_task(task_id: int, db_path: Path | str | None = None) -> None:
    with _connection(db_path) as connection:
        cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise TaskNotFoundError(f"找不到编号为 {task_id} 的任务。")


def create_focus_record(
    *,
    task_id: int | None,
    task_title: str,
    duration: int,
    started_at: str,
    deadline_at: str | None,
    mode: str | None = None,
    planned_duration: int | None = None,
    segment_started_at: str | None = None,
    db_path: Path | str | None = None,
) -> int:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO focus_records (
                task_id, task_title, duration, started_at, status,
                remaining_seconds, deadline_at, mode, planned_duration,
                segment_started_at
            )
            VALUES (?, ?, 0, ?, 'running', ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task_title,
                started_at,
                duration,
                deadline_at,
                mode,
                planned_duration,
                segment_started_at,
            ),
        )
        return int(cursor.lastrowid)


def get_focus_record(
    record_id: int, db_path: Path | str | None = None
) -> dict | None:
    with _connection(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM focus_records WHERE id = ?", (record_id,)
        ).fetchone()
        return dict(row) if row is not None else None


def get_active_focus_record(db_path: Path | str | None = None) -> dict | None:
    with _connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM focus_records
            WHERE status IN ('running', 'paused')
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row is not None else None


def list_focus_records(
    *,
    started_on: str | None = None,
    db_path: Path | str | None = None,
) -> list[dict]:
    query = "SELECT * FROM focus_records"
    parameters: tuple[str, ...] = ()
    if started_on is not None:
        query += " WHERE substr(started_at, 1, 10) = ?"
        parameters = (started_on,)
    query += " ORDER BY julianday(started_at) DESC, id DESC"
    with _connection(db_path) as connection:
        return [
            dict(row)
            for row in connection.execute(query, parameters).fetchall()
        ]


def pause_focus_record(
    record_id: int,
    *,
    duration: int,
    remaining_seconds: int,
    db_path: Path | str | None = None,
) -> None:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE focus_records
            SET status = 'paused', duration = ?, remaining_seconds = ?,
                deadline_at = NULL, segment_started_at = NULL
            WHERE id = ? AND status = 'running'
            """,
            (duration, remaining_seconds, record_id),
        )
        if cursor.rowcount == 0:
            raise FocusRecordNotFoundError("当前专注计时已不存在或状态已变化。")


def resume_focus_record(
    record_id: int,
    *,
    deadline_at: str | None,
    segment_started_at: str | None = None,
    db_path: Path | str | None = None,
) -> None:
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE focus_records
            SET status = 'running', deadline_at = ?, segment_started_at = ?
            WHERE id = ? AND status = 'paused'
                AND (remaining_seconds > 0 OR mode = 'count_up')
            """,
            (deadline_at, segment_started_at, record_id),
        )
        if cursor.rowcount == 0:
            raise FocusRecordNotFoundError("当前专注计时已不存在或无法继续。")


def finish_focus_record(
    record_id: int,
    *,
    duration: int,
    completed_at: str,
    status: str,
    remaining_seconds: int,
    db_path: Path | str | None = None,
) -> None:
    if status not in ("completed", "abandoned"):
        raise ValueError("结束专注记录的状态必须是 completed 或 abandoned。")
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE focus_records
            SET status = ?, duration = ?, completed_at = ?,
                remaining_seconds = ?, deadline_at = NULL,
                segment_started_at = NULL
            WHERE id = ? AND status IN ('running', 'paused')
            """,
            (status, duration, completed_at, remaining_seconds, record_id),
        )
        if cursor.rowcount == 0:
            raise FocusRecordNotFoundError("当前专注计时已不存在或状态已变化。")
