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

"""Regression tests for IFC-Delete on BBIM_Array parents/children.

Invariants pinned here:

* The delete operator's confirmation count reflects how many array children
  would be implicitly deleted alongside a parent the user picked alone. A
  zero count means no destructive dialog needs to fire.
* When the array parent is part of the selection, ``process_arrays``
  dismantles every layer of that array — not only the layers whose children
  are all selected. Without this, deleting just the parent fails the
  ``is_array_child`` guard further down the delete pipeline and the parent
  is silently skipped.
* When only a child of an array is selected, the guard still reports it as
  undeletable so the array stays intact.
"""

from unittest.mock import MagicMock, patch

import bpy
import ifcopenshell
import pytest

import bonsai.tool as tool
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


# ---------------------------------------------------------------------------
# tool.Blender.Modifier.count_implicit_array_children_in_selection
# ---------------------------------------------------------------------------


def test_count_is_zero_when_no_array_in_selection():
    obj = _make_obj("wall")
    element = MagicMock(name="element")

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("bonsai.tool.Blender.Modifier.is_array", return_value=False),
    ):
        result = tool.Blender.Modifier.count_implicit_array_children_in_selection({obj})

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
        patch("bonsai.tool.Blender.Modifier.is_array", return_value=True),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_all_children_objects",
            return_value=iter([child_a, child_b]),
        ),
    ):
        result = tool.Blender.Modifier.count_implicit_array_children_in_selection({parent_obj, child_a, child_b})

    assert result == 0


def test_count_reports_all_children_when_parent_selected_alone():
    parent_obj = _make_obj("parent")
    child_a = _make_obj("child_a")
    child_b = _make_obj("child_b")
    parent_element = MagicMock(name="parent_element")

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=parent_element),
        patch("bonsai.tool.Blender.Modifier.is_array", return_value=True),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_all_children_objects",
            return_value=iter([child_a, child_b]),
        ),
    ):
        result = tool.Blender.Modifier.count_implicit_array_children_in_selection({parent_obj})

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
        patch("bonsai.tool.Blender.Modifier.is_array", return_value=True),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_all_children_objects",
            return_value=iter([child_a, child_b, child_c]),
        ),
    ):
        result = tool.Blender.Modifier.count_implicit_array_children_in_selection({parent_obj, child_a})

    assert result == 2


# ---------------------------------------------------------------------------
# tool.Blender.Modifier.has_blocked_array_child_in_selection
# ---------------------------------------------------------------------------


def test_has_blocked_array_child_false_when_no_array_in_selection():
    obj = _make_obj("wall")
    element = MagicMock(name="element")

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=element),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=False),
    ):
        result = tool.Blender.Modifier.has_blocked_array_child_in_selection({obj})

    assert result is False


def test_has_blocked_array_child_true_when_lone_child_selected():
    child_obj = _make_obj("child")
    parent_obj = _make_obj("parent")
    child_element = MagicMock(name="child_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", return_value=child_element),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("bonsai.tool.Blender.Modifier.is_array_child", return_value=True),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
    ):
        # The parent object isn't in the selection — the child is on its own,
        # so the delete guard would silently skip it.
        result = tool.Blender.Modifier.has_blocked_array_child_in_selection({child_obj})

    assert result is True


def test_has_blocked_array_child_false_when_parent_also_selected():
    child_obj = _make_obj("child")
    parent_obj = _make_obj("parent")
    child_element = MagicMock(name="child_element")
    parent_element = MagicMock(name="parent_element")

    ifc_file = make_ifc_file()
    ifc_file.by_guid.return_value = parent_element

    def is_child(elem):
        return elem is child_element

    def get_entity(obj):
        return child_element if obj is child_obj else MagicMock()

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("bonsai.tool.Ifc.get_entity", side_effect=get_entity),
        patch("bonsai.tool.Ifc.get_object", return_value=parent_obj),
        patch("bonsai.tool.Blender.Modifier.is_array_child", side_effect=is_child),
        patch("ifcopenshell.util.element.get_pset", return_value={"Parent": "p-guid"}),
    ):
        # Both parent and child selected → process_arrays will handle the
        # dismantle path; nothing is silently skipped, so no popup needed.
        result = tool.Blender.Modifier.has_blocked_array_child_in_selection({parent_obj, child_obj})

    assert result is False


# ---------------------------------------------------------------------------
# process_arrays — parent-alone full-dismantle (the actual bug fix)
# ---------------------------------------------------------------------------


