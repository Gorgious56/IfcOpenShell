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

"""Live preview of wall path-connection joins during a Blender ``G`` / ``R``
object-mode transform.

Wired into both ``bim.override_move_macro`` and ``bim.override_rotate_macro``
chains (defined in ``bim.module.geometry``). Two macro steps surround
the Blender transform modal:

    BIM_OT_override_move_select        (existing — expand selection)
    BIM_OT_pre_connected_move_preview  (this file — arm preview)
    TRANSFORM_OT_translate             (G) or TRANSFORM_OT_rotate (R)
    BIM_OT_post_connected_move_finalize (this file — auto-recalc on success)

Scale (``S``) is deliberately out of scope: scaling an IFC body in object
mode is a no-op (``geometry.block_scale`` snaps the scale back to 1) so a
preview would never have anything to show.

The decorator reads each moved wall's live ``matrix_world`` every frame and
draws ghost axis lines + corner points showing where every connected
neighbour would re-join if the user committed at the current cursor position.
No IFC mutation occurs during the transform — the post-step is the single
``bim.recalculate_wall`` dispatch, gated on ``tool.Ifc.is_moved`` (which
covers location AND rotation drift) so a right-click / Esc cancel naturally
no-ops.

The post-step does NOT run when the Blender transform modal returns
``{'CANCELLED'}`` (Blender macro semantics). Stale ``is_active`` is cleared
either by the next ``G`` / ``R`` press re-arming the preview, or by Esc
dispatching ``bim.cancel_connected_move_preview`` via
``preview_base.PREVIEW_CANCEL_OPS``.
"""

from __future__ import annotations

import functools
import traceback

import bpy
import gpu
import ifcopenshell.util.representation
from bpy.app.handlers import persistent
from bpy.types import Operator, PropertyGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

import bonsai.core.model as core_model
import bonsai.tool as tool
from bonsai.bim.module.model.preview_base import (
    is_preview_active,
    sync_uncommitted_moves,
)

GHOST_LINE_WIDTH = 2.5
GHOST_POINT_SIZE = 8.0
GHOST_WARNING_POINT_SIZE = 14.0
UNSAFE_EXTEND_RATIO_DEFAULT = 10.0


def _clear_preview_state(scene):
    """Reset the connected-move preview to its inactive resting state.

    Centralises the four operations every exit path runs: clear the active
    flag, drop the movement memory, empty the tracked-id collection, and
    tear down the GPU draw handler if it's currently installed. Cheap to
    call when the preview is already inactive (idempotent)."""
    preview = getattr(scene, "BIMPreviewProperties", None)
    if preview is None:
        return
    props = preview.connected_move
    props.is_active = False
    props.has_seen_movement = False
    props.moved_wall_ifc_ids.clear()
    if WallConnectionPreviewDecorator.is_installed:
        WallConnectionPreviewDecorator.uninstall()


# Module-level guard against scheduling duplicate cleanup timers. The
# watcher fires on every depsgraph tick and the cancel condition stays
# true for several ticks before the timer runs, so without this we'd
# stack N copies of the same cleanup.
_cancel_cleanup_scheduled = False

# Pairs the user has already been warned about for unsafe joins, scoped to
# the Blender session (cleared on restart). The gate blocks the recalc the
# FIRST time a pair projects a near-parallel junction so the user sees the
# warning, then proceeds silently for the same pair on subsequent drags so
# repeated retries of the same configuration aren't locked out. Pairs are
# keyed by ``frozenset({moved_id, neighbour_id})`` so direction doesn't
# matter. ``preview_base.discard_pending_previews`` clears this on
# ``load_post`` so a freshly opened file starts with a clean slate.
_warned_unsafe_pairs: set[frozenset[int]] = set()


def _schedule_cancel_cleanup(scene):
    global _cancel_cleanup_scheduled
    if _cancel_cleanup_scheduled:
        return
    _cancel_cleanup_scheduled = True
    bpy.app.timers.register(
        functools.partial(_run_cancel_cleanup, scene),
        first_interval=0.0,
    )


