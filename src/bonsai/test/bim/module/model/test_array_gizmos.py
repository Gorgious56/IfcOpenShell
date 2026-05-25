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

"""Regression tests for the array child gizmo hover-highlight wire-up.

Invariants pinned here:

* ``Modifier.Array.get_child_layer_index`` resolves the layer that produced
  a child by walking the parent's ``BBIM_Array.Data`` and matching the
  child's GlobalId. It is total — orphan children, missing pset, unparseable
  JSON, and "child not listed in any layer" all return ``None`` without
  raising.
* The 2x2 grid icon (``GizmoArrayAll``) painted on an array child invokes
  the shared bbox helper when hovered, passing the resolved
  ``(parent_element, layer_index)`` so the highlight matches what the
  parent's per-layer indicator would render.
* The tree icon (``GizmoArrayParent``) stays as pure parent-selection
  navigation — hovering it does NOT trigger the bbox highlight.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bpy
import ifcopenshell
import pytest

import bonsai.tool as tool
from test.bim.module.model.conftest import make_ifc_file

pytestmark = pytest.mark.array


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_element(global_id: str, pset: dict | None = None) -> MagicMock:
    """Build a mock IFC element whose ``.GlobalId`` and ``BBIM_Array`` pset
    are addressable. ``get_pset`` is monkey-patched per-test, so the pset
    body is reached via the side_effect lookup, not via the mock itself."""
    el = MagicMock(name=f"element_{global_id}")
    el.GlobalId = global_id
    el._bbim_array_pset = pset
    return el


def _pset_side_effect_from_elements(
    elements: list, attribute: str | None = None
) -> callable:
    """Return a ``get_pset`` side-effect that maps each element to its
    pre-built ``BBIM_Array`` pset (or its ``Data`` field). Anything else
    returns ``None``."""

    def side_effect(element, pset_name, *attr):
        if pset_name != "BBIM_Array":
            return None
        for cached in elements:
            if cached is element:
                pset = cached._bbim_array_pset
                if not pset:
                    return None
                if attr:
                    return pset.get(attr[0])
                return pset
        return None

    return side_effect


# ---------------------------------------------------------------------------
# tool.Blender.Modifier.Array.get_child_layer_index
# ---------------------------------------------------------------------------


def test_get_child_layer_index_returns_zero_for_single_layer_child():
    parent = _make_element(
        "parent-guid",
        {
            "Parent": "parent-guid",
            "Data": json.dumps([{"children": ["child-a", "child-b"]}]),
        },
    )
    child = _make_element("child-a", {"Parent": "parent-guid"})

    with (
        patch(
            "ifcopenshell.util.element.get_pset",
            side_effect=_pset_side_effect_from_elements([parent, child]),
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({"parent-guid": parent})),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(child)

    assert result == 0


def test_get_child_layer_index_returns_correct_index_for_multi_layer_child():
    parent = _make_element(
        "parent-guid",
        {
            "Parent": "parent-guid",
            "Data": json.dumps(
                [
                    {"children": ["child-a", "child-b"]},
                    {"children": ["child-c", "child-d"]},
                    {"children": ["child-e"]},
                ]
            ),
        },
    )
    child_in_layer_1 = _make_element("child-d", {"Parent": "parent-guid"})

    with (
        patch(
            "ifcopenshell.util.element.get_pset",
            side_effect=_pset_side_effect_from_elements([parent, child_in_layer_1]),
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({"parent-guid": parent})),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(child_in_layer_1)

    assert result == 1


def test_get_child_layer_index_returns_none_for_orphan_child():
    """Parent GUID present but unresolvable — by_guid raises RuntimeError,
    the helper must swallow it and return None."""
    child = _make_element("child-a", {"Parent": "missing-parent-guid"})

    with (
        patch(
            "ifcopenshell.util.element.get_pset",
            side_effect=_pset_side_effect_from_elements([child]),
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({})),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(child)

    assert result is None


def test_get_child_layer_index_returns_none_when_child_not_in_any_layer():
    """Data desync — the child's GlobalId isn't listed anywhere in the
    parent's layers (e.g. mid-regenerate gap). Helper returns None."""
    parent = _make_element(
        "parent-guid",
        {
            "Parent": "parent-guid",
            "Data": json.dumps([{"children": ["other-guid-1", "other-guid-2"]}]),
        },
    )
    stray_child = _make_element("child-a", {"Parent": "parent-guid"})

    with (
        patch(
            "ifcopenshell.util.element.get_pset",
            side_effect=_pset_side_effect_from_elements([parent, stray_child]),
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({"parent-guid": parent})),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(stray_child)

    assert result is None


def test_get_child_layer_index_returns_none_when_no_pset():
    """No BBIM_Array pset on the candidate — helper bails on the first
    lookup, no raise."""
    child = _make_element("child-a", None)

    with patch(
        "ifcopenshell.util.element.get_pset",
        side_effect=_pset_side_effect_from_elements([child]),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(child)

    assert result is None


def test_get_child_layer_index_returns_none_when_parent_self_reference():
    """A parent IS its own ``Parent`` — passing one into the lookup must
    return None instead of confusing it with a child."""
    parent = _make_element(
        "parent-guid",
        {
            "Parent": "parent-guid",
            "Data": json.dumps([{"children": ["child-a"]}]),
        },
    )

    with patch(
        "ifcopenshell.util.element.get_pset",
        side_effect=_pset_side_effect_from_elements([parent]),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(parent)

    assert result is None


def test_get_child_layer_index_returns_none_when_data_is_garbage_json():
    """Malformed Data field — json.loads raises, helper returns None."""
    parent = _make_element(
        "parent-guid",
        {"Parent": "parent-guid", "Data": "not json {{{"},
    )
    child = _make_element("child-a", {"Parent": "parent-guid"})

    with (
        patch(
            "ifcopenshell.util.element.get_pset",
            side_effect=_pset_side_effect_from_elements([parent, child]),
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({"parent-guid": parent})),
    ):
        result = tool.Blender.Modifier.Array.get_child_layer_index(child)

    assert result is None


# ---------------------------------------------------------------------------
# GizmoArrayAll hover wire-up: hover on a child's 2x2 grid icon paints the
# bbox for the containing array layer, the same way the parent's layer
# indicator does.
# ---------------------------------------------------------------------------


def _make_context_with_active(active_obj) -> MagicMock:
    ctx = MagicMock(spec=bpy.types.Context, name="context")
    ctx.active_object = active_obj
    return ctx


def test_gizmo_array_all_hover_calls_bbox_helper_with_resolved_parent_and_layer():
    """When ``GizmoArrayAll`` is hovered with an array child active, the
    shared bbox helper must be invoked with (parent_element, layer_index)
    so the highlight matches what the parent's layer indicator would render."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayAll

    parent_element = MagicMock(name="parent_element")
    child_element = MagicMock(name="child_element")
    child_obj = MagicMock(spec=bpy.types.Object, name="child_obj")
    context = _make_context_with_active(child_obj)

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_child_layer_index",
            return_value=2,
        ),
        patch(
            "ifcopenshell.util.element.get_pset",
            return_value={"Parent": "parent-guid"},
        ),
        patch(
            "bonsai.tool.Ifc.get",
            return_value=make_ifc_file({"parent-guid": parent_element}),
        ),
        patch("bonsai.bim.module.model.decorator.draw_array_layer_children_bbox") as draw_bbox,
    ):
        # ``_draw_containing_array_bbox`` doesn't dereference ``self`` — it
        # only reads from ``context`` — so we can call it unbound.
        GizmoArrayAll._draw_containing_array_bbox(None, context)

    draw_bbox.assert_called_once_with(context, parent_element, 2)


def test_gizmo_array_all_hover_with_orphan_child_skips_bbox():
    """Active child has a Parent GUID that no longer resolves — helper
    returns None, draw bails silently without calling the bbox helper."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayAll

    child_element = MagicMock(name="orphan_child_element")
    context = _make_context_with_active(MagicMock(spec=bpy.types.Object))

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_child_layer_index",
            return_value=None,
        ),
        patch("bonsai.bim.module.model.decorator.draw_array_layer_children_bbox") as draw_bbox,
    ):
        GizmoArrayAll._draw_containing_array_bbox(None, context)

    draw_bbox.assert_not_called()


def test_gizmo_array_all_hover_with_no_active_object_skips_bbox():
    """No active object — draw bails before any IFC lookup."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayAll

    context = _make_context_with_active(None)

    with patch("bonsai.bim.module.model.decorator.draw_array_layer_children_bbox") as draw_bbox:
        GizmoArrayAll._draw_containing_array_bbox(None, context)

    draw_bbox.assert_not_called()


def test_gizmo_array_all_hover_with_unresolvable_parent_guid_skips_bbox():
    """``get_child_layer_index`` returned a layer index, but the parent GUID
    became unresolvable between the two lookups (rare desync). Draw bails."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayAll

    child_element = MagicMock(name="child_element")
    context = _make_context_with_active(MagicMock(spec=bpy.types.Object))

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_child_layer_index",
            return_value=0,
        ),
        patch(
            "ifcopenshell.util.element.get_pset",
            return_value={"Parent": "vanished-guid"},
        ),
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file({})),
        patch("bonsai.bim.module.model.decorator.draw_array_layer_children_bbox") as draw_bbox,
    ):
        GizmoArrayAll._draw_containing_array_bbox(None, context)

    draw_bbox.assert_not_called()


