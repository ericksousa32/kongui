"""Tests of kongui.core.categories: the export-category catalog and filter.

Pure functions, no engine or filesystem involved (``filter_groups`` works on
the already-resolved ``Groups`` shape ``ConfigService.resolve()`` returns).
"""

import unittest

from kongui.core.categories import (
    CATEGORIES,
    CATEGORY_DEPENDENCIES,
    OTHER,
    build_catalog,
    categorize,
    filter_groups,
    validate_categories,
)
from kongui.core.errors import ValidationError


class CatalogTests(unittest.TestCase):
    """What categorize() returns for known and unknown entries."""

    def test_every_default_kde_entry_is_known(self):
        # The entries of konsave/conf_kde.yaml's "configs" group: none of them
        # should fall through to "other" (that catalog is maintained by hand;
        # this test catches a typo or a forgotten addition).
        known = (
            "gtk-2.0 gtk-3.0 gtk-4.0 kate Kvantum latte dolphinrc katerc "
            "konsolerc kcminputrc kdeglobals kglobalshortcutsrc klipperrc "
            "krunnerrc kscreenlockerrc ksmserverrc kwinrc kwinrulesrc "
            "plasma-org.kde.plasma.desktop-appletsrc plasmarc plasmashellrc "
            "gtkrc gtkrc-2.0 lattedockrc breezerc oxygenrc lightlyrc "
            "ksplashrc khotkeysrc systemsettingsrc kded5rc kconf_updaterc "
            "kscreenrc plasma-systemmonitorrc spectaclerc plasmanotifyrc "
            "plasma-localerc plasma_calendar_holiday_regions "
            "xdg-desktop-portal-kderc kwinoutputconfig.json"
        ).split()
        for entry in known:
            with self.subTest(entry=entry):
                category = categorize("configs", entry)
                if entry in (
                    "kconf_updaterc",
                    "plasma_calendar_holiday_regions",
                    "xdg-desktop-portal-kderc",
                ):
                    self.assertEqual(category, OTHER, entry)
                else:
                    self.assertNotEqual(category, OTHER, entry)
                self.assertIn(category, CATEGORIES)

    def test_app_layouts_entries_are_known(self):
        for entry in "dolphin konsole yakuakerc systemsettings spectacle plasma-systemmonitor".split():
            self.assertNotEqual(categorize("app_layouts", entry), OTHER, entry)

    def test_export_entries_are_known(self):
        for entry in "plasma kwin konsole fonts color-schemes aurorae icons wallpapers yakuake".split():
            self.assertNotEqual(categorize("share_folder", entry), OTHER, entry)
        for entry in (".fonts", ".themes", ".icons"):
            self.assertNotEqual(categorize("home_folder", entry), OTHER, entry)

    def test_unknown_entry_is_other(self):
        self.assertEqual(categorize("configs", "my-custom-app.conf"), OTHER)

    def test_autostart_group_is_always_autostart_whatever_its_entries(self):
        self.assertEqual(categorize("autostart", "anything.desktop"), "autostart")
        self.assertEqual(categorize("autostart", "kdeglobals"), "autostart")

    def test_dependencies_only_name_real_categories(self):
        for needing, needs in CATEGORY_DEPENDENCIES.items():
            self.assertIn(needing, CATEGORIES)
            for dependency in needs:
                self.assertIn(dependency, CATEGORIES)
                self.assertNotEqual(dependency, needing)


