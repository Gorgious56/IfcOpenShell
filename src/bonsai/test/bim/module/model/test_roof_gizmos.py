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

"""Unit tests for the roof parametric gizmo group.

Covers the parts of ``GizmoRoofEdition`` that don't need a live Blender
viewport: the mode-conditional ``visibility_condition`` lambdas, the
slope ``compute_value`` / ``apply_value`` roundtrip, the
``CycleRoofGenerationMethod`` operator metadata + cycle behaviour, the
footprint-extents helper, and the ``_update_dimension_gizmo_positions``
override (driven with a stub ``self`` that pre-seeds ``_frame_view_dir``
the way the base class's ``_prime_frame_caches`` would)."""

import math
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import pytest

pytestmark = pytest.mark.model


def _get_config(attr_name):
    """Return the ``DimensionGizmoConfig`` for ``attr_name`` from the roof gizmo."""
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    for cfg in GizmoRoofEdition.dimension_gizmo_props:
        if cfg.attr_name == attr_name:
            return cfg
    raise AssertionError(f"no DimensionGizmoConfig with attr_name={attr_name!r}")


# ----------------------------------------------------------------------------
# Mode-conditional visibility
# ----------------------------------------------------------------------------
#
# ``height`` and ``angle`` are mutually exclusive — exactly one is shown
# depending on ``generation_method``. ``roof_thickness`` applies regardless
# of the generation mode.


def test_height_gizmo_visible_only_in_height_mode():
    cfg = _get_config("height")
    assert cfg.visibility_condition(SimpleNamespace(generation_method="HEIGHT")) is True
    assert cfg.visibility_condition(SimpleNamespace(generation_method="ANGLE")) is False


def test_angle_gizmo_visible_only_in_angle_mode():
    cfg = _get_config("angle")
    assert cfg.visibility_condition(SimpleNamespace(generation_method="ANGLE")) is True
    assert cfg.visibility_condition(SimpleNamespace(generation_method="HEIGHT")) is False


def test_thickness_has_no_mode_gate():
    """Slab thickness applies to both generation modes — pinning
    ``visibility_condition is None`` guards against an accidental mode-gate
    being added later that would silently hide it when toggling modes."""
    assert _get_config("roof_thickness").visibility_condition is None


# ----------------------------------------------------------------------------
# Slope (angle) ↔ rise roundtrip
# ----------------------------------------------------------------------------
#
# The slope handle displays vertical rise at a fixed 1m run; dragging it
# updates ``props.angle`` via ``atan2(rise, run)``. Roundtrip preservation
# is the contract — feeding ``compute_value`` into ``apply_value`` must
# leave the angle unchanged (within float tolerance).


def test_slope_compute_value_returns_rise_at_reference_run():
    from bonsai.bim.module.model.roof import _ROOF_SLOPE_REFERENCE_RUN

    cfg = _get_config("angle")
    # 30° slope → rise = tan(30°) * 1m ≈ 0.5774 m
    props = SimpleNamespace(angle=math.radians(30))
    assert cfg.compute_value(props) == pytest.approx(math.tan(math.radians(30)) * _ROOF_SLOPE_REFERENCE_RUN)


def test_slope_apply_value_sets_angle_from_rise():
    from bonsai.bim.module.model.roof import _ROOF_SLOPE_REFERENCE_RUN

    cfg = _get_config("angle")
    props = SimpleNamespace(angle=0.0)
    cfg.apply_value(props, 0.5)
    assert props.angle == pytest.approx(math.atan2(0.5, _ROOF_SLOPE_REFERENCE_RUN))


def test_slope_roundtrip_preserves_angle():
    cfg = _get_config("angle")
    for deg in (5, 15, 30, 45, 60, 80):
        props = SimpleNamespace(angle=math.radians(deg))
        rise = cfg.compute_value(props)
        cfg.apply_value(props, rise)
        assert math.degrees(props.angle) == pytest.approx(deg, abs=1e-6)


def test_slope_apply_value_clamps_negative_to_zero():
    """A negative drag (rise < 0) must not produce a negative angle —
    ``atan2(-x, run)`` would yield a negative result, but ``apply_value``
    clamps to ``[0, pi/2 - 1e-3]`` so the roof never inverts."""
    cfg = _get_config("angle")
    props = SimpleNamespace(angle=math.radians(30))
    cfg.apply_value(props, -1.0)
    assert props.angle == 0.0