def test_gizmo_array_all_draw_gates_bbox_on_is_highlight():
    """``draw()`` delegates icon rendering to ``StaticTrisGizmoMixin.draw`` so
    the shared 8-direction outline halo is applied, then layers the bbox
    helper on top only when ``is_highlight`` is set — gates the per-frame
    cost of the IFC lookup to the hover window."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayAll, StaticTrisGizmoMixin

    with patch.object(StaticTrisGizmoMixin, "draw") as mixin_draw:
        fake_self = MagicMock(name="gizmo", spec=GizmoArrayAll)
        fake_self.is_highlight = False
        ctx = MagicMock(name="context")
        GizmoArrayAll.draw(fake_self, ctx)
        mixin_draw.assert_called_once_with(ctx)
        fake_self._draw_containing_array_bbox.assert_not_called()

        mixin_draw.reset_mock()
        fake_self.reset_mock()
        fake_self.is_highlight = True
        ctx = MagicMock(name="context")
        GizmoArrayAll.draw(fake_self, ctx)
        mixin_draw.assert_called_once_with(ctx)
        fake_self._draw_containing_array_bbox.assert_called_once_with(ctx)


def test_gizmo_array_parent_hover_does_not_paint_bbox():
    """``GizmoArrayParent`` (the tree icon) is pure navigation — hovering
    it must NOT invoke the bbox helper. Pinned so a future change can't
    accidentally extend the highlight to the wrong icon."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayParent, StaticTrisGizmoMixin

    # GizmoArrayParent has no hover-bbox method — its draw is the plain
    # icon-only paint inherited from StaticTrisGizmoMixin.
    assert not hasattr(GizmoArrayParent, "_draw_containing_array_bbox")
    assert GizmoArrayParent.draw is StaticTrisGizmoMixin.draw


