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

"""Forward-compat guard pinning the parity between
``Scene.BIMPreviewProperties`` and ``preview_base.PREVIEW_CANCEL_OPS``.

Adding a new preview to the umbrella PropertyGroup without wiring an Esc
entry would silently leave that preview uncancellable via the keyboard.
This file fails CI in that scenario so the next preview author is forced
to land the registry entry in the same change."""

import bpy
import pytest

from bonsai.bim.module.model import preview_base

pytestmark = pytest.mark.model


def test_every_preview_with_is_active_has_cancel_entry():
    """For every child PropertyGroup on ``Scene.BIMPreviewProperties`` that
    declares an ``is_active`` flag, ``PREVIEW_CANCEL_OPS`` must carry a
    matching ``(attr, op_name)`` whose operator resolves on
    ``bpy.ops.bim``."""
    umbrella = bpy.context.scene.BIMPreviewProperties
    registry = dict(preview_base.PREVIEW_CANCEL_OPS)

    missing = []
    unresolved = []
    for attr in umbrella.bl_rna.properties.keys():
        child = getattr(umbrella, attr, None)
        if child is None or not hasattr(child, "is_active"):
            continue
        if attr not in registry:
            missing.append(attr)
            continue
        if not hasattr(bpy.ops.bim, registry[attr]):
            unresolved.append((attr, registry[attr]))

    assert not missing, (
        f"BIMPreviewProperties children {missing} have 'is_active' but no entry in "
        f"preview_base.PREVIEW_CANCEL_OPS — Esc will not cancel them."
    )
    assert not unresolved, (
        f"PREVIEW_CANCEL_OPS entries {unresolved} do not resolve via bpy.ops.bim — " f"typo in the operator bl_idname."
    )


def test_one_escape_cancels_every_simultaneously_active_preview():
    """Multiple previews can be flagged active at once (a stale bend left
    open while the user starts a wall fillet, for example). One Esc tap
    must clear them all — the user should never have to count active
    previews and tap Esc once per preview."""
    umbrella = bpy.context.scene.BIMPreviewProperties
    activated = []
    for attr, _ in preview_base.PREVIEW_CANCEL_OPS:
        child = getattr(umbrella, attr, None)
        if child is None or not hasattr(child, "is_active"):
            continue
        child.is_active = True
        activated.append(child)
    assert len(activated) >= 2, "Need at least two preview types to exercise the multi-cancel path."

    bpy.ops.bim.override_escape()

    for child in activated:
        assert child.is_active is False, f"{type(child).__name__} still active after Esc"


def test_registry_entries_target_existing_umbrella_attrs():
    """Inverse direction: every entry in ``PREVIEW_CANCEL_OPS`` must point
    at an attribute that actually exists on the umbrella and exposes
    ``is_active``. Catches stale entries left behind after a preview is
    deleted."""
    umbrella = bpy.context.scene.BIMPreviewProperties
    stale = []
    for attr, _ in preview_base.PREVIEW_CANCEL_OPS:
        child = getattr(umbrella, attr, None)
        if child is None or not hasattr(child, "is_active"):
            stale.append(attr)

    assert not stale, (
        f"PREVIEW_CANCEL_OPS references {stale} which are not is_active-bearing " f"children of BIMPreviewProperties."
    )
