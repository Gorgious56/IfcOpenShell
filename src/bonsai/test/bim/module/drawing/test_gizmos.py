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


# ----------------------------------------------------------------------------
# Contract: no Gizmo subclass may use ``path_resolve`` from inside a render
# method. The pattern proved fragile across addon reloads — when the
# resolved path's PropertyGroup is unregistered or renamed, the resolve
# raises and the gizmo silently falls back to a default shape. State-aware
# visuals must use a static open/closed pair where the consumer decides
# visibility from a typed prop access (see GizmoLockOpen).
# ----------------------------------------------------------------------------


def test_no_path_resolve_in_gizmo_render_methods():
    """AST guard: classes named ``Gizmo*`` in the drawing gizmo module must
    not call ``.path_resolve(...)`` inside ``draw``, ``draw_select``, or
    ``get_custom_shape``. Pins the static-pair pattern."""
    import ast
    from pathlib import Path

    from bonsai.bim.module.drawing import gizmos as gizmos_module

    source_path = Path(gizmos_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    render_methods = {"draw", "draw_select", "get_custom_shape"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Gizmo"):
            continue
        for body_item in node.body:
            if not isinstance(body_item, ast.FunctionDef) or body_item.name not in render_methods:
                continue
            for sub in ast.walk(body_item):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "path_resolve"
                ):
                    offenders.append(f"{node.name}.{body_item.name}:{sub.lineno}")
    assert not offenders, (
        "Gizmo render method(s) invoke .path_resolve(); use the static "
        f"open/closed pair pattern instead. Offenders: {offenders}"
    )


# ----------------------------------------------------------------------------
# Contract: every concrete StaticTrisGizmoMixin subclass must declare a
# non-empty ``tris`` class attribute. Forgetting it produces an invisible /
# unclickable gizmo at first draw because ``setup()`` reads ``self.tris`` and
# silently builds an empty custom shape.
# ----------------------------------------------------------------------------


def test_every_static_tris_gizmo_subclass_declares_non_empty_tris():
    import inspect

    from bonsai.bim.module.drawing import gizmos as gizmos_module

    StaticTrisGizmoMixin = gizmos_module.StaticTrisGizmoMixin
    missing = []
    too_small = []
    for name, cls in inspect.getmembers(gizmos_module, inspect.isclass):
        if not (isinstance(cls, type) and issubclass(cls, StaticTrisGizmoMixin) and cls is not StaticTrisGizmoMixin):
            continue
        # Only concrete gizmos need `tris` — intermediate mixin classes (e.g.
        # TexturedQuadGizmoMixin) don't inherit bpy.types.Gizmo and rely on
        # their concrete subclasses to declare the geometry.
        if not issubclass(cls, bpy.types.Gizmo):
            continue
        if cls.__module__ != gizmos_module.__name__:
            continue
        tris = getattr(cls, "tris", None)
        if tris is None:
            missing.append(name)
            continue
        # ``tris`` is a flat sequence of (x, y, z) triples; one triangle = 3 triples.
        if len(tris) < 3:
            too_small.append(f"{name} (len={len(tris)})")
    assert not missing, (
        f"StaticTrisGizmoMixin subclass(es) missing the `tris` class attribute: {missing}. "
        f"Without `tris`, `setup()` cannot build a custom shape and the gizmo is invisible."
    )
    assert (
        not too_small
    ), f"StaticTrisGizmoMixin subclass(es) with under-3-vertex `tris` (cannot form a triangle): {too_small}."


# ----------------------------------------------------------------------------
# TexturedQuadGizmoMixin POC contracts. The mixin renders a PNG-backed quad
# in place of the inherited tris glyph. The tris path stays intact as the
# fallback when the texture pipeline fails — invariants below pin both the
# inheritance shape and the asset binding.
# ----------------------------------------------------------------------------


def test_textured_quad_gizmo_mixin_inherits_static_tris_mixin():
    from bonsai.bim.module.drawing.gizmos import (
        StaticTrisGizmoMixin,
        TexturedQuadGizmoMixin,
    )

    assert issubclass(TexturedQuadGizmoMixin, StaticTrisGizmoMixin), (
        "TexturedQuadGizmoMixin must inherit StaticTrisGizmoMixin so the tris "
        "draw/select path stays available as the fallback when the texture fails to load."
    )


def test_static_tris_gizmo_mixin_outline_enabled_by_default():
    """Default outline_alpha > 0 and outline_width > 0 keep icon glyphs legible
    against same-color backgrounds (white icon on white wall, dark on dark).
    Both invariants silently disable the visibility defence if violated."""
    from bonsai.bim.module.drawing.gizmos import StaticTrisGizmoMixin

    assert StaticTrisGizmoMixin.outline_alpha > 0.0, (
        "StaticTrisGizmoMixin.outline_alpha must default > 0; the outline halo "
        "is the primary defence against same-color-background invisibility."
    )
    assert StaticTrisGizmoMixin.outline_width > 0.0, (
        "outline_width must default > 0; a width of 0 collapses every outline "
        "pass onto the icon and silently disables the effect."
    )


def test_static_tris_gizmo_mixin_outline_uses_eight_directions():
    """The outline is rendered as 8 offset passes (cardinal + diagonal). Fewer
    passes leave gaps on the diagonals; uniform scaling alone biases the halo
    toward whichever side of origin the geometry extends from."""
    from bonsai.bim.module.drawing.gizmos import _OUTLINE_DIRECTIONS_8

    assert (
        len(_OUTLINE_DIRECTIONS_8) == 8
    ), f"Expected 8 outline directions (4 cardinal + 4 diagonal); got {len(_OUTLINE_DIRECTIONS_8)}."
    # Every direction should be unit-length so the halo is the same width
    # regardless of which side we sample.
    for dx, dy in _OUTLINE_DIRECTIONS_8:
        length = (dx * dx + dy * dy) ** 0.5
        assert abs(length - 1.0) < 1e-9, f"Outline direction ({dx}, {dy}) is not unit length (|{length}|)."


def test_every_static_tris_gizmo_draw_override_routes_through_outline_path():
    """Concrete StaticTrisGizmoMixin subclasses that override ``draw`` MUST
    call either ``super().draw(...)`` or ``draw_tris_with_outline(...)`` in
    the override body; otherwise the icon renders without its halo and
    becomes invisible against same-colour backgrounds."""
    import ast
    import inspect
    import textwrap

    from bonsai.bim.module.drawing import gizmos as gizmos_module

    StaticTrisGizmoMixin = gizmos_module.StaticTrisGizmoMixin
    offenders = []
    for name, cls in inspect.getmembers(gizmos_module, inspect.isclass):
        if not (issubclass(cls, StaticTrisGizmoMixin) and cls is not StaticTrisGizmoMixin):
            continue
        if not issubclass(cls, bpy.types.Gizmo):
            continue
        if cls.__module__ != gizmos_module.__name__:
            continue
        if "draw" not in cls.__dict__:
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls.__dict__["draw"])))
        routes_through_outline = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "draw"
                and isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name)
                and node.func.value.func.id == "super"
            ):
                routes_through_outline = True
                break
            if isinstance(node.func, ast.Name) and node.func.id == "draw_tris_with_outline":
                routes_through_outline = True
                break
        if not routes_through_outline:
            offenders.append(name)
    assert not offenders, (
        f"StaticTrisGizmoMixin subclass(es) override draw() without routing through the "
        f"outline path (super().draw / draw_tris_with_outline): {offenders}. "
        f"The icon will render without its dark halo."
    )


