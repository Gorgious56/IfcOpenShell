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

"""Tests for IFC-Delete on BBIM_Array parents/children.

Invariants pinned here:

* The delete operator's confirmation count reflects how many array
  children would be implicitly deleted alongside a parent the user
  picked alone. A zero count means no destructive dialog needs to fire.
* When the array parent is in the selection, every layer of that array
  is dismantled — not only the layers whose children are also in the
  selection. Otherwise the parent is silently skipped by the array-child
  guard further down the delete pipeline.
* When only a child of an array is selected, the guard reports it as
  undeletable so the array stays intact.
"""

from unittest.mock import MagicMock, patch

import bpy
import ifcopenshell
import pytest

import bonsai.tool as tool
from bonsai.bim.module.geometry.operator import (
    compute_array_dismantle_plan,
    count_implicit_array_children_in_selection,
    has_blocked_array_child_in_selection,
)
from test.bim.module.model.conftest import make_ifc_file

pytestmark = pytest.mark.array


def _make_obj(name: str) -> MagicMock:
    # spec=bpy.types.Object catches typo'd attribute access at test time.
    return MagicMock(spec=bpy.types.Object, name=name)


def _make_context(selected: list) -> MagicMock:
    # spec=bpy.types.Context constrains attribute access to real Context
    # members (selected_objects, temp_override, …) so test-side typos fail
    # loudly instead of silently auto-creating mock attributes.
    ctx = MagicMock(spec=bpy.types.Context, name="context")
    ctx.selected_objects = list(selected)
    return ctx


def _call_unbound(operator_class, method_name: str, fake_self, *args, **kwargs):
    """Call a method of a ``bpy.types.Operator`` subclass with a mock ``self``.

    Operator subclasses inherit ``bpy_struct.__new__`` which rejects the
    no-arg construction pattern. Looking the method up as a class attribute
    and passing ``self`` explicitly gives us the same effect for tests that
    only exercise pure helper logic."""
    return getattr(operator_class, method_name)(fake_self, *args, **kwargs)


def _mock_bim_ops():
    """Replace ``bpy.ops.bim`` wholesale with a MagicMock — leaf patching
    is ineffective because ``bpy.ops.bim.<op>`` resolves through
    ``__getattr__`` at call time and returns a real wrapper."""
    return patch.object(bpy.ops, "bim", new=MagicMock())


# ---------------------------------------------------------------------------
# count_implicit_array_children_in_selection
# ---------------------------------------------------------------------------


def test_count_is_zero_when_no_array_in_selection():
    obj = _make_obj("wall")
    element = MagicMock(name="element")

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("bonsai.tool.Parametric.is_array", return_value=False),
    ):
        result = count_implicit_array_children_in_selection({obj})

    assert result == 0


def test_count_is_zero_when_parent_plus_all_children_selected():
    parent_obj = _make_obj("parent")
    child_a = _make_obj("child_a")
    child_b = _make_obj("child_b")
    parent_element = MagicMock(name="parent_element")

    def get_entity(obj):
        return parent_element if obj is parent_obj else None

    with (
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Parametric.is_array", return_value=True),
        patch(
            "bonsai.tool.Array.get_all_children_objects",
            return_value=iter([child_a, child_b]),
        ),
    ):
        result = count_implicit_array_children_in_selection({parent_obj, child_a, child_b})

    assert result == 0


def test_count_reports_all_children_when_parent_selected_alone():
    parent_obj = _make_obj("parent")
    child_a = _make_obj("child_a")
    child_b = _make_obj("child_b")
    parent_element = MagicMock(name="parent_element")

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=parent_element),
        patch("bonsai.tool.Parametric.is_array", return_value=True),
        patch(
            "bonsai.tool.Array.get_all_children_objects",
            return_value=iter([child_a, child_b]),
        ),
    ):
        result = count_implicit_array_children_in_selection({parent_obj})

    assert result == 2


def test_count_reports_only_unselected_children_when_partial():
    parent_obj = _make_obj("parent")
    child_a = _make_obj("child_a")
    child_b = _make_obj("child_b")
    child_c = _make_obj("child_c")
    parent_element = MagicMock(name="parent_element")

    def get_entity(obj):
        return parent_element if obj is parent_obj else None

    with (
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Parametric.is_array", return_value=True),
        patch(
            "bonsai.tool.Array.get_all_children_objects",
            return_value=iter([child_a, child_b, child_c]),
        ),
    ):
        result = count_implicit_array_children_in_selection({parent_obj, child_a})

    assert result == 2


