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

"""Unit coverage for the shared parametric-edit lifecycle mixins.

``bonsai.bim.parametric_lifecycle`` is the load-bearing path for 4 of 6
parametric features (door, window, railing, roof). The registry smoke test
elsewhere verifies operators are wired up; the mixins' own state-transition
contracts are tested here.

The mixins are exercised through minimal in-test subclasses that supply the
abstract hooks (``_is_element_type``, ``_get_props``, etc.). All ``tool.*`` and
``ifcopenshell.*`` references at the module top of ``parametric_lifecycle`` are
patched at the module attribute (not the source module) so each test sees
isolated mock state."""

import json
from typing import ClassVar
from unittest import mock

import pytest

from test.bim.conftest import _FakePathProps, _FakePropsBase
from test.bim.conftest import make_lifecycle_obj as _make_obj

pytestmark = pytest.mark.model


class _FakeProps(_FakePropsBase):
    """Stand-in for door / window ``BIM<Name>Properties``. Adds the
    lining + panel kwargs accessors that the ``FeatureModifierEditMixin``
    reads on top of the base ``is_editing`` / ``general`` contract."""

    def __init__(self):
        super().__init__(general={"width": 1000})
        self.lining = {"thickness": 50}
        self.panel = {"material": "wood"}

    def get_lining_kwargs(self, convert_to_project_units=True):
        return dict(self.lining)

    def get_panel_kwargs(self, convert_to_project_units=True):
        return dict(self.panel)


def _make_pset_text(general, lining, panel):
    payload = {"lining_properties": lining, "panel_properties": panel, **general}
    return json.dumps(payload)


# ----------------------------------------------------------------------
# FeatureModifierEditMixin (door/window pattern)
# ----------------------------------------------------------------------


def _door_mixin_cls(match=True, raise_on_update=False):
    from bonsai.bim.parametric_lifecycle import FeatureModifierEditMixin

    raised = raise_on_update

    class _TestDoorMixin(FeatureModifierEditMixin):
        pset_name: ClassVar[str] = "BBIM_Door"
        representations_called: ClassVar[list] = []

        @classmethod
        def _is_element_type(cls, element):
            return match

        @classmethod
        def _get_props(cls, obj):
            return obj.props

        @classmethod
        def _update_modifier_representation(cls, obj, context):
            cls.representations_called.append(obj)
            if raised:
                raise RuntimeError("simulated representation failure")

    return _TestDoorMixin


@pytest.fixture
def patched_tool_and_ifc():
    """Patch ``tool`` and ``ifcopenshell.*`` references on the lifecycle module.

    Yields ``(mock_tool, mock_ifc_util_element, mock_ifc_api_pset,
    mock_ifc_util_rep, mock_core_geometry)`` so tests can configure return
    values and assert call args."""
    target = "bonsai.bim.parametric_lifecycle"
    with mock.patch(f"{target}.tool") as mock_tool, mock.patch(f"{target}.ifcopenshell") as mock_ifc, mock.patch(
        f"{target}.bonsai"
    ) as mock_bonsai:
        # Element returned by tool.Ifc.get_entity is reused across mocks.
        element = mock.Mock(name="entity")
        mock_tool.Ifc.get_entity.return_value = element
        mock_tool.Ifc.get.return_value = mock.Mock(name="ifc_file")
        mock_tool.Model.get_constituents_props_data.return_value = {"materials": []}
        mock_tool.Pset.get_element_pset.return_value = mock.Mock(name="pset")
        mock_ifc.util.element.get_type.return_value = None  # skip thumbnail mark
        yield {
            "tool": mock_tool,
            "ifc": mock_ifc,
            "bonsai": mock_bonsai,
            "element": element,
        }


