"""Konsave entry point."""

import argparse
import os
import shutil
from importlib.resources import files

from konsave.consts import (
    CONFIG_FILE,
    KONSAVE_DIR,
    PROFILES_DIR,
    VERSION,
)
from konsave.funcs import (
    apply_profile,
    export,
    import_profile,
    list_profiles,
    remove_profile,
    save_profile,
    wipe,
)
from konsave.lock import EXCLUSIVE, SHARED, command_lock  # KONGUI-PATCH(lock)


def _get_parser() -> argparse.ArgumentParser:
    """Returns CLI parser.

    Returns:
        argparse.ArgumentParser: Created parser.
    """
    parser = argparse.ArgumentParser(
        prog="Konsave",
        description="A simple and powerful utility for managing your dotfiles.",
        epilog="Please report bugs at https://www.github.com/prayag2/konsave",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    # Profile Management Group
    profile_group = parser.add_argument_group(
        "Profile Management", "Commands for managing configuration profiles"
    )
    profile_group.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all saved profiles",
    )
    profile_group.add_argument(
        "-s",
        "--save",
        type=str,
        help="Save current configuration as a new profile",
        metavar="<name>",
    )
    profile_group.add_argument(
        "-a",
        "--apply",
        type=str,
        help="Apply a saved profile to restore its configuration",
        metavar="<name>",
    )
    profile_group.add_argument(
        "-r",
        "--remove",
        type=str,
        help="Delete a saved profile permanently",
        metavar="<name>",
    )
    profile_group.add_argument(
        "-w",
        "--wipe",
        action="store_true",
        help="Delete all saved profiles (use with caution!)",
    )

    # Import/Export Group
    transfer_group = parser.add_argument_group(
        "Import & Export",
        "Commands for sharing profiles with others",
    )
    transfer_group.add_argument(
        "-e",
        "--export-profile",
        type=str,
        help="Export a profile as a shareable .knsv archive file",
        metavar="<name>",
    )
    transfer_group.add_argument(
        "-i",
        "--import-profile",
        type=str,
        help="Import a profile from a .knsv archive file",
        metavar="<path>",
    )

    # Options Group
    options_group = parser.add_argument_group(
        "Options", "Additional options to modify command behavior"
    )
    options_group.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite when saving/exporting (skip confirmation prompts)",
    )
    options_group.add_argument(
        "-d",
        "--export-directory",
        help="Specify custom directory for exported profile (default: current directory)",
        metavar="<directory>",
    )
    options_group.add_argument(
        "-n",
        "--export-name",
        help="Specify custom filename for exported profile archive",
        metavar="<archive-name>",
    )

    # Miscellaneous Group
    misc_group = parser.add_argument_group("Miscellaneous", "Other utility commands")
    misc_group.add_argument(
        "-h", "--help", action="help", help="Show this help message and exit"
    )
    misc_group.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Display the current version of Konsave",
    )

    return parser


def _lock_request(args):  # KONGUI-PATCH(lock)
    """Returns ``(mode, operation)`` of the lock a command needs.

    ``mode`` is ``None`` for commands that touch no shared data.

    Args:
        args: Parsed command line.
    """
    # Same order as the if/elif chain in ``_run``: the first match runs.
    if args.list:
        return SHARED, "list"
    if args.save:
        return EXCLUSIVE, "save"
    if args.remove:
        return EXCLUSIVE, "remove"
    if args.apply:
        return EXCLUSIVE, "apply"
    if args.export_profile:
        return SHARED, "export"
    if args.import_profile:
        return EXCLUSIVE, "import"
    if args.version:
        return None, ""
    if args.wipe:
        return EXCLUSIVE, "wipe"
    return None, ""


def main():
    """The main function that handles all the arguments and options."""

    if not os.path.exists(CONFIG_FILE):
        # KONGUI-PATCH(lock): create the default configuration under the lock
        # and check again inside it (another process may have just done it).
        with command_lock(KONSAVE_DIR, EXCLUSIVE, "create the default configuration"):
            if not os.path.exists(CONFIG_FILE):
                if os.path.expandvars("$XDG_CURRENT_DESKTOP") == "KDE":
                    default_config_path = str(files("konsave") / "conf_kde.yaml")
                    shutil.copy(default_config_path, CONFIG_FILE)
                else:
                    default_config_path = str(files("konsave") / "conf_other.yaml")
                    shutil.copy(default_config_path, CONFIG_FILE)

    parser = _get_parser()
    args = parser.parse_args()

    # KONGUI-PATCH(lock): the command runs under a cross-process lock.
    mode, operation = _lock_request(args)
    with command_lock(KONSAVE_DIR, mode, operation):
        _run(parser, args)


def _run(parser, args):  # KONGUI-PATCH(lock): former body of main() after parsing
    """Runs the chosen command (unchanged from upstream apart from the list).

    Args:
        parser: The argument parser (used to print the help).
        args: Parsed command line.
    """
    # KONGUI-PATCH(lock): upstream reads this list when ``konsave.consts`` is
    # imported, i.e. *before* any waiting for the lock. Read it again now.
    list_of_profiles = os.listdir(PROFILES_DIR)
    length_of_lop = len(list_of_profiles)

    if args.list:
        list_profiles(list_of_profiles, length_of_lop)
    elif args.save:
        save_profile(args.save, list_of_profiles, force=args.force)
    elif args.remove:
        remove_profile(args.remove, list_of_profiles, length_of_lop)
    elif args.apply:
        apply_profile(args.apply, list_of_profiles, length_of_lop)
    elif args.export_profile:
        export(
            args.export_profile,
            list_of_profiles,
            length_of_lop,
            args.export_directory,
            args.export_name,
            args.force,
        )
    elif args.import_profile:
        import_profile(args.import_profile)
    elif args.version:
        print(f"Konsave: {VERSION}")
    elif args.wipe:
        wipe()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