def test_slope_apply_value_clamps_at_near_vertical():
    """Slopes approaching 90° are clamped just below to avoid a vertical
    extrusion that would degenerate the bisect step in
    ``generate_hipped_roof_bmesh``."""
    from bonsai.bim.module.model.roof import _ROOF_MAX_SLOPE_ANGLE

    cfg = _get_config("angle")
    props = SimpleNamespace(angle=0.0)
    cfg.apply_value(props, 1e9)  # absurdly steep
    assert props.angle == pytest.approx(_ROOF_MAX_SLOPE_ANGLE)


# ----------------------------------------------------------------------------
# Cycle operator metadata
# ----------------------------------------------------------------------------
#
# ``CycleRoofGenerationMethod`` plugs into ``CycleTypeMixin`` so the
# HEIGHT ↔ ANGLE icon cycles through the two values. The mixin reads four
# class attributes to do its work; if any drift, the cycle no-ops or
# CANCELLED-loops in subtle ways. Pin them here.


def test_cycle_operator_class_metadata():
    from typing import get_args

    from bonsai import tool
    from bonsai.bim.module.model.roof import CycleRoofGenerationMethod

    assert CycleRoofGenerationMethod.bl_idname == "bim.cycle_roof_generation_method"
    assert CycleRoofGenerationMethod.element_checker == tool.Parametric.is_roof
    assert CycleRoofGenerationMethod.props_getter == tool.Model.get_roof_props
    assert CycleRoofGenerationMethod.type_attr == "generation_method"
    # The Literal resolves to ("HEIGHT", "ANGLE") — the mixin calls
    # ``get_args(type_literal)`` to enumerate the cycle.
    assert get_args(CycleRoofGenerationMethod.type_literal) == ("HEIGHT", "ANGLE")
    assert CycleRoofGenerationMethod.type_literal is tool.Model.RoofGenerationMethod


def test_cycle_operator_wired_on_gizmo_group():
    """The gizmo group's ``cycle_type_operator`` must match the bl_idname or
    the base class skips the cycle icon entirely (see gizmos.py:4987)."""
    from bonsai.bim.module.model.roof import CycleRoofGenerationMethod, GizmoRoofEdition

    assert GizmoRoofEdition.cycle_type_operator == CycleRoofGenerationMethod.bl_idname


def _cycle_stub_self(*, reverse: bool, props, element_is_target: bool = True):
    """Build a stub ``self`` for ``CycleTypeMixin._cycle_type``.

    ``bpy.types.Operator`` subclasses can't be ``__init__``-ed outside of
    Blender's registration path (``bpy_struct.__new__`` rejects a bare
    call). Calling the unbound mixin method with a stub ``self`` that
    mirrors the class attributes the method reads is the cleanest way to
    exercise the cycle logic without launching a registered operator
    instance.

    ``element_checker`` and ``props_getter`` are captured by the cycle
    operator at class-definition time, so global ``tool.*`` patches at
    test time can't intercept them — the stub injects callables directly
    instead. ``_resolve_target`` is bound from ``TypeAccessorBase`` so
    the cycle method's call into it dispatches against the stub
    attributes."""
    from types import MethodType

    from bonsai.bim.module.model.roof import CycleRoofGenerationMethod
    from bonsai.bim.parametric_lifecycle import TypeAccessorBase

    stub = SimpleNamespace(
        reverse=reverse,
        skip_element_check=False,
        element_checker=lambda _elem: element_is_target,
        props_getter=lambda _obj: props,
        type_literal=CycleRoofGenerationMethod.type_literal,
        type_attr=CycleRoofGenerationMethod.type_attr,
    )
    stub._resolve_target = MethodType(TypeAccessorBase._resolve_target, stub)
    return stub


