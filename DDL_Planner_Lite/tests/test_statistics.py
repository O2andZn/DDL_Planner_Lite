"""任务和专注统计中心的服务层测试。"""

from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from src import database
from src.services import focus, statistics, tasks


class StatisticsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "statistics.db"
        database.initialize_database(self.db_path)
        self.today = date.today()
        self.now = datetime.now().astimezone()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, title: str, due_date: date, category: str = "其他") -> int:
        return tasks.add_task(
            title=title,
            due_date=due_date,
            category=category,
            db_path=self.db_path,
        )

    def test_task_counts_categories_priorities_and_weekly_timestamps(self) -> None:
        completed_id = self.add_task("完成的竞赛任务", self.today, "竞赛")
        overdue_id = self.add_task("逾期社团任务", self.today - timedelta(days=2), "社团活动")
        pending_id = self.add_task("科研任务", self.today + timedelta(days=4), "科研项目")
        tasks.complete_task(completed_id, self.db_path)
        with database._connection(self.db_path) as connection:
            connection.execute(
                "UPDATE tasks SET created_at = ?, completed_at = ? WHERE id = ?",
                (
                    self.now.isoformat(),
                    self.now.isoformat(),
                    completed_id,
                ),
            )
            connection.execute(
                "UPDATE tasks SET created_at = ? WHERE id IN (?, ?)",
                (
                    self.now.isoformat(),
                    overdue_id,
                    pending_id,
                ),
            )

        data = statistics.get_statistics(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total"], 3)
        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["pending"], 2)
        self.assertEqual(data["overdue"], 1)
        self.assertEqual(data["completion_rate"], 1 / 3)
        self.assertEqual(data["categories"]["社团活动"], 1)
        self.assertEqual(data["categories"]["科研项目"], 1)
        self.assertEqual(data["priorities"]["中"], 3)
        self.assertEqual(data["weekly_created"][-1], 3)
        self.assertEqual(data["weekly_completed"][-1], 1)

    def test_old_completed_task_without_timestamp_is_not_fabricated_as_completed(self) -> None:
        old_completed_id = self.add_task("旧版已完成任务", self.today)
        tasks.complete_task(old_completed_id, self.db_path)
        with database._connection(self.db_path) as connection:
            connection.execute(
                "UPDATE tasks SET completed_at = NULL WHERE id = ?",
                (old_completed_id,),
            )

        data = statistics.get_statistics(today=self.today, db_path=self.db_path)

        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["weekly_completed"][-1], 0)

    def test_focus_statistics_count_only_completed_records_and_local_completion_day(self) -> None:
        task_id = self.add_task("跨日任务", self.today)
        yesterday = self.now - timedelta(days=1)
        yesterday = yesterday.replace(hour=23, minute=50, second=0, microsecond=0)

        completed_id = database.create_focus_record(
            task_id=task_id,
            task_title="跨日任务",
            duration=focus.POMODORO_SECONDS,
            started_at=yesterday.isoformat(),
            deadline_at=(yesterday + timedelta(minutes=25)).isoformat(),
            db_path=self.db_path,
        )
        database.finish_focus_record(
            completed_id,
            duration=focus.POMODORO_SECONDS,
            completed_at=(self.now.replace(hour=0, minute=10, second=0, microsecond=0)).isoformat(),
            status="completed",
            remaining_seconds=0,
            db_path=self.db_path,
        )

        abandoned_id = database.create_focus_record(
            task_id=task_id,
            task_title="跨日任务",
            duration=focus.POMODORO_SECONDS,
            started_at=self.now.isoformat(),
            deadline_at=(self.now + timedelta(minutes=25)).isoformat(),
            db_path=self.db_path,
        )
        database.finish_focus_record(
            abandoned_id,
            duration=300,
            completed_at=self.now.isoformat(),
            status="abandoned",
            remaining_seconds=1200,
            db_path=self.db_path,
        )

        data = statistics.get_statistics(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total_focus_seconds"], focus.POMODORO_SECONDS)
        self.assertEqual(data["completed_pomodoros"], 1)
        self.assertEqual(data["weekly_focus_seconds"][-1], focus.POMODORO_SECONDS)
        self.assertEqual(len(data["recent_focus_records"]), 1)
        self.assertEqual(data["recent_focus_records"][0]["id"], completed_id)

    def test_count_up_increases_total_and_trend_without_counting_a_pomodoro(self) -> None:
        task_id = self.add_task("自由专注任务", self.today)
        started_at = self.now.replace(microsecond=0)
        record_id = focus.start_focus(
            task_id,
            mode="count_up",
            now=started_at,
            db_path=self.db_path,
        )
        finished_at = started_at + timedelta(seconds=137)
        self.assertEqual(
            focus.finish_count_up_focus(now=finished_at, db_path=self.db_path),
            record_id,
        )

        data = statistics.get_statistics(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total_focus_seconds"], 137)
        self.assertEqual(data["completed_pomodoros"], 0)
        self.assertEqual(data["count_up_sessions"], 1)
        self.assertEqual(data["weekly_focus_seconds"][-1], 137)
        self.assertEqual(data["recent_focus_records"][0]["mode"], "count_up")

    def test_empty_database_returns_zero_statistics_and_seven_days(self) -> None:
        data = statistics.get_statistics(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["completion_rate"], 0.0)
        self.assertEqual(data["total_focus_seconds"], 0)
        self.assertEqual(data["completed_pomodoros"], 0)
        self.assertEqual(len(data["week_dates"]), 7)
        self.assertEqual(data["weekly_created"], [0] * 7)
        self.assertEqual(data["weekly_completed"], [0] * 7)
        self.assertEqual(data["recent_focus_records"], [])


if __name__ == "__main__":
    unittest.main()
