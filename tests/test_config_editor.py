"""Tests of the conf.yaml editor in kongui.core (model, text edits, backups)."""

import os
import json
import random
import re
import stat
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

import yaml

from kongui.core import (
    BackupNotFoundError,
    ConfigConflictError,
    ConfigParseError,
    ConfigValidationError,
    Group,
    apply_model,
    parse_model,
)
from tests.helpers import BASE_CONF
from tests.test_config_service import ConfigTestCase

REAL_KNSV = Path(__file__).with_name("profile_test.knsv")

COMMENTED = """\
# Top comment (kept)
---
save:
    # about configs
    configs:
        location: "$HOME/.config"   # trailing comment
        note: unknown key kept
        entries:
            - kdeglobals   # first
            # between
            - gtk-3.0
    other:
        location: "$HOME/.local/share/${ENDS_WITH='plasma'}"
        entries:
            - a

# before export
export:
    share_folder:
        location: "$HOME/.local/share"
        entries:
            - icons
extra_section:
    keep:
        location: "$HOME"
        entries: []
...
"""


VALID = COMMENTED.replace("/${ENDS_WITH='plasma'}", "")


def comments_of(text):
    """Returns the comment lines of a text, stripped."""
    return [line.strip() for line in text.splitlines() if "#" in line]


def edit(text, change):
    """Parses, lets ``change`` rewrite the model, applies, returns the result."""
    model = parse_model(text)
    return apply_model(text, change(model))


def set_entries(model, kind, name, entries):
    """Returns the model with the entries of one group replaced."""
    groups = [
        replace(g, entries=tuple(entries)) if g.name == name else g
        for g in model.groups(kind)
    ]
    return model.with_groups(kind, groups)


class ModelRoundTripTests(unittest.TestCase):
    """Reading the form and writing it back changes nothing."""

    def test_reading_and_writing_back_gives_the_same_text(self):
        for text in (
            COMMENTED,
            BASE_CONF,
            "save: {}\nexport: {}\n",
        ):
            with self.subTest(text=text[:30]):
                result = apply_model(text, parse_model(text))
                self.assertEqual(result.text, text)
                self.assertTrue(result.preserved)

    @unittest.skipUnless(REAL_KNSV.exists(), "tests/profile_test.knsv missing")
    def test_the_real_plasma6_config_round_trips_byte_for_byte(self):
        with zipfile.ZipFile(REAL_KNSV) as archive:
            text = archive.read("conf.yaml").decode("utf-8")
        model = parse_model(text)
        self.assertEqual([g.name for g in model.save], ["configs", "app_layouts"])
        self.assertEqual(
            [g.name for g in model.export], ["share_folder", "home_folder"]
        )
        self.assertEqual(apply_model(text, model).text, text)

    @unittest.skipUnless(REAL_KNSV.exists(), "tests/profile_test.knsv missing")
    def test_editing_the_real_config_keeps_all_comments(self):
        with zipfile.ZipFile(REAL_KNSV) as archive:
            text = archive.read("conf.yaml").decode("utf-8")
        result = edit(text, lambda m: set_entries(m, "save", "app_layouts", ["x y"]))
        self.assertTrue(result.preserved)
        before = comments_of(text)
        after = comments_of(result.text)
        self.assertEqual(before, after)
        self.assertEqual(
            yaml.safe_load(result.text)["save"]["app_layouts"]["entries"], ["x y"]
        )


class NullSectionTests(ConfigTestCase):
    """``save:`` with nothing under it crashes Konsave; the form repairs it."""

    def test_empty_sections_are_written_as_empty_mappings(self):
        for text in (
            "save:\nexport:\n",
            "save: ~\nexport: null\n",
            "save:   # none\nexport:\n",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.config.validate_text(text).ok)
                result = apply_model(text, parse_model(text))
                self.assertTrue(result.preserved)
                self.assertEqual(
                    yaml.safe_load(result.text), {"save": {}, "export": {}}
                )
                self.assertTrue(self.config.validate_text(result.text).ok)

    def test_groups_can_be_added_to_empty_sections(self):
        text = "save:\nexport:\n"
        model = parse_model(text).with_groups("save", [Group("g", "$HOME/g", ("f",))])
        result = apply_model(text, model)
        self.assertEqual(yaml.safe_load(result.text)["save"]["g"]["entries"], ["f"])