def test_cycle_type_advances_forward():
    """``_cycle_type`` advances the prop value to the next item in the
    Literal. The stub injects ``element_checker`` / ``props_getter``
    directly so the method runs without a live IFC fixture."""
    from bonsai import tool
    from bonsai.bim import parametric_lifecycle as gizmo_module

    props = SimpleNamespace(generation_method="HEIGHT")
    context = SimpleNamespace(active_object=object())

    with patch.object(tool.Ifc, "get_entity", return_value=object()):
        result = gizmo_module.CycleTypeMixin._cycle_type(_cycle_stub_self(reverse=False, props=props), context)
    assert result == {"FINISHED"}
    assert props.generation_method == "ANGLE"


def test_cycle_type_reverse_walks_backward():
    """Shift+click sets ``reverse=True`` and walks the cycle in the other
    direction — from HEIGHT that means wrapping to ANGLE (the last item)."""
    from bonsai import tool
    from bonsai.bim import parametric_lifecycle as gizmo_module

    props = SimpleNamespace(generation_method="HEIGHT")
    context = SimpleNamespace(active_object=object())

    with patch.object(tool.Ifc, "get_entity", return_value=object()):
        gizmo_module.CycleTypeMixin._cycle_type(_cycle_stub_self(reverse=True, props=props), context)
    assert props.generation_method == "ANGLE"  # wrapped from HEIGHT backward


def test_cycle_type_cancels_when_active_is_not_a_roof():
    """Non-roof active object → CANCELLED, props untouched. Guards against
    a stray cycle click on a wall mutating ``wall.generation_method`` (a
    non-existent attr) and silently no-oping or AttributeError-ing later."""
    from bonsai import tool
    from bonsai.bim import parametric_lifecycle as gizmo_module

    props = SimpleNamespace(generation_method="HEIGHT")
    context = SimpleNamespace(active_object=object())

    with patch.object(tool.Ifc, "get_entity", return_value=object()):
        result = gizmo_module.CycleTypeMixin._cycle_type(
            _cycle_stub_self(reverse=False, props=props, element_is_target=False),
            context,
        )
    assert result == {"CANCELLED"}
    assert props.generation_method == "HEIGHT"


# ----------------------------------------------------------------------------
# Footprint extents helper — pset-data sourced, not mesh-sourced
# ----------------------------------------------------------------------------
#
# ``_get_footprint_extents`` reads ``RoofData.path_data["verts"]`` (project
# units), converts to SI, and returns ``(anchor_x, anchor_y, min_y, max_y,
# polyline_z)``. The anchor is Shapely's ``representative_point`` — a
# point guaranteed inside the polygon, including for L- and U-shaped
# footprints where the AABB centroid would fall outside the roof and
# leave the height/slope arrows visually floating in empty space.


def test_footprint_extents_returns_none_when_data_not_loaded():
    from bonsai.bim.module.model.data import RoofData
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    # The helper reads only the RoofData class state — passing a bare
    # ``SimpleNamespace`` as ``self`` to the unbound method works the same
    # way as the cycle-mixin tests above, and avoids the ``Operator``
    # / ``GizmoGroup`` no-instantiate restriction.
    with patch.object(RoofData, "is_loaded", False):
        result = GizmoRoofEdition._get_footprint_extents(SimpleNamespace())
    assert result is None


def test_footprint_extents_returns_none_when_path_data_missing():
    from bonsai.bim.module.model.data import RoofData
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    with patch.object(RoofData, "is_loaded", True), patch.object(RoofData, "data", {}):
        result = GizmoRoofEdition._get_footprint_extents(SimpleNamespace())
    assert result is None


def test_footprint_extents_returns_inside_anchor_and_polyline_z_in_si_units_for_rectangle():
    """Path data is stored in *project* units. The helper applies the unit
    scale so callers receive SI metres. For a convex rectangle the
    representative_point lands at the geometric centre — the anchor for a
    10 × 6 m rectangle should sit somewhere strictly inside. ``min_y`` and
    ``max_y`` round-trip the y bounds the override needs for the eave-side
    selection. ``polyline_z`` is taken from the first vertex per the
    BBIM_Roof contract that ``verts[0]`` is the footprint anchor."""
    from bonsai import tool
    from bonsai.bim.module.model.data import RoofData
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    # 4 verts of a 10×6 rectangle at z=2m, in *project* units (millimetres
    # — si_conversion 0.001 to convert to metres).
    path_data = {
        "verts": [(0.0, 0.0, 2000.0), (10000.0, 0.0, 2000.0), (10000.0, 6000.0, 2000.0), (0.0, 6000.0, 2000.0)]
    }
    with (
        patch.object(RoofData, "is_loaded", True),
        patch.object(RoofData, "data", {"path_data": path_data}),
        patch("ifcopenshell.util.unit.calculate_unit_scale", return_value=0.001),
        patch.object(tool.Ifc, "get", return_value=object()),
    ):
        result = GizmoRoofEdition._get_footprint_extents(SimpleNamespace())
    anchor_x, anchor_y, min_y, max_y, polyline_z = result
    assert 0.0 < anchor_x < 10.0
    assert 0.0 < anchor_y < 6.0
    assert min_y == pytest.approx(0.0)
    assert max_y == pytest.approx(6.0)
    assert polyline_z == pytest.approx(2.0)