def test_count_sums_across_distinct_array_parents():
    """Selecting two distinct array parents alone counts every child of
    each array — the outer loop sums across parents independently."""
    parent_a = _make_obj("parent_a")
    parent_b = _make_obj("parent_b")
    child_a1 = _make_obj("child_a1")
    child_b1 = _make_obj("child_b1")
    child_b2 = _make_obj("child_b2")
    parent_a_element = MagicMock(name="parent_a_element")
    parent_b_element = MagicMock(name="parent_b_element")

    def get_entity(obj):
        return {parent_a: parent_a_element, parent_b: parent_b_element}.get(obj)

    def get_all_children_objects(element):
        return iter([child_a1]) if element is parent_a_element else iter([child_b1, child_b2])

    with (
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Parametric.is_array", return_value=True),
        patch(
            "bonsai.tool.Array.get_all_children_objects",
            side_effect=get_all_children_objects,
        ),
    ):
        result = count_implicit_array_children_in_selection({parent_a, parent_b})

    assert result == 3


# ---------------------------------------------------------------------------
# has_blocked_array_child_in_selection
# ---------------------------------------------------------------------------


def test_has_blocked_array_child_false_when_no_array_in_selection():
    obj = _make_obj("wall")
    element = MagicMock(name="element")
    ifc_file = make_ifc_file()

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=False),
        patch("ifcopenshell.util.element.get_pset", return_value=None),
    ):
        result = has_blocked_array_child_in_selection({obj}, ifc_file)

    assert result is False


def test_has_blocked_array_child_true_when_lone_child_selected():
    child_obj = _make_obj("child")
    sibling_obj = _make_obj("sibling")  # same array layer, NOT in selection
    parent_obj = _make_obj("parent")
    child_element = MagicMock(name="child_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["c-guid", "s-guid"]}

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=True),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0])),
        patch(
            "bonsai.tool.Array.get_children_objects",
            side_effect=lambda layer: iter([child_obj, sibling_obj]),
        ),
    ):
        # The parent object isn't in the selection — and the layer isn't fully
        # selected (sibling is missing) — so the delete pipeline would silently
        # skip the child.
        result = has_blocked_array_child_in_selection({child_obj}, ifc_file)

    assert result is True


def test_has_blocked_array_child_false_when_parent_guid_unresolvable(capsys):
    """Stray children whose stored Parent GUID does not resolve in the
    current file are tolerated — they do not raise, do not surface as
    blocked, and the data-integrity issue is logged to the console."""
    child_obj = _make_obj("orphan_child")
    child_element = MagicMock(name="child_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.side_effect = RuntimeError("not found")

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=True),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "missing-guid"}),
    ):
        result = has_blocked_array_child_in_selection({child_obj}, ifc_file)

    assert result is False
    assert "BBIM_Array" in capsys.readouterr().out


def test_has_blocked_array_child_false_when_parent_also_selected():
    child_obj = _make_obj("child")
    parent_obj = _make_obj("parent")
    child_element = MagicMock(name="child_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["c-guid"]}

    def is_child(elem):
        return elem is child_element

    def get_entity(obj):
        return child_element if obj is child_obj else parent_element

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("bonsai.tool.Blender.Modifier.is_array_child", side_effect=is_child),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0])),
        patch("bonsai.tool.Array.get_children_objects", side_effect=lambda layer: iter([child_obj])),
    ):
        # Both parent and child selected → the dismantle path handles
        # cleanup, so no popup is needed.
        result = has_blocked_array_child_in_selection({parent_obj, child_obj}, ifc_file)

    assert result is False