def test_feature_modifier_enable_one_sets_is_editing_and_loads_kwargs(patched_tool_and_ifc):
    props = _FakeProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 1234}, {"thickness": 50}, {"material": "wood"}
    )

    cls = _door_mixin_cls(match=True)
    cls._enable_one(obj)

    assert props.is_editing is True
    assert props.last_kwargs is not None
    assert props.last_kwargs["width"] == 1234
    assert props.last_kwargs["thickness"] == 50
    assert props.last_kwargs["material"] == "wood"
    assert "materials" in props.last_kwargs  # from get_constituents_props_data


def test_feature_modifier_enable_one_noop_when_element_not_match(patched_tool_and_ifc):
    props = _FakeProps()
    obj = _make_obj(props)

    cls = _door_mixin_cls(match=False)
    cls._enable_one(obj)

    assert props.is_editing is False
    assert props.last_kwargs is None
    # get_pset must not be called when _is_element_type returns False — the
    # _resolve guard short-circuits before reading pset data.
    patched_tool_and_ifc["ifc"].util.element.get_pset.assert_not_called()


def test_feature_modifier_enable_one_noop_when_no_entity(patched_tool_and_ifc):
    """tool.Ifc.get_entity returning None must short-circuit before predicate runs."""
    props = _FakeProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Ifc.get_entity.return_value = None

    cls = _door_mixin_cls(match=True)
    cls._enable_one(obj)

    assert props.is_editing is False


def test_feature_modifier_enable_one_commits_placement_drift(patched_tool_and_ifc):
    """Enable must commit any pre-edit matrix_world drift to IFC at entry —
    otherwise Cancel's restore-from-IFC reads a stale ObjectPlacement and
    snaps the object back to its pre-drift position. The common trigger is
    a filling whose host wall was rotated (filling followed the wall
    visually but its IFC placement was never re-synced).

    apply_scale=False pins the state-transition-vs-commit contract: enable
    must not bake object scale into geometry — that's the finish path's job."""
    props = _FakeProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 1234}, {"thickness": 50}, {"material": "wood"}
    )

    cls = _door_mixin_cls(match=True)
    cls._enable_one(obj)

    patched_tool_and_ifc["tool"].Geometry.commit_placement_if_moved.assert_called_once_with(obj, apply_scale=False)


def test_feature_modifier_finish_one_clears_is_editing_and_writes_pset(patched_tool_and_ifc):
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)
    ctx = mock.Mock(name="context")

    cls = _door_mixin_cls(match=True)
    cls._finish_one(obj, ctx)

    assert props.is_editing is False
    assert obj in cls.representations_called
    # edit_pset is called exactly once; properties key is "Data" wrapping JSON.
    patched_tool_and_ifc["ifc"].api.pset.edit_pset.assert_called_once()
    kwargs = patched_tool_and_ifc["ifc"].api.pset.edit_pset.call_args.kwargs
    assert "properties" in kwargs and "Data" in kwargs["properties"]


def test_feature_modifier_finish_one_exception_leaves_draft_in_progress(patched_tool_and_ifc):
    """If _update_modifier_representation raises, is_editing must stay True
    so the user's draft survives for retry. This is the contract called out
    in parametric_lifecycle.py:161 — set is_editing=False only on success."""
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)
    ctx = mock.Mock(name="context")

    cls = _door_mixin_cls(match=True, raise_on_update=True)
    with pytest.raises(RuntimeError, match="simulated representation failure"):
        cls._finish_one(obj, ctx)

    assert props.is_editing is True  # draft survives


def test_feature_modifier_cancel_one_restores_and_clears_is_editing(patched_tool_and_ifc):
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 900}, {"thickness": 60}, {"material": "steel"}
    )

    cls = _door_mixin_cls(match=True)
    cls._cancel_one(obj)

    assert props.is_editing is False
    assert props.last_kwargs is not None and props.last_kwargs["width"] == 900
    # switch_representation must be called via bonsai.core.geometry.
    patched_tool_and_ifc["bonsai"].core.geometry.switch_representation.assert_called_once()


