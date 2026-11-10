"""任务业务逻辑和 SQLite 持久化测试。"""

from datetime import date, timedelta
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src import database
from src.services import tasks


class TaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tasks.db"
        database.initialize_database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_sample_task(self) -> int:
        return tasks.add_task(
            title="  完成实验报告  ",
            description="整理实验结果",
            due_date=date.today() + timedelta(days=3),
            priority="高",
            category="实验报告",
            db_path=self.db_path,
        )

    def test_create_and_query_task(self) -> None:
        task_id = self.add_sample_task()

        saved = database.get_task(task_id, self.db_path)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["title"], "完成实验报告")
        self.assertEqual(saved["description"], "整理实验结果")
        self.assertEqual(saved["priority"], "高")
        self.assertEqual(saved["category"], "实验报告")
        self.assertEqual(saved["status"], "待完成")
        self.assertEqual(saved["due_time"], "23:59")

    def test_preset_and_custom_categories_are_saved_as_final_names(self) -> None:
        course_id = tasks.add_task(
            title="课程作业",
            due_date=date.today(),
            category="课程作业",
            db_path=self.db_path,
        )
        contest_id = tasks.add_task(
            title="参加竞赛",
            due_date=date.today(),
            category="竞赛",
            db_path=self.db_path,
        )
        custom_id = tasks.add_task(
            title="社团活动",
            due_date=date.today(),
            category=tasks.CUSTOM_CATEGORY_OPTION,
            custom_category=" 社团活动 ",
            db_path=self.db_path,
        )

        self.assertEqual(database.get_task(course_id, self.db_path)["category"], "课程作业")
        self.assertEqual(database.get_task(contest_id, self.db_path)["category"], "竞赛")
        self.assertEqual(database.get_task(custom_id, self.db_path)["category"], "社团活动")

    def test_empty_custom_category_is_rejected(self) -> None:
        with self.assertRaisesRegex(tasks.TaskValidationError, "自定义分类名称不能为空"):
            tasks.add_task(
                title="无分类任务",
                due_date=date.today(),
                category=tasks.CUSTOM_CATEGORY_OPTION,
                custom_category="   ",
                db_path=self.db_path,
            )
        self.assertEqual(database.list_tasks(db_path=self.db_path), [])

    def test_custom_category_can_be_edited_and_filtered(self) -> None:
        task_id = tasks.add_task(
            title="安排活动",
            due_date=date.today(),
            category=tasks.CUSTOM_CATEGORY_OPTION,
            custom_category="社团活动",
            db_path=self.db_path,
        )

        tasks.edit_task(
            task_id,
            title="安排志愿活动",
            due_date=date.today(),
            category=tasks.CUSTOM_CATEGORY_OPTION,
            custom_category="志愿服务",
            db_path=self.db_path,
        )

        saved = database.get_task(task_id, self.db_path)
        filtered = tasks.get_tasks(category="志愿服务", db_path=self.db_path)
        self.assertEqual(saved["category"], "志愿服务")
        self.assertEqual([task["id"] for task in filtered], [task_id])

    def test_deadline_time_can_be_created_and_edited(self) -> None:
        task_id = tasks.add_task(
            title="指定时间任务",
            due_date=date.today(),
            due_time="14:35",
            db_path=self.db_path,
        )
        self.assertEqual(database.get_task(task_id, self.db_path)["due_time"], "14:35")

        tasks.edit_task(
            task_id,
            title="指定时间任务",
            due_date=date.today() + timedelta(days=1),
            due_time="09:10",
            db_path=self.db_path,
        )
        self.assertEqual(database.get_task(task_id, self.db_path)["due_time"], "09:10")

    def test_edit_task(self) -> None:
        task_id = self.add_sample_task()

        tasks.edit_task(
            task_id,
            title="复习期中考试",
            description="复习第三至五章",
            due_date=date.today() + timedelta(days=7),
            priority="中",
            category="考试复习",
            db_path=self.db_path,
        )

        saved = database.get_task(task_id, self.db_path)
        self.assertEqual(saved["title"], "复习期中考试")
        self.assertEqual(saved["priority"], "中")
        self.assertEqual(saved["category"], "考试复习")
        self.assertEqual(saved["description"], "复习第三至五章")

    def test_mark_task_completed(self) -> None:
        task_id = self.add_sample_task()

        tasks.complete_task(task_id, self.db_path)

        self.assertEqual(database.get_task(task_id, self.db_path)["status"], "已完成")

    def test_delete_task(self) -> None:
        task_id = self.add_sample_task()

        tasks.remove_task(task_id, self.db_path)

        self.assertIsNone(database.get_task(task_id, self.db_path))

    def test_empty_title_is_rejected(self) -> None:
        with self.assertRaisesRegex(tasks.TaskValidationError, "任务名称不能为空"):
            tasks.add_task(
                title="  ",
                due_date=date.today(),
                db_path=self.db_path,
            )
        self.assertEqual(database.list_tasks(db_path=self.db_path), [])

    def test_filters_can_be_combined(self) -> None:
        first_id = self.add_sample_task()
        tasks.complete_task(first_id, self.db_path)
        tasks.add_task(
            title="准备数学考试",
            due_date=date.today(),
            priority="高",
            category="考试复习",
            db_path=self.db_path,
        )

        filtered = tasks.get_tasks(
            status="已完成",
            priority="高",
            keyword="实验",
            db_path=self.db_path,
        )

        self.assertEqual([task["id"] for task in filtered], [first_id])

    def test_data_survives_database_reinitialization(self) -> None:
        task_id = self.add_sample_task()

        database.initialize_database(self.db_path)

        saved = database.get_task(task_id, self.db_path)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["title"], "完成实验报告")

    def test_database_errors_are_reported(self) -> None:
        with self.assertRaises(database.DatabaseError):
            database.initialize_database(self.temp_dir.name)

    def test_legacy_schema_migration_preserves_existing_task(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        due_date TEXT,
                        priority TEXT NOT NULL DEFAULT 'medium',
                        category TEXT NOT NULL DEFAULT '其他',
                        is_completed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO tasks (title, due_date, priority, is_completed)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("旧任务", date.today().isoformat(), "high", 1),
                )

        database.initialize_database(legacy_path)

        saved = database.list_tasks(db_path=legacy_path)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["title"], "旧任务")
        self.assertEqual(saved[0]["priority"], "高")
        self.assertEqual(saved[0]["status"], "已完成")
        self.assertNotIn("is_completed", saved[0])


class DashboardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "dashboard.db"
        database.initialize_database(self.db_path)
        self.today = date(2026, 11, 9)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, title: str, due_date: date, *, complete: bool = False) -> int:
        task_id = tasks.add_task(
            title=title,
            due_date=due_date,
            db_path=self.db_path,
        )
        if complete:
            tasks.complete_task(task_id, self.db_path)
        return task_id

    def test_dashboard_counts_and_date_sections_use_database_tasks(self) -> None:
        overdue_id = self.add_task("逾期任务", self.today - timedelta(days=2))
        completed_overdue_id = self.add_task(
            "已完成逾期任务",
            self.today - timedelta(days=1),
            complete=True,
        )
        today_id = self.add_task("今日任务", self.today)
        tomorrow_id = self.add_task("明日任务", self.today + timedelta(days=1))
        last_day_id = self.add_task("第七天任务", self.today + timedelta(days=7))
        outside_id = self.add_task("第八天任务", self.today + timedelta(days=8))

        data = tasks.get_dashboard_data(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total"], 6)
        self.assertEqual(data["pending"], 5)
        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["overdue"], 1)
        self.assertEqual(data["completion_rate"], 1 / 6)
        self.assertEqual(
            [task["id"] for task in data["today_tasks"]],
            [today_id],
        )
        self.assertEqual(
            [task["id"] for task in data["upcoming_tasks"]],
            [today_id, tomorrow_id, last_day_id],
        )
        self.assertEqual(
            [task["id"] for task in data["overdue_tasks"]],
            [overdue_id],
        )
        self.assertNotIn(completed_overdue_id, [
            task["id"]
            for task in data["overdue_tasks"] + data["today_tasks"] + data["upcoming_tasks"]
        ])
        self.assertNotIn(outside_id, [task["id"] for task in data["upcoming_tasks"]])

    def test_dashboard_with_no_tasks_has_zero_completion(self) -> None:
        data = tasks.get_dashboard_data(today=self.today, db_path=self.db_path)

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["completion_rate"], 0.0)
        self.assertEqual(data["today_tasks"], [])
        self.assertEqual(data["upcoming_tasks"], [])
        self.assertEqual(data["overdue_tasks"], [])


if __name__ == "__main__":
    unittest.main()