def test_has_blocked_finds_child_when_other_array_parent_selected():
    """Selecting an unrelated array's parent does not unblock children of
    other arrays — the predicate checks each child's own parent."""
    child_x_obj = _make_obj("child_x")
    sibling_x_obj = _make_obj("sibling_x")  # child_x's array-X layer sibling, NOT selected
    parent_y_obj = _make_obj("parent_y")
    parent_x_obj = _make_obj("parent_x")
    child_x_element = MagicMock(name="child_x_element")
    parent_y_element = MagicMock(name="parent_y_element")
    parent_x_element = MagicMock(name="parent_x_element")

    ifc_file = make_ifc_file()

    def by_guid(guid):
        return {"x-guid": parent_x_element, "y-guid": parent_y_element}.get(guid)

    ifc_file.by_guid.side_effect = by_guid

    layer_x = {"layer": 0, "children": ["cx-guid", "sx-guid"]}
    layer_y = {"layer": 0, "children": ["py-guid"]}

    def is_child(elem):
        # Only child_x is an array child; parent_y_element is its own
        # array's parent (not a child).
        return elem is child_x_element

    def get_entity(obj):
        return {child_x_obj: child_x_element, parent_y_obj: parent_y_element}.get(obj)

    def get_object(elem):
        return {parent_x_element: parent_x_obj, parent_y_element: parent_y_obj}.get(elem)

    def get_pset(element, name):
        if element is child_x_element:
            return {"Parent": "x-guid"}
        if element is parent_y_element:
            return {"Parent": "y-guid"}
        return None

    def get_modifiers_data(parent):
        return iter([layer_x] if parent is parent_x_element else [layer_y])

    def get_children_objects(layer):
        return iter([child_x_obj, sibling_x_obj] if layer is layer_x else [])

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", side_effect=get_object),
        patch("bonsai.tool.Blender.Modifier.is_array_child", side_effect=is_child),
        patch("ifcopenshell.util.element.get_pset", side_effect=get_pset),
        patch("bonsai.tool.Array.get_modifiers_data", side_effect=get_modifiers_data),
        patch("bonsai.tool.Array.get_children_objects", side_effect=get_children_objects),
    ):
        result = has_blocked_array_child_in_selection({child_x_obj, parent_y_obj}, ifc_file)

    assert result is True


def test_has_blocked_false_when_all_layer_children_selected_without_parent():
    """When every child of every array layer is in the selection — but the
    parent is not — the executor dismantles the array cleanly. The dialog
    predicate must agree and stay quiet; otherwise the user sees a modal
    claiming the children are undeletable just before they are deleted."""
    child_l0 = _make_obj("child_l0")
    child_l1 = _make_obj("child_l1")
    parent_obj = _make_obj("parent")
    child_l0_element = MagicMock(name="child_l0_element")
    child_l1_element = MagicMock(name="child_l1_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["a"]}
    layer_1 = {"layer": 1, "children": ["b"]}

    def get_entity(obj):
        return {child_l0: child_l0_element, child_l1: child_l1_element}.get(obj)

    def get_children_objects(layer):
        return iter([child_l0]) if layer is layer_0 else iter([child_l1])

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=True),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0, layer_1])),
        patch("bonsai.tool.Array.get_children_objects", side_effect=get_children_objects),
    ):
        result = has_blocked_array_child_in_selection({child_l0, child_l1}, ifc_file)

    assert result is False


# ---------------------------------------------------------------------------
# compute_array_dismantle_plan
# ---------------------------------------------------------------------------


def test_dismantle_plan_empty_when_no_array_in_selection():
    obj = _make_obj("wall")
    element = MagicMock(name="element")
    ifc_file = make_ifc_file()

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("ifcopenshell.util.element.get_pset", return_value=None),
    ):
        plan, dismantled = compute_array_dismantle_plan({obj}, ifc_file)

    assert plan == {}
    assert dismantled == set()


def test_dismantle_plan_full_dismantle_when_parent_selected():
    """Parent in selection → every layer is dismantled regardless of which
    children are also selected (the executor's full_dismantle branch)."""
    parent_obj = _make_obj("parent")
    child_a = _make_obj("child_a")
    child_b = _make_obj("child_b")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["a"]}
    layer_1 = {"layer": 1, "children": ["b"]}

    def get_children_objects(layer):
        return iter([child_a]) if layer is layer_0 else iter([child_b])

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=parent_element),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0, layer_1])),
        patch("bonsai.tool.Array.get_children_objects", side_effect=get_children_objects),
    ):
        plan, dismantled = compute_array_dismantle_plan({parent_obj}, ifc_file)

    # Layers walked in reverse: last layer first.
    assert plan == {parent_element: [1, 0]}
    assert dismantled == {child_a, child_b}