class EditTests(ConfigTestCase):
    """Edits keep comments, unknown keys and placeholders."""

    def loaded(self, text):
        """Loads the safe_load data of a text."""
        return yaml.safe_load(text)

    def test_adding_an_entry_keeps_every_comment(self):
        result = edit(
            COMMENTED,
            lambda m: set_entries(
                m, "save", "configs", ("kdeglobals", "gtk-3.0", "novo")
            ),
        )
        self.assertTrue(result.preserved)
        self.assertEqual(comments_of(result.text), comments_of(COMMENTED))
        data = self.loaded(result.text)
        self.assertEqual(
            data["save"]["configs"]["entries"], ["kdeglobals", "gtk-3.0", "novo"]
        )
        self.assertEqual(data["save"]["configs"]["note"], "unknown key kept")
        self.assertIn("keep", data["extra_section"])

    def test_removing_an_entry_removes_only_its_line(self):
        result = edit(
            COMMENTED, lambda m: set_entries(m, "save", "configs", ("gtk-3.0",))
        )
        self.assertNotIn("kdeglobals   # first", result.text)
        self.assertIn("# between", result.text)
        self.assertEqual(
            self.loaded(result.text)["save"]["configs"]["entries"], ["gtk-3.0"]
        )

    def test_inserting_at_the_front_and_in_the_middle(self):
        result = edit(
            COMMENTED,
            lambda m: set_entries(
                m, "save", "configs", ("zero", "kdeglobals", "mid", "gtk-3.0")
            ),
        )
        self.assertEqual(
            self.loaded(result.text)["save"]["configs"]["entries"],
            ["zero", "kdeglobals", "mid", "gtk-3.0"],
        )
        self.assertTrue(result.preserved)

    def test_clearing_all_entries_leaves_a_valid_group(self):
        result = edit(VALID, lambda m: set_entries(m, "save", "configs", ()))
        self.assertTrue(result.preserved)
        self.assertEqual(
            self.loaded(result.text)["save"]["configs"].get("entries"), None
        )
        self.assertTrue(self.config.validate_text(result.text).ok)

    def test_changing_a_location_keeps_the_rest(self):
        def change(model):
            groups = [
                replace(g, location="$CONFIG_DIR") if g.name == "configs" else g
                for g in model.save
            ]
            return model.with_groups("save", groups)

        result = edit(COMMENTED, change)
        self.assertTrue(result.preserved)
        data = self.loaded(result.text)
        self.assertEqual(data["save"]["configs"]["location"], "$CONFIG_DIR")
        self.assertEqual(
            data["save"]["other"]["location"],
            "$HOME/.local/share/${ENDS_WITH='plasma'}",
        )

    def test_a_valid_placeholder_that_is_not_edited_stays_byte_for_byte(self):
        result = edit(COMMENTED, lambda m: set_entries(m, "save", "configs", ("a",)))
        self.assertIn("\"$HOME/.local/share/${ENDS_WITH='plasma'}\"", result.text)

    def test_renaming_a_group(self):
        def change(model):
            groups = [
                replace(g, name="renamed") if g.name == "configs" else g
                for g in model.save
            ]
            return model.with_groups("save", groups)

        result = edit(COMMENTED, change)
        data = self.loaded(result.text)["save"]
        self.assertIn("renamed", data)
        self.assertNotIn("configs", data)
        self.assertEqual(data["renamed"]["note"], "unknown key kept")
        self.assertEqual(comments_of(result.text), comments_of(COMMENTED))

    def test_removing_a_group_keeps_the_others_and_the_comments_around(self):
        result = edit(
            COMMENTED,
            lambda m: m.with_groups("save", [g for g in m.save if g.name != "configs"]),
        )
        data = self.loaded(result.text)
        self.assertEqual(list(data["save"]), ["other"])
        self.assertIn("# before export", result.text)
        self.assertTrue(result.preserved)

    def test_removing_every_group_and_adding_one(self):
        result = edit(
            COMMENTED,
            lambda m: m.with_groups("save", [Group("fresh", "$HOME/x", ("a",))]),
        )
        self.assertTrue(result.preserved)
        self.assertEqual(list(self.loaded(result.text)["save"]), ["fresh"])

    def test_adding_a_group_to_each_section_separately(self):
        def change(model):
            model = model.with_groups(
                "save", list(model.save) + [Group("s_new", "$HOME/s", ("one",))]
            )
            return model.with_groups(
                "export", list(model.export) + [Group("e_new", "$HOME/e", ("two",))]
            )

        result = edit(VALID, change)
        data = self.loaded(result.text)
        self.assertEqual(
            data["save"]["s_new"], {"location": "$HOME/s", "entries": ["one"]}
        )
        self.assertEqual(
            data["export"]["e_new"], {"location": "$HOME/e", "entries": ["two"]}
        )
        self.assertNotIn("s_new", data["export"])
        self.assertTrue(result.preserved)
        self.assertTrue(self.config.validate_text(result.text).ok)

    def test_edits_work_with_two_space_indentation(self):
        text = "save:\n  a:\n    location: /x\n    entries:\n    - one\n  b:\n    location: /y\n    entries: []\nexport: {}\n"
        result = edit(
            text,
            lambda m: set_entries(m, "save", "b", ("two",)).with_groups(
                "save",
                list(set_entries(m, "save", "b", ("two",)).save)
                + [Group("c", "/z", ("3",))],
            ),
        )
        data = self.loaded(result.text)
        self.assertEqual(data["save"]["b"]["entries"], ["two"])
        self.assertEqual(data["save"]["c"]["entries"], ["3"])
        self.assertTrue(result.preserved)

    def test_document_end_marker_is_not_swallowed(self):
        result = edit(
            BASE_CONF,
            lambda m: m.with_groups(
                "export", list(m.export) + [Group("n", "$HOME/n", ("z",))]
            ),
        )
        self.assertTrue(result.text.rstrip().endswith("..."))
        self.assertEqual(len(list(yaml.safe_load_all(result.text))), 1)


