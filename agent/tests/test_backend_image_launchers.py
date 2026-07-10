import unittest

from agent.codex import _codex_build_exec
from agent.gemini_cli import _gemini_build_exec
from agent.grok_build import _grok_build_exec
from agent.pi_cli import _pi_build_exec


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

    def test_grok_build_exec_appends_image_paths_to_prompt(self):
        cmd = _grok_build_exec(["grok"], "chat-1", "describe", ["/tmp/a.jpg"])

        self.assertIn("Attached image file path(s):", cmd)
        self.assertIn("/tmp/a.jpg", cmd)

    def test_pi_build_exec_appends_image_paths_and_positional_prompt(self):
        cmd = _pi_build_exec(["pi", "-p", "--mode", "json"], "chat-1", "describe", ["/tmp/a.jpg"])

        self.assertIn("Attached image file path(s):", cmd)
        self.assertIn("/tmp/a.jpg", cmd)
        # prompt is positional (no -p flag prefix; -p already means --print)
        self.assertNotIn("'-p' 'describe", cmd)
        self.assertTrue(cmd.startswith("'pi' '-p' '--mode' 'json'"))


if __name__ == "__main__":
    unittest.main()
