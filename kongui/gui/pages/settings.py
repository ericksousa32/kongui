"""Settings page."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QLineEdit, QSpinBox, QVBoxLayout

from kongui.gui import i18n, messages
from kongui.gui.context import AppContext
from kongui.gui.controller import Outcome
from kongui.gui.i18n import SUPPORTED, Text, effective_language
from kongui.gui.pages.base import Page
from kongui.gui.theme import ThemeMode
from kongui.gui.widgets.common import Button, Card, SegmentedControl, Separator
from kongui.gui.actions import ProfileActions
from kongui.gui.widgets.dialogs import SafetyCopiesDialog
from kongui.gui.widgets.rows import SettingRow

#: Where the original Konsave keeps profiles (documented in docs/INTEGRATION.md).
PROFILES_FOLDER = "~/.config/konsave/profiles"


class SettingsPage(Page):  # pylint: disable=too-many-instance-attributes
    """Appearance, behaviour, notifications and demo data."""

    key = "settings"
    TITLE = QT_TRANSLATE_NOOP("SettingsPage", "Settings")
    SUBTITLE = QT_TRANSLATE_NOOP(
        "SettingsPage", "Appearance and behavior of the application"
    )
    icon_name = "settings"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        settings = ctx.settings

        language = self._group(lambda: self.tr("Language"))
        # The names are written in their own language and never translated.
        self.language_control = SegmentedControl(
            [(code, name, None) for code, name in SUPPORTED.items()]
        )
        self.language_control.set_value(effective_language(settings.get("language")))
        self.language_control.selected.connect(
            lambda value: settings.set("language", value)
        )
        language.addWidget(
            SettingRow(
                lambda: self.tr("Interface language"),
                lambda: self.tr(
                    "Follows your system language until you choose one here. "
                    "The change applies immediately."
                ),
                self.language_control,
            )
        )

        appearance = self._group(lambda: self.tr("Appearance"))
        self.theme_control = SegmentedControl(
            [
                (ThemeMode.SYSTEM.value, lambda: self.tr("System"), "monitor"),
                (ThemeMode.LIGHT.value, lambda: self.tr("Light"), "sun"),
                (ThemeMode.DARK.value, lambda: self.tr("Dark"), "moon"),
            ]
        )
        self.theme_control.set_value(str(settings.get("theme")))
        self.theme_control.selected.connect(lambda value: settings.set("theme", value))
        appearance.addWidget(
            SettingRow(
                lambda: self.tr("Theme"),
                lambda: self.tr(
                    "“System” follows the Plasma color scheme and accent color."
                ),
                self.theme_control,
            )
        )

        profiles = self._group(lambda: self.tr("Profiles"))
        self.view_control = SegmentedControl(
            [
                ("grid", lambda: self.tr("Grid"), "grid"),
                ("list", lambda: self.tr("List"), "list"),
            ]
        )
        self.view_control.set_value(str(settings.get("profiles_view")))
        self.view_control.selected.connect(
            lambda value: settings.set("profiles_view", value)
        )
        profiles.addWidget(
            SettingRow(
                lambda: self.tr("Default view"),
                lambda: self.tr("How the Profiles page is shown."),
                self.view_control,
            )
        )
        self.folder_edit = QLineEdit(PROFILES_FOLDER)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setMinimumWidth(260)
        i18n.bind(
            self.folder_edit,
            lambda: self.folder_edit.setAccessibleName(self.tr("Profiles folder")),
        )
        profiles.addWidget(
            SettingRow(
                lambda: self.tr("Profiles folder"),
                lambda: self.tr("Read-only in this version."),
                self.folder_edit,
            )
        )

        safety = self._group(lambda: self.tr("Safety copies"))
        self.copies_button = Button(lambda: self.tr("Manage…"), icon_name="clock")
        self.copies_button.clicked.connect(self.open_safety_copies)
        safety.addWidget(
            SettingRow(
                lambda: self.tr("Before applying or importing"),
                lambda: self.tr(
                    "The files that would be overwritten are copied first. "
                    "Restore or delete the copies here; they are never deleted "
                    "automatically."
                ),
                self.copies_button,
            )
        )
        self._copies_dialog: Optional[SafetyCopiesDialog] = None

        notifications = self._group(lambda: self.tr("Notifications"))
        self.seconds_spin = QSpinBox()
        self.seconds_spin.setRange(1, 60)
        self.seconds_spin.setSuffix(" s")
        self.seconds_spin.setValue(int(settings.get("toast_seconds")))  # type: ignore[call-overload]
        i18n.bind(
            self.seconds_spin,
            lambda: self.seconds_spin.setAccessibleName(
                self.tr("Notification duration")
            ),
        )
        self.seconds_spin.valueChanged.connect(
            lambda value: settings.set("toast_seconds", value)
        )
        notifications.addWidget(
            SettingRow(
                lambda: self.tr("Duration"),
                lambda: self.tr("How long each notice stays on screen."),
                self.seconds_spin,
            )
        )
        self.test_button = Button(lambda: self.tr("Test"), icon_name="info")
        self.test_button.clicked.connect(
            lambda: ctx.toasts.show_message(
                "info",
                self.tr("Test notification"),
                self.tr("This is how notices appear."),
            )
        )
        notifications.addWidget(
            SettingRow(
                lambda: self.tr("Preview"),
                lambda: self.tr("Shows an example notice."),
                self.test_button,
            )
        )

        self.clear_button = None
        self.reset_button = None
        if ctx.backend.capabilities.demo:
            self._build_demo()
        self.body.addStretch(1)

        settings.changed.connect(self._on_setting_changed)

    def _group(self, title: Text) -> QVBoxLayout:
        """Adds a titled card to the page and returns its layout."""
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(4)
        layout.addWidget(self.section_title(title))
        layout.addWidget(Separator())
        self.body.addWidget(card)
        return layout

    def _on_setting_changed(self, key: str) -> None:
        """Keeps the controls in sync when a setting changes elsewhere."""
        value = self.ctx.settings.get(key)
        if key == "theme":
            self.theme_control.set_value(str(value))
        elif key == "profiles_view":
            self.view_control.set_value(str(value))
        elif key == "toast_seconds":
            self.seconds_spin.setValue(int(value))  # type: ignore[call-overload]
        elif key == "language":
            self.language_control.set_value(effective_language(value))

    def _build_demo(self) -> None:
        """Adds the demonstration-data group (demo backend only)."""
        demo = self._group(lambda: self.tr("Demo data"))
        self.clear_button = Button(
            lambda: self.tr("Empty profiles"), variant="danger", icon_name="trash"
        )
        self.clear_button.clicked.connect(self._clear_profiles)
        self.reset_button = Button(
            lambda: self.tr("Restore fictitious profiles"), icon_name="refresh"
        )
        self.reset_button.clicked.connect(self._reset_profiles)
        demo.addWidget(
            SettingRow(
                lambda: self.tr("Empty list"),
                lambda: self.tr(
                    "Removes all fictitious profiles to show the empty states."
                ),
                self.clear_button,
            )
        )
        demo.addWidget(
            SettingRow(
                lambda: self.tr("Original data"),
                lambda: self.tr("Goes back to the seven example profiles."),
                self.reset_button,
            )
        )

    def build_safety_copies_dialog(self) -> SafetyCopiesDialog:
        """Creates the dialog of safety copies, wired and loading its list.

        Returns:
            SafetyCopiesDialog: Not shown yet (:meth:`open_safety_copies` does).
        """
        actions = ProfileActions(self.ctx)
        dialog = SafetyCopiesDialog(
            self.window(),
            lambda copy: actions.restore_backup(dialog, copy),
            lambda copy: actions.delete_backup(dialog, copy),
        )
        self._copies_dialog = dialog
        controller = self.ctx.controller

        def sync_busy() -> None:
            dialog.set_busy(controller.busy)

        def finished(outcome: Outcome) -> None:
            if outcome.operation in ("restore_backup", "delete_backup"):
                self.reload_safety_copies()

        controller.state_changed.connect(sync_busy)
        controller.operation_finished.connect(finished)

        def forget() -> None:
            controller.state_changed.disconnect(sync_busy)
            controller.operation_finished.disconnect(finished)
            if self._copies_dialog is dialog:
                self._copies_dialog = None

        dialog.finished.connect(lambda _code: forget())
        sync_busy()
        self.reload_safety_copies()
        return dialog

    def reload_safety_copies(self) -> None:
        """Reads the list of copies in the background and shows it."""
        dialog = self._copies_dialog
        if dialog is None:
            return

        def shown(copies, error: Optional[BaseException]) -> None:
            if self._copies_dialog is not dialog:
                return
            if error is not None:
                dialog.set_error(messages.describe_error(error))
            else:
                dialog.set_copies(copies)

        self.ctx.controller.background(self.ctx.backend.list_backups, shown)

    def open_safety_copies(self) -> None:
        """Shows the safety copies (blocks until the dialog is closed)."""
        self.build_safety_copies_dialog().exec()

    def _clear_profiles(self) -> None:
        """Empties the fictitious list after explicit confirmation."""
        ProfileActions(self.ctx).wipe_all(self.window())

    def _reset_profiles(self) -> None:
        """Restores the fictitious profiles."""
        self.ctx.controller.demo_reset()

    def header_actions(self) -> List:
        """Settings has no top-bar actions."""
        return []
