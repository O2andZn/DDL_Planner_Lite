"""每日计划持久化和数据库迁移测试。"""

from datetime import date, timedelta
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src import database
from src.services import daily_plan, tasks


class DailyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "daily_plan.db"
        database.initialize_database(self.db_path)
        self.today = date.today()
        self.task_id = tasks.add_task(
            title="DDL 在下周的任务",
            due_date=self.today + timedelta(days=7),
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_plan_date_is_independent_of_task_deadline_and_persistent(self) -> None:
        self.assertEqual(daily_plan.add_tasks([self.task_id], self.today, self.db_path), 1)

        database.initialize_database(self.db_path)

        planned = daily_plan.get_planned_tasks(self.today, self.db_path)
        self.assertEqual([task["id"] for task in planned], [self.task_id])
        self.assertEqual(planned[0]["due_date"], (self.today + timedelta(days=7)).isoformat())
        self.assertEqual(daily_plan.get_available_tasks(self.today, self.db_path), [])

    def test_duplicate_same_day_is_ignored_but_other_day_is_allowed(self) -> None:
        daily_plan.add_tasks([self.task_id], self.today, self.db_path)
        self.assertEqual(
            daily_plan.add_tasks([self.task_id], self.today, self.db_path),
            0,
        )
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(
            daily_plan.add_tasks([self.task_id], tomorrow, self.db_path),
            1,
        )

        self.assertEqual(len(daily_plan.get_planned_tasks(self.today, self.db_path)), 1)
        self.assertEqual(len(daily_plan.get_planned_tasks(tomorrow, self.db_path)), 1)

    def test_completed_tasks_cannot_be_added_to_new_plan(self) -> None:
        tasks.complete_task(self.task_id, self.db_path)

        with self.assertRaises(database.TaskNotFoundError):
            daily_plan.add_tasks([self.task_id], self.today, self.db_path)

    def test_removing_plan_does_not_delete_original_task(self) -> None:
        daily_plan.add_tasks([self.task_id], self.today, self.db_path)
        plan_item = daily_plan.get_planned_tasks(self.today, self.db_path)[0]

        daily_plan.remove_task(plan_item["plan_item_id"], self.today, self.db_path)

        self.assertEqual(database.get_task(self.task_id, self.db_path)["title"], "DDL 在下周的任务")
        self.assertEqual(daily_plan.get_planned_tasks(self.today, self.db_path), [])

    def test_completing_task_keeps_planned_item_visible(self) -> None:
        daily_plan.add_tasks([self.task_id], self.today, self.db_path)
        tasks.complete_task(self.task_id, self.db_path)

        planned = daily_plan.get_planned_tasks(self.today, self.db_path)

        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["status"], "已完成")
        self.assertIsNotNone(planned[0]["completed_at"])

    def test_completion_timestamp_migration_preserves_related_records(self) -> None:
        migration_path = Path(self.temp_dir.name) / "migration.db"
        with closing(sqlite3.connect(migration_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        due_date TEXT NOT NULL,
                        priority TEXT NOT NULL DEFAULT '中',
                        category TEXT NOT NULL DEFAULT '其他',
                        status TEXT NOT NULL DEFAULT '待完成',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO tasks (title, due_date, status) VALUES (?, ?, ?)",
                    ("历史已完成任务", self.today.isoformat(), "已完成"),
                )
                connection.execute(
                    """
                    CREATE TABLE focus_records (
                        id INTEGER PRIMARY KEY,
                        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                        task_title TEXT NOT NULL,
                        duration INTEGER NOT NULL,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        status TEXT NOT NULL,
                        remaining_seconds INTEGER NOT NULL,
                        deadline_at TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO focus_records
                    VALUES (1, 1, '历史已完成任务', 1500, ?, ?, 'completed', 0, NULL)
                    """,
                    (
                        f"{self.today.isoformat()}T09:00:00+08:00",
                        f"{self.today.isoformat()}T09:25:00+08:00",
                    ),
                )
                connection.execute(
                    """
                    CREATE TABLE daily_plan_items (
                        id INTEGER PRIMARY KEY,
                        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                        plan_date TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(task_id, plan_date)
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO daily_plan_items (id, task_id, plan_date) VALUES (1, 1, ?)",
                    (self.today.isoformat(),),
                )

        database.initialize_database(migration_path)

        task = database.get_task(1, migration_path)
        record = database.get_focus_record(1, migration_path)
        planned = daily_plan.get_planned_tasks(self.today, migration_path)
        self.assertEqual(task["status"], "已完成")
        self.assertIsNone(task["completed_at"])
        self.assertEqual(record["task_title"], "历史已完成任务")
        self.assertEqual(len(planned), 1)


if __name__ == "__main__":
    unittest.main()
