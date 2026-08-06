"""Tests for agent.module_host (todo 3020 phase 3 / D9)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import agent.module_host as mh
from agent.module_host import (
    BACKEND_CONTRACT_VERSION,
    request_owner,
    run_vm_command,
    session,
)
from agent.tools.errors import CommandError

# Exception classes are referenced via the module (`mh.ModuleHostAuthError`)
# instead of a top-level import because ContractSurfaceTest reloads
# agent.module_host, which redefines the classes in place and would leave a
# stale pre-reload reference that `assertRaises` cannot match.


class ContractSurfaceTest(unittest.TestCase):
    def test_backend_contract_version_is_five(self):
        self.assertEqual(BACKEND_CONTRACT_VERSION, 5)

    def test_importing_module_host_does_not_import_paramiko(self):
        # Drop paramiko if a previous test imported it, then re-import the contract.
        sys.modules.pop("paramiko", None)
        # Force a fresh look at agent.module_host's module-level imports.
        import importlib
        import agent.module_host as mh

        importlib.reload(mh)
        self.assertNotIn("paramiko", sys.modules)


class ExternalTableRefTest(unittest.TestCase):
    """A module declares host kernel tables its FKs point at, but does not own them."""

    def _metadata(self):
        from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

        metadata = MetaData()
        Table(
            "user",
            metadata,
            Column("id", Integer, primary_key=True),
            info={mh.EXTERNAL_TABLE_INFO_KEY: True},
        )
        Table(
            "mod_thing",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, ForeignKey("user.id", ondelete="CASCADE")),
        )
        return metadata

    def test_owned_tables_excludes_the_external_stub(self):
        metadata = self._metadata()
        self.assertEqual([t.name for t in mh.owned_tables(metadata)], ["mod_thing"])
        self.assertTrue(mh.is_external_table(metadata.tables["user"]))
        self.assertFalse(mh.is_external_table(metadata.tables["mod_thing"]))

    def test_stub_is_what_makes_the_foreign_key_resolvable(self):
        # Without the stub, sorted_tables raises NoReferencedTableError, which
        # is why the convention exists at all.
        from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
        from sqlalchemy.exc import NoReferencedTableError

        metadata = self._metadata()
        self.assertEqual(len(metadata.sorted_tables), 2)

        orphan = MetaData()
        Table(
            "mod_thing",
            orphan,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, ForeignKey("user.id")),
        )
        with self.assertRaises(NoReferencedTableError):
            orphan.sorted_tables


class CliUserIdTest(unittest.TestCase):
    def test_delegates_to_the_host_user_service(self):
        with patch("storage.service.user.get_cli_user_id", return_value=7) as resolver:
            self.assertEqual(mh.cli_user_id(), 7)
        resolver.assert_called_once_with()


class SessionTest(unittest.TestCase):
    def test_session_is_thin_reexport_of_get_db(self):
        sentinel = object()

        class _CM:
            def __enter__(self):
                return sentinel

            def __exit__(self, *a):
                return False

        with patch("storage.database.base.get_db", return_value=_CM()) as get_db:
            with session() as s:
                self.assertIs(s, sentinel)
        get_db.assert_called_once_with()


class RunVmCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_empty_argv(self):
        with request_owner(1):
            with self.assertRaises(ValueError):
                await run_vm_command(1, None, [])

    async def test_rejects_non_string_argv(self):
        with request_owner(1):
            with self.assertRaises(TypeError):
                await run_vm_command(1, None, ["y", 1])  # type: ignore[list-item]

    async def test_rejects_when_no_request_owner_bound(self):
        """review finding 2: without a bound request owner the capability refuses."""
        with self.assertRaises(mh.ModuleHostAuthError):
            await run_vm_command(1, None, ["y", "todo", "list"])

    async def test_rejects_caller_chosen_user_differing_from_bound_owner(self):
        """review finding 2: a module cannot steer execution at another user's id."""
        with request_owner(5):
            with self.assertRaises(mh.ModuleHostAuthError):
                await run_vm_command(7, None, ["y", "finance", "holdings"])

    async def test_raises_when_owner_has_no_vm_config(self):
        """review finding 2: no fallback to another (default) user's VM."""
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=None) as get_cfg:
            with self.assertRaises(mh.ModuleVmNotConfiguredError):
                await run_vm_command(7, None, ["y", "todo", "list"])
        get_cfg.assert_called_once_with(7, "default")

    async def test_local_path_when_api_token_absent(self):
        vm = SimpleNamespace(api_token=None, work_dir="/tmp/work", vm_name="default")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm) as get_cfg, \
             patch("agent.tools.local_exec.local_exec", new_callable=AsyncMock, return_value="ok") as local, \
             patch("agent.tools.ssh_exec.ssh_exec", new_callable=AsyncMock) as ssh:
            out = await run_vm_command(7, None, ["y", "todo", "list"], timeout=12)
        self.assertEqual(out, "ok")
        get_cfg.assert_called_once_with(7, "default")
        local.assert_awaited_once()
        self.assertEqual(local.await_args.args[0], ["y", "todo", "list"])
        self.assertEqual(local.await_args.kwargs.get("timeout") or local.await_args.args[2], 12)
        self.assertEqual(local.await_args.kwargs.get("cwd"), "/tmp/work")
        self.assertTrue(local.await_args.kwargs.get("check"))
        ssh.assert_not_awaited()

    async def test_ssh_path_when_api_token_present(self):
        vm = SimpleNamespace(api_token="secret-key", work_dir="/home/roy", vm_name="ssh:roy@host")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm) as get_cfg, \
             patch("agent.tools.local_exec.local_exec", new_callable=AsyncMock) as local, \
             patch("agent.tools.ssh_exec.ssh_exec", new_callable=AsyncMock, return_value="remote") as ssh:
            out = await run_vm_command(7, "prod", ["y", "finance", "holdings"], timeout=45)
        self.assertEqual(out, "remote")
        get_cfg.assert_called_once_with(7, "prod")
        local.assert_not_awaited()
        ssh.assert_awaited_once()
        self.assertIs(ssh.await_args.args[0], vm)
        self.assertEqual(ssh.await_args.args[1], ["y", "finance", "holdings"])
        # timeout is keyword on ssh_exec
        self.assertEqual(ssh.await_args.kwargs.get("timeout"), 45)
        self.assertEqual(ssh.await_args.kwargs.get("dir"), "/home/roy")
        self.assertTrue(ssh.await_args.kwargs.get("check"))

    async def test_local_path_accepts_work_dir_and_stdin(self):
        vm = SimpleNamespace(api_token=None, work_dir="/tmp/default", vm_name="default")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch("agent.tools.local_exec.local_exec", new_callable=AsyncMock, return_value="ok") as local:
            out = await run_vm_command(
                7,
                None,
                ["bash", "-c", "cat"],
                work_dir="/tmp/override",
                stdin="payload",
            )
        self.assertEqual(out, "ok")
        self.assertEqual(local.await_args.args[1], "payload")
        self.assertEqual(local.await_args.kwargs["cwd"], "/tmp/override")

    async def test_ssh_path_accepts_work_dir_and_stdin(self):
        vm = SimpleNamespace(api_token="secret-key", work_dir="/home/default", vm_name="ssh:roy@host")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch("agent.tools.ssh_exec.ssh_exec", new_callable=AsyncMock, return_value="remote") as ssh:
            out = await run_vm_command(
                7,
                "prod",
                ["bash", "-c", "cat"],
                work_dir="/home/override",
                stdin="payload",
            )
        self.assertEqual(out, "remote")
        self.assertEqual(ssh.await_args.args[2], "payload")
        self.assertEqual(ssh.await_args.kwargs["dir"], "/home/override")

    async def test_local_nonzero_exit_raises_command_error(self):
        """review finding 2: a failed local producer must look failed."""
        vm = SimpleNamespace(api_token=None, work_dir=None, vm_name="default")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.local_exec.local_exec",
                 new_callable=AsyncMock,
                 side_effect=CommandError(1, "y finance refresh"),
             ):
            with self.assertRaises(CommandError) as ctx:
                await run_vm_command(7, None, ["y", "finance", "refresh"])
        self.assertEqual(ctx.exception.exit_code, 1)

    async def test_ssh_nonzero_exit_raises_command_error(self):
        """review finding 2: a failed SSH producer must look failed."""
        vm = SimpleNamespace(api_token="k", work_dir=None, vm_name="ssh:roy@host")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.ssh_exec.ssh_exec",
                 new_callable=AsyncMock,
                 side_effect=CommandError(2, "y finance refresh"),
             ):
            with self.assertRaises(CommandError) as ctx:
                await run_vm_command(7, None, ["y", "finance", "refresh"])
        self.assertEqual(ctx.exception.exit_code, 2)

    async def test_error_propagates(self):
        vm = SimpleNamespace(api_token=None, work_dir=None, vm_name="default")
        with request_owner(1), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.local_exec.local_exec",
                 new_callable=AsyncMock,
                 side_effect=RuntimeError("boom"),
             ):
            with self.assertRaises(RuntimeError):
                await run_vm_command(1, None, ["y", "todo", "list"])


class ChatCapabilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_every_operation_requires_a_bound_request_owner(self):
        for call in (
            lambda: mh.chat_list(1),
            lambda: mh.chat_get(1, "chat-1"),
            lambda: mh.chat_create_share(1, "chat-1"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(mh.ModuleHostAuthError):
                    await call()

    async def test_refuses_a_user_id_differing_from_bound_owner(self):
        with request_owner(5):
            with self.assertRaises(mh.ModuleHostAuthError):
                await mh.chat_list(7)
            with self.assertRaises(mh.ModuleHostAuthError):
                await mh.chat_get(7, "chat-1")
            with self.assertRaises(mh.ModuleHostAuthError):
                await mh.chat_create_share(7, "chat-1")

    async def test_list_returns_plain_owner_scoped_summaries(self):
        summary = SimpleNamespace(
            chat_id="chat-1", title="A", created_at="c", updated_at="u",
            topic="dev", skill="impl", trace_id="3042", routine_id="",
            routine_name="", backend="claude_code", bot_name="default",
            tier="tier1", status="idle", unread=False,
        )
        with request_owner(3), \
             patch("storage.service.chat.list_chats", new_callable=AsyncMock, return_value=[summary]) as svc:
            result = await mh.chat_list(3, limit=20, query="hello")
        svc.assert_awaited_once()
        self.assertEqual(svc.await_args.args[0], 3)
        self.assertEqual(svc.await_args.kwargs["limit"], 20)
        self.assertEqual(result[0]["chat_id"], "chat-1")
        self.assertNotIn("user_id", result[0])

    async def test_get_returns_plain_content_and_none_for_missing(self):
        message = SimpleNamespace(to_dict=lambda: {"role": "user", "content": "hi"})
        chat = SimpleNamespace(
            id="chat-1", messages=[message], create_time="c", update_time="u"
        )
        with request_owner(3), \
             patch("storage.service.chat.get_chat", new_callable=AsyncMock, side_effect=[chat, None]) as svc:
            result = await mh.chat_get(3, "chat-1")
            missing = await mh.chat_get(3, "missing")
        self.assertEqual(result["messages"], [{"role": "user", "content": "hi"}])
        self.assertIsNone(missing)
        self.assertEqual(svc.await_args_list[0].args, (3, "chat-1"))

    async def test_create_share_hashes_explicit_password(self):
        with request_owner(3), \
             patch("storage.share_password.hash_password", return_value="hash") as hash_fn, \
             patch("storage.service.chat.create_share", new_callable=AsyncMock, return_value="share-1") as svc:
            result = await mh.chat_create_share(3, "chat-1", password="secret")
        hash_fn.assert_called_once_with("secret")
        svc.assert_awaited_once_with(3, "chat-1", None, password_hash="hash")
        self.assertEqual(result, {"share_id": "share-1"})

    async def test_create_share_can_return_generated_password(self):
        with request_owner(3), \
             patch("storage.share_password.generate_password", return_value="generated"), \
             patch("storage.share_password.hash_password", return_value="hash"), \
             patch("storage.service.chat.create_share", new_callable=AsyncMock, return_value="share-1"):
            result = await mh.chat_create_share(3, "chat-1", generate_password=True)
        self.assertEqual(result, {"share_id": "share-1", "password": "generated"})


class NotePathCapabilityTest(unittest.TestCase):
    def test_requires_a_bound_request_owner(self):
        with self.assertRaises(mh.ModuleHostAuthError):
            mh.note_list_at_path(1, "pages/note.md")

    def test_refuses_another_users_note_lookup(self):
        with request_owner(5):
            with self.assertRaises(mh.ModuleHostAuthError):
                mh.note_list_at_path(7, "pages/note.md")

    def test_returns_only_plain_content_key_values_for_the_owner(self):
        notes = [
            SimpleNamespace(content_key="pages/a.md"),
            SimpleNamespace(content_key="pages/b.md"),
        ]
        with request_owner(3), \
             patch("storage.service.note.list_notes_at_path", return_value=notes) as svc:
            result = mh.note_list_at_path(3, "pages/a.md")
        svc.assert_called_once_with(3, "pages/a.md")
        self.assertEqual(result, [{"content_key": "pages/a.md"}, {"content_key": "pages/b.md"}])


class NoteCapabilityTest(unittest.TestCase):
    """v5 capability (plan-3071): owner-bound note browsing/authoring plus
    note↔todo relations. content_key home-escape is a capability-side invariant.
    """

    def _note(self, note_id="note-1", content_key="pages/ok.md", **extra):
        payload = {"note_id": note_id, "content_key": content_key, **extra}
        return SimpleNamespace(to_dict=lambda: dict(payload), **payload)

    def test_every_operation_requires_a_bound_request_owner(self):
        for call in (
            lambda: mh.note_list(1),
            lambda: mh.note_get(1, "note-1"),
            lambda: mh.note_create(1, "pages/ok.md"),
            lambda: mh.note_import(1, "pages/ok.md"),
            lambda: mh.note_update(1, "note-1", content_key="pages/ok.md"),
            lambda: mh.note_delete(1, "note-1"),
            lambda: mh.note_list_by_todo(1, "todo-1"),
            lambda: mh.note_relation_create(1, "note-1", "todo-1"),
            lambda: mh.note_relation_delete(1, "note-1", "todo-1"),
            lambda: mh.note_relations_by_todo(1, "todo-1"),
            lambda: mh.note_relations_by_note(1, "note-1"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(mh.ModuleHostAuthError):
                    call()

    def test_refuses_a_user_id_differing_from_bound_owner(self):
        with request_owner(5):
            for call in (
                lambda: mh.note_list(7),
                lambda: mh.note_get(7, "note-1"),
                lambda: mh.note_create(7, "pages/ok.md"),
                lambda: mh.note_import(7, "pages/ok.md"),
                lambda: mh.note_update(7, "note-1"),
                lambda: mh.note_delete(7, "note-1"),
                lambda: mh.note_list_by_todo(7, "todo-1"),
                lambda: mh.note_relation_create(7, "note-1", "todo-1"),
                lambda: mh.note_relation_delete(7, "note-1", "todo-1"),
                lambda: mh.note_relations_by_todo(7, "todo-1"),
                lambda: mh.note_relations_by_note(7, "note-1"),
            ):
                with self.subTest(call=call):
                    with self.assertRaises(mh.ModuleHostAuthError):
                        call()

    def test_create_import_and_update_reject_home_escaping_content_key(self):
        home = Path("/tmp/agent-home")
        with request_owner(3), \
             patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}, clear=False), \
             patch("storage.service.note.create_note") as create_note, \
             patch("storage.service.note.import_note") as import_note, \
             patch("storage.service.note.update_note") as update_note:
            with self.assertRaises(mh.ModuleHostValidationError):
                mh.note_create(3, "../outside.md")
            with self.assertRaises(mh.ModuleHostValidationError):
                mh.note_import(3, "../outside.md")
            with self.assertRaises(mh.ModuleHostValidationError):
                mh.note_update(3, "note-1", content_key="../outside.md")
        create_note.assert_not_called()
        import_note.assert_not_called()
        update_note.assert_not_called()

    def test_create_import_and_update_accept_in_home_content_key(self):
        note = self._note()
        home = Path("/tmp/agent-home")
        with request_owner(3), \
             patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}, clear=False), \
             patch("storage.service.note.create_note", return_value=note) as create_note, \
             patch("storage.service.note.import_note", return_value=note) as import_note, \
             patch("storage.service.note.update_note", return_value=note) as update_note:
            created = mh.note_create(3, "pages/ok.md", front_matter={"t": 1})
            imported = mh.note_import(3, "pages/ok.md")
            updated = mh.note_update(3, "note-1", content_key="pages/ok.md")
        self.assertEqual(created["note_id"], "note-1")
        self.assertEqual(imported["content_key"], "pages/ok.md")
        self.assertEqual(updated["note_id"], "note-1")
        create_note.assert_called_once_with(3, "pages/ok.md", front_matter={"t": 1})
        import_note.assert_called_once_with(3, "pages/ok.md", front_matter=None)
        update_note.assert_called_once_with(
            3, "note-1", content_key="pages/ok.md", front_matter=None
        )

    def test_list_and_get_return_plain_owner_scoped_dicts(self):
        note = self._note(front_matter={"tags": ["a"]})
        with request_owner(3), \
             patch("storage.service.note.list_notes", return_value=[note]) as list_svc, \
             patch("storage.service.note.get_note", side_effect=[note, None]) as get_svc:
            listed = mh.note_list(3, limit=10, tag="a")
            found = mh.note_get(3, "note-1")
            missing = mh.note_get(3, "missing")
        list_svc.assert_called_once()
        self.assertEqual(list_svc.call_args.args[0], 3)
        self.assertEqual(list_svc.call_args.kwargs["limit"], 10)
        self.assertEqual(list_svc.call_args.kwargs["tag"], "a")
        self.assertEqual(listed[0]["note_id"], "note-1")
        self.assertNotIn("user_id", listed[0])
        self.assertEqual(found["content_key"], "pages/ok.md")
        self.assertIsNone(missing)
        self.assertEqual(get_svc.call_args_list[0].args, (3, "note-1"))

    def test_delete_passes_through_guarded_conflict_result(self):
        conflict = {
            "ok": False,
            "reason": "note is linked to one or more todos; rerun with force=true to unlink and delete",
            "todo_relations": 2,
            "entity_relations": 0,
        }
        with request_owner(3), \
             patch("storage.service.note.delete_note", return_value=conflict) as svc:
            result = mh.note_delete(3, "note-1")
        svc.assert_called_once_with(3, "note-1", force=False)
        self.assertEqual(result, conflict)

    def test_delete_can_force_through_host_service(self):
        ok = {"ok": True, "deleted": True}
        with request_owner(3), \
             patch("storage.service.note.delete_note", return_value=ok) as svc:
            result = mh.note_delete(3, "note-1", force=True)
        svc.assert_called_once_with(3, "note-1", force=True)
        self.assertEqual(result, ok)

    def test_list_by_todo_returns_linked_notes_or_empty(self):
        note = self._note()
        with request_owner(3), \
             patch("storage.service.note_todo_relation.list_by_todo", side_effect=[["note-1"], []]) as rel, \
             patch("storage.service.note.get_notes_by_ids", return_value=[note]) as get_ids:
            linked = mh.note_list_by_todo(3, "todo-1")
            empty = mh.note_list_by_todo(3, "todo-empty")
        self.assertEqual(linked[0]["note_id"], "note-1")
        self.assertEqual(empty, [])
        get_ids.assert_called_once_with(3, ["note-1"], include_deleted=False)
        self.assertEqual(rel.call_args_list[0].args, (3, "todo-1"))

    def test_relation_ops_delegate_to_the_host_service(self):
        with request_owner(3), \
             patch("storage.service.note_todo_relation.create_relation", return_value=True) as create, \
             patch("storage.service.note_todo_relation.delete_relation", return_value=False) as delete, \
             patch("storage.service.note_todo_relation.list_by_todo", return_value=["n1"]) as by_todo, \
             patch("storage.service.note_todo_relation.list_by_note", return_value=["t1"]) as by_note:
            self.assertTrue(mh.note_relation_create(3, "n1", "t1"))
            self.assertFalse(mh.note_relation_delete(3, "n1", "t1"))
            self.assertEqual(mh.note_relations_by_todo(3, "t1"), ["n1"])
            self.assertEqual(mh.note_relations_by_note(3, "n1"), ["t1"])
        create.assert_called_once_with(3, "n1", "t1")
        delete.assert_called_once_with(3, "n1", "t1")
        by_todo.assert_called_once_with(3, "t1")
        by_note.assert_called_once_with(3, "n1")