def test_gizmo_array_layer_indicator_declares_outlined_batch_slot():
    """``GizmoArrayLayerIndicator.setup()`` assigns ``self._outlined_batch``.
    Blender enforces ``__slots__`` on gizmo classes, so a missing slot here
    would silently raise ``AttributeError`` on first instantiation."""
    from bonsai.bim.module.drawing.gizmos import GizmoArrayLayerIndicator

    assert "_outlined_batch" in GizmoArrayLayerIndicator.__slots__, (
        "_outlined_batch must be declared in __slots__; without it, setup() "
        "raises AttributeError under Blender's strict slot enforcement."
    )


def test_every_textured_quad_gizmo_subclass_declares_quad_batch_slot():
    """Concrete TexturedQuadGizmoMixin subclasses assign ``self._quad_batch``
    in setup(); Blender enforces ``__slots__`` on Gizmo classes, so a missing
    slot silently raises ``AttributeError`` on first instantiation. Vacuous
    while no concrete subclass exists — fires the day someone migrates an
    icon to the texture path without declaring the slot."""
    import inspect

    from bonsai.bim.module.drawing import gizmos as gizmos_module
    from bonsai.bim.module.drawing.gizmos import TexturedQuadGizmoMixin

    missing = []
    for name, cls in inspect.getmembers(gizmos_module, inspect.isclass):
        if not (
            isinstance(cls, type) and issubclass(cls, TexturedQuadGizmoMixin) and cls is not TexturedQuadGizmoMixin
        ):
            continue
        if not issubclass(cls, bpy.types.Gizmo):
            continue
        if cls.__module__ != gizmos_module.__name__:
            continue
        if "_quad_batch" not in cls.__slots__:
            missing.append(name)
    assert not missing, (
        f"TexturedQuadGizmoMixin subclass(es) missing `_quad_batch` in __slots__: {missing}. "
        f"setup() assigns self._quad_batch; without the slot, Blender raises AttributeError."
    )


