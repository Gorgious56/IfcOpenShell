# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.
#
# This file was generated with the assistance of an AI coding tool.

"""Module-registration completeness for ``bonsai.bim``.

Adding a feature module under ``bim/module/<name>/`` without an entry in
``bim/__init__.py``'s ``modules`` dict silently skips it — the addon enables
cleanly, the operators / panels / handlers never register, and the UI just
doesn't show up. The reciprocal failure (dict key with no folder) crashes
addon enable with an opaque ``ModuleNotFoundError``. Both are caught here."""

import pathlib

import pytest

pytestmark = pytest.mark.model


# Folders intentionally absent from the modules dict — typically opt-in
# scaffolding kept around but not loaded by default. Update only when the
# corresponding entry is also commented out in ``bim/__init__.py``.
_OPT_OUT_FOLDERS: frozenset[str] = frozenset({"demo"})


def _module_folders() -> set[str]:
    """Subfolders of ``bonsai/bim/module/`` that are real Python packages."""
    import bonsai.bim

    module_root = pathlib.Path(bonsai.bim.__file__).parent / "module"
    return {
        p.name
        for p in module_root.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "__init__.py").exists()
    }


def test_every_module_folder_is_in_modules_dict():
    """A folder under ``bim/module/`` with no matching dict entry is dead
    code from the addon's perspective. Most often the symptom is "I added
    the feature but the panel doesn't show" — there is no error to find."""
    import bonsai.bim

    folders = _module_folders()
    registered = set(bonsai.bim.modules.keys())
    missing = (folders - registered) - _OPT_OUT_FOLDERS
    assert not missing, (
        f"bim/module/ folders without an entry in bim/__init__.py's modules dict: "
        f'{sorted(missing)} — add ``"<name>": None,`` to the dict, or include '
        f"the name in _OPT_OUT_FOLDERS if it's intentionally not loaded."
    )


def test_every_modules_dict_key_has_a_folder():
    """A dict key pointing to a deleted folder crashes addon enable with
    ``ModuleNotFoundError``. The addon-enable loop runs before any other
    test would catch it, so an in-progress branch with a stale key won't
    even reach CI's smoke tests."""
    import bonsai.bim

    folders = _module_folders()
    registered = set(bonsai.bim.modules.keys())
    stale = registered - folders
    assert not stale, (
        f"bim/__init__.py modules dict has keys with no matching bim/module/ "
        f"folder: {sorted(stale)} — remove the stale key or restore the folder."
    )


def test_every_registered_module_was_imported_successfully():
    """The import loop at the end of ``bim/__init__.py`` populates the dict
    values via ``importlib.import_module``. A None value here means the
    loop ran but assignment did not — typically a stub left after a
    partial refactor."""
    import bonsai.bim

    not_imported = [name for name, mod in bonsai.bim.modules.items() if mod is None]
    assert not not_imported, (
        f"modules dict entries never assigned an imported module: {not_imported} — "
        f"the import loop at the end of bim/__init__.py must run."
    )