def test_feature_modifier_finish_one_commits_placement_drift(patched_tool_and_ifc):
    """When the filling's matrix_world has drifted from IFC during the edit
    (typical of a wall-offset gizmo drag), Finish must commit the placement —
    pset write alone is not sufficient because placement isn't in the pset."""
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)

    cls = _door_mixin_cls(match=True)
    cls._finish_one(obj, mock.Mock(name="context"))

    patched_tool_and_ifc["tool"].Geometry.commit_placement_if_moved.assert_called_once_with(obj)


def test_feature_modifier_cancel_one_restores_placement_when_moved(patched_tool_and_ifc):
    """Cancel restores matrix_world from IFC so a drag-then-cancel reverts
    BOTH the draft pset (already covered above) and the placement."""
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 900}, {"thickness": 60}, {"material": "steel"}
    )
    patched_tool_and_ifc["tool"].Ifc.is_moved.return_value = True

    cls = _door_mixin_cls(match=True)
    cls._cancel_one(obj)

    patched_tool_and_ifc["tool"].Geometry.restore_placement_from_ifc.assert_called_once_with(
        obj, patched_tool_and_ifc["element"]
    )


def test_feature_modifier_cancel_one_skips_placement_restore_when_not_moved(patched_tool_and_ifc):
    """When nothing was dragged, Cancel must not touch matrix_world — the
    restore path is an undo-only safeguard, never a forced refresh."""
    props = _FakeProps()
    props.is_editing = True
    obj = _make_obj(props)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 900}, {"thickness": 60}, {"material": "steel"}
    )
    patched_tool_and_ifc["tool"].Ifc.is_moved.return_value = False

    cls = _door_mixin_cls(match=True)
    cls._cancel_one(obj)

    patched_tool_and_ifc["tool"].Geometry.restore_placement_from_ifc.assert_not_called()


def test_feature_modifier_targets_loop_uses_iter_targets(patched_tool_and_ifc):
    """_enable_targets / _finish_targets / _cancel_targets iterate
    _iter_targets — default is [active_object]; subclasses can override."""
    props_a, props_b = _FakeProps(), _FakeProps()
    obj_a, obj_b = _make_obj(props_a), _make_obj(props_b)
    patched_tool_and_ifc["ifc"].util.element.get_pset.return_value = _make_pset_text(
        {"width": 1000}, {"thickness": 50}, {"material": "wood"}
    )

    cls = _door_mixin_cls(match=True)
    cls._iter_targets = classmethod(lambda c, ctx: [obj_a, obj_b])

    result = cls()._enable_targets(mock.Mock())

    assert result == {"FINISHED"}
    assert props_a.is_editing is True
    assert props_b.is_editing is True


# ----------------------------------------------------------------------
# PathPreservingEditMixin (railing/roof pattern)
# ----------------------------------------------------------------------


def _path_mixin_cls(match=True):
    """Build a fresh ``PathPreservingEditMixin`` subclass per call with its own
    call-tracking lists. Each invocation returns a distinct class so tests are
    isolated by construction — no ``.clear()`` between tests needed.

    The tracking lists live on the **class** but are fresh per factory call
    (they're created inside the closure). This avoids the
    ``ClassVar[list] = []`` foot-gun where every subclass shared the same
    mutable default."""
    from bonsai.bim.parametric_lifecycle import PathPreservingEditMixin

    pset_updates: list = []
    ifc_data_updates: list = []
    bmesh_updates: list = []

    class _TestPathMixin(PathPreservingEditMixin):
        pset_name: ClassVar[str] = "BBIM_Railing"

        @classmethod
        def _is_element_type(cls, element):
            return match

        @classmethod
        def _get_props(cls, obj):
            return obj.props

        @classmethod
        def _update_pset(cls, element, data):
            pset_updates.append((element, data))

        @classmethod
        def _update_modifier_ifc_data(cls, obj, context):
            ifc_data_updates.append(obj)

        @classmethod
        def _restore_viewport_after_cancel(cls, obj, context):
            bmesh_updates.append(obj)

    # Expose the per-factory-call lists on the class so tests can assert against them.
    _TestPathMixin.pset_updates = pset_updates
    _TestPathMixin.ifc_data_updates = ifc_data_updates
    _TestPathMixin.bmesh_updates = bmesh_updates
    return _TestPathMixin