def test_gizmo_textures_cache_falls_back_on_missing_image(monkeypatch):
    from bonsai.bim.module.drawing import gizmo_textures

    monkeypatch.setattr(gizmo_textures, "_texture_cache", {})
    monkeypatch.setattr(gizmo_textures, "_loaded_images", set())

    # Non-existent icon name: filesystem check returns False, no exception.
    assert gizmo_textures.get_icon_texture("definitely_not_a_real_icon_xyz") is None
    # Empty name is treated as missing, not an error.
    assert gizmo_textures.get_icon_texture("") is None


def test_clear_gizmo_gpu_caches_on_load_handler_registered():
    """``bim/__init__.py`` must register a load_post handler that clears
    both gizmo GPU caches (texture + static-tris batches). Both hold GPU
    resources that go stale across blend-file reloads and addon teardown."""
    import os

    import bonsai

    bim_init_path = os.path.join(os.path.dirname(bonsai.__file__), "bim", "__init__.py")
    with open(bim_init_path, encoding="utf-8") as f:
        src = f.read()
    assert "_clear_gizmo_gpu_caches_on_load" in src, "Expected a load_post handler clearing both gizmo GPU caches."
    assert "gizmo_textures.clear_cache()" in src, "unregister() / load_post must call gizmo_textures.clear_cache()."
    assert "gizmos.clear_static_tris_cache()" in src, (
        "unregister() / load_post must call gizmos.clear_static_tris_cache() "
        "so the per-class GPUBatch dict doesn't keep stale references after a reload."
    )


# ----------------------------------------------------------------------------
# CountGizmoConfig validation contract. The __post_init__ guards the two
# invariants that keep the drag-snap-to-int handle from misbehaving:
# min_count <= max_count, and step >= 1. Drop or relax either and the gizmo
# can clamp to an empty range or snap by zero — silent visual freeze.
# ----------------------------------------------------------------------------


def test_count_gizmo_config_rejects_min_greater_than_max():
    from bonsai.bim.module.drawing.gizmos import CountGizmoConfig

    with pytest.raises(ValueError, match="min_count .* must be <= max_count"):
        CountGizmoConfig(attr_name="count", axis=(1, 0, 0), min_count=5, max_count=3)


def test_count_gizmo_config_rejects_step_below_one():
    from bonsai.bim.module.drawing.gizmos import CountGizmoConfig

    with pytest.raises(ValueError, match="step must be >= 1"):
        CountGizmoConfig(attr_name="count", axis=(1, 0, 0), step=0)


def test_count_gizmo_config_rejects_negative_step():
    from bonsai.bim.module.drawing.gizmos import CountGizmoConfig

    with pytest.raises(ValueError, match="step must be >= 1"):
        CountGizmoConfig(attr_name="count", axis=(1, 0, 0), step=-1)