class ValidateCategoriesTests(unittest.TestCase):
    """validate_categories() input checking."""

    def test_accepts_a_known_subset(self):
        self.assertEqual(validate_categories(["system", "icons"]), {"system", "icons"})

    def test_deduplicates(self):
        self.assertEqual(validate_categories(["system", "system"]), {"system"})

    def test_rejects_empty(self):
        with self.assertRaises(ValidationError):
            validate_categories([])

    def test_rejects_unknown_keys(self):
        with self.assertRaises(ValidationError):
            validate_categories(["system", "nope"])

    def test_rejects_a_bare_string(self):
        # A common mistake: "system" iterates as letters, not one category.
        with self.assertRaises(ValidationError):
            validate_categories("system")

    def test_rejects_non_collections(self):
        for bad in (None, 1, {"system": True}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_categories(bad)


class FilterGroupsTests(unittest.TestCase):
    """filter_groups() on the resolved Groups shape."""

    def setUp(self):
        self.groups = {
            "save": {
                "configs": {
                    "location": "/home/u/.config",
                    "entries": ["kdeglobals", "gtk-3.0", "my-custom-app.conf"],
                },
                "autostart": {
                    "location": "/home/u/.config/autostart",
                    "entries": ["thing.desktop"],
                },
            },
            "export": {
                "share_folder": {
                    "location": "/home/u/.local/share",
                    "entries": ["icons", "wallpapers"],
                },
            },
        }

    def test_keeps_only_the_chosen_categories(self):
        result = filter_groups(self.groups, frozenset({"system"}))
        self.assertEqual(result["save"]["configs"]["entries"], ["kdeglobals"])
        self.assertEqual(result["save"]["autostart"]["entries"], [])
        self.assertEqual(result["export"]["share_folder"]["entries"], [])

    def test_other_keeps_unrecognized_entries(self):
        result = filter_groups(self.groups, frozenset({"other"}))
        self.assertEqual(result["save"]["configs"]["entries"], ["my-custom-app.conf"])

    def test_autostart_whole_group_follows_its_own_category(self):
        result = filter_groups(self.groups, frozenset({"autostart"}))
        self.assertEqual(result["save"]["autostart"]["entries"], ["thing.desktop"])
        self.assertEqual(result["save"]["configs"]["entries"], [])

    def test_groups_and_locations_are_always_kept(self):
        # Even a group with everything filtered out stays, with its location,
        # the same as a group that already had no files on disk.
        result = filter_groups(self.groups, frozenset({"icons"}))
        self.assertEqual(set(result["save"]), {"configs", "autostart"})
        self.assertEqual(
            result["save"]["configs"]["location"], self.groups["save"]["configs"]["location"]
        )

    def test_individual_entries_can_be_excluded_within_a_kept_category(self):
        result = filter_groups(
            self.groups,
            frozenset({"system", "gtk"}),
            frozenset({("save", "configs", "gtk-3.0")}),
        )
        self.assertEqual(result["save"]["configs"]["entries"], ["kdeglobals"])

    def test_selecting_every_category_keeps_everything(self):
        result = filter_groups(self.groups, frozenset(CATEGORIES))
        self.assertEqual(result, self.groups)

    def test_input_is_not_mutated(self):
        before = {k: {n: dict(b) for n, b in s.items()} for k, s in self.groups.items()}
        filter_groups(self.groups, frozenset({"system"}))
        self.assertEqual(self.groups["save"]["configs"]["entries"], before["save"]["configs"]["entries"])


class BuildCatalogTests(unittest.TestCase):
    """build_catalog() / CategoryCatalog, used by the interface to group by category."""

    def test_entries_of_groups_by_category(self):
        groups = {
            "save": {"configs": {"location": "/x", "entries": ["kdeglobals", "kwinrc"]}},
            "export": {},
        }
        catalog = build_catalog(groups)
        self.assertEqual(
            catalog.entries_of("system"), (("save", "configs", "kdeglobals"),)
        )
        self.assertEqual(
            catalog.entries_of("window_management"), (("save", "configs", "kwinrc"),)
        )
        self.assertEqual(catalog.entries_of("fonts"), ())

    def test_category_of_matches_categorize(self):
        groups = {"save": {"configs": {"location": "/x", "entries": ["kdeglobals"]}}}
        catalog = build_catalog(groups)
        self.assertEqual(catalog.category_of("save", "configs", "kdeglobals"), "system")
        # Falls back to categorize() for an entry it never saw.
        self.assertEqual(catalog.category_of("save", "configs", "kwinrc"), "window_management")


if __name__ == "__main__":
    unittest.main()
