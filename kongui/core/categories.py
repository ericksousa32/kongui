"""Export categories: a finer grouping of what a profile can contain.

Konsave's own ``conf.yaml`` groups are coarse: the default KDE configuration
keeps dozens of unrelated files (themes, panels, shortcuts, GTK, window
management…) in one single ``save`` group, ``configs``. There is no structure
in Konsave itself that distinguishes "Themes" from "Window management" or
"GTK Settings".

This module adds that structure on top, as a **best-effort, KonGUI-only**
catalog: it recognizes the file and folder names that the KDE template
(``konsave/conf_kde.yaml``) ships, and sorts them into the categories a user
would actually think in. Anything not recognized — a custom group or entry the
user added by hand — falls into :data:`OTHER`, never silently dropped.

It knows nothing about *why* a file matters (that stays with Konsave); it only
answers "what kind of setting is this file", so the interface can offer
category checkboxes before saving a profile (``docs/INTEGRATION.md`` §11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple

from kongui.core.config import Groups
from kongui.core.errors import ValidationError

#: Stable, English, never-translated keys. The order here is the order
#: categories are offered in the interface.
SYSTEM = "system"
PANELS = "panels"
THEMES = "themes"
ICONS = "icons"
WALLPAPER = "wallpaper"
FONTS = "fonts"
APPS = "apps"
WINDOW_MANAGEMENT = "window_management"
GTK = "gtk"
SHORTCUTS = "shortcuts"
AUTOSTART = "autostart"
OTHER = "other"

#: All category keys, in display order. :data:`OTHER` is always last and
#: always offered (the catch-all for anything not recognized).
CATEGORIES: Tuple[str, ...] = (
    SYSTEM,
    PANELS,
    THEMES,
    ICONS,
    WALLPAPER,
    FONTS,
    APPS,
    WINDOW_MANAGEMENT,
    GTK,
    SHORTCUTS,
    AUTOSTART,
    OTHER,
)

#: A category a selected category depends on, and why: the dependency holds
#: files whose *choice* (which theme, which wallpaper…) is actually stored,
#: not duplicate content. Best-effort, based on where KDE is known to keep
#: that choice by default; not exhaustive and not version-checked.
CATEGORY_DEPENDENCIES: Dict[str, Tuple[str, ...]] = {
    ICONS: (SYSTEM,),
    WALLPAPER: (PANELS,),
    FONTS: (SYSTEM,),
    THEMES: (SYSTEM,),
}

#: ``konsave/conf_kde.yaml`` entry (file or folder name, as written in
#: ``entries:``) to category. Matched by exact name, regardless of which
#: group the entry is physically found in (a user's hand-edited ``conf.yaml``
#: may have moved things around). Entries of the ``autostart`` group are
#: *not* looked up here: see :func:`categorize`.
_CATALOG: Dict[str, str] = {
    # GTK Settings
    "gtk-2.0": GTK,
    "gtk-3.0": GTK,
    "gtk-4.0": GTK,
    "gtkrc": GTK,
    "gtkrc-2.0": GTK,
    ".themes": GTK,
    # Application Settings
    "kate": APPS,
    "katerc": APPS,
    "dolphinrc": APPS,
    "dolphin": APPS,
    "konsolerc": APPS,
    "konsole": APPS,
    "klipperrc": APPS,
    "krunnerrc": APPS,
    "plasma-systemmonitorrc": APPS,
    "plasma-systemmonitor": APPS,
    "spectaclerc": APPS,
    "spectacle": APPS,
    "yakuakerc": APPS,
    "yakuake": APPS,
    "systemsettings": APPS,
    # Panels and Desktop Layout
    "latte": PANELS,
    "lattedockrc": PANELS,
    "plasma-org.kde.plasma.desktop-appletsrc": PANELS,
    "plasmashellrc": PANELS,
    # Themes and Appearance
    "kvantum": THEMES,
    "plasmarc": THEMES,
    "breezerc": THEMES,
    "oxygenrc": THEMES,
    "lightlyrc": THEMES,
    "ksplashrc": THEMES,
    "plasma": THEMES,
    "color-schemes": THEMES,
    "aurorae": THEMES,
    # Icons and Cursors
    "icons": ICONS,
    ".icons": ICONS,
    # Wallpaper
    "wallpapers": WALLPAPER,
    # Fonts
    "fonts": FONTS,
    ".fonts": FONTS,
    # Window Management
    "kwinrc": WINDOW_MANAGEMENT,
    "kwinrulesrc": WINDOW_MANAGEMENT,
    "kwinoutputconfig.json": WINDOW_MANAGEMENT,
    "kwin": WINDOW_MANAGEMENT,
    # Keyboard Shortcuts and Input
    "kglobalshortcutsrc": SHORTCUTS,
    "khotkeysrc": SHORTCUTS,
    # System Settings
    "kcminputrc": SYSTEM,
    "kdeglobals": SYSTEM,
    "kscreenlockerrc": SYSTEM,
    "ksmserverrc": SYSTEM,
    "systemsettingsrc": SYSTEM,
    "kded5rc": SYSTEM,
    "kscreenrc": SYSTEM,
    "plasmanotifyrc": SYSTEM,
    "plasma-localerc": SYSTEM,
}
# "kvantum" above matches the lower-cased name; the shipped entry is
# "Kvantum" (mixed case). Keep both spellings, since conf.yaml is free text.
_CATALOG["Kvantum"] = THEMES


@dataclass(frozen=True)
class CategoryCatalog:
    """A snapshot of which entry belongs to which category, for one set of
    resolved groups (see :func:`build_catalog`).

    Attributes:
        entry_category: ``{(group_kind, group_name, entry): category}`` for
            every entry of the resolved groups.
    """

    entry_category: Dict[Tuple[str, str, str], str]

    def category_of(self, group_kind: str, group_name: str, entry: str) -> str:
        """Returns the category of one entry (see :func:`categorize`)."""
        return self.entry_category.get(
            (group_kind, group_name, entry), categorize(group_name, entry)
        )

    def entries_of(self, category: str) -> Tuple[Tuple[str, str, str], ...]:
        """Returns the ``(group_kind, group_name, entry)`` triples of a category,
        in a stable order (grouped, then alphabetical)."""
        return tuple(
            sorted(
                key for key, value in self.entry_category.items() if value == category
            )
        )


def validate_categories(categories: object) -> FrozenSet[str]:
    """Checks a requested set of categories.

    Args:
        categories: Candidate collection of category keys.

    Returns:
        FrozenSet[str]: The same categories, deduplicated.

    Raises:
        ValidationError: If ``categories`` is not a collection of strings, is
            empty, or names a key outside :data:`CATEGORIES`.
    """
    if isinstance(categories, str) or not isinstance(categories, (list, tuple, set, frozenset)):
        raise ValidationError(f"categories must be a list of strings, not {categories!r}")
    chosen = frozenset(categories)
    if not chosen:
        raise ValidationError("choose at least one category")
    unknown = sorted(chosen - frozenset(CATEGORIES))
    if unknown:
        raise ValidationError(f"unknown category: {', '.join(unknown)}")
    return chosen


def categorize(group_name: str, entry: str) -> str:
    """Returns the category of one ``conf.yaml`` entry.

    Args:
        group_name: Name of the group the entry is written under (as in
            ``conf.yaml``; for example ``"configs"`` or ``"autostart"``).
        entry: The entry name itself (a file or folder name).

    Returns:
        str: One of :data:`CATEGORIES`. The ``autostart`` group is always
        :data:`AUTOSTART`, whatever its entries are called (they are
        arbitrary ``.desktop`` files KonGUI cannot know in advance). Anything
        else not in the catalog is :data:`OTHER`.
    """
    if group_name == "autostart":
        return AUTOSTART
    return _CATALOG.get(entry, OTHER)


def build_catalog(groups: Groups) -> CategoryCatalog:
    """Categorizes every entry of a resolved configuration.

    Args:
        groups: Output of ``ConfigService.resolve()`` (``save`` and ``export``
            groups, placeholders already resolved).

    Returns:
        CategoryCatalog: One category per entry found.
    """
    entry_category: Dict[Tuple[str, str, str], str] = {}
    for kind, section in groups.items():
        for group_name, body in section.items():
            for entry in body.get("entries", []):
                entry_category[(kind, group_name, entry)] = categorize(
                    group_name, entry
                )
    return CategoryCatalog(entry_category)


def filter_groups(
    groups: Groups,
    categories: FrozenSet[str],
    excluded_entries: FrozenSet[Tuple[str, str, str]] = frozenset(),
) -> Groups:
    """Keeps only the entries of the chosen categories.

    Args:
        groups: Output of ``ConfigService.resolve()``.
        categories: Category keys to keep (see :data:`CATEGORIES`); an entry
            whose category is not in this set is dropped.
        excluded_entries: ``(group_kind, group_name, entry)`` triples to drop
            even though their category was kept (individual overrides).

    Returns:
        Groups: The same shape as ``groups``, with ``entries`` filtered.
        Groups and their ``location`` are always kept, even if every entry
        of a group ends up filtered out (an empty group saves nothing, the
        same as a group that already had no files on disk).
    """
    result: Groups = {}
    for kind, section in groups.items():
        kept_section: Dict[str, Dict[str, object]] = {}
        for group_name, body in section.items():
            entries = [
                entry
                for entry in body.get("entries", [])
                if categorize(group_name, entry) in categories
                and (kind, group_name, entry) not in excluded_entries
            ]
            kept_section[group_name] = {"location": body["location"], "entries": entries}
        result[kind] = kept_section
    return result