def test_path_preserving_enable_one_sets_is_editing(patched_tool_and_ifc):
    props = _FakePathProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 250, "path_data": {"points": [[0, 0], [1, 0]]}}
    }

    cls = _path_mixin_cls(match=True)
    cls._enable_one(obj)

    assert props.is_editing is True
    assert props.last_kwargs is not None
    assert props.last_kwargs["width"] == 250
    # path_data passes through (default _post_load_data is pass-through)
    assert props.last_kwargs["path_data"] == {"points": [[0, 0], [1, 0]]}


def test_path_preserving_finish_one_preserves_path_data_and_clears_is_editing(patched_tool_and_ifc):
    props = _FakePathProps()
    props.is_editing = True
    obj = _make_obj(props)
    ctx = mock.Mock(name="context")
    sentinel_path = {"points": [[5, 5], [9, 9]], "edges": [[0, 1]]}
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"path_data": sentinel_path}
    }

    cls = _path_mixin_cls(match=True)
    cls._finish_one(obj, ctx)

    assert props.is_editing is False
    assert cls.pset_updates, "_update_pset must be called on Finish"
    assert cls.pset_updates[-1][1]["path_data"] is sentinel_path  # preserved by reference
    assert obj in cls.ifc_data_updates


def test_path_preserving_cancel_one_calls_restore_viewport_after_cancel(patched_tool_and_ifc):
    props = _FakePathProps()
    props.is_editing = True
    obj = _make_obj(props)
    ctx = mock.Mock(name="context")
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 250, "path_data": {"points": []}}
    }

    cls = _path_mixin_cls(match=True)
    cls._cancel_one(obj, ctx)

    assert props.is_editing is False
    assert obj in cls.bmesh_updates


def test_path_preserving_enable_one_post_load_data_hook_runs(patched_tool_and_ifc):
    """Railing overrides _post_load_data to JSON-serialise path_data —
    confirm the hook is honoured (here we drop a sentinel key)."""
    props = _FakePathProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 250, "extra": "drop_me"}
    }

    cls = _path_mixin_cls(match=True)
    cls._post_load_data = classmethod(lambda c, data: {k: v for k, v in data.items() if k != "extra"})
    cls._enable_one(obj)

    assert "extra" not in props.last_kwargs


def test_path_preserving_finish_one_short_circuits_when_draft_matches_stored(patched_tool_and_ifc):
    """Finish-without-changes must not call ``_update_pset`` or
    ``_update_modifier_ifc_data`` — every IFC commit creates a fresh
    ``IfcShapeRepresentation`` and burns an undo entry, so a no-op edit
    should be invisible from IFC's perspective."""
    # general matches stored exactly (modulo path_data which is merged in).
    props = _FakePathProps()  # general={"width": 200, "thickness": 10}
    props.is_editing = True
    obj = _make_obj(props)
    sentinel_path = {"points": [[0, 0]]}
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 200, "thickness": 10, "path_data": sentinel_path}
    }

    cls = _path_mixin_cls(match=True)
    cls._finish_one(obj, mock.Mock(name="context"))

    assert props.is_editing is False, "is_editing must still flip on no-op"
    assert not cls.pset_updates, "_update_pset must NOT fire on no-op finish"
    assert not cls.ifc_data_updates, "_update_modifier_ifc_data must NOT fire on no-op finish"


