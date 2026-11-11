#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disk_cleaner 核心安全逻辑的单元测试。"""

import os
import shutil
import tempfile
import time
import unittest

import disk_cleaner as dc


class TestDiskCleaner(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="disk_cleaner_test_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_file(self, relative_path, size=1024, age_days=0):
        path = os.path.join(self.root, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        if age_days:
            timestamp = time.time() - age_days * 86400
            os.utime(path, (timestamp, timestamp))
        return path

    def test_fmt_size(self):
        self.assertEqual(dc.fmt_size(0), "0 B")
        self.assertEqual(dc.fmt_size(1536), "1.5 KB")
        self.assertEqual(dc.fmt_size(5 * 1024 ** 3), "5.0 GB")

    def test_measure_respects_age(self):
        self._make_file("old.tmp", size=2048, age_days=3)
        self._make_file("fresh.tmp", size=4096, age_days=0)
        info = dc.measure_paths([self.root], age_hours=24)
        self.assertEqual(info.total_files, 2)
        self.assertEqual(info.deletable_files, 1)
        self.assertEqual(info.deletable_bytes, 2048)

    def test_clean_keeps_fresh_files(self):
        old_file = self._make_file("sub/old.tmp", size=2048, age_days=3)
        fresh_file = self._make_file("sub/fresh.tmp", size=4096, age_days=0)
        category = dc.Category(
            key="test",
            title="测试",
            desc="测试类别",
            targets=lambda: [self.root],
            age_hours=24,
        )
        stats = dc.clean_category(category, None, dry_run=False)
        self.assertFalse(os.path.exists(old_file))
        self.assertTrue(os.path.exists(fresh_file))
        self.assertEqual(stats.deleted_bytes, 2048)
        self.assertEqual(stats.deleted_files, 1)

    def test_dry_run_deletes_nothing(self):
        old_file = self._make_file("old.tmp", size=2048, age_days=3)
        category = dc.Category(
            key="test",
            title="测试",
            desc="测试类别",
            targets=lambda: [self.root],
            age_hours=24,
        )
        stats = dc.clean_category(category, None, dry_run=True)
        self.assertTrue(os.path.exists(old_file))
        self.assertEqual(stats.deleted_bytes, 2048)

    def test_dedupe_paths(self):
        merged = dc._dedupe([self.root, self.root + os.sep, None, ""])
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main()
