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

"""Tests for the live wall-connection move/rotate preview.

Coverage:

- ``_is_unsafe_extend`` math: TRIM is always safe; an EXTEND whose delta
  exceeds the configured multiple of the original axis flips to unsafe;
  degenerate inputs flag unsafe.
- Registry contract: every entry in ``preview_base.PREVIEW_CANCEL_OPS``
  resolves to a registered ``bim.<op>`` operator AND maps to a child
  PointerProperty on ``BIMPreviewProperties``. Forward-compat guard so a
  future preview registration that forgets one half of the pair fails CI.
- Decorator install/uninstall symmetry through the three operator exits
  (pre, post, cancel) so a missing teardown surfaces as a test failure
  rather than a stale draw handler.
"""

import types
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import pytest
from mathutils import Vector

from bonsai.bim.module.model import connected_move_preview as cmp
from bonsai.bim.module.model import preview_base

pytestmark = pytest.mark.wall


@pytest.fixture(autouse=True)
def _require_real_bpy():
    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")


@pytest.fixture(autouse=True)
def _clean_preview_state():
    """Each test starts with no decorator registered and no watcher armed."""
    if cmp.WallConnectionPreviewDecorator.is_installed:
        cmp.WallConnectionPreviewDecorator.uninstall()
    cmp._uninstall_cancel_watcher()
    cmp._clear_preview_state(bpy.context.scene)
    yield
    if cmp.WallConnectionPreviewDecorator.is_installed:
        cmp.WallConnectionPreviewDecorator.uninstall()
    cmp._uninstall_cancel_watcher()
    cmp._clear_preview_state(bpy.context.scene)


# --- _is_unsafe_extend math --------------------------------------------------


class TestUnsafeExtendMath:
    def test_trim_case_is_always_safe(self):
        """Intersection inside the original segment = trim; bounded delta,
        never unsafe regardless of the multiplier."""
        p0, p1 = Vector((0, 0, 0)), Vector((10, 0, 0))
        intersection = Vector((3, 0, 0))
        assert not cmp._is_unsafe_extend(p0, p1, intersection, max_ratio=2.0)

    def test_extend_within_ratio_is_safe(self):
        """A 2× extension under a 10× threshold stays safe."""
        p0, p1 = Vector((0, 0, 0)), Vector((10, 0, 0))
        intersection = Vector((-15, 0, 0))  # 15 units past near=0,0,0; original=10
        assert not cmp._is_unsafe_extend(p0, p1, intersection, max_ratio=10.0)

    def test_extend_beyond_ratio_is_unsafe(self):
        """An extension > max_ratio × original length flags as unsafe."""
        p0, p1 = Vector((0, 0, 0)), Vector((1, 0, 0))  # 1m wall
        intersection = Vector((-50, 0, 0))  # 50× extension
        assert cmp._is_unsafe_extend(p0, p1, intersection, max_ratio=10.0)

    def test_degenerate_segment_is_unsafe(self):
        """Zero-length input is treated as unsafe — refuses to recalc rather
        than risk dividing by zero downstream."""
        p0 = p1 = Vector((0, 0, 0))
        intersection = Vector((1, 0, 0))
        assert cmp._is_unsafe_extend(p0, p1, intersection, max_ratio=10.0)


# --- PREVIEW_CANCEL_OPS registry contract ------------------------------------


