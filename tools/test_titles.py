# -*- coding: utf-8 -*-
"""任务标题自动编号回归测试：python -m unittest discover -s tools -p 'test_titles.py'"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import unique_task_title


class UniqueTaskTitleTests(unittest.TestCase):
    def setUp(self):
        self.data = {"tasks": [
            {"id": "a", "title": "任务A", "archived": False},
            {"id": "b", "title": "任务A (1)", "archived": True},
            {"id": "c", "title": "任务A (3)", "archived": False},
        ]}

    def test_unused_title_is_unchanged(self):
        self.assertEqual(unique_task_title(self.data, "新任务"), "新任务")

    def test_archived_titles_reserve_names(self):
        self.assertEqual(unique_task_title(self.data, "任务A"), "任务A (2)")

    def test_smallest_available_suffix(self):
        self.assertEqual(unique_task_title(self.data, "任务A (1)"), "任务A (1) (1)")

    def test_rename_to_own_title_is_unchanged(self):
        self.assertEqual(unique_task_title(self.data, "任务A", exclude_id="a"), "任务A")

    def test_rename_to_another_tasks_title(self):
        self.assertEqual(unique_task_title(self.data, "任务A", exclude_id="c"), "任务A (2)")

    def test_missing_number_one(self):
        self.data["tasks"] = [{"id": "a", "title": "任务A", "archived": True},
                              {"id": "b", "title": "任务A (2)", "archived": False}]
        self.assertEqual(unique_task_title(self.data, "任务A"), "任务A (1)")

    def test_no_tasks(self):
        self.assertEqual(unique_task_title({"tasks": []}, "任务A"), "任务A")


if __name__ == "__main__":
    unittest.main()