class IncompleteFileTests(ConfigTestCase):
    """Files with missing parts can be completed in the form."""

    def test_missing_sections_are_added(self):
        for text in (
            "",
            "# only a comment\n",
            "save: {}\n",
            "export:\n    a:\n        location: /x\n        entries: []\n",
        ):
            with self.subTest(text=text):
                model = parse_model(text)
                model = model.with_groups("save", [Group("g", "$HOME/g", ("f",))])
                model = model.with_groups(
                    "export", list(model.export) + [Group("h", "$HOME/h", ())]
                )
                result = apply_model(text, model)
                data = yaml.safe_load(result.text)
                self.assertEqual(data["save"]["g"]["entries"], ["f"])
                self.assertIn("h", data["export"])
                self.assertTrue(self.config.validate_text(result.text).ok, result.text)
                if text.startswith("#"):
                    self.assertIn("# only a comment", result.text)

    def test_group_without_location_or_entries_is_shown_and_completed(self):
        text = "save:\n    g:\n        note: kept\nexport: {}\n"
        model = parse_model(text)
        self.assertEqual(model.save[0], Group("g", "", (), origin="g"))
        completed = model.with_groups(
            "save", [replace(model.save[0], location="/x", entries=("a",))]
        )
        data = yaml.safe_load(apply_model(text, completed).text)
        self.assertEqual(
            data["save"]["g"], {"note": "kept", "location": "/x", "entries": ["a"]}
        )

    def test_null_and_flow_entries_and_empty_group(self):
        text = (
            "save:\n    a:\n        location: /x\n        entries:\n"
            "    b:\n        location: /y\n        entries: [p, q]\n"
            "    c: {}\n"
            "export: {}\n"
        )
        model = parse_model(text)
        groups = [
            replace(model.save[0], entries=("n1", "n2")),
            replace(model.save[1], entries=("q", "r")),
            replace(model.save[2], location="/z", entries=("w",)),
        ]
        result = apply_model(text, model.with_groups("save", groups))
        data = yaml.safe_load(result.text)["save"]
        self.assertEqual(data["a"]["entries"], ["n1", "n2"])
        self.assertEqual(data["b"]["entries"], ["q", "r"])
        self.assertEqual(data["c"], {"location": "/z", "entries": ["w"]})
        self.assertTrue(result.preserved)

    def test_unsupported_layout_falls_back_and_says_so(self):
        text = "save: {a: {location: /x, entries: [b], keep: 1}}\nexport: {}\nextra: {k: v}\n"
        result = edit(text, lambda m: set_entries(m, "save", "a", ("c",)))
        self.assertFalse(result.preserved)
        data = yaml.safe_load(result.text)
        self.assertEqual(
            data["save"]["a"], {"location": "/x", "entries": ["c"], "keep": 1}
        )
        self.assertEqual(data["extra"], {"k": "v"})


