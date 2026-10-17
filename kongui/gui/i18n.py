"""Interface language: detection, loading of translations and live switching.

The source language of every text in the code is English. Translations are Qt
``.ts`` files (``translations/kongui_<lang>.ts``) compiled to ``.qm`` and loaded
with :class:`~PySide6.QtCore.QTranslator`. A text without a translation shows the
English source, which is the fallback for every language.

Choosing the language:

* The user's explicit choice (``AppSettings`` key ``language``) always wins.
* Without a choice (empty value) the system locale decides, and the detected
  language is **never** written to the settings: ``pt_BR`` selects Brazilian
  Portuguese, anything else (``pt_PT``, ``pt``, ``C``, ``de_DE`` ...) selects English.

Switching is live. Installing or removing a translator makes Qt send
``QEvent.LanguageChange`` to every widget; widgets that show translatable text
register a function with :func:`bind` (or use the text-or-callable support of
``Label``, ``Badge`` and ``Button``) and are refreshed without being recreated, so
the current page and any typed data stay untouched.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Union

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QLibraryInfo,
    QLocale,
    QObject,
    QTranslator,
    Signal,
)
from PySide6.QtWidgets import QApplication

#: Languages the interface offers: code -> name shown in the selector. Each name is
#: written in its own language and is never translated.
SUPPORTED: Dict[str, str] = {"en": "English", "pt_BR": "Português (Brasil)"}
#: Language used when nothing else applies; also the language of the source texts.
DEFAULT_LANGUAGE = "en"
#: Value of the ``language`` setting while the user has not chosen.
NO_PREFERENCE = ""

TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), "translations")

#: A text, or a function that returns the text in the current language.
Text = Union[str, Callable[[], str]]


def resolve_text(text: Text) -> str:
    """Returns the string of a :data:`Text`.

    Args:
        text: A plain string or a zero-argument function returning one.

    Returns:
        str: The text in the language in use at this moment.
    """
    return text() if callable(text) else text


def system_locale_name() -> str:
    """Returns the system locale name, for example ``pt_BR`` or ``en_US``."""
    return QLocale.system().name()


def detect_language(locale_name: Optional[str] = None) -> str:
    """Chooses a supported language for a system locale.

    Only the exact locale ``pt_BR`` selects Portuguese; every other locale, even
    ``pt_PT`` or ``pt``, selects English.

    Args:
        locale_name: Locale to look at; the system locale when omitted.

    Returns:
        str: A key of :data:`SUPPORTED`.
    """
    name = system_locale_name() if locale_name is None else locale_name
    return "pt_BR" if name.split(".")[0].split("@")[0] == "pt_BR" else DEFAULT_LANGUAGE


def normalize_preference(value: object) -> str:
    """Cleans a stored ``language`` value.

    Args:
        value: What was read from the settings.

    Returns:
        str: A key of :data:`SUPPORTED`, or :data:`NO_PREFERENCE` for anything else.
    """
    text = str(value) if value is not None else ""
    return text if text in SUPPORTED else NO_PREFERENCE


def effective_language(preference: object) -> str:
    """Resolves the language to use.

    Args:
        preference: The ``language`` setting (may be empty or invalid).

    Returns:
        str: The saved choice when valid, otherwise the detected language.
    """
    saved = normalize_preference(preference)
    return saved or detect_language()


def translation_path(language: str) -> str:
    """Returns the path of the compiled translation of a language."""
    return os.path.join(TRANSLATIONS_DIR, f"kongui_{language}.qm")


class LanguageManager(QObject):
    """Loads the translators of the running application and announces changes.

    There is one per process (:func:`manager`), because Qt translators belong to
    the application.

    Signals:
        language_changed: Emitted with the new language code after the translators
            were replaced and the widgets received ``LanguageChange``.
    """

    language_changed = Signal(str)

    def __init__(self) -> None:
        """Creates the manager with no translator installed."""
        super().__init__()
        self._language = DEFAULT_LANGUAGE
        self._installed = False
        self._translators: List[QTranslator] = []
        self._settings: Optional[QObject] = None

    @property
    def language(self) -> str:
        """The language code in use."""
        return self._language

    def install(self, language: str) -> str:
        """Makes a language the one in use.

        An unknown language falls back to English. A missing or unreadable ``.qm``
        file leaves the English source texts in place; it never raises.

        Args:
            language: A key of :data:`SUPPORTED`.

        Returns:
            str: The language actually applied.
        """
        language = language if language in SUPPORTED else DEFAULT_LANGUAGE
        if self._installed and language == self._language:
            return language
        self._remove_translators()
        for translator in self._load_translators(language):
            QCoreApplication.installTranslator(translator)
            self._translators.append(translator)
        QLocale.setDefault(QLocale(language))
        self._language = language
        self._installed = True
        self._broadcast()
        self.language_changed.emit(language)
        return language

    def uninstall(self) -> None:
        """Removes every translator and goes back to the English source texts."""
        self._remove_translators()
        QLocale.setDefault(QLocale(DEFAULT_LANGUAGE))
        self._language = DEFAULT_LANGUAGE
        self._installed = False
        self._broadcast()

    def apply_preference(self, preference: object) -> str:
        """Installs the language that a stored preference resolves to.

        Args:
            preference: The ``language`` setting.

        Returns:
            str: The language applied.
        """
        return self.install(effective_language(preference))

    def follow(self, settings: QObject) -> None:
        """Applies the ``language`` setting now and whenever it changes.

        Only one settings object is followed at a time.

        Args:
            settings: An ``AppSettings`` (``get`` and ``changed(str)``).
        """
        if self._settings is not None:
            try:
                self._settings.changed.disconnect(self._on_setting)  # type: ignore[attr-defined]
            except (RuntimeError, TypeError):
                pass
        self._settings = settings
        settings.changed.connect(self._on_setting)  # type: ignore[attr-defined]
        self.apply_preference(settings.get("language"))  # type: ignore[attr-defined]

    def _on_setting(self, key: str) -> None:
        """Reacts to a changed setting."""
        if key == "language" and self._settings is not None:
            self.apply_preference(self._settings.get("language"))  # type: ignore[attr-defined]

    def _remove_translators(self) -> None:
        """Removes the installed translators."""
        for translator in self._translators:
            QCoreApplication.removeTranslator(translator)
        self._translators = []

    @staticmethod
    def _load_translators(language: str) -> List[QTranslator]:
        """Loads the KonGUI translator and Qt's own one for a language.

        Qt's file translates what Qt itself shows (standard buttons of the file
        dialog, for example). Files that do not exist are skipped.
        """
        loaded: List[QTranslator] = []
        own = QTranslator()
        if own.load(translation_path(language)):
            loaded.append(own)
        if language != DEFAULT_LANGUAGE:
            qt_own = QTranslator()
            qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if qt_own.load(f"qtbase_{language}", qt_dir):
                loaded.append(qt_own)
        return loaded

    @staticmethod
    def _broadcast() -> None:
        """Sends ``LanguageChange`` to every top-level widget and its children.

        Qt does not reliably deliver the application-wide event to hidden or
        not yet shown windows, and sends nothing when no translator changed
        (English without a file), so the event is sent explicitly. Widgets
        pass it on to their children.
        """
        app = QCoreApplication.instance()
        if app is None:
            return
        for widget in QApplication.topLevelWidgets():
            QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.LanguageChange))


_MANAGER: Optional[LanguageManager] = None


def manager() -> LanguageManager:
    """Returns the process-wide :class:`LanguageManager`."""
    global _MANAGER  # pylint: disable=global-statement
    if _MANAGER is None:
        _MANAGER = LanguageManager()
    return _MANAGER


def current() -> str:
    """Returns the language code in use."""
    return manager().language


class _Binding(QObject):
    """Runs a function whenever its owner receives ``LanguageChange``."""

    def __init__(self, owner: QObject, apply: Callable[[], None]) -> None:
        """Creates the binding and attaches it to ``owner``."""
        super().__init__(owner)
        self._apply = apply
        owner.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Calls the function on ``LanguageChange``; never swallows the event."""
        if event.type() == QEvent.Type.LanguageChange:
            self._apply()
        return super().eventFilter(watched, event)


def bind(owner: QObject, apply: Callable[[], None], *, now: bool = True) -> None:
    """Refreshes translatable text of ``owner`` when the language changes.

    Args:
        owner: The widget (or object) that shows the text. The binding lives and
            dies with it.
        apply: Function that sets the texts again, using the current language.
        now: Also call ``apply`` right away.
    """
    _Binding(owner, apply)
    if now:
        apply()