def test_path_preserving_cancel_one_short_circuits_when_draft_matches_stored(patched_tool_and_ifc):
    """Cancel-without-changes must skip ``_restore_viewport_after_cancel`` —
    the mesh on screen is still the committed representation, and rebuilding
    it on every cancel is wasteful (some subclass overrides reload a
    high-poly IFC representation rather than rebuild a preview mesh,
    which is expensive on long polylines)."""
    props = _FakePathProps()  # general={"width": 200, "thickness": 10}
    props.is_editing = True
    obj = _make_obj(props)
    sentinel_path = {"points": [[0, 0]]}
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 200, "thickness": 10, "path_data": sentinel_path}
    }

    cls = _path_mixin_cls(match=True)
    cls._cancel_one(obj, mock.Mock(name="context"))

    assert props.is_editing is False, "is_editing must still flip on no-op"
    assert not cls.bmesh_updates, "_restore_viewport_after_cancel must NOT fire on no-op cancel"


def test_path_preserving_enable_one_commits_placement_drift(patched_tool_and_ifc):
    """Path-preserving Enable mirrors FeatureModifier Enable: any pre-edit
    matrix_world drift commits to IFC at entry, otherwise Cancel restores
    from a stale ObjectPlacement. ``apply_scale=False`` so Enable doesn't
    bake object scale into geometry."""
    props = _FakePathProps()
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 250, "path_data": {"points": []}}
    }

    cls = _path_mixin_cls(match=True)
    cls._enable_one(obj)

    patched_tool_and_ifc["tool"].Geometry.commit_placement_if_moved.assert_called_once_with(obj, apply_scale=False)


def test_path_preserving_finish_one_commits_placement_drift_on_change(patched_tool_and_ifc):
    """Finish-with-changes commits placement after the pset/IFC writes —
    pset content is independent of matrix_world drift."""
    props = _FakePathProps()  # general={"width": 200, "thickness": 10}
    props.is_editing = True
    obj = _make_obj(props)
    # Stored differs from draft → triggers the commit path.
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 999, "thickness": 99, "path_data": {"points": []}}
    }

    cls = _path_mixin_cls(match=True)
    cls._finish_one(obj, mock.Mock(name="context"))

    patched_tool_and_ifc["tool"].Geometry.commit_placement_if_moved.assert_called_once_with(obj)


def test_path_preserving_finish_one_commits_placement_drift_on_no_change(patched_tool_and_ifc):
    """Even when the pset draft equals stored (no IFC write), the drift
    commit must still fire — matrix_world drift is independent of pset
    content, so an Enable → drag → Finish without prop changes must still
    persist the placement move."""
    props = _FakePathProps()  # general={"width": 200, "thickness": 10}
    props.is_editing = True
    obj = _make_obj(props)
    sentinel_path = {"points": [[0, 0]]}
    # Stored == draft → no-op pset path.
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 200, "thickness": 10, "path_data": sentinel_path}
    }

    cls = _path_mixin_cls(match=True)
    cls._finish_one(obj, mock.Mock(name="context"))

    patched_tool_and_ifc["tool"].Geometry.commit_placement_if_moved.assert_called_once_with(obj)
    assert not cls.pset_updates, "no-op finish must skip pset write"


def test_path_preserving_cancel_one_restores_placement_when_moved(patched_tool_and_ifc):
    """Cancel restores matrix_world from IFC when the user dragged during
    the edit — symmetric to FeatureModifier Cancel."""
    props = _FakePathProps()
    props.is_editing = True
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 200, "thickness": 10, "path_data": {"points": []}}
    }
    patched_tool_and_ifc["tool"].Ifc.is_moved.return_value = True

    cls = _path_mixin_cls(match=True)
    cls._cancel_one(obj, mock.Mock(name="context"))

    patched_tool_and_ifc["tool"].Geometry.restore_placement_from_ifc.assert_called_once_with(
        obj, patched_tool_and_ifc["element"]
    )