# ----------------------------------------------------------------------------
# IconActionConfig.visibility_condition is the per-icon hide hook used by
# BaseIconActionGroup.position_gizmos. The contract is "callable taking the
# active object and returning a truthy/falsy value". MEP exercises it via
# integration paths; pin the contract in isolation so a refactor that
# changes the signature trips here first.
# ----------------------------------------------------------------------------


def test_icon_action_config_visibility_condition_defaults_to_none():
    from bonsai.bim.module.drawing.gizmos import IconActionConfig

    config = IconActionConfig(name="x", icon="VIEW3D_GT_cycle", operator="bim.test")
    assert config.visibility_condition is None


def test_icon_action_config_visibility_condition_stores_and_invokes_predicate():
    from bonsai.bim.module.drawing.gizmos import IconActionConfig

    sentinel = object()
    config = IconActionConfig(
        name="x",
        icon="VIEW3D_GT_cycle",
        operator="bim.test",
        visibility_condition=lambda obj: obj is sentinel,
    )
    assert config.visibility_condition is not None
    assert config.visibility_condition(sentinel) is True


# ----------------------------------------------------------------------------
# _make_dimension_setter: ``min_value`` is consulted only in the default
# ``attr_name`` path. When a custom ``apply_value`` is supplied, the framework
# forwards the raw dragged value unmodified — the callback owns any bounding
# (pass-through, absolutise, atan2-recover) and choosing the lambda is itself
# the opt-in to that responsibility. Pins the contract so future framework
# edits don't quietly re-introduce a clamp in the apply_value branch.
# ----------------------------------------------------------------------------


def test_dimension_setter_forwards_raw_value_when_apply_value_supplied():
    """A custom ``apply_value`` lambda must receive the dragged value
    unmodified, even when it falls below the config's ``min_value``."""
    from unittest import mock

    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    received = []
    config = DimensionGizmoConfig(
        attr_name="x",
        axis=(1, 0, 0),
        min_value=10.0,
        apply_value=lambda props, value: received.append(value),
    )
    fake_self = SimpleNamespace(get_props=lambda obj: SimpleNamespace())
    setter = BaseParametricGizmoGroup._make_dimension_setter(fake_self, config)

    with mock.patch("bonsai.bim.module.drawing.gizmos.bpy.context") as ctx:
        ctx.active_object = mock.Mock()
        setter(-5.0)

    assert received == [-5.0]


def test_dimension_setter_clamps_to_min_value_in_default_attr_path():
    """The default ``attr_name`` setter still enforces ``min_value`` as a
    floor — the framework owns the clamp when the caller hasn't opted into
    a custom ``apply_value``."""
    from unittest import mock

    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    props = SimpleNamespace()
    config = DimensionGizmoConfig(
        attr_name="x",
        axis=(1, 0, 0),
        min_value=0.5,
        visibility_condition=lambda obj: False,
    )
    fake_self = SimpleNamespace(get_props=lambda obj: props)
    setter = BaseParametricGizmoGroup._make_dimension_setter(fake_self, config)

    with mock.patch("bonsai.bim.module.drawing.gizmos.bpy.context") as ctx:
        ctx.active_object = mock.Mock()
        setter(-3.0)

    assert props.x == 0.5
    assert config.visibility_condition(object()) is False


# ----------------------------------------------------------------------------
# Callable dispatch contract for CycleTypeMixin and BaseParametricGizmoGroup
# ----------------------------------------------------------------------------
#
# ``element_checker`` and ``props_getter`` are class attributes captured at
# class-definition time. A typo'd string regression (e.g. ``props_getter =
# "get_root_props"`` instead of ``tool.Model.get_roof_props``) won't surface
# until a user actually clicks the affected gizmo — the type hint is
# annotation-only, not runtime-enforced. These tests enumerate the concrete
# subclasses so any future drift fails at collection time.


def test_cycle_operator_dispatch_attrs_are_callable():
    from bonsai.bim.module.model.railing import CycleRailingType
    from bonsai.bim.module.model.roof import CycleRoofGenerationMethod

    for op in (CycleRailingType, CycleRoofGenerationMethod):
        if not getattr(op, "skip_element_check", False):
            assert callable(op.element_checker), f"{op.__name__}.element_checker must be callable"
        assert callable(op.props_getter), f"{op.__name__}.props_getter must be callable"