class SpecialCharacterTests(ConfigTestCase):
    """Names with characters that need YAML quoting survive the round trip."""

    NAMES = (
        "with space",
        "colon: inside",
        "hash # inside",
        "quote'single",
        'quote"double',
        "ação-ü-日本",
        "$dollar",
        "{braces}",
        "[brackets]",
        "- dash",
        "*star",
        "&amp",
        "!bang",
        "yes",
        "null",
        "123",
        "back\\slash",
        ".hidden",
        "trailing.",
        "a,b",
    )

    def test_entries_and_group_names_round_trip(self):
        groups = [Group(f"g {name}", "$HOME/x", (name,)) for name in self.NAMES]
        text = "save: {}\nexport: {}\n"
        result = apply_model(text, parse_model(text).with_groups("save", groups))
        data = yaml.safe_load(result.text)["save"]
        for name in self.NAMES:
            self.assertEqual(data[f"g {name}"]["entries"], [name], name)
        again = parse_model(result.text)
        self.assertEqual([g.name for g in again.save], [g.name for g in groups])
        self.assertEqual(apply_model(result.text, again).text, result.text)

    def test_special_names_added_to_an_existing_list(self):
        names = tuple(self.NAMES)
        result = edit(COMMENTED, lambda m: set_entries(m, "save", "configs", names))
        self.assertEqual(
            yaml.safe_load(result.text)["save"]["configs"]["entries"], list(names)
        )
        self.assertTrue(result.preserved)

    def test_locations_with_quotes_unicode_and_functions(self):
        locations = (
            "$HOME/.local/share/${BEGINS_WITH='plasma'}",
            'C:\\dir "quoted" $HOME',
            "$HOME/açaí/日本",
            "$HOME/with 'single' quotes",
            "$HOME/#hash",
        )
        for location in locations:
            with self.subTest(location=location):
                result = edit(
                    COMMENTED,
                    lambda m: m.with_groups(
                        "save",
                        [
                            replace(g, location=location) if g.name == "other" else g
                            for g in m.save
                        ],
                    ),
                )
                self.assertEqual(
                    yaml.safe_load(result.text)["save"]["other"]["location"], location
                )

    def test_special_names_pass_the_service_validation(self):
        names = [n for n in self.NAMES if "/" not in n]
        result = edit(VALID, lambda m: set_entries(m, "save", "configs", names))
        self.assertTrue(self.config.validate_text(result.text).ok)


class ParseErrorTests(unittest.TestCase):
    """Texts that cannot be shown as a form are refused with a position."""

    def assert_refused(self, text, code, line=None):
        with self.assertRaises(ConfigParseError) as caught:
            parse_model(text)
        problems = caught.exception.problems
        self.assertIn(code, [p.code for p in problems], problems)
        hit = next(p for p in problems if p.code == code)
        self.assertIsNotNone(hit.line)
        if line is not None:
            self.assertEqual(hit.line, line)

    def test_invalid_yaml_has_line_and_column(self):
        self.assert_refused("save:\n  a: [unclosed\nexport: {}\n", "yaml-syntax")

    def test_root_must_be_a_mapping(self):
        self.assert_refused("- a\n- b\n", "root-not-mapping")

    def test_entry_that_is_not_text(self):
        self.assert_refused(
            "save:\n  a:\n    location: /x\n    entries:\n      - ok\n      - 12\nexport: {}\n",
            "entry-invalid",
            line=6,
        )

    def test_group_that_is_not_a_mapping(self):
        self.assert_refused(
            "save:\n  a: just text\nexport: {}\n", "group-not-mapping", line=2
        )

    def test_section_that_is_not_a_mapping(self):
        self.assert_refused("save: [1]\nexport: {}\n", "section-not-mapping", line=1)

    def test_duplicate_group_names(self):
        text = "save:\n  a:\n    location: /x\n    entries: []\n  a:\n    location: /y\n    entries: []\nexport: {}\n"
        self.assert_refused(text, "duplicate-key", line=5)