def test_dismantle_plan_all_children_selected_without_parent():
    """All children of every layer in selection, parent not — every layer
    is still dismantled because each layer's child set is a subset of the
    selection. This is the user's reported scenario."""
    child_l0 = _make_obj("child_l0")
    child_l1 = _make_obj("child_l1")
    parent_obj = _make_obj("parent")
    child_l0_element = MagicMock(name="child_l0_element")
    child_l1_element = MagicMock(name="child_l1_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["a"]}
    layer_1 = {"layer": 1, "children": ["b"]}

    def get_entity(obj):
        return {child_l0: child_l0_element, child_l1: child_l1_element}.get(obj)

    def get_children_objects(layer):
        return iter([child_l0]) if layer is layer_0 else iter([child_l1])

    with (
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0, layer_1])),
        patch("bonsai.tool.Array.get_children_objects", side_effect=get_children_objects),
    ):
        plan, dismantled = compute_array_dismantle_plan({child_l0, child_l1}, ifc_file)

    assert plan == {parent_element: [1, 0]}
    assert dismantled == {child_l0, child_l1}


def test_dismantle_plan_breaks_when_higher_layer_partial():
    """Reverse-walk stops at the first partially-selected layer. Layer 1
    fully selected → dismantled. Layer 0 only partially selected → break,
    layer 0 stays (even though some of its children are selected)."""
    child_l0_a = _make_obj("child_l0_a")
    child_l0_b = _make_obj("child_l0_b")  # NOT in selection
    child_l1 = _make_obj("child_l1")
    parent_obj = _make_obj("parent")
    child_l0_a_element = MagicMock(name="child_l0_a_element")
    child_l1_element = MagicMock(name="child_l1_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["a", "b"]}
    layer_1 = {"layer": 1, "children": ["c"]}

    def get_entity(obj):
        return {child_l0_a: child_l0_a_element, child_l1: child_l1_element}.get(obj)

    def get_children_objects(layer):
        return iter([child_l0_a, child_l0_b]) if layer is layer_0 else iter([child_l1])

    with (
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
        patch("bonsai.tool.Array.get_modifiers_data", return_value=iter([layer_0, layer_1])),
        patch("bonsai.tool.Array.get_children_objects", side_effect=get_children_objects),
    ):
        plan, dismantled = compute_array_dismantle_plan({child_l0_a, child_l1}, ifc_file)

    # Only layer 1 dismantled; layer 0 left alone because it's partial.
    assert plan == {parent_element: [1]}
    assert dismantled == {child_l1}


# ---------------------------------------------------------------------------
# process_arrays — parent-alone full-dismantle
# ---------------------------------------------------------------------------


def test_process_arrays_fully_dismantles_when_parent_selected_alone():
    """Selecting only the array parent for delete must dismantle every
    layer of the array; otherwise the parent is silently skipped further
    down the delete pipeline."""
    parent_obj = _make_obj("parent")
    parent_element = MagicMock(name="parent_element")
    parent_element.GlobalId = "parent-guid"

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    layer_0 = {"layer": 0, "children": ["child-a-guid"]}
    layer_1 = {"layer": 1, "children": ["child-b-guid"]}

    fake_pset = {"Parent": "parent-guid", "Data": "..."}

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", return_value=parent_element),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("ifcopenshell.util.element.get_pset", return_value=fake_pset),
        patch(
            "bonsai.tool.Array.get_modifiers_data",
            return_value=iter([layer_0, layer_1]),
        ),
        # Returning children not present in the selection ensures the
        # per-layer subset check fails for every layer.
        patch(
            "bonsai.tool.Array.get_children_objects",
            side_effect=lambda layer: iter([_make_obj(f"unselected-{layer['layer']}")]),
        ),
        _mock_bim_ops() as bim_ops,
    ):
        ctx = _make_context([parent_obj])
        # temp_override is a context-manager method on bpy.types.Context —
        # MagicMock returns a context manager by default, so this just works.
        from bonsai.bim.module.geometry.operator import OverrideDelete

        _call_unbound(OverrideDelete, "process_arrays", MagicMock(), ctx)

    # One call per layer, walked in reverse order (last layer first).
    assert bim_ops.remove_array.call_count == 2
    call_items = [call.kwargs.get("item") for call in bim_ops.remove_array.call_args_list]
    assert call_items == [1, 0]


