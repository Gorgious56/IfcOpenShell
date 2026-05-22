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

import types
from types import SimpleNamespace

import bpy
import pytest

from bonsai.bim.module.drawing.gizmos import DimensionGizmoConfig

pytestmark = pytest.mark.drawing


@pytest.fixture(autouse=True)
def _require_real_bpy():
    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")


def test_text_formatter_defaults_to_none():
    config = DimensionGizmoConfig(attr_name="length", axis=(1, 0, 0))
    assert config.text_formatter is None


def test_text_formatter_field_stores_callable():
    formatter = lambda props, value: f"{value:.2f}m"  # noqa: E731
    config = DimensionGizmoConfig(attr_name="length", axis=(1, 0, 0), text_formatter=formatter)
    assert config.text_formatter is not None
    assert callable(config.text_formatter)


def test_text_formatter_receives_props_and_value():
    formatter = lambda props, value: f"{props.label}={value}"  # noqa: E731
    config = DimensionGizmoConfig(attr_name="length", axis=(1, 0, 0), text_formatter=formatter)
    props = SimpleNamespace(label="L")
    assert config.text_formatter(props, 3.14) == "L=3.14"


# ----------------------------------------------------------------------------
# BaseParametricGizmoGroup.pick_visible_anchor — view-aware anchor picker
# used by wall gizmo groups so a 3D view shows the wall-top anchor while a
# plan / top-down view swaps to a screen-up offset (the world-Z gap
# collapses on screen in 2D, otherwise two anchors land on the same pixel).
# ----------------------------------------------------------------------------


def test_pick_visible_anchor_returns_world_top_in_3d_view():
    from unittest.mock import patch

    from mathutils import Vector

    from bonsai import tool
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    with patch.object(tool.Blender, "is_view_top_down", return_value=False):
        result = BaseParametricGizmoGroup.pick_visible_anchor(
            None,
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 5.0)),
        )
    assert result == Vector((0.0, 0.0, 5.0))


def test_pick_visible_anchor_returns_base_lifted_along_screen_up_in_top_down():
    from unittest.mock import patch

    from mathutils import Vector

    from bonsai import tool
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    screen_up = Vector((0.0, 1.0, 0.0))
    base = Vector((1.0, 2.0, 3.0))
    with (
        patch.object(tool.Blender, "is_view_top_down", return_value=True),
        patch.object(tool.Blender, "get_screen_up_world", return_value=screen_up),
    ):
        result = BaseParametricGizmoGroup.pick_visible_anchor(
            None,
            base,
            Vector((1.0, 2.0, 10.0)),  # world_top: irrelevant in top-down branch
        )
    expected = base + screen_up * BaseParametricGizmoGroup.SCREEN_STACK_OFFSET
    assert result == expected


# ----------------------------------------------------------------------------
# Gizmo class registration smoke test — every ``bpy.types.Gizmo`` subclass in
# gizmos.py with a ``bl_idname`` must be in the feature's ``classes`` tuple so
# Blender registers it at addon enable. Forgetting one yields silent setup
# failure: ``gizmos.new("VIEW3D_GT_<missing>")`` returns None and downstream
# ``self.<gizmo_attr>`` access raises ``AttributeError`` on first draw — the
# exact bug shipped + reverted earlier on this branch for ``GizmoTrash``.
# ----------------------------------------------------------------------------


def test_every_gizmo_subclass_with_bl_idname_is_registered():
    """Every ``bpy.types.Gizmo`` subclass that defines ``bl_idname`` in the
    Bonsai drawing gizmo module must appear in the registered ``classes``
    tuple. Catches the "forgotten-in-classes" silent-setup-failure bug at
    test time instead of at first viewport draw."""
    import inspect

    from bonsai.bim.module.drawing import classes as drawing_classes
    from bonsai.bim.module.drawing import gizmos as gizmos_module

    expected_registered = set()
    for name, cls in inspect.getmembers(gizmos_module, inspect.isclass):
        # Only concrete bpy.types.Gizmo subclasses with a bl_idname. Base
        # classes / mixins without bl_idname (e.g. GizmoMovable) are
        # intentionally unregistered — they're abstract.
        if not (isinstance(cls, type) and issubclass(cls, bpy.types.Gizmo) and cls is not bpy.types.Gizmo):
            continue
        if not getattr(cls, "bl_idname", None):
            continue
        # Skip classes imported from outside this module (re-exports etc.).
        if cls.__module__ != gizmos_module.__name__:
            continue
        expected_registered.add(cls)

    registered = set(drawing_classes)
    missing = sorted(c.__name__ for c in expected_registered - registered)
    assert not missing, (
        f"Gizmo class(es) defined in bim/module/drawing/gizmos.py with a "
        f"bl_idname but missing from the drawing module's `classes` tuple: "
        f"{missing}. Add them to `classes` in bim/module/drawing/__init__.py "
        f"or the gizmo will silently fail to register and crash on first draw."
    )
