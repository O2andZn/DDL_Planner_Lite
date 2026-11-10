"""DDL 时间字段和一次性提醒规则测试。"""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from src import database
from src.services import reminders, tasks


class ReminderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "reminders.db"
        database.initialize_database(self.db_path)
        self.now = datetime.now().astimezone().replace(second=0, microsecond=0)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task_at(self, title: str, due_at: datetime, due_time: str | None = None) -> int:
        return tasks.add_task(
            title=title,
            due_date=due_at.date(),
            due_time=due_time or due_at.strftime("%H:%M"),
            category="课程作业",
            db_path=self.db_path,
        )

    def test_deadline_migration_defaults_existing_tasks_to_2359(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "tasks-without-deadline-time.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
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
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO tasks (title, due_date) VALUES ('旧任务', '2026-11-10')"
                )

        database.initialize_database(legacy_path)
        migrated = database.list_tasks(db_path=legacy_path)
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["due_time"], "23:59")

    def test_reminder_thresholds_are_claimed_once_and_escalate(self) -> None:
        task_id = self.add_task_at(
            "阶段提醒任务", self.now + timedelta(hours=23)
        )

        first = reminders.get_due_reminders(now=self.now, db_path=self.db_path)
        self.assertEqual(
            [(item["id"], item["reminder_type"]) for item in first],
            [(task_id, "24h")],
        )
        self.assertEqual(
            reminders.get_due_reminders(now=self.now, db_path=self.db_path), []
        )

        second = reminders.get_due_reminders(
            now=self.now + timedelta(hours=12), db_path=self.db_path
        )
        self.assertEqual([item["reminder_type"] for item in second], ["12h"])

        urgent = reminders.get_due_reminders(
            now=self.now + timedelta(hours=21), db_path=self.db_path
        )
        self.assertEqual([item["reminder_type"] for item in urgent], ["3h"])

        overdue = reminders.get_due_reminders(
            now=self.now + timedelta(hours=24), db_path=self.db_path
        )
        self.assertEqual([item["reminder_type"] for item in overdue], ["overdue"])
        self.assertEqual(
            reminders.get_due_reminders(
                now=self.now + timedelta(hours=25), db_path=self.db_path
            ),
            [],
        )

    def test_completed_and_deleted_tasks_do_not_produce_reminders(self) -> None:
        completed_id = self.add_task_at(
            "已完成任务", self.now + timedelta(hours=2)
        )
        deleted_id = self.add_task_at(
            "已删除任务", self.now + timedelta(hours=2)
        )
        tasks.complete_task(completed_id, self.db_path)
        tasks.remove_task(deleted_id, self.db_path)

        self.assertEqual(
            reminders.get_due_reminders(now=self.now, db_path=self.db_path), []
        )
        with database._connection(self.db_path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM task_reminders").fetchone()[0],
                0,
            )

    def test_multiple_tasks_are_returned_together_and_deadline_edit_resets_stages(self) -> None:
        first_id = self.add_task_at("任务一", self.now + timedelta(hours=20))
        second_id = self.add_task_at("任务二", self.now + timedelta(hours=2))

        due = reminders.get_due_reminders(now=self.now, db_path=self.db_path)
        self.assertEqual(len(due), 4)
        self.assertEqual(
            {(item["id"], item["reminder_type"]) for item in due},
            {
                (first_id, "24h"),
                (second_id, "24h"),
                (second_id, "12h"),
                (second_id, "3h"),
            },
        )

        updated_deadline = self.now + timedelta(hours=2)
        tasks.edit_task(
            first_id,
            title="任务一",
            due_date=updated_deadline.date(),
            due_time=updated_deadline.strftime("%H:%M"),
            category="课程作业",
            db_path=self.db_path,
        )
        with database._connection(self.db_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM task_reminders WHERE task_id = ?",
                    (first_id,),
                ).fetchone()[0],
                0,
            )
        updated_reminders = reminders.get_due_reminders(
            now=self.now, db_path=self.db_path
        )
        self.assertEqual(
            {item["reminder_type"] for item in updated_reminders},
            {"24h", "12h", "3h"},
        )
        self.assertEqual({item["id"] for item in updated_reminders}, {first_id})

    def test_editing_non_deadline_fields_does_not_reset_reminders(self) -> None:
        task_id = self.add_task_at("不变截止时间", self.now + timedelta(hours=10))
        reminders.get_due_reminders(now=self.now, db_path=self.db_path)

        tasks.edit_task(
            task_id,
            title="修改名称",
            due_date=self.now.date() + timedelta(days=1),
            due_time=(self.now + timedelta(hours=10)).strftime("%H:%M"),
            description="仅编辑任务信息",
            category="课程作业",
            db_path=self.db_path,
        )

        self.assertEqual(
            reminders.get_due_reminders(now=self.now, db_path=self.db_path), []
        )


class ReminderDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "reminder-dialog.db"
        database.initialize_database(self.db_path)
        self.now = datetime.now().astimezone().replace(second=0, microsecond=0)
        tasks.add_task(
            title="提醒弹窗任务",
            due_date=(self.now + timedelta(hours=2)).date(),
            due_time=(self.now + timedelta(hours=2)).strftime("%H:%M"),
            category="实验报告",
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_later_dismisses_dialog_and_does_not_repeat_on_rerun(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "首页"
            app.run()
            self.assertEqual(len(app.session_state["ddl_pending_reminders"]), 3)
            app.button(key="ddl_reminder_later").click().run()
            self.assertNotIn("ddl_pending_reminders", app.session_state)
            self.assertEqual(
                reminders.get_due_reminders(now=self.now, db_path=self.db_path), []
            )
            self.assertFalse(app.exception)

    def test_view_task_routes_to_task_manager_and_filters_title(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "首页"
            app.run()
            app.button(key="ddl_reminder_view_task").click().run()
            self.assertEqual(app.sidebar.radio[0].value, "任务管理")
            self.assertEqual(app.session_state["task_search"], "提醒弹窗任务")
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
