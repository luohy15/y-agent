import unittest

from agent.poll_loop import _normalize_steer_msg


class SteerImagesSmokeTest(unittest.TestCase):
    def test_poll_loop_accepts_old_and_new_steer_shapes(self):
        self.assertEqual(_normalize_steer_msg(("text", "m1")), ("text", "m1", []))
        self.assertEqual(_normalize_steer_msg(("text", "m2", ["/tmp/a.png"])), ("text", "m2", ["/tmp/a.png"]))


if __name__ == "__main__":
    unittest.main()