def test_process_arrays_layer_by_layer_when_all_children_selected():
    """When the parent plus all children of every layer are selected,
    each layer is dismantled in reverse order, and the walk stops at the
    first layer with partially-selected children."""
    parent_obj = _make_obj("parent")
    child_layer0 = _make_obj("child-l0")
    child_layer1 = _make_obj("child-l1")
    parent_element = MagicMock(name="parent_element")
    parent_element.GlobalId = "parent-guid"
    child_layer0_element = MagicMock(name="child0_element")
    child_layer1_element = MagicMock(name="child1_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    def get_entity(obj):
        return {
            parent_obj: parent_element,
            child_layer0: child_layer0_element,
            child_layer1: child_layer1_element,
        }.get(obj)

    layer_0 = {"layer": 0, "children": ["a"]}
    layer_1 = {"layer": 1, "children": ["b"]}
    parent_pset = {"Parent": "parent-guid", "Data": "..."}
    child_pset = {"Parent": "parent-guid", "Data": None}

    def get_pset(element, name):
        # All three elements in this array share the same parent_guid.
        return parent_pset if element is parent_element else child_pset

    def get_children_objects(layer):
        return iter([child_layer0]) if layer is layer_0 else iter([child_layer1])

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("ifcopenshell.util.element.get_pset", side_effect=get_pset),
        patch(
            "bonsai.tool.Array.get_modifiers_data",
            return_value=iter([layer_0, layer_1]),
        ),
        patch(
            "bonsai.tool.Array.get_children_objects",
            side_effect=get_children_objects,
        ),
        _mock_bim_ops() as bim_ops,
    ):
        ctx = _make_context([parent_obj, child_layer0, child_layer1])
        from bonsai.bim.module.geometry.operator import OverrideDelete

        _call_unbound(OverrideDelete, "process_arrays", MagicMock(), ctx)

    # Both layers' children are in the selection → both dismantled, in reverse.
    assert bim_ops.remove_array.call_count == 2
    call_items = [call.kwargs.get("item") for call in bim_ops.remove_array.call_args_list]
    assert call_items == [1, 0]


def test_process_arrays_does_nothing_when_no_array_in_selection():
    obj = _make_obj("plain_wall")
    element = MagicMock(name="element")

    with (
        patch("bonsai.tool.Ifc.get", return_value=MagicMock()),
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("ifcopenshell.util.element.get_pset", return_value=None),
        _mock_bim_ops() as bim_ops,
    ):
        from bonsai.bim.module.geometry.operator import OverrideDelete

        _call_unbound(OverrideDelete, "process_arrays", MagicMock(), _make_context([obj]))

    bim_ops.remove_array.assert_not_called()


# ---------------------------------------------------------------------------
# OverrideOutlinerDelete — array warning symmetric with viewport delete
# ---------------------------------------------------------------------------


def _make_outliner_context(selected_ids: list) -> MagicMock:
    """Build a context shaped like what Blender hands the Outliner delete op.

    ``context.selected_ids`` is the Outliner's selection model (sequence of
    ``bpy.types.ID`` — collections, objects, materials, …). ``window_manager``
    is needed because the operator asserts it before opening a dialog;
    ``bpy.types.Context`` exposes it via C-level attribute machinery that
    ``Mock(spec=...)`` doesn't see, so attach it explicitly. We skip the
    ``spec=`` argument here for the same reason — the operator touches
    several dynamically-resolved Context attributes."""
    ctx = MagicMock(name="outliner_context")
    ctx.selected_ids = list(selected_ids)
    return ctx


def _instantiate_outliner_op_mock(*, implicit_count: int = 0, has_blocked: bool = False) -> MagicMock:
    """A stand-in ``self`` for ``OverrideOutlinerDelete.invoke``.

    The operator writes the computed counts onto ``self`` via Property
    descriptors; a plain MagicMock accepts those writes and lets us inspect
    them after invoke returns."""
    fake_self = MagicMock(name="outliner_op")
    fake_self.implicit_array_children_count = implicit_count
    fake_self.has_blocked_array_child = has_blocked
    # The operator delegates to a classmethod that returns the parsed
    # selection; the mock lets each test supply its own objects set.
    return fake_self


