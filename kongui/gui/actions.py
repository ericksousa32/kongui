"""Profile actions shared by several pages.

They only change the in-memory models. Every message says so, to avoid any
doubt that the system was modified.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import QDialog, QWidget

from kongui.gui.context import AppContext
from kongui.gui.mock_data import SECTIONS
from kongui.gui.state import Profile
from kongui.gui.widgets.dialogs import ConfirmDialog, ProfileDialog

SIMULATED = "Simulação: nada foi alterado no sistema."


class ProfileActions:
    """Create, apply, duplicate and remove profiles in the fictitious store."""

    def __init__(self, ctx: AppContext) -> None:
        """Creates the helper.

        Args:
            ctx: Shared services.
        """
        self.ctx = ctx

    def save_current(self, parent: QWidget) -> Optional[Profile]:
        """Asks for details and adds a profile.

        Args:
            parent: Window used as dialog parent.

        Returns:
            Optional[Profile]: The new profile, or ``None`` if cancelled.
        """
        dialog = ProfileDialog(parent, self.ctx.store.names(), SECTIONS)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return self.create(*dialog.values())

    def create(self, name: str, description: str, sections: tuple) -> Profile:
        """Adds a profile with an invented size.

        Args:
            name: Profile name.
            description: Description text.
            sections: Included sections.

        Returns:
            Profile: The new profile.
        """
        profile = Profile(
            name,
            description or "Sem descrição.",
            sections,
            round(4.0 + 7.3 * len(sections), 1),
            datetime.now(),
        )
        self.ctx.store.add(profile)
        self.ctx.activity.add("save", f"Perfil “{name}” criado")
        self.ctx.toasts.show_message("success", f"Perfil “{name}” salvo", SIMULATED)
        return profile

    def apply(self, parent: QWidget, name: str) -> bool:
        """Applies a profile after the optional confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Profile name.

        Returns:
            bool: Whether the profile was applied.
        """
        if self.ctx.settings.get("confirm_apply") and not ConfirmDialog.ask(
            parent,
            f"Aplicar “{name}”?",
            "A aparência e as configurações atuais serão substituídas pelas deste perfil. "
            "Salve o estado atual antes se quiser poder voltar. (Protótipo: nada será alterado.)",
            "Aplicar",
        ):
            return False
        self.ctx.store.activate(name)
        self.ctx.activity.add("apply", f"Perfil “{name}” aplicado")
        self.ctx.toasts.show_message("success", f"Perfil “{name}” aplicado", SIMULATED)
        return True

    def duplicate(self, name: str) -> Profile:
        """Duplicates a profile.

        Args:
            name: Profile to copy.

        Returns:
            Profile: The copy.
        """
        copy = self.ctx.store.duplicate(name)
        self.ctx.activity.add("save", f"Perfil “{name}” duplicado como “{copy.name}”")
        self.ctx.toasts.show_message("info", f"Criado “{copy.name}”", SIMULATED)
        return copy

    def remove(self, parent: QWidget, name: str) -> bool:
        """Removes a profile after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Profile name.

        Returns:
            bool: Whether the profile was removed.
        """
        if not ConfirmDialog.ask(
            parent,
            f"Remover “{name}”?",
            "O perfil será apagado e não poderá ser recuperado. (Protótipo: apenas a lista "
            "fictícia é alterada.)",
            "Remover",
            destructive=True,
        ):
            return False
        self.ctx.store.remove(name)
        self.ctx.activity.add("remove", f"Perfil “{name}” removido")
        self.ctx.toasts.show_message("warning", f"Perfil “{name}” removido", SIMULATED)
        return True