class LocatedProblemTests(ConfigTestCase):
    """The validation report says where each problem is."""

    def problems(self, text):
        return {p.code: p for p in self.config.validate_text(text).problems}

    def test_invalid_entry_points_at_the_item(self):
        text = (
            'save:\n  a:\n    location: "$HOME/x"\n    entries:\n'
            "      - ok\n      - bad/nested\nexport: {}\n"
        )
        problem = self.problems(text)["entry-invalid"]
        self.assertEqual(problem.path, ("save", "a", "entries", 1))
        self.assertEqual(problem.dotted_path, "save.a.entries[1]")
        self.assertEqual(problem.line, 6)
        self.assertEqual(problem.args["value"], "bad/nested")
        self.assertTrue(problem.is_error)

    def test_unknown_placeholder_points_at_the_location(self):
        text = 'save:\n  a:\n    location: "$NOPE/x"\n    entries: []\nexport: {}\n'
        problem = self.problems(text)["placeholder-unsupported"]
        self.assertEqual((problem.line, problem.column), (3, 5))
        self.assertEqual(problem.args["name"], "NOPE")
        self.assertIn("$HOME", problem.args["supported"])

    def test_missing_entries_points_at_the_group(self):
        text = 'save:\n  a:\n    location: "$HOME/x"\nexport: {}\n'
        problem = self.problems(text)["entries-missing"]
        self.assertEqual(problem.line, 2)

    def test_yaml_error_position(self):
        report = self.config.validate_text("save:\n  a: [x\nexport: {}\n")
        problem = report.problems[0]
        self.assertEqual(problem.code, "yaml-syntax")
        self.assertGreaterEqual(problem.line, 2)
        self.assertIsNotNone(problem.column)

    def test_legacy_strings_match_the_structured_problems(self):
        report = self.config.validate_text("save:\n  a:\n    location: 5\nexport: {}\n")
        self.assertEqual(
            report.errors, tuple(p.text for p in report.problems if p.is_error)
        )

    def test_warnings_are_located_too(self):
        text = (
            'save:\n  a:\n    location: "$HOME/missing-dir"\n    entries:\n'
            "      - x\n      - x\nexport: {}\n"
        )
        report = self.config.validate_text(text)
        dup = [p for p in report.problems if p.code == "entry-duplicate"][0]
        self.assertFalse(dup.is_error)
        self.assertEqual(dup.line, 6)

    def test_duplicate_key_is_an_error_at_the_second_one(self):
        text = "save:\n  a:\n    location: /x\n    entries: []\n  a:\n    location: /y\n    entries: []\nexport: {}\n"
        report = self.config.validate_text(text)
        self.assertFalse(report.ok)
        self.assertEqual(self.problems(text)["duplicate-key"].line, 5)