def test_pick_operator_dispatch_attrs_are_callable():
    """Sibling of the cycle-attr contract test for ``PickTypeMixin`` consumers.

    Picker operators use the same class-attr interface as cycle operators
    (``element_checker``, ``props_getter``, ``type_literal``, ``type_attr``);
    a typo'd string binding would only surface when a user clicks the menu
    gizmo on the wrong element type. Catching that at collection time."""
    from bonsai.bim.module.model.door import PickDoorType
    from bonsai.bim.module.model.railing import PickRailingTerminalType
    from bonsai.bim.module.model.stair import PickStairType
    from bonsai.bim.module.model.window import PickWindowType

    for op in (PickDoorType, PickWindowType, PickStairType, PickRailingTerminalType):
        if not getattr(op, "skip_element_check", False):
            assert callable(op.element_checker), f"{op.__name__}.element_checker must be callable"
        assert callable(op.props_getter), f"{op.__name__}.props_getter must be callable"


def test_parametric_gizmo_group_props_getter_is_callable():
    from bonsai.bim.module.model.array import GizmoArrayEdition
    from bonsai.bim.module.model.door import GizmoDoorEdition
    from bonsai.bim.module.model.mep import (
        GizmoDuctSegmentEdition,
        GizmoPipeSegmentEdition,
    )
    from bonsai.bim.module.model.roof import GizmoRoofEdition
    from bonsai.bim.module.model.stair import GizmoStairEdition
    from bonsai.bim.module.model.wall import GizmoWallEdition
    from bonsai.bim.module.model.window import GizmoWindowEdition

    for cls in (
        GizmoDoorEdition,
        GizmoWindowEdition,
        GizmoStairEdition,
        GizmoWallEdition,
        GizmoRoofEdition,
        GizmoArrayEdition,
        GizmoPipeSegmentEdition,
        GizmoDuctSegmentEdition,
    ):
        assert callable(cls.props_getter), f"{cls.__name__}.props_getter must be callable"


# The callable-only contract tests above catch typo'd strings but not
# wrong-but-callable bindings (e.g. a picker's ``element_checker`` mistakenly
# pointing at ``tool.Blender.Modifier.is_window`` when it should be
# ``is_door``). Those would silently pass at class-load and only surface when
# the user clicks the gizmo on the wrong element. The tests below pin the
# exact predicate / props lookup per subclass so any swap fails at
# collection time. Roof and railing have equivalent pins in their per-feature
# test files (test_roof_gizmos.py, test_railing_schematic.py).


def test_cycle_operator_dispatch_routes_to_matching_modifier_and_props():
    from bonsai import tool
    from bonsai.bim.module.model.railing import CycleRailingType
    from bonsai.bim.module.model.roof import CycleRoofGenerationMethod

    # element_checker: (cycle_op, expected predicate or None when skip_element_check).
    element_checker_expectations = [
        (CycleRailingType, tool.Blender.Modifier.is_railing),
        (CycleRoofGenerationMethod, tool.Blender.Modifier.is_roof),
    ]
    for op, expected in element_checker_expectations:
        if expected is None:
            assert getattr(
                op, "skip_element_check", False
            ), f"{op.__name__} declares no element_checker but is not marked skip_element_check"
        else:
            assert (
                op.element_checker == expected
            ), f"{op.__name__}.element_checker is not bound to the expected predicate"

    props_getter_expectations = [
        (CycleRailingType, tool.Model.get_railing_props),
        (CycleRoofGenerationMethod, tool.Model.get_roof_props),
    ]
    for op, expected in props_getter_expectations:
        assert op.props_getter == expected, f"{op.__name__}.props_getter is not bound to the expected props lookup"


