"""Runs last (alphabetical order): proves the real home was never touched."""

import unittest

from tests import REAL_HOME, REAL_HOME_BEFORE, real_home_state


class RealHomeGuardTests(unittest.TestCase):
    """The suite must leave ``~/.config/konsave`` and the log as it found them."""

    def test_the_real_home_was_not_touched(self):
        self.assertEqual(
            real_home_state(),
            REAL_HOME_BEFORE,
            f"a test modified Konsave files in the real home ({REAL_HOME})",
        )


if __name__ == "__main__":
    unittest.main()