def test_path_preserving_cancel_one_skips_placement_restore_when_not_moved(patched_tool_and_ifc):
    """No drag → no restore. Cancel must not touch matrix_world for an
    unmoved object — the restore path is an undo-only safeguard."""
    props = _FakePathProps()
    props.is_editing = True
    obj = _make_obj(props)
    patched_tool_and_ifc["tool"].Model.get_modeling_bbim_pset_data.return_value = {
        "data_dict": {"width": 200, "thickness": 10, "path_data": {"points": []}}
    }
    patched_tool_and_ifc["tool"].Ifc.is_moved.return_value = False

    cls = _path_mixin_cls(match=True)
    cls._cancel_one(obj, mock.Mock(name="context"))

    patched_tool_and_ifc["tool"].Geometry.restore_placement_from_ifc.assert_not_called()


# ----------------------------------------------------------------------
# _ArrayEditMixin (array.py — list-of-layers, per-layer scope)
# ----------------------------------------------------------------------


class _FakeArrayProps:
    """Stand-in for BIMArrayProperties — direct attribute access (no kwargs methods).

    The array mixin doesn't fit FeatureModifierEditMixin or PathPreservingEditMixin
    because BBIM_Array stores a JSON list of layers rather than a dict. The mixin
    reads/writes props.count / props.x / props.y / props.z / props.method /
    props.use_local_space directly, and pairs ``is_editing`` (registry contract)
    with ``editing_item_index`` (which layer is being edited)."""

    def __init__(self):
        self.is_editing = False
        self.editing_item_index = -1
        self.count = 0
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.use_local_space = True
        self.method = "OFFSET"
        self.mirror_to_host = True


def _make_pset_layers(layers: list) -> str:
    return json.dumps(layers)


@pytest.fixture
def patched_array():
    """Patch tool / ifcopenshell on bonsai.bim.module.model.array so _ArrayEditMixin
    can be exercised without Blender state.

    Returns the mocks so each test configures pset return values and asserts call args."""
    target = "bonsai.bim.module.model.array"
    with mock.patch(f"{target}.tool") as mock_tool, mock.patch(f"{target}.ifcopenshell") as mock_ifc:
        element = mock.Mock(name="array_element")
        mock_tool.Ifc.get_entity.return_value = element
        mock_tool.Ifc.get.return_value = mock.Mock(name="ifc_file")
        mock_tool.Blender.Modifier.is_array.return_value = True
        mock_ifc.util.unit.calculate_unit_scale.return_value = 1.0  # SI=1 to keep math obvious
        # tool.Model.get_array_props is rebound per-test to return the FakeProps.
        yield {
            "tool": mock_tool,
            "ifc": mock_ifc,
            "element": element,
        }


def _make_array_obj(props):
    obj = mock.Mock(name="array_obj")
    obj.props = props
    # ``_parent_geometry_changed`` reads obj.bound_box to compare against the
    # first child's bbox; without this the helper crashes on ``Mock not
    # iterable`` for tests that call ``_finish_one`` directly. A unit-cube
    # bbox is fine — tests don't assert on the wipe-or-not branch.
    obj.bound_box = [(0.0, 0.0, 0.0)] * 8
    return obj


def test_array_enable_one_default_item_hydrates_layer_zero(patched_array):
    """``_enable_one(obj)`` defaults item=0 — loads the first layer's data
    and pairs ``is_editing=True`` with ``editing_item_index=0``."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [{"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"}]
    )

    _ArrayEditMixin._enable_one(obj)

    assert props.is_editing is True
    assert props.editing_item_index == 0
    assert props.count == 5
    assert props.x == 1.0
    assert props.method == "OFFSET"


def test_array_enable_one_with_item_hydrates_specified_layer(patched_array):
    """Multi-layer support: ``_enable_one(obj, item=1)`` loads layer[1] and
    records the index so Finish / Cancel target the right layer."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [
            {"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"},
            {"count": 3, "x": 0.0, "y": 2.0, "z": 0.0, "use_local_space": True, "method": "DISTRIBUTE"},
        ]
    )

    _ArrayEditMixin._enable_one(obj, item=1)

    assert props.is_editing is True
    assert props.editing_item_index == 1
    assert props.count == 3
    assert props.y == 2.0
    assert props.method == "DISTRIBUTE"