class WriteAndBackupTests(ConfigTestCase):
    """Writing validates first, backs up, and never loses the old file."""

    def setUp(self):
        super().setUp()
        self.engine.ensure_runtime_dirs()
        self.path = self.engine.config_file
        self.path.write_text(BASE_CONF, encoding="utf-8")

    def backups(self):
        return [b.name for b in self.config.list_backups()]

    def test_invalid_text_is_never_written_and_makes_no_backup(self):
        with self.assertRaises(ConfigValidationError) as caught:
            self.config.write_text("save: [oops\n")
        self.assertTrue(caught.exception.report.problems)
        self.assertEqual(self.path.read_text(encoding="utf-8"), BASE_CONF)
        self.assertEqual(self.backups(), [])

    def test_valid_text_replaces_the_file_after_backing_it_up(self):
        new = VALID
        result = self.config.write_text(new)
        self.assertTrue(result.ok)
        self.assertEqual(self.path.read_text(encoding="utf-8"), new)
        names = self.backups()
        self.assertEqual(len(names), 1)
        self.assertEqual(self.config.read_backup(names[0]), BASE_CONF)

    def test_no_temporary_files_are_left_behind(self):
        self.config.write_text(VALID)
        leftovers = [n for n in os.listdir(self.path.parent) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_backups_are_listed_newest_first_and_names_never_collide(self):
        for index in range(3):
            self.config.write_text(VALID.replace("kdeglobals", f"k{index}"))
        listed = self.config.list_backups()
        self.assertEqual(len(listed), 3)
        self.assertEqual(len({b.name for b in listed}), 3)
        self.assertEqual(
            [b.created for b in listed],
            sorted((b.created for b in listed), reverse=True),
        )
        self.assertIn("k1", self.config.read_backup(listed[0].name))

    def test_restoring_a_backup_backs_up_the_current_file_first(self):
        self.config.write_text(VALID)
        first = self.config.list_backups()[0].name
        result = self.config.restore_backup(first)
        self.assertTrue(result.ok)
        self.assertEqual(result.operation, "restore_config")
        self.assertEqual(self.path.read_text(encoding="utf-8"), BASE_CONF)
        contents = [self.config.read_backup(n) for n in self.backups()]
        self.assertIn(VALID, contents)

    def test_an_invalid_backup_is_not_restored(self):
        self.config.write_text(VALID)
        (self.path.parent / "conf.yaml.bak-20200101-000000-000000").write_text(
            "save: [broken", encoding="utf-8"
        )
        with self.assertRaises(ConfigValidationError):
            self.config.restore_backup("conf.yaml.bak-20200101-000000-000000")
        self.assertEqual(self.path.read_text(encoding="utf-8"), VALID)

    def test_backup_names_cannot_escape_the_folder(self):
        outside = self.path.parent.parent / "secret.txt"
        outside.write_text("x", encoding="utf-8")
        for name in (
            "../secret.txt",
            "/etc/passwd",
            "conf.yaml",
            "conf.yaml.bak-nope",
            "",
        ):
            with self.subTest(name=name):
                with self.assertRaises(BackupNotFoundError):
                    self.config.read_backup(name)
                with self.assertRaises(BackupNotFoundError):
                    self.config.restore_backup(name)

    def test_a_change_made_outside_is_detected(self):
        digest = self.config.digest()
        self.path.write_text(BASE_CONF + "# edited elsewhere\n", encoding="utf-8")
        with self.assertRaises(ConfigConflictError):
            self.config.write_text(VALID, expected_digest=digest)
        self.assertIn("edited elsewhere", self.path.read_text(encoding="utf-8"))
        self.config.write_text(VALID, expected_digest=self.config.digest())

    def test_expected_missing_file(self):
        self.path.unlink()
        self.assertIsNone(self.config.digest())
        self.config.write_text(VALID, expected_digest=None)
        self.assertEqual(self.backups(), [])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    def test_permissions_of_the_old_file_are_kept(self):
        self.path.chmod(0o640)
        self.config.write_text(VALID)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_a_symlinked_config_stays_a_symlink(self):
        real = self.path.parent.parent / "dotfiles-conf.yaml"
        real.write_text(BASE_CONF, encoding="utf-8")
        self.path.unlink()
        self.path.symlink_to(real)
        self.config.write_text(VALID)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), VALID)

    def test_cancelling_is_just_not_writing(self):
        model = parse_model(self.path.read_text(encoding="utf-8"))
        apply_model(BASE_CONF, model.with_groups("save", []))
        self.assertEqual(self.path.read_text(encoding="utf-8"), BASE_CONF)
        self.assertEqual(self.backups(), [])

    def test_unrelated_files_are_not_listed_as_backups(self):
        (self.path.parent / "conf.yaml.bak-x").mkdir()
        (self.path.parent / "other.bak-1").write_text("x", encoding="utf-8")
        self.assertEqual(self.backups(), [])
        self.assertTrue(re.match(r"^$", ""))