def test_outliner_invoke_fires_array_dialog_when_implicit_count_positive():
    """Selecting only the array parent from the Outliner must trigger
    the array-children confirmation dialog; otherwise the array silently
    dismantles."""
    from bonsai.bim.module.geometry.operator import (
        OverrideOutlinerDelete,
        SelectedIdsData,
    )

    parent_obj = _make_obj("parent")
    fake_self = _instantiate_outliner_op_mock()
    fake_self.get_selected_ids_data = MagicMock(return_value=SelectedIdsData(objects={parent_obj}, collections=set()))

    ctx = _make_outliner_context([parent_obj])

    with (
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file()),
        patch("bonsai.bim.module.geometry.operator.calc_delete_is_batch", return_value=False),
        patch(
            "bonsai.bim.module.geometry.operator.count_implicit_array_children_in_selection",
            return_value=3,
        ),
        patch(
            "bonsai.bim.module.geometry.operator.has_blocked_array_child_in_selection",
            return_value=False,
        ),
    ):
        _call_unbound(OverrideOutlinerDelete, "invoke", fake_self, ctx, MagicMock(name="event"))

    # Confirmation dialog opened with the wide layout — not the default 300.
    ctx.window_manager.invoke_props_dialog.assert_called_once()
    kwargs = ctx.window_manager.invoke_props_dialog.call_args.kwargs
    assert kwargs.get("width") == 450
    # Destructive confirm uses the default OK label, not the acknowledgment one.
    assert "confirm_text" not in kwargs
    assert fake_self.implicit_array_children_count == 3
    assert fake_self.has_blocked_array_child is False


def test_outliner_invoke_uses_got_it_label_when_only_blocked_children():
    """Selecting a lone array child from the Outliner must surface a
    'Got it' acknowledgment popup — there is no destructive consequence,
    so the OK button reads as an acknowledgment."""
    from bonsai.bim.module.geometry.operator import (
        OverrideOutlinerDelete,
        SelectedIdsData,
    )

    child_obj = _make_obj("lone_child")
    fake_self = _instantiate_outliner_op_mock()
    fake_self.get_selected_ids_data = MagicMock(return_value=SelectedIdsData(objects={child_obj}, collections=set()))

    ctx = _make_outliner_context([child_obj])

    with (
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file()),
        patch("bonsai.bim.module.geometry.operator.calc_delete_is_batch", return_value=False),
        patch(
            "bonsai.bim.module.geometry.operator.count_implicit_array_children_in_selection",
            return_value=0,
        ),
        patch(
            "bonsai.bim.module.geometry.operator.has_blocked_array_child_in_selection",
            return_value=True,
        ),
    ):
        _call_unbound(OverrideOutlinerDelete, "invoke", fake_self, ctx, MagicMock(name="event"))

    ctx.window_manager.invoke_props_dialog.assert_called_once()
    kwargs = ctx.window_manager.invoke_props_dialog.call_args.kwargs
    assert kwargs.get("width") == 450
    assert kwargs.get("confirm_text") == "Got it"


def test_outliner_invoke_skips_dialog_for_non_array_selection():
    """Plain objects from the Outliner must not get the array popup."""
    from bonsai.bim.module.geometry.operator import (
        OverrideOutlinerDelete,
        SelectedIdsData,
    )

    obj = _make_obj("plain_wall")
    fake_self = _instantiate_outliner_op_mock()
    fake_self.get_selected_ids_data = MagicMock(return_value=SelectedIdsData(objects={obj}, collections=set()))
    fake_self.execute = MagicMock(return_value={"FINISHED"})

    ctx = _make_outliner_context([obj])

    with (
        patch("bonsai.tool.Ifc.get", return_value=make_ifc_file()),
        patch("bonsai.bim.module.geometry.operator.calc_delete_is_batch", return_value=False),
        patch(
            "bonsai.bim.module.geometry.operator.count_implicit_array_children_in_selection",
            return_value=0,
        ),
        patch(
            "bonsai.bim.module.geometry.operator.has_blocked_array_child_in_selection",
            return_value=False,
        ),
    ):
        _call_unbound(OverrideOutlinerDelete, "invoke", fake_self, ctx, MagicMock(name="event"))

    # No popup; control falls through to execute().
    ctx.window_manager.invoke_props_dialog.assert_not_called()
    fake_self.execute.assert_called_once_with(ctx)