def test_array_enable_one_noop_when_item_out_of_range(patched_array):
    """Stale gizmo bindings (layer removed via panel since the gizmo was drawn)
    must not crash the operator. is_editing stays False, props untouched."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [{"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"}]
    )

    _ArrayEditMixin._enable_one(obj, item=7)

    assert props.is_editing is False
    assert props.editing_item_index == -1
    assert props.count == 0  # untouched


def test_array_enable_one_noop_when_element_not_array(patched_array):
    """is_array=False short-circuits via _resolve before any pset read."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["tool"].Blender.Modifier.is_array.return_value = False

    _ArrayEditMixin._enable_one(obj)

    assert props.is_editing is False
    patched_array["ifc"].util.element.get_pset.assert_not_called()


def test_array_finish_one_writes_back_to_recorded_layer(patched_array):
    """Finish reads ``editing_item_index`` to pick the target layer — not
    a fixed layer 0. Pset write is delegated to ``regenerate_array``."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = 1  # layer 1 is being edited
    props.count = 7
    props.x = 2.5
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [
            {"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"},
            {"count": 3, "x": 0.0, "y": 2.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"},
        ]
    )

    _ArrayEditMixin._finish_one(obj, mock.Mock(name="context"))

    assert props.is_editing is False
    assert props.editing_item_index == -1
    patched_array["tool"].Model.regenerate_array.assert_called_once()
    # Layer-1 draft values made it into the in-memory layers passed to regenerate.
    regen_layers = patched_array["tool"].Model.regenerate_array.call_args.args[1]
    assert regen_layers[1]["count"] == 7
    assert regen_layers[1]["x"] == 2.5
    # Layer 0 untouched.
    assert regen_layers[0]["count"] == 5


def test_array_finish_one_index_out_of_range_clears_flag_without_writing(patched_array):
    """An out-of-range ``editing_item_index`` (layer deleted mid-edit) must
    clear the flag rather than write to the wrong slot."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = 5  # out of range
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [{"count": 5, "x": 1.0, "y": 0.0, "z": 0.0}]
    )

    _ArrayEditMixin._finish_one(obj, mock.Mock())

    assert props.is_editing is False
    assert props.editing_item_index == -1
    # No IFC mutation: drift safeguard returns before remove_constraints /
    # regenerate_array / constrain_children_to_parent.
    patched_array["tool"].Model.regenerate_array.assert_not_called()


def test_array_finish_one_exception_leaves_draft_in_progress(patched_array):
    """Finish-on-exception contract: if regenerate_array raises, is_editing
    must stay True so the user's draft survives for retry."""
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = 0
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [{"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"}]
    )
    patched_array["tool"].Model.regenerate_array.side_effect = RuntimeError("simulated regen failure")

    with pytest.raises(RuntimeError, match="simulated regen failure"):
        _ArrayEditMixin._finish_one(obj, mock.Mock())

    assert props.is_editing is True
    assert props.editing_item_index == 0  # draft layer index preserved for retry


def test_array_cancel_one_rehydrates_and_clears(patched_array):
    from bonsai.bim.module.model.array import _ArrayEditMixin

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = 0
    props.count = 999  # draft value to be discarded
    obj = _make_array_obj(props)
    patched_array["tool"].Model.get_array_props.return_value = props
    patched_array["ifc"].util.element.get_pset.return_value = _make_pset_layers(
        [{"count": 5, "x": 1.0, "y": 0.0, "z": 0.0, "use_local_space": True, "method": "OFFSET"}]
    )

    _ArrayEditMixin._cancel_one(obj)

    assert props.is_editing is False
    assert props.count == 5  # restored from pset


# ----------------------------------------------------------------------
# _ParametricEditMixinBase._resolve guard
# ----------------------------------------------------------------------


