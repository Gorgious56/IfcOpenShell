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

"""Pin the contract that ``preview_base.discard_pending_previews`` clears
every active preview, and that the IFC save operator dispatches it next to
the existing parametric-edit auto-commit step.

The Scene-level preview PropertyGroup is part of the ``.blend`` file. Without
a save-time discard, a session saved while a preview was active would persist
the ``is_active`` flag; on next file open the sibling gizmo polls gated on
it would silently hide with no UI cue for the user to recover."""

import ast
import inspect
import pathlib

import bpy
import pytest

from bonsai.bim.module.model import preview_base
from bonsai.bim.module.project import operator as project_operator

pytestmark = pytest.mark.model


def _set_all_previews_active() -> None:
    umbrella = bpy.context.scene.BIMPreviewProperties
    for attr, _op_name in preview_base.PREVIEW_CANCEL_OPS:
        getattr(umbrella, attr).is_active = True


def test_discard_pending_previews_clears_every_active_child():
    """Every registered preview's ``is_active`` flag must drop to ``False``
    after the discard helper runs — regardless of which previews were
    active at call time."""
    _set_all_previews_active()

    preview_base.discard_pending_previews(bpy.context.scene)

    umbrella = bpy.context.scene.BIMPreviewProperties
    for attr, _op_name in preview_base.PREVIEW_CANCEL_OPS:
        assert getattr(umbrella, attr).is_active is False, (
            f"BIMPreviewProperties.{attr}.is_active was not cleared by " f"discard_pending_previews."
        )


def test_discard_pending_previews_is_idempotent_when_nothing_is_active():
    """Calling the helper with no preview active must not raise and must
    leave the umbrella state untouched."""
    umbrella = bpy.context.scene.BIMPreviewProperties
    for attr, _op_name in preview_base.PREVIEW_CANCEL_OPS:
        getattr(umbrella, attr).is_active = False

    preview_base.discard_pending_previews(bpy.context.scene)

    for attr, _op_name in preview_base.PREVIEW_CANCEL_OPS:
        assert getattr(umbrella, attr).is_active is False


def test_ifc_save_operator_dispatches_preview_discard():
    """The IFC save operator's ``_execute`` must call
    ``preview_base.discard_pending_previews`` — paired with the existing
    ``commit_pending_edits`` auto-commit so previews are discarded at the
    same save-flow hook that validates parametric object edits.

    Asserted via AST inspection rather than a live save round-trip: the
    save operator does a full IFC export, far too heavy to exercise from
    a unit test."""
    source = inspect.getsource(project_operator.ExportIFC._execute)
    tree = ast.parse(source.strip().splitlines()[0] + "\n" + "\n".join(source.splitlines()[1:]))

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    names = {f"{call.func.value.id}.{call.func.attr}" for call in calls if isinstance(call.func.value, ast.Name)}
    assert "preview_base.discard_pending_previews" in names, (
        "ExportIFC._execute must call preview_base.discard_pending_previews "
        "next to commit_pending_edits so saving the IFC project also "
        f"discards any active preview. Calls found: {sorted(names)}"
    )