def test_pick_operator_dispatch_routes_to_matching_modifier_and_props():
    """Sibling pin-test for ``PickTypeMixin`` consumers. Mirrors the cycle
    contract — picker operators must bind to the matching modifier predicate
    and props getter."""
    from bonsai import tool
    from bonsai.bim.module.model.door import PickDoorType
    from bonsai.bim.module.model.railing import PickRailingTerminalType
    from bonsai.bim.module.model.stair import PickStairType
    from bonsai.bim.module.model.window import PickWindowType

    element_checker_expectations = [
        (PickDoorType, tool.Blender.Modifier.is_door),
        (PickWindowType, tool.Blender.Modifier.is_window),
        (PickStairType, None),  # skip_element_check=True — no checker bound
        (PickRailingTerminalType, None),  # skip_element_check=True — gate via resolve_active_props_for_edit
    ]
    for op, expected in element_checker_expectations:
        if expected is None:
            assert getattr(
                op, "skip_element_check", False
            ), f"{op.__name__} declares no element_checker but is not marked skip_element_check"
        else:
            assert (
                op.element_checker == expected
            ), f"{op.__name__}.element_checker is not bound to the expected predicate"

    props_getter_expectations = [
        (PickDoorType, tool.Model.get_door_props),
        (PickWindowType, tool.Model.get_window_props),
        (PickStairType, tool.Model.get_stair_props),
        (PickRailingTerminalType, tool.Model.get_railing_props),
    ]
    for op, expected in props_getter_expectations:
        assert op.props_getter == expected, f"{op.__name__}.props_getter is not bound to the expected props lookup"


def test_parametric_gizmo_group_props_getter_routes_to_matching_props():
    from bonsai import tool
    from bonsai.bim.module.model.array import GizmoArrayEdition
    from bonsai.bim.module.model.door import GizmoDoorEdition
    from bonsai.bim.module.model.mep import (
        GizmoDuctSegmentEdition,
        GizmoPipeSegmentEdition,
    )
    from bonsai.bim.module.model.stair import GizmoStairEdition
    from bonsai.bim.module.model.wall import GizmoWallEdition
    from bonsai.bim.module.model.window import GizmoWindowEdition

    expectations = [
        (GizmoDoorEdition, tool.Model.get_door_props),
        (GizmoWindowEdition, tool.Model.get_window_props),
        (GizmoStairEdition, tool.Model.get_stair_props),
        (GizmoWallEdition, tool.Model.get_wall_props),
        (GizmoArrayEdition, tool.Model.get_array_props),
        (GizmoPipeSegmentEdition, tool.Model.get_pipe_segment_props),
        (GizmoDuctSegmentEdition, tool.Model.get_duct_segment_props),
    ]
    for cls, expected in expectations:
        assert cls.props_getter == expected, f"{cls.__name__}.props_getter is not bound to the expected props lookup"


def test_pick_operator_wired_on_pick_type_operator_slot():
    """``PickTypeMixin`` operators must bind via ``pick_type_operator``, not
    ``cycle_type_operator`` — ``BaseParametricGizmoGroup.setup`` resolves the
    icon by which slot is non-empty (cycle arrow vs menu glyph), so a pick
    operator wired into the cycle slot renders the wrong icon. Mirror of
    test_roof_gizmos.py::test_cycle_operator_wired_on_gizmo_group for the
    pick path."""
    from bonsai.bim.module.drawing.gizmos import PickTypeMixin
    from bonsai.bim.module.model.door import GizmoDoorEdition, PickDoorType
    from bonsai.bim.module.model.stair import GizmoStairEdition, PickStairType
    from bonsai.bim.module.model.window import GizmoWindowEdition, PickWindowType

    expectations = [
        (PickDoorType, GizmoDoorEdition),
        (PickWindowType, GizmoWindowEdition),
        (PickStairType, GizmoStairEdition),
    ]
    for op_cls, gg_cls in expectations:
        assert issubclass(op_cls, PickTypeMixin), f"{op_cls.__name__} does not inherit PickTypeMixin"
        assert (
            gg_cls.pick_type_operator == op_cls.bl_idname
        ), f"{gg_cls.__name__}.pick_type_operator must match {op_cls.__name__}.bl_idname"
        assert (
            not gg_cls.cycle_type_operator
        ), f"{gg_cls.__name__} sets cycle_type_operator alongside pick_type_operator — the icon slot is mutually exclusive"
