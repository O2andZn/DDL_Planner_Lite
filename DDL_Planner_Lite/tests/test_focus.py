"""番茄钟状态转换和专注记录持久化测试。"""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database
from src.services import focus, statistics, tasks


class FocusServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "focus.db"
        database.initialize_database(self.db_path)
        self.start = datetime.now().astimezone().replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        self.task_id = tasks.add_task(
            title="完成课程作业",
            due_date=self.start.date(),
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        active = focus.get_active_focus(self.db_path)
        if active is not None:
            focus.reset_focus(now=self.start + timedelta(days=1), db_path=self.db_path)
        self.temp_dir.cleanup()

    def test_start_free_focus_and_reload_state(self) -> None:
        record_id = focus.start_focus(now=self.start, db_path=self.db_path)

        active = focus.get_active_focus(self.db_path)
        self.assertEqual(active["id"], record_id)
        self.assertIsNone(active["task_id"])
        self.assertEqual(active["task_title"], "自由专注")
        self.assertEqual(active["status"], "running")
        self.assertEqual(
            focus.get_remaining_seconds(active, now=self.start + timedelta(seconds=12)),
            focus.POMODORO_SECONDS - 12,
        )

    def test_focus_is_associated_with_selected_task(self) -> None:
        record_id = focus.start_focus(
            self.task_id, now=self.start, db_path=self.db_path
        )

        record = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(record["task_id"], self.task_id)
        self.assertEqual(record["task_title"], "完成课程作业")

    def test_pause_resume_uses_remaining_time_without_double_counting(self) -> None:
        record_id = focus.start_focus(
            self.task_id, now=self.start, db_path=self.db_path
        )
        paused_at = self.start + timedelta(seconds=100)
        focus.pause_focus(now=paused_at, db_path=self.db_path)

        paused = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["duration"], 100)
        self.assertEqual(paused["remaining_seconds"], focus.POMODORO_SECONDS - 100)

        resumed_at = self.start + timedelta(minutes=5)
        focus.resume_focus(now=resumed_at, db_path=self.db_path)
        resumed = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(
            focus.get_remaining_seconds(resumed, now=resumed_at),
            focus.POMODORO_SECONDS - 100,
        )
        self.assertEqual(
            focus.get_remaining_seconds(
                resumed, now=resumed_at + timedelta(seconds=35)
            ),
            focus.POMODORO_SECONDS - 135,
        )

        focus.pause_focus(
            now=resumed_at + timedelta(seconds=35), db_path=self.db_path
        )
        twice_paused = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(twice_paused["duration"], 135)
        self.assertEqual(
            twice_paused["remaining_seconds"], focus.POMODORO_SECONDS - 135
        )

    def test_expired_timer_creates_completed_record_and_stats(self) -> None:
        record_id = focus.start_focus(
            self.task_id, now=self.start, db_path=self.db_path
        )
        completed_at = self.start + timedelta(seconds=focus.POMODORO_SECONDS)

        self.assertEqual(
            focus.complete_expired_focus(now=completed_at, db_path=self.db_path),
            record_id,
        )
        record = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["duration"], focus.POMODORO_SECONDS)
        self.assertEqual(
            database.get_task(self.task_id, self.db_path)["status"],
            "待完成",
        )

        stats = focus.get_today_focus_stats(
            today=self.start.date(), now=completed_at, db_path=self.db_path
        )
        self.assertEqual(stats["total_seconds"], focus.POMODORO_SECONDS)
        self.assertEqual(stats["completed_pomodoros"], 1)
        self.assertEqual(stats["task_totals"][0]["task_title"], "完成课程作业")

    def test_reset_saves_actual_time_without_counting_completed_pomodoro(self) -> None:
        record_id = focus.start_focus(
            self.task_id, now=self.start, db_path=self.db_path
        )
        reset_at = self.start + timedelta(seconds=240)

        focus.reset_focus(now=reset_at, db_path=self.db_path)

        record = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(record["status"], "abandoned")
        self.assertEqual(record["duration"], 240)
        self.assertIsNotNone(record["completed_at"])
        stats = focus.get_today_focus_stats(
            today=self.start.date(), now=reset_at, db_path=self.db_path
        )
        self.assertEqual(stats["total_seconds"], 0)
        self.assertEqual(stats["completed_pomodoros"], 0)

    def test_task_deletion_keeps_focus_title_snapshot(self) -> None:
        record_id = focus.start_focus(
            self.task_id, now=self.start, db_path=self.db_path
        )

        tasks.remove_task(self.task_id, self.db_path)

        record = database.get_focus_record(record_id, self.db_path)
        self.assertIsNone(record["task_id"])
        self.assertEqual(record["task_title"], "完成课程作业")

    def test_active_timer_is_persisted_and_only_one_can_run(self) -> None:
        first_id = focus.start_focus(now=self.start, db_path=self.db_path)
        with self.assertRaises(focus.FocusTimerError):
            focus.start_focus(self.task_id, now=self.start, db_path=self.db_path)

        focus.pause_focus(
            now=self.start + timedelta(seconds=10), db_path=self.db_path
        )
        self.assertEqual(focus.get_active_focus(self.db_path)["id"], first_id)

    def test_completed_work_from_another_day_is_not_in_todays_stats(self) -> None:
        previous_day = self.start - timedelta(days=1)
        record_id = focus.start_focus(now=previous_day, db_path=self.db_path)
        focus.complete_expired_focus(
            now=previous_day + timedelta(seconds=focus.POMODORO_SECONDS),
            db_path=self.db_path,
        )

        stats = focus.get_today_focus_stats(
            today=self.start.date(), now=self.start, db_path=self.db_path
        )

        self.assertEqual(
            database.get_focus_record(record_id, self.db_path)["status"],
            "completed",
        )
        self.assertEqual(stats["total_seconds"], 0)
        self.assertEqual(stats["completed_pomodoros"], 0)
        self.assertIsNone(stats["recent_record"])

    def test_countdown_duration_defaults_and_validates_custom_range(self) -> None:
        self.assertEqual(focus.validate_countdown_minutes(15), 15 * 60)
        self.assertEqual(focus.validate_countdown_minutes(45), 45 * 60)
        self.assertEqual(focus.validate_countdown_minutes(180), 180 * 60)
        for invalid_minutes in (0, 181, True):
            with self.subTest(minutes=invalid_minutes):
                with self.assertRaises(focus.FocusTimerError):
                    focus.validate_countdown_minutes(invalid_minutes)

        default_id = focus.start_focus(now=self.start, db_path=self.db_path)
        default_record = database.get_focus_record(default_id, self.db_path)
        self.assertEqual(default_record["planned_duration"], focus.POMODORO_SECONDS)
        focus.reset_focus(now=self.start, db_path=self.db_path)

        custom_id = focus.start_focus(
            self.task_id,
            planned_duration_seconds=45 * 60,
            now=self.start,
            db_path=self.db_path,
        )
        custom_record = database.get_focus_record(custom_id, self.db_path)
        self.assertEqual(custom_record["mode"], "countdown")
        self.assertEqual(custom_record["planned_duration"], 45 * 60)
        self.assertEqual(custom_record["remaining_seconds"], 45 * 60)
        self.assertEqual(
            datetime.fromisoformat(custom_record["deadline_at"]) - self.start,
            timedelta(minutes=45),
        )
        focus.reset_focus(now=self.start, db_path=self.db_path)

        with self.assertRaises(focus.FocusTimerError):
            focus.start_focus(
                planned_duration_seconds=181 * 60,
                now=self.start,
                db_path=self.db_path,
            )

    def test_count_up_pause_resume_end_and_statistics_use_actual_time(self) -> None:
        record_id = focus.start_focus(
            self.task_id,
            mode="count_up",
            now=self.start,
            db_path=self.db_path,
        )
        started = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(started["mode"], "count_up")
        self.assertIsNone(started["planned_duration"])
        self.assertEqual(focus.get_elapsed_seconds(started, now=self.start), 0)
        self.assertEqual(
            focus.get_elapsed_seconds(
                started, now=self.start + timedelta(seconds=37)
            ),
            37,
        )

        paused_at = self.start + timedelta(seconds=37)
        focus.pause_focus(now=paused_at, db_path=self.db_path)
        paused = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(paused["duration"], 37)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(
            focus.get_elapsed_seconds(
                paused, now=paused_at + timedelta(hours=2)
            ),
            37,
        )

        resumed_at = paused_at + timedelta(hours=2)
        focus.resume_focus(now=resumed_at, db_path=self.db_path)
        resumed = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(
            focus.get_elapsed_seconds(
                resumed, now=resumed_at + timedelta(seconds=42)
            ),
            79,
        )
        ended_at = resumed_at + timedelta(seconds=42)
        self.assertEqual(
            focus.finish_count_up_focus(now=ended_at, db_path=self.db_path),
            record_id,
        )
        self.assertIsNone(
            focus.finish_count_up_focus(
                now=ended_at + timedelta(seconds=1), db_path=self.db_path
            )
        )
        completed = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(completed["duration"], 79)
        self.assertEqual(completed["status"], "completed")

        stats = focus.get_today_focus_stats(
            today=self.start.date(), now=ended_at, db_path=self.db_path
        )
        self.assertEqual(stats["total_seconds"], 79)
        self.assertEqual(stats["completed_pomodoros"], 0)
        self.assertEqual(stats["count_up_sessions"], 1)
        self.assertEqual(stats["task_totals"][0]["count_up_sessions"], 1)

    def test_resetting_count_up_is_not_counted_as_a_valid_focus_session(self) -> None:
        record_id = focus.start_focus(
            mode="count_up", now=self.start, db_path=self.db_path
        )
        focus.reset_focus(
            now=self.start + timedelta(seconds=59), db_path=self.db_path
        )

        record = database.get_focus_record(record_id, self.db_path)
        self.assertEqual(record["status"], "abandoned")
        self.assertEqual(record["duration"], 59)
        stats = focus.get_today_focus_stats(
            today=self.start.date(),
            now=self.start + timedelta(seconds=59),
            db_path=self.db_path,
        )
        self.assertEqual(stats["total_seconds"], 0)
        self.assertEqual(stats["completed_pomodoros"], 0)
        self.assertEqual(stats["count_up_sessions"], 0)

    def test_old_focus_record_schema_migrates_without_fabricating_mode(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-focus.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    due_date TEXT,
                    priority TEXT NOT NULL DEFAULT '中',
                    category TEXT NOT NULL DEFAULT '其他',
                    status TEXT NOT NULL DEFAULT '待完成',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE focus_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    task_title TEXT NOT NULL,
                    duration INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    remaining_seconds INTEGER NOT NULL DEFAULT 0,
                    deadline_at TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO focus_records (
                    task_title, duration, started_at, completed_at, status
                )
                VALUES ('旧记录', ?, ?, ?, 'completed')
                """,
                (
                    focus.POMODORO_SECONDS,
                    self.start.isoformat(),
                    (self.start + timedelta(minutes=25)).isoformat(),
                ),
            )

        connection.close()
        database.initialize_database(legacy_path)
        legacy_record = database.list_focus_records(db_path=legacy_path)[0]
        self.assertIsNone(legacy_record["mode"])
        self.assertIsNone(legacy_record["planned_duration"])
        self.assertEqual(legacy_record["duration"], focus.POMODORO_SECONDS)
        stats = statistics.get_statistics(
            today=self.start.date(), db_path=legacy_path
        )
        self.assertEqual(stats["completed_pomodoros"], 1)
        self.assertEqual(stats["count_up_sessions"], 0)

    def test_daily_plan_ui_applies_quick_duration_and_persists_running_timer(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "今日计划"
            app.run()
            self.assertEqual(
                app.radio(key="focus_timer_mode").value,
                "countdown",
            )
            self.assertEqual(
                app.selectbox(key="focus_duration_choice").value,
                "25分钟",
            )

            app.selectbox(key="focus_duration_choice").set_value("15分钟").run()
            self.assertEqual(app.session_state["focus_planned_minutes"], 15)
            app.button(key="focus_start").click().run()
            active = focus.get_active_focus(self.db_path)
            self.assertEqual(active["planned_duration"], 15 * 60)
            self.assertEqual(active["mode"], "countdown")
            active_id = active["id"]

            app.run()
            self.assertEqual(focus.get_active_focus(self.db_path)["id"], active_id)
            self.assertTrue(app.radio(key="focus_timer_mode").disabled)
            app.button(key="focus_reset").click().run()
            self.assertIsNone(focus.get_active_focus(self.db_path))
            self.assertFalse(app.exception)

    def test_daily_plan_ui_custom_duration_and_count_up_mode(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.object(database, "DATABASE_PATH", self.db_path):
            app = AppTest.from_file(str(app_path), default_timeout=15)
            app.session_state["main_navigation"] = "今日计划"
            app.run()
            app.selectbox(key="focus_duration_choice").set_value("自定义").run()
            app.number_input(key="focus_custom_minutes").set_value(45).run()
            app.button(key="focus_apply_custom_duration").click().run()
            self.assertEqual(app.session_state["focus_planned_minutes"], 45)
            app.button(key="focus_start").click().run()
            countdown = focus.get_active_focus(self.db_path)
            self.assertEqual(countdown["planned_duration"], 45 * 60)
            app.button(key="focus_reset").click().run()

            app.radio(key="focus_timer_mode").set_value("count_up").run()
            app.button(key="focus_start").click().run()
            count_up = focus.get_active_focus(self.db_path)
            self.assertEqual(count_up["mode"], "count_up")
            self.assertIsNone(count_up["deadline_at"])
            self.assertEqual(count_up["remaining_seconds"], 0)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
