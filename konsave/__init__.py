"""Top-level Konsave package."""

from importlib.metadata import distribution, PackageNotFoundError

try:
    __version__ = distribution(__name__).version
except PackageNotFoundError:
    # Package is not installed
    # KONGUI-PATCH(rename): this copy is distributed as "kongui", so the lookup
    # above finds nothing and konsave.consts could not be imported. Version of
    # the Konsave release the bundled code derives from.
    try:
        distribution("kongui")
        __version__ = "2.2.0+kongui"
    except PackageNotFoundError:
        pass