def _run_cancel_cleanup(scene):
    """Run the cancel-path cleanup outside the depsgraph callback.

    Mutating PropertyGroup state directly from ``depsgraph_update_post``
    is a re-entrancy hazard per the Blender API discipline cardinals; the
    timer hop lands the writes in a clean main-thread tick instead."""
    global _cancel_cleanup_scheduled
    _cancel_cleanup_scheduled = False
    _clear_preview_state(scene)
    _uninstall_cancel_watcher()
    tool.Blender.update_all_viewports()
    return None


@persistent
def _watch_for_preview_cancel(scene, depsgraph):
    """Detect a right-click / Esc cancel of the wall transform whose macro
    therefore skipped the post-step.

    Blender macros stop processing steps when an intermediate operator
    returns ``{'CANCELLED'}``, so ``PostConnectedMoveFinalize`` never runs
    on a cancelled transform. Without this watcher, ``is_active`` would
    stay set until the user pressed G / R / Esc again. The handler is
    installed only while a preview is live, and uninstalls itself the
    moment it detects either an explicit cancel (all walls back at IFC
    baseline after having moved) or a stale ``is_active=False`` state."""
    props = getattr(scene, "BIMPreviewProperties", None)
    if props is None:
        _uninstall_cancel_watcher()
        return
    cm = props.connected_move
    if not cm.is_active:
        _uninstall_cancel_watcher()
        return

    ifc_file = tool.Ifc.get()
    if ifc_file is None:
        return

    any_moved = False
    for item in cm.moved_wall_ifc_ids:
        try:
            element = ifc_file.by_id(item.value)
        except RuntimeError:
            continue
        obj = tool.Ifc.get_object(element)
        if obj is not None and tool.Ifc.is_moved(obj):
            any_moved = True
            break

    if any_moved:
        if not cm.has_seen_movement:
            cm.has_seen_movement = True
        return

    if cm.has_seen_movement:
        _schedule_cancel_cleanup(scene)


def _install_cancel_watcher():
    if _watch_for_preview_cancel not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_watch_for_preview_cancel)


def _uninstall_cancel_watcher():
    try:
        bpy.app.handlers.depsgraph_update_post.remove(_watch_for_preview_cancel)
    except ValueError:
        pass


@persistent
def _clear_unsafe_pair_memory(scene):
    """Reset the per-session unsafe-pair memory on ``load_post``.

    Walls keep their IFC ids across saves, but a freshly opened file is a
    fresh editing context — the user shouldn't inherit "already warned"
    state from the previous session's pair configurations."""
    _warned_unsafe_pairs.clear()


@persistent
def _discard_on_undo_redo(scene):
    """Tear down preview state on Ctrl+Z / Ctrl+Y.

    Blender undo snapshots ``Scene.BIMPreviewProperties`` along with the
    rest of the scene. A snapshot taken mid-drag (``is_active=True`` with
    populated ``moved_wall_ifc_ids``) can be restored as Blender rewinds
    past the recalc step — leaving the decorator and watcher pointing at
    a state that no longer matches the live mesh. Sweep matches the
    ``load_post`` discard pattern."""
    _uninstall_cancel_watcher()
    _clear_preview_state(scene)


def _run_deferred_recalc(wall_obj_names):
    """Run the wall recalc as a standalone operator invocation after the
    macro chain has returned.

    The deferral via ``bpy.app.timers`` separates the recalc from the
    transform under Blender's undo machinery (one Ctrl+Z drops the recalc
    while keeping the transform). Every exit path emits a tagged console
    line so silent no-ops remain diagnosable."""
    tag = "[connected_move_preview]"
    try:
        objs = [bpy.data.objects.get(n) for n in wall_obj_names]
        objs = [o for o in objs if o is not None]
        if not objs:
            print(f"{tag} deferred recalc: snapshot resolved to 0 walls; skipping. " f"(snapshot was {wall_obj_names})")
            return None

        # temp_override gives the operator a stable selection. The recalc
        # operator's poll reads live selection, which may have drifted
        # between drop and timer-fire.
        with bpy.context.temp_override(
            selected_objects=objs,
            selected_editable_objects=objs,
            active_object=objs[0],
            object=objs[0],
        ):
            try:
                result = bpy.ops.bim.recalculate_wall()
            except RuntimeError as exc:
                # Blender raises RuntimeError when an operator's poll
                # fails AND no message was set. Surface the cause.
                print(f"{tag} deferred recalc: bim.recalculate_wall raised: {exc}")
                return None
            if "CANCELLED" in result:
                print(
                    f"{tag} deferred recalc: bim.recalculate_wall returned "
                    f"{set(result)} for {[o.name for o in objs]}; nothing changed"
                )

        # regenerate_wall_representation replaces the Body representation
        # entity. UI data caches keyed on the old id must re-resolve on
        # next panel draw.
        try:
            from bonsai.bim.module.model.data import AuthoringData, ItemData

            ItemData.is_loaded = False
            AuthoringData.is_loaded = False
        except Exception:
            pass
    except Exception:
        # Outer guard — Blender swallows timer exceptions silently otherwise.
        print(f"{tag} _run_deferred_recalc raised at top level:")
        traceback.print_exc()
    return None