class TestPreviewCancelOpsContract:
    """Forward-compat guard: every preview registered for Esc dispatch must
    have both an operator the user can invoke and a child PointerProperty
    the gizmo polls / load_post discards consult. A future preview that
    appends only half of the pair will fail one of these assertions."""

    def test_every_entry_resolves_to_a_registered_operator(self):
        """``getattr(bpy.ops.bim, op_name)`` succeeds → operator exists at
        the dotted path the Esc dispatcher walks."""
        for attr, op_name in preview_base.PREVIEW_CANCEL_OPS:
            op = getattr(bpy.ops.bim, op_name, None)
            assert op is not None, f"PREVIEW_CANCEL_OPS entry ('{attr}', '{op_name}') points at a missing operator"

    def test_connected_move_entry_targets_our_cancel_op(self):
        """Pin the specific contract for the entry this module owns. A rename
        of ``CancelConnectedMovePreview`` without updating the registry
        breaks Esc cancellation silently — this assertion catches it."""
        assert ("connected_move", "cancel_connected_move_preview") in preview_base.PREVIEW_CANCEL_OPS

    def test_idle_state_invariants(self):
        """Pin the addon's rest state: when no preview is running, the
        decorator is NOT installed, the cancel watcher is NOT in the
        ``depsgraph_update_post`` list, ``is_active`` is False, and the
        cleanup-dedupe flag is False. A register/unregister leak — or a
        missed teardown in any operator — fails this assertion.

        Sits in TestPreviewCancelOpsContract because the contract being
        pinned is the same shape: a registry-level invariant that has to
        hold any time the addon is sitting idle."""
        assert not cmp.WallConnectionPreviewDecorator.is_installed
        assert cmp._watch_for_preview_cancel not in bpy.app.handlers.depsgraph_update_post
        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        assert cm.is_active is False
        assert cm.has_seen_movement is False
        assert len(cm.moved_wall_ifc_ids) == 0
        assert cmp._cancel_cleanup_scheduled is False

    def test_load_post_and_undo_post_handlers_registered(self):
        """Pin: the three persistent handlers are wired into Blender's
        handler lists. A register/unregister symmetry break — or a
        partial hot-reload — would silently disable cancel detection on
        Ctrl+Z and per-session unsafe-pair memory clearing."""
        assert cmp._clear_unsafe_pair_memory in bpy.app.handlers.load_post
        assert cmp._discard_on_undo_redo in bpy.app.handlers.undo_post
        assert cmp._discard_on_undo_redo in bpy.app.handlers.redo_post

    def test_connected_move_child_exists_on_preview_umbrella(self):
        """``Scene.BIMPreviewProperties.connected_move`` must be a populated
        PointerProperty after register. Without it, ``is_preview_active``
        and the decorator both no-op silently."""
        scene = bpy.context.scene
        preview = getattr(scene, "BIMPreviewProperties", None)
        assert preview is not None, "BIMPreviewProperties umbrella not attached to Scene"
        assert hasattr(preview, "connected_move"), "connected_move child PointerProperty missing"


# --- Decorator install/uninstall lifecycle -----------------------------------


