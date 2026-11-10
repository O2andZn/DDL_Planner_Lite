"""数据清理、备份、统计刷新及确认流程测试。"""

from datetime import date, datetime, timedelta
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database
from src.services import daily_plan, focus, statistics, tasks


class DataManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "management.db"
        database.initialize_database(self.db_path)
        self.today = date.today()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, title: str, due_date: date | None = None) -> int:
        return tasks.add_task(
            title=title,
            due_date=due_date or self.today + timedelta(days=2),
            category="课程作业",
            db_path=self.db_path,
        )

    def add_focus_record(
        self, task_id: int | None, title: str, *, status: str = "completed"
    ) -> int:
        started = datetime.now().astimezone() - timedelta(minutes=25)
        record_id = database.create_focus_record(
            task_id=task_id,
            task_title=title,
            duration=focus.POMODORO_SECONDS,
            started_at=started.isoformat(),
            deadline_at=(started + timedelta(seconds=focus.POMODORO_SECONDS)).isoformat(),
            db_path=self.db_path,
        )
        if status != "running":
            database.finish_focus_record(
                record_id,
                duration=focus.POMODORO_SECONDS if status == "completed" else 300,
                completed_at=datetime.now().astimezone().isoformat(),
                status=status,
                remaining_seconds=0 if status == "completed" else 1200,
                db_path=self.db_path,
            )
        return record_id

    def counts(self) -> tuple[int, int, int]:
        summary = database.get_data_management_summary(self.db_path)
        return (
            summary["tasks_total"],
            summary["daily_plan_items"],
            summary["focus_records"],
        )

    def test_clearing_focus_records_preserves_tasks_and_daily_plan(self) -> None:
        task_id = self.add_task("保留任务")
        daily_plan.add_tasks([task_id], self.today, self.db_path)
        self.add_focus_record(task_id, "保留任务")

        from src.services import data_management

        deleted = data_management.clear_focus_history(self.db_path)

        self.assertEqual(deleted, 1)
        self.assertEqual(self.counts(), (1, 1, 0))
        summary = statistics.get_statistics(today=self.today, db_path=self.db_path)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["completed_pomodoros"], 0)
        self.assertEqual(summary["total_focus_seconds"], 0)

    def test_clearing_focus_is_blocked_while_timer_is_active(self) -> None:
        task_id = self.add_task("计时任务")
        record_id = focus.start_focus(task_id, db_path=self.db_path)

        with self.assertRaises(database.ActiveFocusError):
            database.clear_focus_records(self.db_path)

        self.assertEqual(database.get_focus_record(record_id, self.db_path)["status"], "running")
        self.assertEqual(database.get_data_management_summary(self.db_path)["focus_records"], 1)

    def test_completed_task_cleanup_preserves_pending_tasks_and_focus_history(self) -> None:
        completed_id = self.add_task("已完成任务")
        pending_id = self.add_task("待完成任务")
        daily_plan.add_tasks([completed_id, pending_id], self.today, self.db_path)
        tasks.complete_task(completed_id, self.db_path)
        completed_record_id = self.add_focus_record(completed_id, "已完成任务")
        pending_record_id = self.add_focus_record(pending_id, "待完成任务")

        from src.services import data_management

        result = data_management.clear_completed_tasks(self.db_path)

        self.assertEqual(
            result,
            {
                "tasks_deleted": 1,
                "daily_plan_items_deleted": 1,
                "focus_records_preserved": 2,
            },
        )
        self.assertIsNone(database.get_task(completed_id, self.db_path))
        self.assertEqual(database.get_task(pending_id, self.db_path)["status"], "待完成")
        self.assertEqual(len(daily_plan.get_planned_tasks(self.today, self.db_path)), 1)
        completed_record = database.get_focus_record(completed_record_id, self.db_path)
        self.assertIsNone(completed_record["task_id"])
        self.assertEqual(completed_record["task_title"], "已完成任务")
        self.assertEqual(
            database.get_focus_record(pending_record_id, self.db_path)["task_id"],
            pending_id,
        )
        summary = statistics.get_statistics(today=self.today, db_path=self.db_path)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["categories"], {"课程作业": 1})
        self.assertEqual(summary["completed_pomodoros"], 2)
        dashboard = tasks.get_dashboard_data(today=self.today, db_path=self.db_path)
        self.assertEqual(dashboard["total"], 1)
        self.assertEqual(dashboard["pending"], 1)
        self.assertEqual(dashboard["completed"], 0)

    def test_completed_task_cleanup_rolls_back_all_changes_on_failure(self) -> None:
        completed_id = self.add_task("待清理任务")
        daily_plan.add_tasks([completed_id], self.today, self.db_path)
        tasks.complete_task(completed_id, self.db_path)
        self.add_focus_record(completed_id, "待清理任务")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TRIGGER reject_completed_cleanup
                    BEFORE DELETE ON tasks
                    WHEN OLD.status = '已完成'
                    BEGIN
                        SELECT RAISE(ABORT, 'injected cleanup failure');
                    END
                    """
                )

        with self.assertRaises(database.DatabaseError):
            database.clear_completed_tasks(self.db_path)

        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(database.get_task(completed_id, self.db_path)["status"], "已完成")

    def test_reset_rolls_back_prior_table_deletes_on_failure(self) -> None:
        task_id = self.add_task("保留任务")
        daily_plan.add_tasks([task_id], self.today, self.db_path)
        self.add_focus_record(task_id, "保留任务")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TRIGGER reject_task_reset
                    BEFORE DELETE ON tasks
                    BEGIN
                        SELECT RAISE(ABORT, 'injected reset failure');
                    END
                    """
                )

        with self.assertRaises(database.DatabaseError):
            database.reset_all_business_data(self.db_path)

        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(database.list_focus_records(db_path=self.db_path)[0]["task_id"], task_id)

    def test_reset_clears_all_business_data_keeps_schema_and_accepts_new_tasks(self) -> None:
        pending_id = self.add_task("待完成任务")
        completed_id = self.add_task("已完成任务")
        daily_plan.add_tasks([pending_id, completed_id], self.today, self.db_path)
        tasks.complete_task(completed_id, self.db_path)
        self.add_focus_record(pending_id, "待完成任务")

        from src.services import data_management

        result = data_management.reset_all_data(self.db_path)

        self.assertEqual(result["tasks_deleted"], 2)
        self.assertEqual(result["daily_plan_items_deleted"], 2)
        self.assertEqual(result["focus_records_deleted"], 1)
        self.assertEqual(self.counts(), (0, 0, 0))
        summary = statistics.get_statistics(today=self.today, db_path=self.db_path)
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["completion_rate"], 0.0)
        self.assertEqual(summary["categories"], {})
        self.assertEqual(summary["priorities"], {})
        self.assertEqual(summary["completed_pomodoros"], 0)
        self.assertEqual(summary["weekly_focus_seconds"], [0] * 7)
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            log = connection.execute(
                "SELECT action, tasks_deleted FROM data_management_logs "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertTrue({"tasks", "daily_plan_items", "focus_records"} <= tables)
        self.assertEqual(log, ("reset_all_data", 2))
        new_id = self.add_task("重置后新任务")
        self.assertEqual(database.get_task(new_id, self.db_path)["title"], "重置后新任务")

    def test_backup_creates_distinct_readable_database_copies(self) -> None:
        task_id = self.add_task("备份验证任务")
        backup_dir = self.root / "backups"

        from src.services import data_management

        first = data_management.create_backup(self.db_path, backup_dir)
        second = data_management.create_backup(self.db_path, backup_dir)

        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        with closing(sqlite3.connect(first)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                connection.execute("SELECT id FROM tasks").fetchone()[0], task_id
            )

    def test_statistics_clear_focus_confirmation_preserves_other_data(self) -> None:
        pending_id = self.add_task("确认保护任务")
        daily_plan.add_tasks([pending_id], self.today, self.db_path)
        self.add_focus_record(pending_id, "确认保护任务")

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "数据统计"
            app.session_state["theme_toggle"] = True
            app.run()
            self.assertEqual(self.counts(), (1, 1, 1))
            self.assertNotIn("数据管理", app.sidebar.radio[0].options)

            app.button(key="open_clear_focus_confirmation").click().run()
            app.button(key="cancel_clear_focus_records").click().run()
            self.assertEqual(self.counts(), (1, 1, 1))
            self.assertTrue(app.session_state["theme_toggle"])

            app.button(key="open_clear_focus_confirmation").click().run()
            app.button(key="confirm_clear_focus_records").click().run()
            self.assertEqual(self.counts(), (1, 1, 0))
            summary = statistics.get_statistics(today=self.today, db_path=self.db_path)
            self.assertEqual(summary["total_focus_seconds"], 0)
            self.assertEqual(summary["completed_pomodoros"], 0)
            self.assertEqual(summary["weekly_focus_seconds"], [0] * 7)
            self.assertEqual(len(daily_plan.get_planned_tasks(self.today, self.db_path)), 1)
            self.assertEqual(database.get_task(pending_id, self.db_path)["status"], "待完成")
            metric_values = {metric.label: metric.value for metric in app.metric}
            self.assertEqual(metric_values["累计有效专注时长"], "0 分钟")
            self.assertEqual(metric_values["已完成番茄钟"], "0")
            self.assertTrue(
                any(
                    "还没有已完成的番茄钟记录" in message.value
                    for message in app.info
                )
            )
            self.assertFalse(app.exception)

    def test_statistics_clear_focus_dialog_blocks_an_active_timer(self) -> None:
        task_id = self.add_task("进行中的专注")
        focus.start_focus(task_id, db_path=self.db_path)

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "数据统计"
            app.run()
            app.button(key="open_clear_focus_confirmation").click().run()
            self.assertTrue(app.button(key="confirm_clear_focus_records").disabled)
            self.assertEqual(self.counts(), (1, 0, 1))
            self.assertFalse(app.exception)

    def test_removed_data_management_navigation_falls_back_to_home(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "数据管理"
            app.run()
            self.assertEqual(app.sidebar.radio[0].value, "首页")
            self.assertNotIn("数据管理", app.sidebar.radio[0].options)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