class ReorderTests(unittest.TestCase):
    """Entries that change order are still written exactly as asked."""

    def test_reordering_and_replacing_entries(self):
        text = "save:\n  a:\n    location: /x\n    entries:\n      - one  # keep\n      - two\n      - three\nexport: {}\n"
        for wanted in (
            ("three", "one", "two"),
            ("two", "one"),
            ("three", "two", "one"),
            ("one", "one", "two"),
            ("new", "three"),
        ):
            with self.subTest(wanted=wanted):
                result = edit(text, lambda m: set_entries(m, "save", "a", wanted))
                self.assertTrue(result.preserved)
                self.assertEqual(
                    yaml.safe_load(result.text)["save"]["a"]["entries"], list(wanted)
                )


class OriginalBehaviourTests(ConfigTestCase):
    """What the original ``read_konsave_config`` does, and what we say about it.

    These are the findings of the audit (docs/GUI_CONFIG.md): each case asks the
    original code to resolve a location and then checks that the validation
    verdict agrees with what came back.
    """

    def setUp(self):
        super().setUp()
        home = self.engine.home
        for name in (
            ".config",
            ".local/share/plasma-x",
            ".mozilla/firefox/abc.default-release",
        ):
            (Path(home) / name).mkdir(parents=True, exist_ok=True)
        self.engine.ensure_runtime_dirs()

    def resolve(self, location, entries="[a]"):
        text = (
            f"save:\n  g:\n    location: {json.dumps(location)}\n"
            f"    entries: {entries}\nexport: {{}}\n"
        )
        report = self.config.validate_text(text)
        probe = Path(self.engine.home) / "probe.yaml"
        probe.write_text(text, encoding="utf-8")
        call = self.engine.call("read_konsave_config", str(probe))
        original = call.returned["save"]["g"] if call.returned else None
        return report, original

    def test_keywords_are_plain_substitutions_and_keep_a_trailing_slash(self):
        home = str(self.engine.home)
        cases = {
            "$HOME": home,
            "$HOME/": home + "/",
            "$CONFIG_DIR": home + "/.config",
            "$SHARE_DIR": home + "/.local/share",
            "$BIN_DIR": home + "/.local/bin",
            "$HOME/with space/ç": home + "/with space/ç",
        }
        for location, resolved in cases.items():
            with self.subTest(location=location):
                report, original = self.resolve(location)
                self.assertEqual(original["location"], resolved)
                self.assertTrue(report.ok, report.errors)
                self.assertEqual(report.resolved["save"]["g"]["location"], resolved)

    def test_functions_pick_a_matching_folder_with_either_quote(self):
        home = str(self.engine.home)
        for location, resolved in {
            "$HOME/.mozilla/firefox/${ENDS_WITH='.default-release'}": ".mozilla/firefox/abc.default-release",
            '$HOME/.mozilla/firefox/${ENDS_WITH=".default-release"}': ".mozilla/firefox/abc.default-release",
            "$HOME/.local/share/${BEGINS_WITH='plasma'}": ".local/share/plasma-x",
        }.items():
            with self.subTest(location=location):
                report, original = self.resolve(location)
                self.assertEqual(original["location"], f"{home}/{resolved}")
                self.assertTrue(report.ok, report.errors)

    def test_what_the_original_leaves_unresolved_is_an_error_here(self):
        for location, code in {
            "$HOME/.local/share/${BEGINS_WITH='nomatch'}": "location-unresolved",
            "$HOME/.local/share/${ENDS_WITH='nomatch'}": "location-unresolved",
            "$HOME/.local/share/${BEGINS_WITH='plasma y'}": "location-unresolved",
            "$HOME/.local/share/${BEGINS_WITH='plasma'}/${ENDS_WITH='x'}": "location-unresolved",
            "$HOME/.local/share/${FOO='x'}": "function-unsupported",
            "$HOME/$NOPE/x": "placeholder-unsupported",
            "$KONSAVE_DIR/x": "placeholder-unsupported",
            "~/x": "location-relative",
            "relative/path": "location-relative",
        }.items():
            with self.subTest(location=location):
                report, original = self.resolve(location)
                self.assertFalse(report.ok)
                self.assertIn(code, {p.code for p in report.problems}, report.errors)

    def test_the_original_crashes_when_a_function_has_no_parent_folder(self):
        report, original = self.resolve("$HOME/nodir/${ENDS_WITH='x'}")
        self.assertIsNone(original)
        self.assertIn("konsave-failed", {p.code for p in report.problems})
        self.assertFalse(report.ok)

    def test_empty_entries_become_an_empty_list(self):
        for entries in ("", "[]", "null"):
            with self.subTest(entries=entries):
                report, original = self.resolve("$HOME", entries)
                self.assertEqual(original["entries"], [])
                self.assertTrue(report.ok, report.errors)

    def test_the_placeholders_offered_are_the_ones_the_original_defines(self):
        listed = self.config.placeholders()
        self.assertEqual(
            sorted(listed["keywords"]),
            sorted("$" + name for name in self.engine.parse.tokens["keywords"]["dict"]),
        )
        self.assertEqual(
            sorted(listed["functions"]),
            sorted(self.engine.parse.tokens["functions"]["dict"]),
        )
        self.assertNotIn("$KONSAVE_DIR", listed["keywords"])


