"""The conf.yaml editor page: demo backend (in memory) and real services."""

from __future__ import annotations

import os
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import yaml

from kongui.core import (
    ConfigConflictError,
    ConfigService,
    ConfigValidationError,
    KonsaveEngine,
    ProfileService,
)
from kongui.gui.backend import FakeBackend, ServiceBackend
from kongui.gui.state import AppSettings
from kongui.gui.tasks import InlineExecutor
from kongui.gui.widgets.dialogs import (
    BackupsDialog,
    ChoiceDialog,
    ConfirmDialog,
    GroupNameDialog,
)
from tests.gui_helpers import GuiTestCase, WindowCase
from tests.helpers import BASE_CONF, non_root, really_root, write

REAL_KNSV = Path(__file__).with_name("profile_test.knsv")


def add_group(editor, name, location="$HOME", entries=()):
    """Adds a complete (valid) group through the section editor."""
    editor.add_group(name)
    editor.insert_text(location)
    for entry in entries:
        editor.add_entry(entry)


def comment_lines(text):
    """Comment lines of a text, stripped."""
    return [line.strip() for line in text.splitlines() if "#" in line]


class DialogPatches:
    """Replaces the modal dialogs so a test can answer them."""

    def patch_dialogs(self, confirm=True, choice="cancel", group_name=None):
        self.confirm = mock.patch.object(
            ConfirmDialog, "ask", return_value=confirm
        ).start()
        self.choice = mock.patch.object(
            ChoiceDialog, "ask", return_value=choice
        ).start()
        self.group_dialog = mock.patch.object(
            GroupNameDialog, "ask", return_value=group_name
        ).start()


