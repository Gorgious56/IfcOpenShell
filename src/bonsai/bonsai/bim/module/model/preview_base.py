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

"""Shared infrastructure for Bonsai's parametric preview flows.

Multiple Bonsai features follow the same Scene-level preview pattern:

    Enable<X>Preview   — validates a selection, populates draft state on
                         ``Scene.BIMPreviewProperties.<x>``, flips ``is_active``.
    Gizmo<X>Preview    — polls on ``is_active``, surfaces tunable widgets +
                         validate/cancel icons.
    <X>PreviewDecorator — GPU lines drawn while ``is_active`` is True.
    Finish<X>Preview   — dispatches to a final ``bim.<verb>`` operator with
                         params read off the draft state, then clears it.
    Cancel<X>Preview   — pure state reset.

The MEP bend and wall fillet flows are the two current callers. Both share
the lifecycle exactly; only the props-attribute name, ID/parameter field
names, and the dispatch-op idname differ. This module centralises the
cross-cutting helpers and the boilerplate base classes so adding a new
preview triad doesn't duplicate all of it.

The GPU draw-handler lifecycle for ``<X>PreviewDecorator`` lives on the
feature-neutral ``tool.Blender.ViewportDecorator`` base, which every
viewport decorator (preview or otherwise) inherits from.

Layered design — non-preview Bonsai code can call ``get_preview_props`` /
``is_preview_active`` to introspect the active preview without taking on
the bigger Operator / Gizmo bases. The bases are purely opt-in for new
preview triads."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import bpy

import bonsai.tool as tool

# --- Props accessors ---------------------------------------------------------


def get_preview_props(context: bpy.types.Context, attr: str):
    """Resolve a child preview PropertyGroup under ``Scene.BIMPreviewProperties``.

    Returns ``None`` if the umbrella isn't attached yet — true briefly
    during addon register and during plug-out, so polls / draw callbacks
    must defend against ``None`` rather than assuming the prop is always
    available."""
    preview = getattr(context.scene, "BIMPreviewProperties", None)
    return getattr(preview, attr, None) if preview is not None else None


def is_preview_active(context: bpy.types.Context, attr: str) -> bool:
    """``True`` while a specific preview is open. Used by sibling gizmo
    polls to hide themselves so the preview is the only interactive
    surface in the viewport (the bend / fillet preview groups take over
    the same selection's icon stack)."""
    props = get_preview_props(context, attr)
    return bool(props is not None and props.is_active)


# --- Lazy closure factories --------------------------------------------------
#
# Used by preview gizmo groups when wiring ``BIM_GT_gizmo_dimension``'s
# ``move_get_cb`` / ``move_set_cb`` callbacks. The closures re-resolve
# ``bpy.context.scene`` per CALL rather than capturing it at setup() time
# — the captured Scene's RNA struct can be freed on file open / undo, and
# referencing a freed struct crashes Blender. Lazy lookup survives the
# whole undo / reload lifecycle.


def make_props_callback(attr: str) -> Callable[[], Any]:
    """Return a zero-arg callable that lazily fetches the preview props.

    Equivalent to ``getattr(bpy.context.scene.BIMPreviewProperties, attr)``
    with full defensiveness against missing scene / missing umbrella."""

    def _props():
        scene = bpy.context.scene
        preview = getattr(scene, "BIMPreviewProperties", None) if scene else None
        return getattr(preview, attr, None) if preview is not None else None

    return _props


def make_dim_getter(props_callback: Callable[[], Any], field: str) -> Callable[[], float]:
    """Factory for ``BIM_GT_gizmo_dimension.move_get_cb`` reading a single
    FloatProperty off the live preview state. Returns ``0.0`` defensively
    when the props are temporarily unavailable so the widget doesn't crash
    Blender during plug-out / reload."""

    def _get() -> float:
        props = props_callback()
        return getattr(props, field) if props is not None else 0.0

    return _get


def make_dim_setter(
    props_callback: Callable[[], Any],
    field: str,
    min_value: float = 0.001,
) -> Callable[[float], None]:
    """Factory for ``BIM_GT_gizmo_dimension.move_set_cb`` writing a single
    FloatProperty + tagging viewport areas for redraw so the GPU preview
    decorator tracks the value live during drag. Clamps at ``min_value``
    to match the FloatProperty's declared lower bound."""

    def _set(value: float) -> None:
        props = props_callback()
        if props is None:
            return
        setattr(props, field, max(min_value, float(value)))
        for area in bpy.context.screen.areas if bpy.context.screen else ():
            if area.type == "VIEW_3D":
                area.tag_redraw()

    return _set


# --- Shared Enable lifecycle helpers -----------------------------------------


def sync_uncommitted_moves(objects: list) -> None:
    """Push any Blender-side translation / rotation of ``objects`` back to
    their IFC ``ObjectPlacement`` before a preview decorator starts reading
    ``obj.matrix_world`` per frame.

    Without this sync, a user who grabbed-moved an object but didn't commit
    the move sees the live preview at the dragged position while the final
    commit lands at the stale IFC position — a confusing "where did my
    preview go?" experience. Both bend and fillet enable paths call this
    on the relevant pair just before activating the preview."""
    # Local import: ``bonsai.core.geometry`` pulls in ``tool.Geometry``
    # which can cycle with the model module at addon enable.
    import bonsai.core.geometry

    for obj in objects:
        if tool.Ifc.is_moved(obj):
            bonsai.core.geometry.edit_object_placement(
                tool.Ifc, tool.Geometry, tool.Surveyor, obj=obj, apply_scale=False
            )


# --- Base classes for Finish / Cancel operators ------------------------------


class BasePreviewFinishOperator(bpy.types.Operator):
    """Skeleton for ``Finish<X>Preview`` operators.

    Subclasses set the class attributes ``PREVIEW_ATTR``,
    ``DISPATCH_OPERATOR``, ``DISPATCH_PROP_MAP``, and ``RESET_FIELDS``; the
    base class handles the shared lifecycle: read the preview props,
    early-return if inactive or no IFC, dispatch via ``bpy.ops.bim.<op>``
    with kwargs gathered from the props, clear the state on FINISHED.

    ``RESET_FIELDS`` is a tuple of ``(field_name, reset_value)`` pairs so
    drafts can mix integer IDs, floats (radii), enums, etc. without the
    base needing to know each field's type."""

    bl_options = {"REGISTER", "UNDO"}

    # Subclass overrides — declared as ``ClassVar`` so they're class-only
    # data, not Blender props on the operator instance.
    PREVIEW_ATTR: ClassVar[str]
    DISPATCH_OPERATOR: ClassVar[str]
    DISPATCH_PROP_MAP: ClassVar[dict[str, str]]
    RESET_FIELDS: ClassVar[tuple[tuple[str, Any], ...]]

    def execute(self, context: bpy.types.Context):
        props = get_preview_props(context, self.PREVIEW_ATTR)
        if props is None or not props.is_active:
            return {"CANCELLED"}
        if tool.Ifc.get() is None:
            self.report({"ERROR"}, "No IFC file loaded.")
            return {"CANCELLED"}
        kwargs = {kwarg: getattr(props, prop_attr) for kwarg, prop_attr in self.DISPATCH_PROP_MAP.items()}
        op = getattr(bpy.ops.bim, self.DISPATCH_OPERATOR)
        result = op(**kwargs)
        # Only clear preview state on a successful commit — a failed
        # dispatch (geometric error caught by the create operator) keeps
        # the gizmos visible so the user can re-tune or cancel.
        if "FINISHED" in result:
            props.is_active = False
            for field, reset_value in self.RESET_FIELDS:
                setattr(props, field, reset_value)
        return result


class BasePreviewCancelOperator(bpy.types.Operator):
    """Skeleton for ``Cancel<X>Preview`` operators.

    Pure state reset — preview itself never mutates IFC, so cancel just
    clears the draft fields. Subclasses set ``PREVIEW_ATTR`` and
    ``RESET_FIELDS`` (tuple of ``(field_name, reset_value)`` pairs)."""

    bl_options = {"REGISTER", "UNDO"}

    PREVIEW_ATTR: ClassVar[str]
    RESET_FIELDS: ClassVar[tuple[tuple[str, Any], ...]]

    def execute(self, context: bpy.types.Context):
        props = get_preview_props(context, self.PREVIEW_ATTR)
        if props is None or not props.is_active:
            # ESC routes here even when no preview is active; tell Blender
            # nothing happened so the keymap can fall through to whichever
            # other ESC handler is next.
            return {"CANCELLED"}
        props.is_active = False
        for field, reset_value in self.RESET_FIELDS:
            setattr(props, field, reset_value)
        return {"FINISHED"}