def _make_wall_obj(name: str, ifc_id: int):
    """Real Blender object backed by a stub IFC entity. Avoids fixture
    overhead of a real ``ifcopenshell.file()`` while still exercising the
    decorator's draw_handler registration and the operators' state
    mutations against a real Scene."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = (0, 0, 0)
    return obj, SimpleNamespace(id=lambda: ifc_id, ConnectedTo=[], ConnectedFrom=[], is_a=lambda t: t == "IfcWall")


@pytest.fixture
def two_connected_walls():
    a_obj, a_el = _make_wall_obj("Wall.A", 101)
    b_obj, b_el = _make_wall_obj("Wall.B", 102)
    # Fake an IfcRelConnectsPathElements pair between them.
    rel = SimpleNamespace(
        RelatingElement=a_el,
        RelatedElement=b_el,
        RelatingConnectionType="ATEND",
        RelatedConnectionType="ATSTART",
        is_a=lambda t: t == "IfcRelConnectsPathElements",
    )
    a_el.ConnectedTo = [rel]
    b_el.ConnectedFrom = [rel]
    yield a_obj, b_obj, a_el, b_el
    for o in (a_obj, b_obj):
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)


def _patched_tools(entity_map, prefs_enabled=True):
    """Mock tool.Ifc.get_entity and the addon-pref toggle so the operators
    can be exercised without a real IFC project loaded."""
    addon_prefs = SimpleNamespace(should_use_connected_move_preview=prefs_enabled)
    from bonsai import tool

    return [
        patch.object(tool.Blender, "get_addon_preferences", return_value=addon_prefs),
        patch.object(tool.Ifc, "get_entity", side_effect=lambda obj: entity_map.get(id(obj))),
    ]


class TestLifecycle:
    def test_pre_step_arms_decorator_and_watcher(self, two_connected_walls):
        a_obj, b_obj, a_el, b_el = two_connected_walls
        bpy.context.view_layer.objects.active = a_obj
        a_obj.select_set(True)
        entity_map = {id(a_obj): a_el, id(b_obj): b_el}

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in _patched_tools(entity_map):
                stack.enter_context(p)
            stack.enter_context(patch.object(cmp, "sync_uncommitted_moves", side_effect=lambda objs: None))
            bpy.ops.bim.pre_connected_move_preview()

        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        assert cm.is_active is True
        assert cmp.WallConnectionPreviewDecorator.is_installed
        assert cmp._watch_for_preview_cancel in bpy.app.handlers.depsgraph_update_post

    def test_cancel_op_tears_down_everything(self, two_connected_walls):
        a_obj, b_obj, a_el, b_el = two_connected_walls
        bpy.context.view_layer.objects.active = a_obj
        a_obj.select_set(True)
        entity_map = {id(a_obj): a_el, id(b_obj): b_el}

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in _patched_tools(entity_map):
                stack.enter_context(p)
            stack.enter_context(patch.object(cmp, "sync_uncommitted_moves", side_effect=lambda objs: None))
            bpy.ops.bim.pre_connected_move_preview()
        bpy.ops.bim.cancel_connected_move_preview()

        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        assert cm.is_active is False
        assert len(cm.moved_wall_ifc_ids) == 0
        assert not cmp.WallConnectionPreviewDecorator.is_installed
        assert cmp._watch_for_preview_cancel not in bpy.app.handlers.depsgraph_update_post

    def test_watcher_first_moved_tick_flips_has_seen_movement(self, two_connected_walls):
        """Pin: on the first depsgraph tick where any tracked wall reports
        ``is_moved=True``, the watcher must flip ``has_seen_movement``.
        Without this gate, the trailing all-not-moved tick would falsely
        trigger cleanup before the user had moved anything."""
        a_obj, b_obj, a_el, b_el = two_connected_walls
        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        cm.is_active = True
        item = cm.moved_wall_ifc_ids.add()
        item.value = a_el.id()

        from contextlib import ExitStack

        from bonsai import tool as _tool

        with ExitStack() as stack:
            ifc_stub = SimpleNamespace(by_id=lambda i: a_el if i == a_el.id() else None)
            stack.enter_context(patch.object(_tool.Ifc, "get", return_value=ifc_stub))
            stack.enter_context(patch.object(_tool.Ifc, "get_object", return_value=a_obj))
            stack.enter_context(patch.object(_tool.Ifc, "is_moved", return_value=True))

            cmp._watch_for_preview_cancel(bpy.context.scene, None)

        assert cm.has_seen_movement is True

    def test_watcher_returns_to_baseline_schedules_cleanup(self, two_connected_walls):
        """Pin: after the moved→baseline transition the watcher schedules
        one cleanup timer; the dedupe guard prevents stacking duplicates
        on the subsequent ticks before the timer runs."""
        a_obj, b_obj, a_el, b_el = two_connected_walls
        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        cm.is_active = True
        cm.has_seen_movement = True
        item = cm.moved_wall_ifc_ids.add()
        item.value = a_el.id()

        from contextlib import ExitStack

        from bonsai import tool as _tool

        cmp._cancel_cleanup_scheduled = False
        registered: list = []
        with ExitStack() as stack:
            ifc_stub = SimpleNamespace(by_id=lambda i: a_el if i == a_el.id() else None)
            stack.enter_context(patch.object(_tool.Ifc, "get", return_value=ifc_stub))
            stack.enter_context(patch.object(_tool.Ifc, "get_object", return_value=a_obj))
            stack.enter_context(patch.object(_tool.Ifc, "is_moved", return_value=False))
            stack.enter_context(
                patch.object(bpy.app.timers, "register", side_effect=lambda fn, **kw: registered.append(fn))
            )

            cmp._watch_for_preview_cancel(bpy.context.scene, None)
            assert len(registered) == 1, "First baseline tick must schedule cleanup"

            cmp._watch_for_preview_cancel(bpy.context.scene, None)
            assert len(registered) == 1, "Second baseline tick must NOT stack a duplicate cleanup"

        cmp._cancel_cleanup_scheduled = False

    def test_watcher_self_uninstalls_when_inactive(self):
        """Pin: the watcher removes itself from ``depsgraph_update_post``
        when it fires against ``is_active=False`` — defensive cleanup
        against stale handler registrations after a missed teardown."""
        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        cm.is_active = False
        bpy.app.handlers.depsgraph_update_post.append(cmp._watch_for_preview_cancel)

        cmp._watch_for_preview_cancel(bpy.context.scene, None)

        assert cmp._watch_for_preview_cancel not in bpy.app.handlers.depsgraph_update_post

    def test_unsafe_pair_warns_once_then_lets_recalc_proceed(self, two_connected_walls):
        """Pin: the unsafe-pair gate blocks the recalc the FIRST time a pair
        is flagged, then lets subsequent drags of the same pair proceed
        silently.

        The earlier bug-shape was ``if unsafe_pair: report + return`` with no
        per-pair memory, so every retry of the same near-parallel
        configuration fired the warning and skipped the recalc — locking
        the user out of progress past a flagged configuration. The
        regression guard here calls ``execute()`` twice with a forced
        unsafe-pair detection and asserts the second call schedules a
        timer (the recalc dispatch)."""
        a_obj, b_obj, a_el, b_el = two_connected_walls

        # Pre-populate preview state as if PreConnectedMovePreview just ran.
        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        cm.is_active = True
        item = cm.moved_wall_ifc_ids.add()
        item.value = a_el.id()

        cmp._warned_unsafe_pairs.clear()
        fake_pair = (a_obj.name, b_obj.name, frozenset({a_el.id(), b_el.id()}))
        from contextlib import ExitStack

        with ExitStack() as stack:
            from bonsai import tool as _tool

            ifc_stub = SimpleNamespace(by_id=lambda i: a_el if i == a_el.id() else b_el)
            stack.enter_context(patch.object(_tool.Ifc, "get", return_value=ifc_stub))
            stack.enter_context(
                patch.object(_tool.Ifc, "get_entity", side_effect=lambda obj: a_el if obj is a_obj else b_el)
            )
            stack.enter_context(
                patch.object(_tool.Ifc, "get_object", side_effect=lambda e: a_obj if e is a_el else b_obj)
            )
            stack.enter_context(patch.object(_tool.Ifc, "is_moved", return_value=True))
            stack.enter_context(
                patch.object(cmp.PostConnectedMoveFinalize, "_has_body_representation", return_value=True)
            )
            stack.enter_context(
                patch.object(cmp.PostConnectedMoveFinalize, "_first_unsafe_pair", return_value=fake_pair)
            )
            registered: list = []
            stack.enter_context(
                patch.object(bpy.app.timers, "register", side_effect=lambda fn, **kw: registered.append(fn))
            )

            # First call: pair is unflagged → warning + blocked recalc.
            bpy.ops.bim.post_connected_move_finalize()
            assert fake_pair[2] in cmp._warned_unsafe_pairs
            assert not registered, "First unsafe-pair detection must NOT schedule recalc"

            # Second call against the same pair: warning suppressed, recalc proceeds.
            cm.is_active = True
            item2 = cm.moved_wall_ifc_ids.add()
            item2.value = a_el.id()
            bpy.ops.bim.post_connected_move_finalize()
            assert registered, "Second unsafe-pair detection MUST schedule recalc"

    def test_pre_step_bails_on_multi_wall_selection(self, two_connected_walls):
        """PoC scope-gate: when more than one IFC wall with connections is
        in the moved set, the preview must NOT activate. Falls back to
        vanilla Blender behaviour for multi-wall drags."""
        a_obj, b_obj, a_el, b_el = two_connected_walls
        bpy.context.view_layer.objects.active = a_obj
        a_obj.select_set(True)
        b_obj.select_set(True)
        entity_map = {id(a_obj): a_el, id(b_obj): b_el}

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in _patched_tools(entity_map):
                stack.enter_context(p)
            stack.enter_context(patch.object(cmp, "sync_uncommitted_moves", side_effect=lambda objs: None))
            bpy.ops.bim.pre_connected_move_preview()

        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        assert cm.is_active is False
        assert not cmp.WallConnectionPreviewDecorator.is_installed
        assert cmp._watch_for_preview_cancel not in bpy.app.handlers.depsgraph_update_post

    def test_pre_step_bails_when_addon_pref_disabled(self, two_connected_walls):
        """The global toggle short-circuits ``execute`` before any state
        mutation. The macro must still see ``{'FINISHED'}`` so the
        TRANSFORM step proceeds (we just observe rather than activate)."""
        a_obj, b_obj, a_el, b_el = two_connected_walls
        bpy.context.view_layer.objects.active = a_obj
        a_obj.select_set(True)
        entity_map = {id(a_obj): a_el, id(b_obj): b_el}

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in _patched_tools(entity_map, prefs_enabled=False):
                stack.enter_context(p)
            bpy.ops.bim.pre_connected_move_preview()

        cm = bpy.context.scene.BIMPreviewProperties.connected_move
        assert cm.is_active is False
        assert not cmp.WallConnectionPreviewDecorator.is_installed
