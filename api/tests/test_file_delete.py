import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.controller import file as file_controller


def run_safe_unlink(agent_home: Path, work_dir: Path, requested_path: str) -> dict:
    result = subprocess.run(
        ["python3", "-c", file_controller._SAFE_UNLINK_SCRIPT, requested_path, str(agent_home)],
        cwd=work_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_safe_unlink_accepts_relative_and_absolute_paths(tmp_path: Path):
    agent_home = tmp_path / "agent-home"
    work_dir = agent_home / "project"
    work_dir.mkdir(parents=True)
    relative_file = work_dir / "relative.txt"
    absolute_file = work_dir / "absolute.txt"
    relative_file.touch()
    absolute_file.touch()

    assert run_safe_unlink(agent_home, work_dir, "relative.txt")["status"] == "deleted"
    assert not relative_file.exists()
    assert run_safe_unlink(agent_home, work_dir, str(absolute_file))["status"] == "deleted"
    assert not absolute_file.exists()


def test_safe_unlink_rejects_outside_root_and_parent_symlink(tmp_path: Path):
    agent_home = tmp_path / "agent-home"
    work_dir = agent_home / "project"
    outside_dir = tmp_path / "outside"
    work_dir.mkdir(parents=True)
    outside_dir.mkdir()
    outside_file = outside_dir / "outside.txt"
    outside_file.touch()
    (work_dir / "escape").symlink_to(outside_dir, target_is_directory=True)

    assert run_safe_unlink(agent_home, work_dir, "../../outside/outside.txt")["status"] == "invalid"
    assert outside_file.exists()
    assert run_safe_unlink(agent_home, work_dir, "escape/outside.txt")["status"] == "invalid"
    assert outside_file.exists()


def test_safe_unlink_refuses_missing_directories_and_root(tmp_path: Path):
    agent_home = tmp_path / "agent-home"
    work_dir = agent_home / "project"
    work_dir.mkdir(parents=True)
    directory = work_dir / "directory"
    directory.mkdir()

    assert run_safe_unlink(agent_home, work_dir, "missing.txt")["status"] == "missing"
    assert run_safe_unlink(agent_home, work_dir, "directory")["status"] == "unsupported"
    assert directory.exists()
    assert run_safe_unlink(agent_home, work_dir, str(agent_home))["status"] == "unsupported"


def test_safe_unlink_removes_symlink_without_touching_target(tmp_path: Path):
    agent_home = tmp_path / "agent-home"
    work_dir = agent_home / "project"
    outside_dir = tmp_path / "outside"
    work_dir.mkdir(parents=True)
    outside_dir.mkdir()
    target = outside_dir / "target.txt"
    target.write_text("keep")
    link = work_dir / "link.txt"
    link.symlink_to(target)

    assert run_safe_unlink(agent_home, work_dir, "link.txt")["status"] == "deleted"
    assert not link.exists()
    assert target.read_text() == "keep"


def test_delete_endpoint_maps_target_results(monkeypatch):
    async def run_with_output(*args, **kwargs):
        return json.dumps({"status": "missing", "detail": "File does not exist"})

    monkeypatch.setattr(file_controller, "_exec", run_with_output)
    request = type("Request", (), {"state": type("State", (), {"user_id": 1})()})()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(file_controller.delete_file(request, file_controller.DeleteRequest(path="missing.txt")))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "File does not exist"


def test_delete_endpoint_passes_api_agent_home(monkeypatch, tmp_path: Path):
    commands = []

    async def run_with_output(*args, **kwargs):
        commands.append(args[1])
        return json.dumps({"status": "deleted"})

    monkeypatch.setattr(file_controller, "_exec", run_with_output)
    monkeypatch.setattr(file_controller, "Y_AGENT_HOME", tmp_path)
    request = type("Request", (), {"state": type("State", (), {"user_id": 1})()})()

    result = asyncio.run(file_controller.delete_file(request, file_controller.DeleteRequest(path="file.txt")))

    assert result == {"path": "file.txt", "deleted": True}
    assert commands == [["python3", "-c", file_controller._SAFE_UNLINK_SCRIPT, "file.txt", str(tmp_path)]]
