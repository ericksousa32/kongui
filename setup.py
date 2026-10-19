"""Setup module"""

from pathlib import Path
from typing import List

from setuptools import setup, find_packages


def _read_desc() -> str:
    """Reads the README.md.

    Returns:
        str: Contents of README.md file.
    """
    with open("README.md", "r", encoding="utf-8") as desc:
        return desc.read()


def _read_reqs(path: Path) -> List[str]:
    """Reads a pip requirement file.

    Args:
        path (Path): Path to pip requirements file.

    Returns:
        :type: list of str: List of dependency identifiers.
    """
    with open(path, "r", encoding="utf-8") as file:
        return file.readlines()


# Package requirements
_REQUIREMENTS: List[str] = _read_reqs(Path("requirements.txt"))
_REQUIREMENTS_DEV: List[str] = _read_reqs(Path("requirements_dev.txt"))

setup(
    name="kongui",
    # The version comes from the git tag; setuptools_scm is a build requirement
    # declared in pyproject.toml.
    use_scm_version=True,
    author="KonGUI contributors (Konsave by Prayag Jain)",
    description="A graphical interface for managing KDE Plasma configuration profiles, "
    "built on a fork of Konsave.",
    long_description=_read_desc(),
    long_description_content_type="text/markdown",
    url="https://github.com/ericksousa32/kongui",
    project_urls={
        "Source": "https://github.com/ericksousa32/kongui",
        "Issues": "https://github.com/ericksousa32/kongui/issues",
        "Upstream (Konsave)": "https://github.com/Prayag2/konsave",
    },
    license="GPL-3.0-or-later",
    packages=find_packages(exclude=["tests", "tests.*"]),
    package_data={
        "config": ["conf.yaml"],
        # Interface translations: sources (.ts) and compiled catalogs (.qm).
        "kongui.gui": ["translations/*.qm", "translations/*.ts"],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=_REQUIREMENTS,
    extras_require={
        "dev": _REQUIREMENTS_DEV,
        "gui": [
            # PySide6 6.10 and newer crash the interpreter on Python older than 3.12
            # (a segmentation fault, or an abort at exit); 6.8 and 6.9 pass the whole
            # test suite there. See docs/LIMITATIONS.md.
            "PySide6>=6.8,<6.10; python_version < '3.12'",
            "PySide6>=6.8; python_version >= '3.12'",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Development Status :: 3 - Alpha",
        "Operating System :: POSIX :: Linux",
        "Environment :: X11 Applications :: Qt",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3",
    ],
    entry_points={
        "console_scripts": [
            "konsave = konsave.__main__:main",
            "kongui = kongui.gui.app:main",
        ]
    },
)
