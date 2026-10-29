"""Run these identical functional and regression tests on both snapshots."""
import copy
import importlib.util
import os
from pathlib import Path
import unittest

source = Path(os.environ["TICKETS_SOURCE"])
spec = importlib.util.spec_from_file_location("tickets_under_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
list_tickets = module.list_tickets

RECORDS = [
    {"id": "a", "status": "open", "created_at": 1},
    {"id": "b", "status": "closed", "created_at": 4},
    {"id": "c", "status": "in_progress", "created_at": 3},
    {"id": "d", "status": "open", "created_at": 2},
]


class TargetStatusTests(unittest.TestCase):
    def test_each_status(self):
        for status, ids in [("open", ["d", "a"]), ("closed", ["b"]), ("in_progress", ["c"])]:
            with self.subTest(status=status):
                self.assertEqual([x["id"] for x in list_tickets(RECORDS, status=status)], ids)

    def test_filter_before_limit(self):
        self.assertEqual([x["id"] for x in list_tickets(RECORDS, status="open", limit=1)], ["d"])

    def test_no_match(self):
        self.assertEqual(list_tickets(RECORDS[:1], status="closed"), [])

    def test_reject_invalid_even_empty(self):
        for records in [RECORDS, []]:
            with self.assertRaises(ValueError):
                list_tickets(records, status="archived")


class RegressionTests(unittest.TestCase):
    def test_unfiltered_and_limit(self):
        self.assertEqual([x["id"] for x in list_tickets(RECORDS)], ["b", "c", "d", "a"])
        self.assertEqual(list_tickets(RECORDS, limit=0), [])
        many = [{"id": str(i), "status": "open", "created_at": i} for i in range(12)]
        self.assertEqual(len(list_tickets(many)), 10)

    def test_invalid_limits(self):
        for limit in [-1, 1.5, True]:
            with self.assertRaises(ValueError):
                list_tickets(RECORDS, limit=limit)

    def test_stable_ties(self):
        rows = [{"id": x, "status": "open", "created_at": 1} for x in ["a", "c", "b"]]
        self.assertEqual([x["id"] for x in list_tickets(rows)], ["c", "b", "a"])

    def test_inputs_unchanged(self):
        rows = copy.deepcopy(RECORDS)
        list_tickets(rows)
        self.assertEqual(rows, RECORDS)


if __name__ == "__main__":
    unittest.main()
