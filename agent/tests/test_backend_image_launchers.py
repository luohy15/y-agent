import unittest

from agent.codex import _codex_build_exec
from agent.gemini_cli import _gemini_build_exec


class BackendImageLauncherTest(unittest.TestCase):
    def test_codex_build_exec_adds_image_flags(self):
        cmd = _codex_build_exec(["codex", "exec"], "chat-1", "describe", ["/tmp/a.jpg", "/tmp/b.png"])

        self.assertIn("'--image' '/tmp/a.jpg'", cmd)
        self.assertIn("'--image' '/tmp/b.png'", cmd)
        self.assertTrue(cmd.endswith(" 'describe'"))

    def test_gemini_build_exec_appends_image_paths_to_prompt(self):
        cmd = _gemini_build_exec(["gemini"], "chat-1", "describe", ["/tmp/a.jpg"])

        self.assertIn("Attached image file path(s):", cmd)
        self.assertIn("/tmp/a.jpg", cmd)


if __name__ == "__main__":
    unittest.main()