def test_footprint_extents_anchor_lands_inside_polygon_for_l_shape():
    """The fix the AABB midpoint can't handle: an L-shaped footprint whose
    AABB centroid falls in the notch *outside* the polygon. The L below has
    its upper-right quadrant (``x ∈ [4, 10], y ∈ [4, 10]``) removed — the
    AABB centroid (5, 5) sits in that notch (x > 4 above y = 4 is outside
    the polygon). The representative_point lookup must land inside the L's
    body so the height/slope arrows visually attach to the roof."""
    import shapely

    from bonsai import tool
    from bonsai.bim.module.model.data import RoofData
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    l_shape_verts = [
        (0.0, 0.0, 0.0),
        (10000.0, 0.0, 0.0),
        (10000.0, 4000.0, 0.0),
        (4000.0, 4000.0, 0.0),
        (4000.0, 10000.0, 0.0),
        (0.0, 10000.0, 0.0),
    ]
    with (
        patch.object(RoofData, "is_loaded", True),
        patch.object(RoofData, "data", {"path_data": {"verts": l_shape_verts}}),
        patch("ifcopenshell.util.unit.calculate_unit_scale", return_value=0.001),
        patch.object(tool.Ifc, "get", return_value=object()),
    ):
        result = GizmoRoofEdition._get_footprint_extents(SimpleNamespace())
    anchor_x, anchor_y, *_ = result

    polygon = shapely.Polygon([(x * 0.001, y * 0.001) for x, y, _ in l_shape_verts])
    assert polygon.contains(shapely.Point(anchor_x, anchor_y))
    # Pin the regression: the AABB midpoint is NOT inside this polygon, so
    # any future "use bbox centre" shortcut would fail this assertion.
    assert not polygon.contains(shapely.Point(5.0, 5.0))


# ----------------------------------------------------------------------------
# _update_dimension_gizmo_positions — view-flip + footprint-aware anchoring
# ----------------------------------------------------------------------------
#
# The override repositions three handles each frame: ``height`` and ``angle``
# at the footprint centroid (axis Z+), ``roof_thickness`` on the
# camera-facing eave (axis Z-). Both arrows share the same anchor Z (the
# polyline elevation) so they read as "from the eave, the apex goes UP and
# the slab depth goes DOWN".


