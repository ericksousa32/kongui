"""User actions on profiles: ask first, then call the controller.

* :class:`ProfileActions` opens the dialogs (name, confirmation) and starts the
  operation. Destructive operations are *never* started without the user
  pressing the confirm button; the controller refuses them otherwise.
* :class:`OutcomeNotifier` turns every finished operation into a notification
  and an activity entry. It exists once per window.
"""

from __future__ import annotations


from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QWidget

from kongui.gui.context import AppContext
from kongui.gui.controller import Outcome
from kongui.gui.mock_data import SECTIONS
from kongui.gui.widgets.dialogs import ConfirmDialog, ProfileDialog

SIMULATED = "Simulação: nada foi alterado no sistema."
#: Word the user must type to wipe every profile.
WIPE_WORD = "APAGAR"

_ACTIVITY_KIND = {
    "save": "save",
    "overwrite": "save",
    "duplicate": "save",
    "apply": "apply",
    "remove": "remove",
    "wipe_all": "remove",
    "import": "import",
    "export": "export",
}


class ProfileActions:
    """Dialogs plus controller calls for each profile operation."""

    def __init__(self, ctx: AppContext) -> None:
        """Creates the helper.

        Args:
            ctx: Shared services.
        """
        self.ctx = ctx

    @property
    def _demo(self) -> bool:
        """Whether the fictitious backend is in use."""
        return self.ctx.backend.capabilities.demo

    def _dispatched(self, started: bool) -> bool:
        """Tells the user when an operation could not start."""
        if not started:
            self.ctx.toasts.show_message(
                "info", "Aguarde", "Outra operação ainda está em andamento."
            )
        return started

    def save_current(self, parent: QWidget) -> bool:
        """Asks for a name and saves the current configuration as a new profile.

        Args:
            parent: Window used as dialog parent.

        Returns:
            bool: Whether an operation was started.
        """
        caps = self.ctx.backend.capabilities
        dialog = ProfileDialog(
            parent, self.ctx.store.names(), SECTIONS, ask_details=caps.descriptions
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        name, description, sections = dialog.values()
        return self._dispatched(self.ctx.controller.save(name, description, sections))

    def overwrite(self, parent: QWidget, name: str) -> bool:
        """Replaces a profile with the current configuration, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            f"Sobrescrever “{name}”?",
            "O perfil será substituído pela configuração atual do Plasma. O conteúdo "
            "antigo é perdido e não há desfazer."
            + (" (Protótipo: nada será alterado.)" if self._demo else ""),
            "Sobrescrever",
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.overwrite(name, confirmed=True))

    def apply(self, parent: QWidget, name: str) -> bool:
        """Applies a profile to the session, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            f"Aplicar “{name}”?",
            "Os arquivos de configuração atuais serão substituídos pelos deste perfil, "
            "sem backup (ainda não existe). Salve o estado atual antes se quiser "
            "poder voltar."
            + (" (Protótipo: nada será alterado.)" if self._demo else ""),
            "Aplicar",
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.apply(name, confirmed=True))

    def remove(self, parent: QWidget, name: str) -> bool:
        """Removes a profile, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            f"Remover “{name}”?",
            "O perfil será apagado e não poderá ser recuperado."
            + (" (Protótipo: apenas a lista fictícia muda.)" if self._demo else ""),
            "Remover",
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.remove(name, confirmed=True))

    def wipe_all(self, parent: QWidget) -> bool:
        """Removes every profile; the user must type :data:`WIPE_WORD`.

        Args:
            parent: Window used as dialog parent.

        Returns:
            bool: Whether an operation was started.
        """
        count = len(self.ctx.store.names())
        if not ConfirmDialog.ask(
            parent,
            "Limpar todos os perfis?",
            f"Os {count} perfis salvos serão apagados e não poderão ser recuperados. "
            "O conf.yaml do Konsave é mantido."
            + (" (Protótipo: apenas a lista fictícia muda.)" if self._demo else ""),
            "Limpar tudo",
            destructive=True,
            require_text=WIPE_WORD,
        ):
            return False
        return self._dispatched(self.ctx.controller.wipe_all(confirmed=True))

    def duplicate(self, name: str) -> bool:
        """Duplicates a profile (demo backend only).

        Args:
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        return self._dispatched(self.ctx.controller.duplicate(name))


class OutcomeNotifier(QObject):
    """Shows a notification and logs an activity for each finished operation."""

    def __init__(self, ctx: AppContext) -> None:
        """Connects to the controller.

        Args:
            ctx: Shared services.
        """
        super().__init__()
        self.ctx = ctx
        ctx.controller.operation_finished.connect(self.on_finished)

    def on_finished(self, outcome: Outcome) -> None:
        """Reports an outcome.

        Args:
            outcome: What happened.
        """
        demo = self.ctx.backend.capabilities.demo
        if outcome.operation == "list":
            # A failed listing is shown inside the page, with a retry button.
            return
        details = list(outcome.details)
        if outcome.ok and demo:
            details.append(SIMULATED)
        text = "\n".join(details)
        if outcome.ok:
            kind = (
                "warning" if outcome.operation in ("remove", "wipe_all") else "success"
            )
            self.ctx.toasts.show_message(kind, outcome.title, text)
            activity = _ACTIVITY_KIND.get(outcome.operation)
            if activity:
                self.ctx.activity.add(activity, outcome.title)
        else:
            self.ctx.toasts.show_message("error", outcome.title, text, seconds=0)


__all__ = ["ProfileActions", "OutcomeNotifier", "SIMULATED", "WIPE_WORD"]