# ---------------------------------------------------------------------------
# GizmoArrayLayerIndicator stateful shape rebuild — set_count, set_layer_index,
# _ensure_shape. The gizmo's custom shape encodes the count via 7-segment digit
# triangles, so the rebuild is load-bearing: if _ensure_shape silently no-ops
# after a count change, the icon freezes at the old number.
#
# Tests call the mutators unbound with a SimpleNamespace stand-in (same pattern
# as test_gizmo_array_all_hover_calls_bbox_helper_with_resolved_parent_and_layer
# above, which calls _draw_containing_array_bbox with None as self). Direct
# instantiation via __new__ is broken under Blender 5.1's bpy_struct.
# ---------------------------------------------------------------------------


def test_array_layer_indicator_set_count_stores_int():
    """``set_count`` coerces to int and stores on ``_count``. No shape rebuild
    happens here — that's _ensure_shape's job, called per draw."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayLayerIndicator

    ns = SimpleNamespace(_count=0)
    GizmoArrayLayerIndicator.set_count(ns, 7)
    assert ns._count == 7

    # Float input coerced via ``int(...)``.
    GizmoArrayLayerIndicator.set_count(ns, 3.9)
    assert ns._count == 3


def test_array_layer_indicator_set_layer_index_stores_int():
    """``set_layer_index`` binds the gizmo instance to one array layer.
    Default ``-1`` means unassigned; a non-negative value enables the
    children-bbox highlight path in ``_draw_layer_children_bbox``."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayLayerIndicator

    ns = SimpleNamespace(_layer_index=-1)
    GizmoArrayLayerIndicator.set_layer_index(ns, 2)
    assert ns._layer_index == 2


def test_array_layer_indicator_ensure_shape_rebuilds_when_count_changed():
    """When ``_count != _built_count``, ``_ensure_shape`` must reassign
    ``custom_shape`` from a freshly built tris tuple and update
    ``_built_count`` to match. This is the path that keeps the visible
    count in sync with the underlying array layer."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayLayerIndicator

    rebuilt = []

    def fake_new_custom_shape(kind, tris):
        rebuilt.append((kind, len(tris)))
        return ("SHAPE", kind, len(tris))

    ns = SimpleNamespace(
        _count=5,
        _built_count=-1,
        custom_shape=("OLD_SHAPE",),
        new_custom_shape=fake_new_custom_shape,
        # Stubbed so the test isolates _ensure_shape's rebuild-or-skip
        # logic without depending on the actual tris layout.
        _build_tris=lambda: ((0.0, 0.0, 0.0),) * 3,
    )
    GizmoArrayLayerIndicator._ensure_shape(ns)

    assert ns._built_count == 5
    assert ns.custom_shape != ("OLD_SHAPE",)
    assert len(rebuilt) == 1
    assert rebuilt[0][0] == "TRIS"


def test_array_layer_indicator_ensure_shape_no_rebuild_when_count_unchanged():
    """When ``_count == _built_count``, ``_ensure_shape`` must NOT rebuild —
    the per-frame draw path would otherwise allocate a fresh tris tuple
    every redraw, defeating the cache."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayLayerIndicator

    def must_not_be_called(kind, tris):  # noqa: ARG001
        raise AssertionError("_ensure_shape rebuilt the shape when count was unchanged")

    ns = SimpleNamespace(
        _count=5,
        _built_count=5,
        custom_shape=("CACHED",),
        new_custom_shape=must_not_be_called,
    )
    GizmoArrayLayerIndicator._ensure_shape(ns)
    assert ns.custom_shape == ("CACHED",)
    assert ns._built_count == 5
