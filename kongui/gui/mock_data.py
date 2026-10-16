"""Fictitious data for the visual prototype.

Everything here is invented. No file is read and Konsave is never called.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from kongui.gui.state import ActivityEntry, Profile

#: Configuration areas offered when saving a profile.
SECTIONS = (
    "Plasma (painéis e widgets)",
    "Atalhos de teclado",
    "Ícones e cursores",
    "Temas de aplicativos",
    "Fontes",
    "Papel de parede",
    "Konsole e Dolphin",
)


def demo_profiles() -> List[Profile]:
    """Returns the fictitious profiles.

    Returns:
        List[Profile]: Seven profiles; ``Trabalho`` is the active one.
    """
    now = datetime.now()
    day = timedelta(days=1)
    return [
        Profile(
            "Trabalho",
            "Painel único, tema escuro e atalhos para janelas lado a lado.",
            SECTIONS[:5],
            48.2,
            now - 2 * day,
            active=True,
        ),
        Profile(
            "Minimalista",
            "Sem widgets, ícones monocromáticos e papel de parede liso.",
            (SECTIONS[0], SECTIONS[2], SECTIONS[5]),
            12.7,
            now - 9 * day,
        ),
        Profile(
            "Gaming",
            "Efeitos desativados e painel flutuante.",
            (SECTIONS[0], SECTIONS[1], SECTIONS[3]),
            31.5,
            now - 21 * day,
        ),
        Profile(
            "Apresentação",
            "Fontes grandes e alto contraste para projetor.",
            (SECTIONS[2], SECTIONS[4]),
            9.1,
            now - 45 * day,
        ),
        Profile(
            "Retrô",
            "Visual clássico com barra de tarefas inferior.",
            SECTIONS,
            76.9,
            now - 120 * day,
        ),
        Profile(
            "Noturno",
            "Cores quentes e brilho reduzido.",
            (SECTIONS[0], SECTIONS[3], SECTIONS[5]),
            22.4,
            now - 200 * day,
        ),
        Profile(
            "Tablet",
            "Alvos de toque maiores e painel lateral.",
            (SECTIONS[0], SECTIONS[1], SECTIONS[6]),
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
        ActivityEntry(now - timedelta(hours=3), "apply", "Perfil “Trabalho” aplicado"),
        ActivityEntry(now - timedelta(days=2), "save", "Perfil “Trabalho” atualizado"),
        ActivityEntry(
            now - timedelta(days=5),
            "export",
            "“Minimalista” exportado para ~/Downloads",
        ),
        ActivityEntry(
            now - timedelta(days=9), "import", "“Gaming” importado de gaming.knsv"
        ),
        ActivityEntry(now - timedelta(days=21), "save", "Perfil “Apresentação” criado"),
        ActivityEntry(now - timedelta(days=45), "remove", "Perfil “Teste” removido"),
    ]