def test_process_arrays_fully_dismantles_when_parent_selected_alone():
    """Reproduces the reported bug: selecting only the array parent and
    deleting must dismantle every layer of the array. Without the
    ``array_parents_to_fully_dismantle`` branch, the per-layer
    ``children.issubset(selected_objects)`` check fails (children weren't
    selected) and the array stays — leaving the parent stuck behind the
    ``is_array_child`` guard down the pipeline."""
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
            "bonsai.tool.Blender.Modifier.Array.get_modifiers_data",
            return_value=iter([layer_0, layer_1]),
        ),
        # Returning children not in selection forces a `break` in the legacy
        # path — a passing test here proves the full-dismantle override fires.
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_children_objects",
            side_effect=lambda layer: iter([_make_obj(f"unselected-{layer['layer']}")]),
        ),
        # ``bpy.ops.bim.<op>`` resolves through ``__getattr__`` at call time,
        # so patching the leaf attribute directly is ineffective — the
        # registry hands back a real BPyOpsSubModOp regardless. Replacing the
        # whole ``bpy.ops.bim`` submodule with a Mock catches every chained
        # access.
        patch.object(bpy.ops, "bim", new=MagicMock()) as bim_ops,
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
    """Regression guard: the pre-existing 'select parent + all children'
    workflow must keep working unchanged. Each layer whose children are all
    in the selection gets removed, in reverse order, and the walk stops at
    the first layer with partially-selected children."""
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
            "bonsai.tool.Blender.Modifier.Array.get_modifiers_data",
            return_value=iter([layer_0, layer_1]),
        ),
        patch(
            "bonsai.tool.Blender.Modifier.Array.get_children_objects",
            side_effect=get_children_objects,
        ),
        # ``bpy.ops.bim.<op>`` resolves through ``__getattr__`` at call time,
        # so patching the leaf attribute directly is ineffective — the
        # registry hands back a real BPyOpsSubModOp regardless. Replacing the
        # whole ``bpy.ops.bim`` submodule with a Mock catches every chained
        # access.
        patch.object(bpy.ops, "bim", new=MagicMock()) as bim_ops,
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
        # ``bpy.ops.bim.<op>`` resolves through ``__getattr__`` at call time,
        # so patching the leaf attribute directly is ineffective — the
        # registry hands back a real BPyOpsSubModOp regardless. Replacing the
        # whole ``bpy.ops.bim`` submodule with a Mock catches every chained
        # access.
        patch.object(bpy.ops, "bim", new=MagicMock()) as bim_ops,
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
    # The classmethod is called as ``self.get_selected_ids_data(context)`` —
    # routing it through the mock lets each test supply its own objects set.
    return fake_self


def test_outliner_invoke_fires_array_dialog_when_implicit_count_positive():
    """Selecting only the array parent from the Outliner must trigger the same
    confirmation dialog the viewport already shows. Without this wiring the
    array silently dismantles."""
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
            "bonsai.tool.Blender.Modifier.count_implicit_array_children_in_selection",
            return_value=3,
        ),
        patch(
            "bonsai.tool.Blender.Modifier.has_blocked_array_child_in_selection",
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
    """Selecting a lone array child from the Outliner must surface the same
    'Got it' acknowledgment popup the viewport shows — no destructive
    consequence, so the OK button reads as an acknowledgment."""
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
            "bonsai.tool.Blender.Modifier.count_implicit_array_children_in_selection",
            return_value=0,
        ),
        patch(
            "bonsai.tool.Blender.Modifier.has_blocked_array_child_in_selection",
            return_value=True,
        ),
    ):
        _call_unbound(OverrideOutlinerDelete, "invoke", fake_self, ctx, MagicMock(name="event"))

    ctx.window_manager.invoke_props_dialog.assert_called_once()
    kwargs = ctx.window_manager.invoke_props_dialog.call_args.kwargs
    assert kwargs.get("width") == 450
    assert kwargs.get("confirm_text") == "Got it"


def test_outliner_invoke_skips_dialog_for_non_array_selection():
    """Plain objects from the Outliner must not get the array popup — that's
    a UX regression for the common case."""
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
            "bonsai.tool.Blender.Modifier.count_implicit_array_children_in_selection",
            return_value=0,
        ),
        patch(
            "bonsai.tool.Blender.Modifier.has_blocked_array_child_in_selection",
            return_value=False,
        ),
    ):
        _call_unbound(OverrideOutlinerDelete, "invoke", fake_self, ctx, MagicMock(name="event"))

    # No popup; control falls through to execute() — matching the pre-fix path.
    ctx.window_manager.invoke_props_dialog.assert_not_called()
    fake_self.execute.assert_called_once_with(ctx)