@unittest.skipIf(really_root(), "the demo backend builds a real engine")
class ConfigPageDemoTests(WindowCase, DialogPatches):
    """The editor on the in-memory backend (a sandboxed copy of the default)."""

    def setUp(self):
        super().setUp()
        self.patch_dialogs()

    def open_config(self):
        window = self.open_window(page="config", load=False)
        self.run_all()
        return window, window.pages["config"]

    def settle(self):
        """Runs the queued check jobs."""
        self.run_all()

    def test_the_page_is_in_the_sidebar_and_loads_the_default_config(self):
        window, page = self.open_config()
        self.assertEqual(window.current_key, "config")
        self.assertIsNotNone(page.snapshot)
        self.assertIn("configuration file for konsave", page.text)
        self.assertEqual(
            [g.name for g in page.editors["save"].groups],
            ["configs", "app_layouts", "autostart"],
        )
        self.assertEqual(
            [g.name for g in page.editors["export"].groups],
            ["share_folder", "home_folder"],
        )
        self.assertIn("demonstração", page.notice_label.text())
        self.assertFalse(page.is_dirty)

    def test_save_and_export_are_edited_separately(self):
        _window, page = self.open_config()
        before_export = [g for g in page.editors["export"].groups]
        add_group(page.editors["save"], "novo")
        self.settle()
        self.assertEqual([g.name for g in page.editors["save"].groups][-1], "novo")
        self.assertEqual(list(page.editors["export"].groups), before_export)
        data = yaml.safe_load(page.text)
        self.assertIn("novo", data["save"])
        self.assertNotIn("novo", data["export"])
        add_group(page.editors["export"], "fora")
        self.settle()
        data = yaml.safe_load(page.text)
        self.assertIn("fora", data["export"])
        self.assertNotIn("fora", data["save"])

    def test_editing_never_writes_until_save_is_pressed(self):
        _window, page = self.open_config()
        digest = page.snapshot.digest
        add_group(page.editors["save"], "novo")
        page.editors["save"].add_entry("arquivo")
        self.settle()
        self.assertTrue(page.is_dirty)
        self.assertTrue(page.dirty_badge.isVisibleTo(page))
        self.assertEqual(self.backend.load_config().digest, digest)
        self.assertEqual(self.backend.list_config_backups(), ())

    def test_save_is_blocked_while_the_text_has_errors(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        editor.select_group("configs")
        editor.insert_text("$NOPE")
        self.settle()
        self.assertFalse(page.check.ok)
        self.assertFalse(page.save_button.isEnabled())
        error = next(p for p in page.check.problems if p.is_error)
        self.assertEqual(error.code, "placeholder-unsupported")
        self.assertEqual(error.path, ("save", "configs", "location"))
        self.assertEqual(self.backend.list_config_backups(), ())
        digest = self.backend.load_config().digest
        self.assertFalse(page.save())
        self.settle()
        self.assertEqual(self.backend.load_config().digest, digest)
        row = page.problems.rows()[0]
        self.assertIn("linha", row.place_label.text())
        self.assertIn("save.configs.location", row.place_label.text())
        self.assertIn("$NOPE", row.text_label.text())

    def test_a_valid_edit_is_saved_with_a_backup(self):
        _window, page = self.open_config()
        before = page.snapshot.text
        add_group(page.editors["save"], "extra", "$HOME/.local/share", ("kwin",))
        self.settle()
        self.assertTrue(page.can_save())
        self.assertTrue(page.save())
        self.settle()
        self.assertFalse(page.is_dirty)
        saved = self.backend.load_config()
        self.assertIn("extra:", saved.text)
        self.assertEqual(comment_lines(before), comment_lines(saved.text))
        self.assertEqual(len(saved.backups), 1)
        self.assertEqual(self.backend.read_config_backup(saved.backups[0].name), before)
        self.assertTrue(
            any(o.operation == "save_config" and o.ok for o in self.outcomes)
        )

    def test_cancel_discards_without_saving(self):
        _window, page = self.open_config()
        original = page.text
        add_group(page.editors["save"], "x")
        self.settle()
        self.confirm.return_value = False
        self.assertFalse(page.discard())
        self.assertTrue(page.is_dirty)
        self.confirm.return_value = True
        self.assertTrue(page.discard())
        self.settle()
        self.assertEqual(page.text, original)
        self.assertFalse(page.is_dirty)
        self.assertEqual(self.backend.list_config_backups(), ())
        self.assertEqual(self.backend.load_config().text, original)

    def test_leaving_with_unsaved_edits_asks_first(self):
        window, page = self.open_config()
        add_group(page.editors["save"], "x")
        self.settle()
        self.confirm.return_value = False
        window.show_page("about")
        self.assertEqual(window.current_key, "config")
        self.assertEqual(window.sidebar.current_key(), "config")
        self.confirm.return_value = True
        window.show_page("about")
        self.assertEqual(window.current_key, "about")

    def test_closing_with_unsaved_edits_asks_first(self):
        window, page = self.open_config()
        add_group(page.editors["save"], "x")
        self.settle()
        self.confirm.return_value = False
        self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        self.confirm.return_value = True
        self.assertTrue(window.close())

    def test_text_tab_with_broken_yaml_shows_a_located_error(self):
        _window, page = self.open_config()
        page.show_view("text")
        page.text_edit.setPlainText("save:\n  a: [broken\nexport: {}\n")
        page.validate_now()
        self.settle()
        self.assertIsNone(page.model)
        self.assertFalse(page.save_button.isEnabled())
        problem = page.check.problems[0]
        self.assertEqual(problem.code, "yaml-syntax")
        self.assertGreaterEqual(problem.line, 2)
        self.assertFalse(page.editors["save"].unavailable_label.isHidden())
        self.assertFalse(page.editors["save"].add_button.isEnabled())
        page.goto_problem(problem)
        self.assertEqual(page.current_view(), "text")
        self.assertEqual(page.text_edit.textCursor().blockNumber() + 1, problem.line)

    def test_fixing_the_text_brings_the_forms_back(self):
        _window, page = self.open_config()
        page.show_view("text")
        page.text_edit.setPlainText("save: [oops\n")
        self.settle()
        page.text_edit.setPlainText(
            "save:\n  g:\n    location: /tmp\n    entries:\n      - a\nexport: {}\n"
        )
        page.validate_now()
        self.settle()
        self.assertIsNotNone(page.model)
        self.assertEqual([g.name for g in page.editors["save"].groups], ["g"])
        self.assertTrue(page.editors["save"].unavailable_label.isHidden())

    def test_typing_in_the_text_tab_updates_the_form(self):
        _window, page = self.open_config()
        page.show_view("text")
        page.text_edit.setPlainText(
            "save:\n  one:\n    location: /tmp\n    entries: [a, b]\n"
            "  two:\n    location: /var\n    entries: []\nexport: {}\n"
        )
        self.settle()
        editor = page.editors["save"]
        self.assertEqual([g.name for g in editor.groups], ["one", "two"])
        editor.select_group("one")
        self.assertEqual(editor.entries_list.count(), 2)

    def test_problem_rows_jump_to_the_field(self):
        _window, page = self.open_config()
        text = (
            "save:\n  a:\n    location: /tmp\n    entries:\n      - ok\n      - bad/x\n"
            "export: {}\n"
        )
        page.show_view("text")
        page.text_edit.setPlainText(text)
        page.validate_now()
        self.settle()
        problem = next(p for p in page.check.problems if p.code == "entry-invalid")
        self.assertEqual(problem.line, 6)
        row = next(r for r in page.problems.rows() if r.problem is problem)
        self.assertIn("linha 6", row.place_label.text())
        row.goto_button.click()
        self.assertEqual(page.current_view(), "save")
        editor = page.editors["save"]
        self.assertEqual(editor.current_name(), "a")
        self.assertEqual(editor.entries_list.currentRow(), 1)

    def test_placeholder_buttons_are_the_ones_of_the_original(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        engine_tokens = self.backend._config_service("x").placeholders()
        for token in engine_tokens["keywords"]:
            self.assertIn(token, editor.placeholder_buttons)
        for name in engine_tokens["functions"]:
            self.assertIn(name, editor.placeholder_buttons)
        self.assertEqual(
            sorted(editor.placeholder_buttons),
            sorted(engine_tokens["keywords"] + engine_tokens["functions"]),
        )

    def test_inserting_a_placeholder_edits_the_location(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        editor.select_group("configs")
        editor.location_edit.setText("")
        editor.location_edit.editingFinished.emit()
        editor.placeholder_buttons["$SHARE_DIR"].click()
        self.settle()
        self.assertEqual(
            yaml.safe_load(page.text)["save"]["configs"]["location"], "$SHARE_DIR"
        )
        editor.placeholder_buttons["ENDS_WITH"].click()
        self.assertTrue(
            editor.location_edit.text().endswith("${ENDS_WITH='texto'}"),
            editor.location_edit.text(),
        )

    def test_the_resolved_location_comes_from_the_original_reader(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        editor.select_group("configs")
        self.assertIn("/.config", editor.resolved_label.text())
        self.assertNotIn("$CONFIG_DIR", editor.resolved_label.text())

    def test_renaming_and_removing_groups_and_entries(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        editor.select_group("autostart")
        editor.name_edit.setText("auto")
        editor.name_edit.editingFinished.emit()
        self.settle()
        self.assertEqual(editor.current_name(), "auto")
        self.assertIn("auto", yaml.safe_load(page.text)["save"])
        self.assertNotIn("autostart", yaml.safe_load(page.text)["save"])
        editor.select_group("app_layouts")
        before = len(editor.current_group().entries)
        editor.entries_list.setCurrentRow(0)
        editor.remove_current_entry()
        self.settle()
        self.assertEqual(len(editor.current_group().entries), before - 1)
        editor.select_group("auto")
        editor.remove_current()
        self.settle()
        self.assertNotIn("auto", [g.name for g in editor.groups])
        self.assertTrue(page.check.ok)

    def test_a_duplicate_or_invalid_group_name_is_refused_in_the_form(self):
        _window, page = self.open_config()
        editor = page.editors["save"]
        editor.select_group("autostart")
        for bad in ("configs", "a/b", "..", ""):
            editor.name_edit.setText(bad)
            editor.name_edit.editingFinished.emit()
            self.assertEqual(editor.current_name(), "autostart", bad)
            self.assertTrue(editor.name_error.isVisibleTo(editor) or bad == "")
        self.assertNotIn("a/b", page.text)
        self.assertFalse(page.is_dirty)

    def test_new_group_dialog_adds_the_group(self):
        _window, page = self.open_config()
        self.group_dialog.return_value = "via dialogo"
        page.editors["save"].add_button.click()
        self.settle()
        self.assertEqual(page.editors["save"].current_name(), "via dialogo")
        self.group_dialog.return_value = None
        page.editors["save"].add_button.click()
        self.assertEqual(len(page.editors["save"].groups), 4)

    def test_a_stale_check_is_ignored(self):
        _window, page = self.open_config()
        add_group(page.editors["save"], "primeiro")
        add_group(page.editors["save"], "segundo")
        queued = len(self.executor.queue)
        self.assertGreaterEqual(queued, 2)
        self.executor.run_next()  # a check of an older text
        self.flush()
        self.assertIsNone(page.check)
        self.assertFalse(page.can_save())
        self.run_all()
        self.assertIsNotNone(page.check)
        self.assertTrue(page.can_save())

    def test_the_view_buttons_switch_sections(self):
        _window, page = self.open_config()
        for value in ("export", "text", "save"):
            page.view_control.button(value).click()
            self.flush()
            self.assertEqual(page.current_view(), value)
        self.assertIs(page.stack.currentWidget(), page.editors["save"])

    def test_restoring_a_backup_through_the_dialog(self):
        _window, page = self.open_config()
        original = page.snapshot.text
        add_group(page.editors["save"], "v2")
        self.settle()
        page.save()
        self.settle()
        self.assertIn("v2:", page.text)
        chosen = page.snapshot.backups[0].name

        def fake_exec(dialog):
            self.run_all()  # loads the preview of the first backup
            self.assertIn(
                "configuration file for konsave", dialog.preview.toPlainText()
            )
            self.assertTrue(dialog.confirm_button.isEnabled())
            dialog.chosen = chosen
            return 1

        with mock.patch.object(BackupsDialog, "exec", new=fake_exec):
            page.open_backups()
            self.settle()
        self.settle()
        self.assertEqual(self.backend.load_config().text, original)
        self.assertEqual(len(self.backend.load_config().backups), 2)
        self.assertNotIn("v2:", page.text)

    def test_conflict_reload_force_and_cancel(self):
        _window, page = self.open_config()
        config = self.backend._config_service("x")
        add_group(page.editors["save"], "mine")
        self.settle()
        config.config_path.write_text(
            config.config_path.read_text() + "\n# changed elsewhere\n"
        )
        self.choice.return_value = "cancel"
        page.save()
        self.settle()
        self.assertIn("# changed elsewhere", config.config_path.read_text())
        self.assertNotIn("mine:", config.config_path.read_text())
        self.assertTrue(page.is_dirty)
        self.choice.return_value = "force"
        page.save()
        self.settle()
        self.assertIn("mine:", config.config_path.read_text())
        self.assertTrue(
            any(
                "changed elsewhere" in config.read_backup(b.name)
                for b in config.list_backups()
            )
        )
        # and again, choosing to reload
        add_group(page.editors["save"], "again")
        self.settle()
        config.config_path.write_text(
            config.config_path.read_text() + "\n# once more\n"
        )
        self.choice.return_value = "reload"
        page.save()
        self.settle()
        self.assertNotIn("again:", page.text)
        self.assertIn("# once more", page.text)
        self.assertFalse(page.is_dirty)

    def test_the_demo_never_touches_the_real_config(self):
        home_conf = Path(self.home) / ".config" / "konsave" / "conf.yaml"
        _window, page = self.open_config()
        add_group(page.editors["save"], "x")
        self.settle()
        page.save()
        self.settle()
        self.assertFalse(home_conf.exists())


@unittest.skipIf(really_root(), "refusing to run file operations as root")
class ConfigPageRealTests(GuiTestCase, DialogPatches):
    """The editor on the real services, in a temporary home."""

    def setUp(self):
        super().setUp()
        self.patch_dialogs()
        self.root = Path(os.path.realpath(self.home))
        (self.root / ".config").mkdir(exist_ok=True)
        (self.root / ".local/share").mkdir(parents=True, exist_ok=True)
        engine = KonsaveEngine(self.root, euid_provider=non_root)
        self.config = ConfigService(engine)
        self.service = ProfileService(engine, self.config)
        self.backend = ServiceBackend(self.service)

    def open_page(self, initial=BASE_CONF):
        if initial is not None:
            self.config.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.config_path.write_text(initial, encoding="utf-8")
        window = self.make_window(
            backend=self.backend, executor=InlineExecutor(), settings=AppSettings()
        )
        page = window.show_page("config")
        self.flush()
        return window, page

    def on_disk(self):
        return self.config.config_path.read_text(encoding="utf-8")

    def test_missing_file_starts_from_the_default_and_creates_it_on_save(self):
        _window, page = self.open_page(initial=None)
        self.assertFalse(page.snapshot.exists)
        self.assertIn("ainda não existe", page.state_label.text())
        self.assertFalse(self.config.config_path.exists())
        self.assertTrue(page.can_save())
        page.save()
        self.flush()
        self.assertTrue(self.config.config_path.exists())
        self.assertIn("configuration file for konsave", self.on_disk())
        self.assertEqual(self.config.list_backups(), ())

    def test_saved_text_keeps_comments_unknown_keys_and_placeholders(self):
        text = (
            '# header\n---\nsave:\n    configs:\n        location: "$CONFIG_DIR"  # why\n'
            "        note: unknown\n        entries:\n            - kdeglobals\n"
            'export:\n    share:\n        location: "$SHARE_DIR"\n        entries: []\n'
            'extra:\n    keep:\n        location: "$HOME"\n        entries: []\n...\n'
        )
        _window, page = self.open_page(text)
        editor = page.editors["save"]
        editor.select_group("configs")
        editor.add_entry("gtk-3.0")
        self.flush()
        page.save()
        self.flush()
        saved = self.on_disk()
        self.assertEqual(comment_lines(text), comment_lines(saved))
        data = yaml.safe_load(saved)
        self.assertEqual(data["save"]["configs"]["note"], "unknown")
        self.assertEqual(data["save"]["configs"]["location"], "$CONFIG_DIR")
        self.assertEqual(data["save"]["configs"]["entries"], ["kdeglobals", "gtk-3.0"])
        self.assertIn("keep", data["extra"])
        self.assertTrue(saved.rstrip().endswith("..."))
        self.assertEqual(len(self.config.list_backups()), 1)
        self.assertEqual(
            self.config.read_backup(self.config.list_backups()[0].name), text
        )

    def test_invalid_config_is_never_written(self):
        _window, page = self.open_page()
        before = self.on_disk()
        for broken in (
            "save: [x\n",
            "- a\n- b\n",
            "save:\n  a:\n    location: /x\n    entries:\n      - a/b\nexport: {}\n",
            "save: {}\n",
            "save:\n  a:\n    location: '$NOPE'\n    entries: []\nexport: {}\n",
            "save:\nexport: {}\nextra: 5\n",
        ):
            with self.subTest(text=broken):
                page.show_view("text")
                page.text_edit.setPlainText(broken)
                page.validate_now()
                self.flush()
                self.assertFalse(page.check.ok, broken)
                self.assertFalse(page.save_button.isEnabled())
                self.assertFalse(page.save())
                self.assertEqual(self.on_disk(), before)
                self.assertEqual(self.config.list_backups(), ())
                self.assertTrue(all(p.line for p in page.check.problems))

    def test_the_service_itself_refuses_when_the_page_is_bypassed(self):
        _window, page = self.open_page()
        before = self.on_disk()
        with self.assertRaises(ConfigValidationError) as caught:
            self.backend.save_config("save: [x\n", page.snapshot.digest)
        self.assertTrue(caught.exception.report.problems[0].line)
        self.assertEqual(self.on_disk(), before)

    def test_incomplete_files_open_and_can_be_completed(self):
        incomplete = 'save:\n    configs:\n        location: "$CONFIG_DIR"\n'
        _window, page = self.open_page(incomplete)
        self.assertFalse(page.check.ok)
        codes = {p.code for p in page.check.problems}
        self.assertIn("missing-top-key", codes)
        self.assertIn("entries-missing", codes)
        self.assertEqual([g.name for g in page.editors["save"].groups], ["configs"])
        page.editors["save"].select_group("configs")
        page.editors["save"].add_entry("kdeglobals")
        self.flush()
        self.assertIn("missing-top-key", {p.code for p in page.check.problems})
        page.editors["export"].add_group("share")
        page.editors["export"].insert_text("$SHARE_DIR")
        self.flush()
        self.assertTrue(page.check.ok, page.check.problems)
        page.save()
        self.flush()
        data = yaml.safe_load(self.on_disk())
        self.assertEqual(data["save"]["configs"]["entries"], ["kdeglobals"])
        self.assertIn("share", data["export"])

    def test_special_characters_survive_the_whole_trip(self):
        _window, page = self.open_page()
        editor = page.editors["save"]
        editor.add_group("grupo ação #1: ü")
        editor.insert_text("$HOME/.local/share")
        for name in (
            "arquivo com espaço",
            "a:b",
            "#hash",
            "ação.txt",
            "it's",
            '"q"',
            "日本語",
        ):
            editor.add_entry(name)
        self.flush()
        self.assertTrue(page.check.ok, page.check.problems)
        page.save()
        self.flush()
        group = yaml.safe_load(self.on_disk())["save"]["grupo ação #1: ü"]
        self.assertEqual(
            group["entries"],
            ["arquivo com espaço", "a:b", "#hash", "ação.txt", "it's", '"q"', "日本語"],
        )
        self.assertEqual(group["location"], "$HOME/.local/share")
        self.assertTrue(self.config.validate().ok)

    def test_restore_a_backup_and_undo_the_restore(self):
        _window, page = self.open_page()
        first = self.on_disk()
        add_group(page.editors["save"], "second")
        self.flush()
        page.save()
        self.flush()
        second = self.on_disk()
        backup = self.config.list_backups()[0].name
        page.restore(backup)
        self.flush()
        self.assertEqual(self.on_disk(), first)
        self.assertEqual(len(self.config.list_backups()), 2)
        # the version replaced by the restore was kept, so it can be restored
        kept = [
            b.name
            for b in self.config.list_backups()
            if self.config.read_backup(b.name) == second
        ]
        self.assertEqual(len(kept), 1)
        page.restore(kept[0])
        self.flush()
        self.assertEqual(self.on_disk(), second)

    def test_restore_asks_for_confirmation_and_can_be_declined(self):
        _window, page = self.open_page()
        add_group(page.editors["save"], "second")
        self.flush()
        page.save()
        self.flush()
        saved = self.on_disk()
        self.confirm.return_value = False
        self.assertFalse(page.restore(self.config.list_backups()[0].name))
        self.assertEqual(self.on_disk(), saved)

    def test_an_invalid_backup_is_not_restored(self):
        window, page = self.open_page()
        bad = self.config.config_path.with_name("conf.yaml.bak-20200101-000000-000000")
        bad.write_text("save: [x", encoding="utf-8")
        before = self.on_disk()
        with mock.patch.object(window.toasts, "show_message") as toast:
            page.restore(bad.name)
            self.flush()
        self.assertEqual(self.on_disk(), before)
        self.assertEqual(toast.call_args.args[0], "error")
        self.assertIn("linha", toast.call_args.args[2])

    def test_a_symlinked_config_is_edited_in_place(self):
        real = self.root / "dotfiles" / "conf.yaml"
        real.parent.mkdir()
        real.write_text(BASE_CONF, encoding="utf-8")
        self.config.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.config_path.symlink_to(real)
        _window, page = self.open_page(initial=None)
        add_group(page.editors["save"], "viasymlink")
        self.flush()
        page.save()
        self.flush()
        self.assertTrue(self.config.config_path.is_symlink())
        self.assertIn("viasymlink", real.read_text(encoding="utf-8"))

    @unittest.skipUnless(REAL_KNSV.exists(), "tests/profile_test.knsv missing")
    def test_the_real_plasma6_config_edits_cleanly(self):
        with zipfile.ZipFile(REAL_KNSV) as archive:
            text = archive.read("conf.yaml").decode("utf-8")
        _window, page = self.open_page(text)
        self.assertEqual(page.text, text)
        self.assertEqual(
            [g.name for g in page.editors["save"].groups], ["configs", "app_layouts"]
        )
        self.assertEqual(
            [g.name for g in page.editors["export"].groups],
            ["share_folder", "home_folder"],
        )
        editor = page.editors["export"]
        editor.select_group("home_folder")
        editor.add_entry(".mozilla")
        editor.select_group("home_folder")
        self.flush()
        self.assertTrue(page.check.ok, page.check.problems)
        page.save()
        self.flush()
        saved = self.on_disk()
        self.assertEqual(comment_lines(text), comment_lines(saved))
        self.assertIn(
            ".mozilla", yaml.safe_load(saved)["export"]["home_folder"]["entries"]
        )
        # nothing else moved: the only difference is the added line
        old_lines, new_lines = text.splitlines(), saved.splitlines()
        self.assertEqual(len(new_lines), len(old_lines) + 1)
        self.assertEqual(
            [l for l in new_lines if l not in old_lines], ["            - .mozilla"]
        )

    def test_the_resolved_location_is_shown_for_functions(self):
        folder = self.root / ".local/share/plasma-abc"
        folder.mkdir(parents=True)
        text = (
            "save:\n  g:\n    location: \"$HOME/.local/share/${BEGINS_WITH='plasma'}\"\n"
            "    entries: []\nexport: {}\n"
        )
        _window, page = self.open_page(text)
        editor = page.editors["save"]
        editor.select_group("g")
        self.assertIn(str(folder), editor.resolved_label.text())

    def test_failed_save_reports_in_pt_br_and_keeps_the_edits(self):
        window, page = self.open_page()
        add_group(page.editors["save"], "ok")
        self.flush()
        error = PermissionError(13, "Permission denied", "conf.yaml")
        with mock.patch.object(
            ConfigService, "write_text", side_effect=error
        ), mock.patch.object(window.toasts, "show_message") as toast:
            page.save()
            self.flush()
        self.assertEqual(toast.call_args.args[0], "error")
        self.assertIn("Sem permissão", toast.call_args.args[2])
        self.assertTrue(page.is_dirty)
        self.assertNotIn("ok:", self.on_disk())


class ConfigBackendTests(unittest.TestCase):
    """The backend contract, without Qt."""

    def test_the_fake_backend_edits_a_sandbox(self):
        if really_root():
            self.skipTest("the demo backend builds a real engine")
        backend = FakeBackend()
        snapshot = backend.load_config()
        self.assertTrue(snapshot.sandbox)
        self.assertTrue(snapshot.exists)
        self.assertIn("$HOME", snapshot.keywords)
        self.assertIn("ENDS_WITH", snapshot.functions)
        check = backend.check_config(snapshot.text)
        self.assertTrue(check.ok)
        self.assertIn(("save", "configs"), check.resolved)
        with self.assertRaises(ConfigValidationError):
            backend.save_config("save: [", snapshot.digest)
        result = backend.save_config(snapshot.text + "\n# note\n", snapshot.digest)
        self.assertTrue(result.ok)
        with self.assertRaises(ConfigConflictError):
            backend.save_config(snapshot.text, snapshot.digest)
        self.assertTrue(
            backend.save_config(snapshot.text, snapshot.digest, force=True).ok
        )
        self.assertEqual(len(backend.list_config_backups()), 2)


if __name__ == "__main__":
    unittest.main()
