import tomllib
import unittest

from storage.entity.dto import BotConfig

from agent.grok_config import (
    build_grok_model_entry,
    merge_grok_config_toml,
    write_grok_config_toml,
)


class _FakeStd:
    def __init__(self, data: str = "", exit_code: int = 0):
        self._data = data.encode()
        self.channel = self

    def recv_exit_status(self) -> int:
        return 0

    def read(self) -> bytes:
        return self._data


class _FakeSFTPFile:
    def __init__(self, sink: dict, path: str):
        self._sink = sink
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, content: str) -> None:
        self._sink[self._path] = content


class _FakeSFTP:
    def __init__(self, writes: dict):
        self._writes = writes

    def open(self, path: str, mode: str):
        return _FakeSFTPFile(self._writes, path)

    def close(self) -> None:
        pass


class _FakeSSHClient:
    """Records executed commands and serves a preseeded ~/.grok/config.toml so a
    regression test can assert the remote paths are absolute (no literal ``~``)."""

    def __init__(self, home: str, existing_config: str = ""):
        self._home = home
        self._existing = existing_config
        self.commands: list[str] = []
        self.writes: dict[str, str] = {}

    def exec_command(self, cmd: str):
        self.commands.append(cmd)
        if 'printf %s "$HOME"' in cmd:
            return None, _FakeStd(self._home), _FakeStd()
        if cmd.startswith("cat "):
            return None, _FakeStd(self._existing), _FakeStd()
        return None, _FakeStd(), _FakeStd()

    def open_sftp(self):
        return _FakeSFTP(self.writes)


class GrokConfigTest(unittest.TestCase):
    def test_builds_responses_model_from_bot_config(self):
        alias, entry = build_grok_model_entry(
            BotConfig(
                name="grok",
                backend="grok_build",
                model='"grok-4.5"',
                base_url="https://cc1.yovy.app/openai",
            )
        )

        self.assertEqual(alias, "y-grok")
        self.assertEqual(entry["model"], "grok-4.5")
        self.assertEqual(entry["base_url"], "https://cc1.yovy.app/openai")
        self.assertEqual(entry["api_backend"], "responses")
        self.assertEqual(entry["env_key"], "XAI_API_KEY")

    def test_merges_relay_model_without_losing_existing_tables(self):
        existing = """[cli]\ninstaller = \"internal\"\n\n[[marketplace.sources]]\nname = \"xAI Official\"\ngit = \"https://example.com/plugins.git\"\n"""
        content = merge_grok_config_toml(
            existing,
            "y-grok",
            {
                "model": "grok-4.5",
                "base_url": "https://cc1.yovy.app/openai",
                "api_backend": "responses",
                "env_key": "XAI_API_KEY",
            },
        )

        data = tomllib.loads(content)
        self.assertEqual(data["cli"]["installer"], "internal")
        self.assertEqual(data["marketplace"]["sources"][0]["name"], "xAI Official")
        self.assertEqual(data["model"]["y-grok"]["base_url"], "https://cc1.yovy.app/openai")
        self.assertEqual(data["model"]["y-grok"]["env_key"], "XAI_API_KEY")


class GrokConfigWriteTest(unittest.TestCase):
    """Regression for the quoted-tilde bug: the setup hook must operate on an
    absolute path so cat reads the real config and chmod does not crash."""

    def test_write_uses_absolute_paths_and_preserves_existing(self):
        home = "/home/ec2-user"
        existing = '[cli]\ninstaller = "internal"\n'
        client = _FakeSSHClient(home, existing_config=existing)

        write_grok_config_toml(
            client,
            "y-grok",
            {
                "model": "grok-4.5",
                "base_url": "https://cc1.yovy.app/openai",
                "api_backend": "responses",
                "env_key": "XAI_API_KEY",
            },
        )

        # No remote command may carry a literal `~` (the shell never expands it
        # inside the single quotes _shell_quote emits).
        for cmd in client.commands:
            self.assertNotIn("~", cmd, f"command leaked a literal tilde: {cmd}")

        # cat / chmod target the resolved absolute path.
        config_path = f"{home}/.grok/config.toml"
        self.assertTrue(
            any(cmd.startswith("cat ") and config_path in cmd for cmd in client.commands)
        )
        self.assertTrue(
            any(cmd.startswith("chmod 600 ") and config_path in cmd for cmd in client.commands)
        )

        # The sftp write lands on the same absolute path, and the merge actually
        # read the preseeded config (existing tables survive).
        self.assertIn(config_path, client.writes)
        written = tomllib.loads(client.writes[config_path])
        self.assertEqual(written["cli"]["installer"], "internal")
        self.assertEqual(
            written["model"]["y-grok"]["base_url"], "https://cc1.yovy.app/openai"
        )


if __name__ == "__main__":
    unittest.main()