def _make_override_stub(extents, *, viewing_from_neg_y):
    """Build the minimal ``self`` ``_update_dimension_gizmo_positions`` reads.

    Records each ``set_dimension_gizmo_position`` call as a dict keyed by
    ``attr_name`` so tests can assert on which axes and positions were
    requested without depending on call order."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    calls: dict[str, tuple] = {}

    def record(attr_name, _mw, position, axis, _value=None):
        calls[attr_name] = (position, axis)

    stub = SimpleNamespace(
        _get_footprint_extents=lambda: extents,
        _frame_view_dir=(viewing_from_neg_y, False),
        get_camera_facing_outer_y=BaseParametricGizmoGroup.get_camera_facing_outer_y,
        set_dimension_gizmo_position=record,
        GIZMO_OFFSET=BaseParametricGizmoGroup.GIZMO_OFFSET,
    )
    stub._recorded_calls = calls
    return stub


def test_override_no_ops_when_extents_unavailable():
    """If ``path_data`` hasn't been loaded yet, the override must early-return
    rather than crash. The base class then leaves the matrix at Identity,
    which is the standard "no info" gizmo state."""
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    stub = _make_override_stub(extents=None, viewing_from_neg_y=False)
    GizmoRoofEdition._update_dimension_gizmo_positions(stub, context=None, mw=None, props=None)
    assert stub._recorded_calls == {}


def test_override_no_ops_when_view_dir_not_primed():
    """``_frame_view_dir`` is set by the base class's per-frame ``_prime_frame_caches``.
    If the override fires before that ran (a possible ordering on the very
    first redraw), it must early-return rather than unpack ``None``."""
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    stub = _make_override_stub(extents=(5.0, 3.0, 0.0, 6.0, 0.0), viewing_from_neg_y=False)
    stub._frame_view_dir = None
    GizmoRoofEdition._update_dimension_gizmo_positions(stub, context=None, mw=None, props=None)
    assert stub._recorded_calls == {}


def test_override_anchors_height_and_slope_at_inside_point_and_thickness_at_camera_facing_eave():
    """The extents tuple is ``(anchor_x, anchor_y, min_y, max_y,
    polyline_z)``. The override copies the anchor straight into the
    height/slope handles and uses ``min_y/max_y`` to pick the eave the
    thickness handle anchors at. Viewing from +Y → camera-facing eave is
    ``max_y + GIZMO_OFFSET``."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    stub = _make_override_stub(extents=(7.0, 3.0, 0.0, 6.0, 2.0), viewing_from_neg_y=False)
    GizmoRoofEdition._update_dimension_gizmo_positions(stub, context=None, mw=None, props=None)

    expected_eave_y = 6.0 + BaseParametricGizmoGroup.GIZMO_OFFSET
    assert stub._recorded_calls["height"][0].xyz[:] == pytest.approx((7.0, 3.0, 2.0))
    assert stub._recorded_calls["height"][1] == (0, 0, 1)
    assert stub._recorded_calls["angle"][0].xyz[:] == pytest.approx((7.0, 3.0, 2.0))
    assert stub._recorded_calls["angle"][1] == (0, 0, 1)
    assert stub._recorded_calls["roof_thickness"][0].xyz[:] == pytest.approx((7.0, expected_eave_y, 2.0))
    assert stub._recorded_calls["roof_thickness"][1] == (0, 0, -1)


def test_override_flips_thickness_to_near_eave_when_viewing_from_neg_y():
    """Orbiting to the -Y side of the roof must move the thickness handle to
    the ``min_y`` eave (pushed *outside* by ``-GIZMO_OFFSET`` per
    ``get_camera_facing_outer_y``'s contract). The inside-anchored height
    & slope handles stay put because their position has no Y-side bias."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup
    from bonsai.bim.module.model.roof import GizmoRoofEdition

    stub = _make_override_stub(extents=(7.0, 3.0, 0.0, 6.0, 2.0), viewing_from_neg_y=True)
    GizmoRoofEdition._update_dimension_gizmo_positions(stub, context=None, mw=None, props=None)

    expected_eave_y = 0.0 - BaseParametricGizmoGroup.GIZMO_OFFSET
    assert stub._recorded_calls["roof_thickness"][0].xyz[:] == pytest.approx((7.0, expected_eave_y, 2.0))
    # Inside-anchored handles are view-independent — unchanged from the +Y case.
    assert stub._recorded_calls["height"][0].xyz[:] == pytest.approx((7.0, 3.0, 2.0))
    assert stub._recorded_calls["angle"][0].xyz[:] == pytest.approx((7.0, 3.0, 2.0))


# ----------------------------------------------------------------------------
# Registration smoke test
# ----------------------------------------------------------------------------
#
# Pattern 4 from _shared/bonsai-test-patterns.md: assert the operator is
# actually registered as ``bim.cycle_roof_generation_method``. Catches
# ``bl_idname`` typos and missing-from-``classes``-tuple regressions at
# test time rather than at user-click time (the failure mode otherwise is
# a silent no-op on the cycle icon, because the gizmo base class skips the
# icon entirely if its ``cycle_type_operator`` resolves to nothing).


def test_cycle_operator_is_registered_under_bim_namespace():
    assert hasattr(bpy.ops.bim, "cycle_roof_generation_method")
