"""KonGUI: graphical front end for Konsave.

The version is not written here: it is the version of the installed ``kongui``
package, which comes from the git tag (``setuptools_scm``). A checkout that was
never installed has no such version and reports :data:`UNKNOWN_VERSION`.
"""

from importlib.metadata import PackageNotFoundError, version

#: Reported when ``kongui`` is not installed as a package (a plain checkout).
UNKNOWN_VERSION = "0+unknown"

try:
    __version__ = version("kongui")
except PackageNotFoundError:
    __version__ = UNKNOWN_VERSION


def short_version() -> str:
    """Returns the version without its "local" part, for narrow places.

    A build between two tags looks like ``0.1.0a2.dev3+g1a2b3c4.d20261018``; the
    part after ``+`` says which commit and whether files were modified, and is only
    useful in full on the *About* page.

    Returns:
        str: For example ``0.1.0a2.dev3``, or ``""`` if the version is unknown.
    """
    if __version__ == UNKNOWN_VERSION:
        return ""
    return __version__.split("+", 1)[0]


def version_label() -> str:
    """Returns the short text the interface shows next to the name.

    Returns:
        str: ``v0.1.0a1`` for a known version, ``dev`` when it is unknown.
    """
    short = short_version()
    return f"v{short}" if short else "dev"