def test_resolve_returns_none_when_obj_has_no_entity(patched_tool_and_ifc):
    cls = _door_mixin_cls(match=True)
    patched_tool_and_ifc["tool"].Ifc.get_entity.return_value = None
    obj = _make_obj(_FakeProps())

    assert cls._resolve(obj) is None


def test_resolve_returns_none_when_element_type_mismatch(patched_tool_and_ifc):
    cls = _door_mixin_cls(match=False)
    obj = _make_obj(_FakeProps())

    assert cls._resolve(obj) is None


def test_resolve_returns_tuple_when_match(patched_tool_and_ifc):
    cls = _door_mixin_cls(match=True)
    props = _FakeProps()
    obj = _make_obj(props)

    resolved = cls._resolve(obj)

    assert resolved is not None
    element, returned_props = resolved
    assert element is patched_tool_and_ifc["element"]
    assert returned_props is props


# ----------------------------------------------------------------------
# RemoveArrayLayerFromEdit dispatcher — trash-gizmo entry point that
# cancels the in-progress edit and deletes the layer atomically. The
# structural contract (inherits tool.Ifc.Operator so cancel + remove
# share one transaction) and the poll guard (mirrors execute's
# preconditions) are pinned here so the atomic-undo invariant + poll
# correctness can't silently regress.
# ----------------------------------------------------------------------


def test_remove_array_layer_from_edit_inherits_tool_ifc_operator():
    """The dispatcher chains two ``tool.Ifc.Operator`` sub-ops
    (``bim.cancel_editing_array`` + ``bim.remove_array``). It MUST itself
    inherit ``tool.Ifc.Operator`` so both sub-ops join one top-level
    transaction — otherwise a single click produces two undo steps AND
    a partial failure leaves the array in a torn state (draft discarded
    but layer still present)."""
    from bonsai import tool
    from bonsai.bim.module.model.array import RemoveArrayLayerFromEdit

    assert issubclass(RemoveArrayLayerFromEdit, tool.Ifc.Operator), (
        "RemoveArrayLayerFromEdit must inherit tool.Ifc.Operator so the "
        "cancel + remove chain runs as one IFC transaction (one undo step, "
        "atomic rollback on partial failure)."
    )
    # tool.Ifc.Operator subclasses define _execute (the wrapped body);
    # the @final execute on the base class is what opens the transaction.
    assert hasattr(RemoveArrayLayerFromEdit, "_execute"), (
        "tool.Ifc.Operator subclasses implement `_execute`; the base "
        "`execute` method is reserved (and @final) for transaction wiring."
    )


def test_remove_array_layer_from_edit_poll_rejects_when_editing_index_unset():
    """``poll`` must mirror ``_execute``'s preconditions so the trash
    gizmo correctly disables on stale states. ``is_editing=True`` with
    ``editing_item_index < 0`` is a transient drift state where execute
    would CANCEL — poll should report unavailable rather than show a
    clickable button that no-ops."""
    from unittest.mock import patch

    from bonsai.bim.module.model.array import RemoveArrayLayerFromEdit

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = -1  # drift state
    obj = _make_array_obj(props)
    ctx = mock.Mock(name="context")
    ctx.active_object = obj

    with patch("bonsai.bim.module.model.array.tool.Model.get_array_props", return_value=props):
        assert RemoveArrayLayerFromEdit.poll(ctx) is False


def test_remove_array_layer_from_edit_poll_accepts_when_index_in_range():
    """Healthy edit state (is_editing AND editing_item_index >= 0) ->
    poll True, button enabled."""
    from unittest.mock import patch

    from bonsai.bim.module.model.array import RemoveArrayLayerFromEdit

    props = _FakeArrayProps()
    props.is_editing = True
    props.editing_item_index = 0
    obj = _make_array_obj(props)
    ctx = mock.Mock(name="context")
    ctx.active_object = obj

    with patch("bonsai.bim.module.model.array.tool.Model.get_array_props", return_value=props):
        assert RemoveArrayLayerFromEdit.poll(ctx) is True
