"""Fictitious data for the visual prototype.

Everything here is invented. No file is read and Konsave is never called.
The data is always in English, whatever the interface language: it is sample
content (profile names, descriptions, areas and activity), not interface text, so
it is not part of the translation catalogs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

from kongui.gui.state import ActivityEntry, Profile


def sections() -> Tuple[str, ...]:
    """Returns the configuration areas offered when saving a profile.

    Returns:
        Tuple[str, ...]: Seven area names (always English).
    """
    return (
        "Plasma (panels and widgets)",
        "Keyboard shortcuts",
        "Icons and cursors",
        "Application themes",
        "Fonts",
        "Wallpaper",
        "Konsole and Dolphin",
    )


def demo_profiles() -> List[Profile]:
    """Returns the fictitious profiles.

    Returns:
        List[Profile]: Seven profiles; the first one ("Work") is the active one.
    """
    now = datetime.now()
    day = timedelta(days=1)
    areas = sections()
    return [
        Profile(
            "Work",
            "Single panel, dark theme and shortcuts for side-by-side windows.",
            areas[:5],
            48.2,
            now - 2 * day,
            active=True,
        ),
        Profile(
            "Minimalist",
            "No widgets, monochrome icons and a plain wallpaper.",
            (areas[0], areas[2], areas[5]),
            12.7,
            now - 9 * day,
        ),
        Profile(
            "Gaming",
            "Effects turned off and a floating panel.",
            (areas[0], areas[1], areas[3]),
            31.5,
            now - 21 * day,
        ),
        Profile(
            "Presentation",
            "Large fonts and high contrast for a projector.",
            (areas[2], areas[4]),
            9.1,
            now - 45 * day,
        ),
        Profile(
            "Retro",
            "Classic look with a bottom taskbar.",
            areas,
            76.9,
            now - 120 * day,
        ),
        Profile(
            "Night",
            "Warm colors and reduced brightness.",
            (areas[0], areas[3], areas[5]),
            22.4,
            now - 200 * day,
        ),
        Profile(
            "Tablet",
            "Larger touch targets and a side panel.",
            (areas[0], areas[1], areas[6]),
            27.8,
            now - 400 * day,
        ),
    ]


def demo_activity() -> List[ActivityEntry]:
    """Returns the fictitious activity feed, newest first.

    Returns:
        List[ActivityEntry]: Six entries.
    """
    now = datetime.now()
    return [
        ActivityEntry(now - timedelta(hours=3), "apply", "Profile “Work” applied"),
        ActivityEntry(now - timedelta(days=2), "save", "Profile “Work” updated"),
        ActivityEntry(
            now - timedelta(days=5),
            "export",
            "“Minimalist” exported to ~/Downloads",
        ),
        ActivityEntry(
            now - timedelta(days=9),
            "import",
            "“Gaming” imported from gaming.knsv",
        ),
        ActivityEntry(
            now - timedelta(days=21), "save", "Profile “Presentation” created"
        ),
        ActivityEntry(now - timedelta(days=45), "remove", "Profile “Test” removed"),
    ]