class RandomEditTests(unittest.TestCase):
    """Many random edits: the text always reads back as the form that made it."""

    NAMES = ("w", "x y", "c: d", "é", "$z", "#h", "'q'", '"d"')

    def sources(self):
        with zipfile.ZipFile(REAL_KNSV) as archive:
            real = archive.read("conf.yaml").decode("utf-8")
        return [
            VALID,
            BASE_CONF,
            real,
            "save:\n  a:\n    location: /x\n    entries:\n    - one\nexport: {}\n",
            "save: {}\nexport: {}\n",
            "save:\n    a:\n        location: /x\n        entries: [p, q]\n    b: {}\nexport:\n",
            "",
        ]

    def mutate(self, rnd, groups):
        for _ in range(rnd.randint(0, 3)):
            op = rnd.choice("aderlE")
            pick = rnd.randrange(len(groups)) if groups else None
            if op == "a":
                name = rnd.choice(self.NAMES) + str(rnd.randint(0, 99))
                entries = tuple(rnd.sample(self.NAMES, rnd.randint(0, 3)))
                groups.append(Group(name, "$HOME/" + rnd.choice(self.NAMES), entries))
            elif pick is None:
                continue
            elif op == "d":
                groups.pop(pick)
            elif op == "e":
                entries = tuple(rnd.sample(self.NAMES, rnd.randint(0, 4)))
                groups[pick] = replace(groups[pick], entries=entries)
            elif op == "r":
                name = rnd.choice(self.NAMES) + str(rnd.randint(100, 199))
                groups[pick] = replace(groups[pick], name=name)
            elif op == "l":
                location = "/" + rnd.choice(self.NAMES)
                groups[pick] = replace(groups[pick], location=location)
            else:
                entries = groups[pick].entries + (rnd.choice(self.NAMES) + "!",)
                groups[pick] = replace(groups[pick], entries=entries)

    def test_random_edits_round_trip_and_keep_comments(self):
        rnd = random.Random(20260716)
        sources = self.sources()
        for _ in range(600):
            text = rnd.choice(sources)
            model = parse_model(text)
            for kind in ("save", "export"):
                groups = list(model.groups(kind))
                self.mutate(rnd, groups)
                model = model.with_groups(kind, groups)
            result = apply_model(text, model)
            self.assertTrue(result.preserved, (text, model))
            back = parse_model(result.text)
            for kind in ("save", "export"):
                shown = [(g.name, g.location, g.entries) for g in back.groups(kind)]
                wanted = [(g.name, g.location, g.entries) for g in model.groups(kind)]
                self.assertEqual(shown, wanted)


if __name__ == "__main__":
    unittest.main()