def _axis_to_seg_tuple(axis: tuple[Vector, Vector]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Flatten a ``(Vector, Vector)`` world-axis pair into the plain-tuple
    shape ``bonsai.core.model.project_axis_intersection`` expects."""
    return ((axis[0].x, axis[0].y, axis[0].z), (axis[1].x, axis[1].y, axis[1].z))


def _is_unsafe_extend(p0: Vector, p1: Vector, intersection: Vector, max_ratio: float) -> bool:
    """True when extending the (``p0``→``p1``) axis to meet ``intersection``
    would build a wall absurdly longer than the original.

    Near-parallel walls project their axis intersection at infinity; the join
    is still mathematically valid but the resulting wall is nearly always
    the result of a slight rotation drift, not user intent. ``max_ratio`` is
    the multiplier of the original axis length above which the extend is
    flagged as unsafe.

    Returns ``False`` for TRIM cases (intersection inside the original axis):
    those are bounded by the segment length and always physically reasonable.
    """
    d0_sq = (p0 - intersection).length_squared
    d1_sq = (p1 - intersection).length_squared
    if d0_sq <= d1_sq:
        near, far = p0, p1
    else:
        near, far = p1, p0
    inside = far - near
    denom = inside.length_squared
    if denom < 1e-9:
        return True
    t = inside.dot(intersection - near) / denom
    if 0.0 < t < 1.0:
        return False
    original_len = inside.length
    return (intersection - near).length > max_ratio * original_len


class BIMConnectedMovePreviewWallId(PropertyGroup):
    """Wrapper PropertyGroup so an IFC id can live in a CollectionProperty
    (Blender disallows raw IntProperty members in collections)."""

    value: bpy.props.IntProperty()


class BIMConnectedMovePreviewProperties(PropertyGroup):
    """Draft state scoped to a single transform drag.

    ``is_active`` is the gate every consumer (decorator draw, gizmo poll,
    Esc dispatch) reads. The global enable lives on the addon preferences
    so it survives across files."""

    is_active: bpy.props.BoolProperty(default=False)
    moved_wall_ifc_ids: bpy.props.CollectionProperty(type=BIMConnectedMovePreviewWallId)
    has_seen_movement: bpy.props.BoolProperty(default=False)
    unsafe_extend_ratio: bpy.props.FloatProperty(
        name="Unsafe Extend Ratio",
        description=(
            "Skip the auto-recalc when any moved wall's projected new "
            "endpoint sits more than N× its current length away (the "
            "near-parallel-junction case). Lower = stricter."
        ),
        default=UNSAFE_EXTEND_RATIO_DEFAULT,
        min=1.5,
        max=1000.0,
    )


class BIMPreviewProperties(PropertyGroup):
    """Umbrella PropertyGroup on ``Scene.BIMPreviewProperties``.

    Each preview feature (currently ``connected_move``; ``bend`` and
    ``wall_fillet`` are reserved in ``preview_base.PREVIEW_CANCEL_OPS`` for
    upcoming features) hangs a child PointerProperty here. Children must be
    optional via ``getattr(..., name, None)`` so the umbrella can carry only
    the children defined in this revision without breaking the Esc dispatch
    or ``load_post`` discard."""

    connected_move: bpy.props.PointerProperty(type=BIMConnectedMovePreviewProperties)


class PreConnectedMovePreview(Operator):
    """Macro pre-step: arm the connected-move preview before
    ``TRANSFORM_OT_translate`` enters its modal.

    Always returns ``{'FINISHED'}`` so the macro proceeds — a missing umbrella,
    disabled toggle, or a selection containing no connected walls is a
    silent no-op rather than blocking ``G``."""

    bl_idname = "bim.pre_connected_move_preview"
    bl_label = "Pre-Move Connection Preview"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        preview = getattr(context.scene, "BIMPreviewProperties", None)
        if preview is None:
            return {"FINISHED"}
        if not tool.Blender.get_addon_preferences().should_use_connected_move_preview:
            return {"FINISHED"}
        props = preview.connected_move

        moved_walls = self._collect_walls_with_connections(context.selected_objects)
        # PoC scope: only activate on single-wall transforms. Multi-wall
        # drags fall back to vanilla Blender + manual Update Geometry to
        # avoid surprising users of existing multi-wall edit workflows.
        if len(moved_walls) != 1:
            return {"FINISHED"}

        sync_uncommitted_moves(moved_walls)

        props.is_active = True
        props.has_seen_movement = False
        props.moved_wall_ifc_ids.clear()
        for obj in moved_walls:
            element = tool.Ifc.get_entity(obj)
            item = props.moved_wall_ifc_ids.add()
            item.value = element.id()

        WallConnectionPreviewDecorator.install(context)
        _install_cancel_watcher()
        tool.Blender.update_all_viewports(context)
        return {"FINISHED"}

    @staticmethod
    def _collect_walls_with_connections(objects):
        result = []
        for obj in objects:
            element = tool.Ifc.get_entity(obj)
            if element is None or not element.is_a("IfcWall"):
                continue
            if not (getattr(element, "ConnectedTo", None) or getattr(element, "ConnectedFrom", None)):
                continue
            result.append(obj)
        return result


class PostConnectedMoveFinalize(Operator):
    """Macro post-step: auto-recalculate connected walls after a committed
    ``TRANSFORM_OT_translate``.

    ``tool.Ifc.is_moved`` is the source of truth for "did the user really
    move anything". After a right-click / Esc cancel the modal restores the
    matrix and ``is_moved`` returns ``False``, so no recalc runs."""

    bl_idname = "bim.post_connected_move_finalize"
    bl_label = "Post-Move Connection Finalize"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        preview = getattr(context.scene, "BIMPreviewProperties", None)
        if preview is None:
            return {"FINISHED"}
        props = preview.connected_move
        if not props.is_active:
            return {"FINISHED"}

        ifc_file = tool.Ifc.get()
        moved_objs: list[bpy.types.Object] = []
        if ifc_file is not None:
            for item in props.moved_wall_ifc_ids:
                try:
                    element = ifc_file.by_id(item.value)
                except RuntimeError:
                    continue
                obj = tool.Ifc.get_object(element)
                if obj is None:
                    continue
                if tool.Ifc.is_moved(obj):
                    moved_objs.append(obj)

        # The recalc kernel requires a Body/MODEL_VIEW representation.
        # Walls missing it are filtered here; bad neighbours pulled in by
        # the recalc's own expansion are caught by the dispatch guard.
        moved_objs = [obj for obj in moved_objs if self._has_body_representation(tool.Ifc.get_entity(obj))]

        unsafe_pair = self._first_unsafe_pair(moved_objs, props.unsafe_extend_ratio)

        _uninstall_cancel_watcher()
        _clear_preview_state(context.scene)
        tool.Blender.update_all_viewports(context)

        if unsafe_pair is not None:
            wall_a_name, wall_b_name, pair_key = unsafe_pair
            if pair_key not in _warned_unsafe_pairs:
                _warned_unsafe_pairs.add(pair_key)
                self.report(
                    {"WARNING"},
                    f"Auto-recalc skipped: '{wall_a_name}' ↔ '{wall_b_name}' would "
                    f"project a near-parallel junction. Transform kept; press Update "
                    f"Geometry manually or rotate to a less acute angle. Subsequent "
                    f"drags of this pair will proceed without further warnings.",
                )
                return {"FINISHED"}

        if moved_objs:
            # Defer to one event-loop tick later so the recalc lands as a
            # standalone operator invocation: separate undo entry, and any
            # downstream exception is isolated from the macro's exit path.
            obj_names = [obj.name for obj in moved_objs]
            bpy.app.timers.register(
                functools.partial(_run_deferred_recalc, obj_names),
                first_interval=0.0,
            )
        return {"FINISHED"}

    @staticmethod
    def _has_body_representation(element) -> bool:
        if element is None:
            return False
        try:
            return (
                ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW") is not None
            )
        except Exception:
            return False

    @staticmethod
    def _first_unsafe_pair(moved_objs, max_ratio):
        """Return ``(wall_a_name, wall_b_name, pair_key)`` for the first
        connection whose projected intersection is absurdly far from either
        wall's endpoints, or ``None`` if every pair would join cleanly.

        ``pair_key`` is a ``frozenset({moved_id, neighbour_id})`` so the
        caller can consult ``_warned_unsafe_pairs`` regardless of which
        side initiated the connection.

        Mirrors the decorator's pre-render filter so what the user sees
        during the drag matches what the post-step is willing to commit."""
        seen_pairs: set[tuple[int, int]] = set()
        for moved_obj in moved_objs:
            moved_element = tool.Ifc.get_entity(moved_obj)
            if moved_element is None:
                continue
            moved_axis = tool.Wall.get_world_reference_line(moved_obj)
            if moved_axis is None:
                continue
            connections = []
            for rel in getattr(moved_element, "ConnectedTo", None) or ():
                if rel.is_a("IfcRelConnectsPathElements"):
                    connections.append(rel.RelatedElement)
            for rel in getattr(moved_element, "ConnectedFrom", None) or ():
                if rel.is_a("IfcRelConnectsPathElements"):
                    connections.append(rel.RelatingElement)
            for neighbour in connections:
                if neighbour is None or not neighbour.is_a("IfcWall"):
                    continue
                pair_key = tuple(sorted((moved_element.id(), neighbour.id())))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                neighbour_obj = tool.Ifc.get_object(neighbour)
                if neighbour_obj is None:
                    continue
                neighbour_axis = tool.Wall.get_world_reference_line(neighbour_obj)
                if neighbour_axis is None:
                    continue
                intersection = core_model.project_axis_intersection(
                    _axis_to_seg_tuple(moved_axis),
                    _axis_to_seg_tuple(neighbour_axis),
                    core_model.PARALLEL_DOT_THRESHOLD,
                )
                if intersection is None:
                    continue
                ix_vec = Vector(intersection)
                if _is_unsafe_extend(moved_axis[0], moved_axis[1], ix_vec, max_ratio) or _is_unsafe_extend(
                    neighbour_axis[0], neighbour_axis[1], ix_vec, max_ratio
                ):
                    return moved_obj.name, neighbour_obj.name, frozenset(pair_key)
        return None


class CancelConnectedMovePreview(Operator):
    """Explicit cancel target for ``preview_base.PREVIEW_CANCEL_OPS``.

    Used when the user presses Esc after the modal has already returned —
    e.g. after a right-click cancel that left ``is_active`` stuck because the
    post-step was skipped."""

    bl_idname = "bim.cancel_connected_move_preview"
    bl_label = "Cancel Connection Preview"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        _uninstall_cancel_watcher()
        _clear_preview_state(context.scene)
        tool.Blender.update_all_viewports(context)
        return {"FINISHED"}


class WallConnectionPreviewDecorator(tool.Blender.ViewportDecorator):
    """GPU ghost lines for the live wall connection preview.

    Installed dynamically by ``PreConnectedMovePreview`` and torn down by
    ``PostConnectedMoveFinalize`` / ``CancelConnectedMovePreview`` so the
    draw handler only sits in ``SpaceView3D``'s handler list while a drag is
    active.

    Each delta segment between a wall's current axis endpoint and the new
    projected corner is classified as TRIM (the segment lies inside the
    original axis — that part of the wall would be cut away) or EXTEND (the
    segment lies past the original endpoint — that part would be added).
    The two cases render in distinct preference colours so the user sees
    both the future shape and what would be sacrificed to get there."""

    draw_method = "draw"

    def draw(self, context):
        ctx = bpy.context
        if not is_preview_active(ctx, "connected_move"):
            return

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return

        props = ctx.scene.BIMPreviewProperties.connected_move
        moved_ids = {item.value for item in props.moved_wall_ifc_ids}
        if not moved_ids:
            return

        trim_lines: list[tuple[Vector, Vector]] = []
        extend_lines: list[tuple[Vector, Vector]] = []
        corner_points: list[Vector] = []
        warning_points: list[Vector] = []

        for moved_id in moved_ids:
            try:
                moved_element = ifc_file.by_id(moved_id)
            except RuntimeError:
                continue
            moved_obj = tool.Ifc.get_object(moved_element)
            if moved_obj is None:
                continue
            moved_axis = tool.Wall.get_world_reference_line(moved_obj)
            if moved_axis is None:
                continue
            moved_top_offset = self._top_offset(moved_obj, moved_element)

            for rel in getattr(moved_element, "ConnectedTo", None) or ():
                if rel.is_a("IfcRelConnectsPathElements"):
                    self._collect_ghost_for_neighbour(
                        moved_obj,
                        moved_axis,
                        moved_top_offset,
                        rel.RelatedElement,
                        moved_ids,
                        trim_lines,
                        extend_lines,
                        corner_points,
                        warning_points,
                        moved_conn_type=getattr(rel, "RelatingConnectionType", None),
                        neighbour_conn_type=getattr(rel, "RelatedConnectionType", None),
                    )
            for rel in getattr(moved_element, "ConnectedFrom", None) or ():
                if rel.is_a("IfcRelConnectsPathElements"):
                    self._collect_ghost_for_neighbour(
                        moved_obj,
                        moved_axis,
                        moved_top_offset,
                        rel.RelatingElement,
                        moved_ids,
                        trim_lines,
                        extend_lines,
                        corner_points,
                        warning_points,
                        moved_conn_type=getattr(rel, "RelatedConnectionType", None),
                        neighbour_conn_type=getattr(rel, "RelatingConnectionType", None),
                    )

        if not (trim_lines or extend_lines or warning_points):
            return
        self._render(trim_lines, extend_lines, corner_points, warning_points)

    @classmethod
    def _collect_ghost_for_neighbour(
        cls,
        moved_obj,
        moved_axis,
        moved_top_offset,
        neighbour_element,
        moved_ids,
        trim_lines,
        extend_lines,
        corner_points,
        warning_points,
        moved_conn_type,
        neighbour_conn_type,
    ):
        if neighbour_element is None or not neighbour_element.is_a("IfcWall"):
            return
        if neighbour_element.id() in moved_ids:
            return
        neighbour_obj = tool.Ifc.get_object(neighbour_element)
        if neighbour_obj is None:
            return
        neighbour_axis = tool.Wall.get_world_reference_line(neighbour_obj)
        if neighbour_axis is None:
            return
        neighbour_top_offset = cls._top_offset(neighbour_obj, neighbour_element)

        intersection = core_model.project_axis_intersection(
            _axis_to_seg_tuple(moved_axis),
            _axis_to_seg_tuple(neighbour_axis),
            core_model.PARALLEL_DOT_THRESHOLD,
        )
        if intersection is None:
            return

        ix_vec = Vector((intersection[0], intersection[1], intersection[2]))

        # Near-parallel pair → projected intersection is at infinity. Drop a
        # warning dot at each wall's near endpoint instead of vanishing the
        # ghost silently, so the user sees WHERE the bad join is rather than
        # wondering why a corner stopped previewing. PostMoveFinalize's
        # matching check refuses to commit when this marker is up.
        props = bpy.context.scene.BIMPreviewProperties.connected_move
        max_ratio = props.unsafe_extend_ratio
        if _is_unsafe_extend(moved_axis[0], moved_axis[1], ix_vec, max_ratio) or _is_unsafe_extend(
            neighbour_axis[0], neighbour_axis[1], ix_vec, max_ratio
        ):
            near_moved = cls._nearest_endpoint(moved_axis[0], moved_axis[1], ix_vec)
            near_neighbour = cls._nearest_endpoint(neighbour_axis[0], neighbour_axis[1], ix_vec)
            warning_points.append(near_moved)
            warning_points.append(near_moved + moved_top_offset)
            warning_points.append(near_neighbour)
            warning_points.append(near_neighbour + neighbour_top_offset)
            return

        # IfcRelConnectsPathElements.{Relating,Related}ConnectionType ==
        # "ATPATH" means the wall is the host of a T-junction; its endpoints
        # don't move when the connection re-resolves, only the joining wall's
        # endpoint does. Suppress the host's ghost so the user doesn't see a
        # phantom trim/extend on the unchanging axis.
        if moved_conn_type != "ATPATH":
            cls._classify_and_emit(
                moved_axis[0],
                moved_axis[1],
                ix_vec,
                moved_top_offset,
                trim_lines,
                extend_lines,
            )
        if neighbour_conn_type != "ATPATH":
            cls._classify_and_emit(
                neighbour_axis[0],
                neighbour_axis[1],
                ix_vec,
                neighbour_top_offset,
                trim_lines,
                extend_lines,
            )

        corner_points.append(ix_vec)
        corner_points.append(ix_vec + moved_top_offset)

    @staticmethod
    def _nearest_endpoint(p0: Vector, p1: Vector, intersection: Vector) -> Vector:
        return p0 if (p0 - intersection).length_squared <= (p1 - intersection).length_squared else p1

    @staticmethod
    def _classify_and_emit(p0, p1, intersection, top_offset, trim_lines, extend_lines):
        """Push the (near→intersection) delta into the trim or extend bucket
        and mirror it at ``+ top_offset`` so both bottom and top axes show."""
        d0_sq = (p0 - intersection).length_squared
        d1_sq = (p1 - intersection).length_squared
        if d0_sq <= d1_sq:
            near, far = p0, p1
        else:
            near, far = p1, p0

        # Sub-millimetre delta in plan = endpoint already coincides with the
        # new intersection. No reshape needed, so no ghost to render.
        end_at_int = Vector((intersection.x, intersection.y, near.z))
        if (near - end_at_int).length_squared < 1e-6:
            return

        inside = far - near
        toward_int = intersection - near
        denom = inside.length_squared
        if denom < 1e-9:
            t = -1.0
        else:
            t = inside.dot(toward_int) / denom

        bucket = trim_lines if 0.0 < t < 1.0 else extend_lines
        bucket.append((near, end_at_int))
        bucket.append((near + top_offset, end_at_int + top_offset))

    @staticmethod
    def _top_offset(obj, element) -> Vector:
        """World-space vector from the reference line to the wall's top edge,
        or zero when the height isn't recoverable (non-parametric body)."""
        result = tool.Wall.get_length_and_height(element)
        if result is None:
            return Vector((0.0, 0.0, 0.0))
        _, height = result
        local_z = obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
        return local_z * height

    @staticmethod
    def _render(trim_lines, extend_lines, corner_points, warning_points):
        region = bpy.context.region
        if region is None:
            return

        colors = tool.Blender.get_decorator_colors()
        trim_color = colors.error
        extend_color = colors.special
        point_color = colors.special
        warning_color = colors.error

        # Ghost lines are an overlay — they must remain visible even when
        # other walls / opaque geometry would otherwise occlude them in the
        # 3D scene. Disabling depth-test makes the draw an unconditional
        # paint over whatever's already in the framebuffer; we restore the
        # default LESS_EQUAL at the end so other decorators don't inherit
        # the override.
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        line_shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        line_shader.uniform_float("viewportSize", (region.width, region.height))
        line_shader.uniform_float("lineWidth", GHOST_LINE_WIDTH)

        def _draw_lines(lines, color):
            if not lines:
                return
            verts = [tuple(p) for line in lines for p in line]
            line_shader.uniform_float("color", color)
            batch_for_shader(line_shader, "LINES", {"pos": verts}).draw(line_shader)

        _draw_lines(extend_lines, extend_color)
        _draw_lines(trim_lines, trim_color)

        point_shader = gpu.shader.from_builtin("UNIFORM_COLOR")

        def _draw_points(points, color, size):
            if not points:
                return
            point_shader.uniform_float("color", color)
            gpu.state.point_size_set(size)
            batch_for_shader(point_shader, "POINTS", {"pos": [tuple(p) for p in points]}).draw(point_shader)

        _draw_points(corner_points, point_color, GHOST_POINT_SIZE)
        _draw_points(warning_points, warning_color, GHOST_WARNING_POINT_SIZE)
        gpu.state.point_size_set(1.0)

        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")
