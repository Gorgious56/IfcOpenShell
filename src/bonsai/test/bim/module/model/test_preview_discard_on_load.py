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
every active preview registered for Esc cancellation, and that the load_post
handler dispatches it.

The Scene-level preview PropertyGroup is part of the ``.blend`` file. Without
this discard step, a session saved while a preview was active would silently
hide every sibling gizmo poll gated on the preview's ``is_active`` flag on
the next file open."""

import bpy
import pytest

from bonsai.bim import handler
from bonsai.bim.module.model import preview_base

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


def test_load_post_discards_pending_previews():
    """The Blender ``load_post`` handler must invoke the discard step so a
    ``.blend`` opened with stuck preview flags lands in a clean state."""
    _set_all_previews_active()

    handler.load_post(bpy.context.scene)

    umbrella = bpy.context.scene.BIMPreviewProperties
    for attr, _op_name in preview_base.PREVIEW_CANCEL_OPS:
        assert getattr(umbrella, attr).is_active is False, f"load_post did not discard BIMPreviewProperties.{attr}."
