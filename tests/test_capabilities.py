import unittest
from datetime import date

from pgintel.capabilities import lifecycle_info, major_from_version_num, support_info


class CapabilityTests(unittest.TestCase):
    def test_version_num_mapping_13_to_18(self):
        for major in range(13, 19):
            self.assertEqual(major_from_version_num(major * 10000 + 23), major)

    def test_supported_range(self):
        self.assertEqual(support_info(13)["level"], "supported")
        self.assertEqual(support_info(18)["level"], "supported")
        self.assertEqual(support_info(12)["level"], "unsupported")
        self.assertEqual(support_info(19)["level"], "unvalidated_newer")

    def test_expected_major_mismatch(self):
        self.assertFalse(support_info(16, 15)["expected_major_match"])

    def test_pg13_eol(self):
        info = lifecycle_info(13, today=date(2026, 9, 18))
        self.assertEqual(info["status"], "eol")

    def test_pg14_near_eol(self):
        info = lifecycle_info(14, today=date(2026, 9, 18))
        self.assertEqual(info["status"], "near_eol")
        self.assertGreater(info["days_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
