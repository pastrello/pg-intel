import unittest

from pgintel.util import delta, pct, sha256_text


class UtilTests(unittest.TestCase):
    def test_delta_first_sample_is_zero(self):
        self.assertEqual(delta(100, None), 0)

    def test_delta_normal(self):
        self.assertEqual(delta(150, 100), 50)

    def test_delta_counter_reset(self):
        self.assertEqual(delta(12, 100), 12)

    def test_pct(self):
        self.assertAlmostEqual(pct(90, 100), 0.9)
        self.assertIsNone(pct(1, 0))

    def test_hash(self):
        self.assertEqual(len(sha256_text("select 1")), 64)


if __name__ == "__main__":
    unittest.main()
