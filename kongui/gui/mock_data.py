"""Fictitious data for the visual prototype.

Everything here is invented. No file is read and Konsave is never called.
The texts are written in the interface language in use when the data is made
(profile names and descriptions are data, like the ones a user would type), so
switching the language later does not rename profiles that already exist; the
"restore fictitious profiles" action makes them again in the new language.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

from PySide6.QtCore import QCoreApplication as Q

from kongui.gui.state import ActivityEntry, Profile


def sections() -> Tuple[str, ...]:
    """Returns the configuration areas offered when saving a profile.

    Returns:
        Tuple[str, ...]: Seven area names in the current language.
    """
    return (
        Q.translate("mock_data", "Plasma (panels and widgets)"),
        Q.translate("mock_data", "Keyboard shortcuts"),
        Q.translate("mock_data", "Icons and cursors"),
        Q.translate("mock_data", "Application themes"),
        Q.translate("mock_data", "Fonts"),
        Q.translate("mock_data", "Wallpaper"),
        Q.translate("mock_data", "Konsole and Dolphin"),
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
            Q.translate("mock_data", "Work"),
            Q.translate(
                "mock_data",
                "Single panel, dark theme and shortcuts for side-by-side windows.",
            ),
            areas[:5],
            48.2,
            now - 2 * day,
            active=True,
        ),
        Profile(
            Q.translate("mock_data", "Minimalist"),
            Q.translate(
                "mock_data", "No widgets, monochrome icons and a plain wallpaper."
            ),
            (areas[0], areas[2], areas[5]),
            12.7,
            now - 9 * day,
        ),
        Profile(
            Q.translate("mock_data", "Gaming"),
            Q.translate("mock_data", "Effects turned off and a floating panel."),
            (areas[0], areas[1], areas[3]),
            31.5,
            now - 21 * day,
        ),
        Profile(
            Q.translate("mock_data", "Presentation"),
            Q.translate("mock_data", "Large fonts and high contrast for a projector."),
            (areas[2], areas[4]),
            9.1,
            now - 45 * day,
        ),
        Profile(
            Q.translate("mock_data", "Retro"),
            Q.translate("mock_data", "Classic look with a bottom taskbar."),
            areas,
            76.9,
            now - 120 * day,
        ),
        Profile(
            Q.translate("mock_data", "Night"),
            Q.translate("mock_data", "Warm colors and reduced brightness."),
            (areas[0], areas[3], areas[5]),
            22.4,
            now - 200 * day,
        ),
        Profile(
            Q.translate("mock_data", "Tablet"),
            Q.translate("mock_data", "Larger touch targets and a side panel."),
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
    work = Q.translate("mock_data", "Work")
    return [
        ActivityEntry(
            now - timedelta(hours=3),
            "apply",
            Q.translate("mock_data", "Profile “{name}” applied").format(name=work),
        ),
        ActivityEntry(
            now - timedelta(days=2),
            "save",
            Q.translate("mock_data", "Profile “{name}” updated").format(name=work),
        ),
        ActivityEntry(
            now - timedelta(days=5),
            "export",
            Q.translate("mock_data", "“{name}” exported to {folder}").format(
                name=Q.translate("mock_data", "Minimalist"), folder="~/Downloads"
            ),
        ),
        ActivityEntry(
            now - timedelta(days=9),
            "import",
            Q.translate("mock_data", "“{name}” imported from {file}").format(
                name=Q.translate("mock_data", "Gaming"), file="gaming.knsv"
            ),
        ),
        ActivityEntry(
            now - timedelta(days=21),
            "save",
            Q.translate("mock_data", "Profile “{name}” created").format(
                name=Q.translate("mock_data", "Presentation")
            ),
        ),
        ActivityEntry(
            now - timedelta(days=45),
            "remove",
            Q.translate("mock_data", "Profile “{name}” removed").format(
                name=Q.translate("mock_data", "Test")
            ),
        ),
    ]