class BotConfigCapabilityTest(unittest.TestCase):
    """v2 capability (plan-3028): a narrow bot-config store over host-owned
    BotConfig values. Request-bound like run_vm_command, so a module cannot
    read or overwrite another user's bot configuration."""

    def test_every_operation_requires_a_bound_request_owner(self):
        for call in (
            lambda: mh.bot_config_list(1),
            lambda: mh.bot_config_get(1, "default"),
            lambda: mh.bot_config_upsert(1, SimpleNamespace(name="x")),
            lambda: mh.bot_config_delete(1, "x"),
            lambda: mh.bot_config_set_enabled(1, "x", True),
            lambda: mh.bot_config_rename(1, "a", "b"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(mh.ModuleHostAuthError):
                    call()

    def test_refuses_a_user_id_differing_from_the_bound_owner(self):
        with request_owner(5):
            with self.assertRaises(mh.ModuleHostAuthError):
                mh.bot_config_list(7)
            with self.assertRaises(mh.ModuleHostAuthError):
                mh.bot_config_delete(7, "x")

    def test_list_delegates_to_the_host_service(self):
        expected = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
        with request_owner(3), \
             patch("storage.service.bot_config.list_configs", return_value=expected) as svc:
            self.assertEqual(mh.bot_config_list(3), expected)
        svc.assert_called_once_with(3)

    def test_get_delegates_to_the_host_service(self):
        expected = SimpleNamespace(name="default")
        with request_owner(3), \
             patch("storage.service.bot_config.get_config", return_value=expected) as svc:
            self.assertEqual(mh.bot_config_get(3, "default"), expected)
        svc.assert_called_once_with(3, "default")

    def test_get_defaults_to_default_name(self):
        with request_owner(3), \
             patch("storage.service.bot_config.get_config", return_value=None) as svc:
            self.assertIsNone(mh.bot_config_get(3))
        svc.assert_called_once_with(3, "default")

    def test_upsert_delegates_the_botconfig_value_to_the_host_service(self):
        cfg = SimpleNamespace(name="c")
        with request_owner(3), \
             patch("storage.service.bot_config.add_config", return_value=cfg) as svc:
            self.assertIs(mh.bot_config_upsert(3, cfg), cfg)
        svc.assert_called_once_with(3, cfg)

    def test_delete_delegates_to_the_host_service(self):
        with request_owner(3), \
             patch("storage.service.bot_config.delete_config", return_value=False) as svc:
            self.assertFalse(mh.bot_config_delete(3, "x"))
        svc.assert_called_once_with(3, "x")

    def test_set_enabled_delegates_to_the_host_service(self):
        with request_owner(3), \
             patch("storage.service.bot_config.set_enabled", return_value=True) as svc:
            self.assertTrue(mh.bot_config_set_enabled(3, "x", False))
        svc.assert_called_once_with(3, "x", False)

    def test_rename_goes_through_the_host_service_for_chat_cascade(self):
        # The whole point of routing rename through module_host is that the
        # host bot_config service preserves the chat.bot_name cascade that a
        # bare repository update would skip.
        with request_owner(3), \
             patch("storage.service.bot_config.rename_config", return_value=True) as svc:
            self.assertTrue(mh.bot_config_rename(3, "old", "new"))
        svc.assert_called_once_with(3, "old", "new")


if __name__ == "__main__":
    unittest.main()
