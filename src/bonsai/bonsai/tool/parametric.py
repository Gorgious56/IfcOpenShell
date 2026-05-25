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

"""Registry and save-time auto-commit for parametric draft edits.

Adding a new parametric element type is a single entry in ``EDIT_TYPES``."""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import bpy

import bonsai.core.tool
import bonsai.tool as tool

if TYPE_CHECKING:
    from ifcopenshell import entity_instance


# Lowercase ASCII snake_case token; each segment a non-empty letter/digit
# sequence starting with a letter. ``"pipe_segment"`` → ``"BIMPipeSegmentProperties"``.
_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _camel_case(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


@dataclass(frozen=True)
class ParametricObject:
    """One parametric element type's draft + enable + finish + cancel triad.

    The ``name`` token drives every derived identifier: the
    ``BIM<Name>Properties`` attribute on ``bpy.types.Object`` and the
    ``bim.enable_editing_<name>`` / ``bim.finish_editing_<name>`` /
    ``bim.cancel_editing_<name>`` operator ``bl_idname``s.

    The paired runtime predicate ``tool.Blender.Modifier.is_<name>`` is part
    of the contract and MUST be total — accept any IFC entity, return a
    bool, never raise. A raising predicate breaks the save path for every
    parametric type, not just its own."""

    name: str
    has_non_editable_path: bool = False

    def __post_init__(self) -> None:
        if not _VALID_NAME_RE.match(self.name):
            raise ValueError(
                f"ParametricObject name {self.name!r} must match "
                f"{_VALID_NAME_RE.pattern!r} — lowercase letters / digits, "
                f"optionally split by single underscores (e.g. ``door`` or "
                f"``pipe_segment``). Leading / trailing underscores and "
                f"consecutive underscores are rejected because they produce "
                f"empty CamelCase segments in derived class names."
            )

    @property
    def props_attr(self) -> str:
        return f"BIM{_camel_case(self.name)}Properties"

    @property
    def enable_op(self) -> str:
        return f"bim.enable_editing_{self.name}"

    @property
    def finish_op(self) -> str:
        return f"bim.finish_editing_{self.name}"

    @property
    def cancel_op(self) -> str:
        return f"bim.cancel_editing_{self.name}"

    def is_editing(self, obj: bpy.types.Object) -> bool:
        props = getattr(obj, self.props_attr, None)
        return bool(props and getattr(props, "is_editing", False))


class Parametric(bonsai.core.tool.Parametric):
    class GenerationKeyedCache:
        """A dict-keyed cache stamped with the parametric generation counter
        at fill time. Reads at a later generation drop the whole dict and
        re-run the loader. Any IFC commit bumps the generation, invalidating
        all entries en bloc.

        ``None`` values are stored verbatim; only "key not in dict" counts as
        a miss."""

        def __init__(self) -> None:
            self._gen: int | None = None
            self._data: dict = {}

        def get_or_compute(self, key, loader):
            current = Parametric.get_geom_generation()
            if self._gen != current:
                self._data.clear()
                self._gen = current
            if key not in self._data:
                self._data[key] = loader()
            return self._data[key]

        def clear(self) -> None:
            """Explicit drop. Use from ``load_post`` so a fresh file starts clean."""
            self._data.clear()
            self._gen = None

        def __bool__(self) -> bool:
            return bool(self._data)

        def __len__(self) -> int:
            return len(self._data)

        def __contains__(self, key) -> bool:
            return key in self._data

    EDIT_TYPES: list[ParametricObject] = [
        ParametricObject("door", has_non_editable_path=True),
        ParametricObject("window", has_non_editable_path=True),
        ParametricObject("stair", has_non_editable_path=True),
        ParametricObject("railing"),
        ParametricObject("roof"),
        ParametricObject("wall"),
        ParametricObject("array"),
        ParametricObject("pipe_segment", has_non_editable_path=True),
        ParametricObject("duct_segment", has_non_editable_path=True),
    ]

    _geom_generation: int = 0

    @classmethod
    def get_geom_generation(cls) -> int:
        return cls._geom_generation

    @classmethod
    def refresh_post_commit(cls) -> None:
        """Post-commit hook for ``tool.Ifc.Operator``: re-syncs scene-level
        workspace-tool header fields from current IFC state and bumps the
        geometry generation counter so caches keyed off it drop stale
        entries on the next draw."""
        import bonsai.bim.handler  # late import: bim.handler imports tool.*

        cls._geom_generation += 1
        bonsai.bim.handler.update_bim_tool_props()
        screen = getattr(bpy.context, "screen", None)
        if screen is not None:
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    @classmethod
    def find_by_name(cls, name: str) -> Optional[ParametricObject]:
        return next((f for f in cls.EDIT_TYPES if f.name == name), None)

    @classmethod
    def find_for_element(cls, element: entity_instance) -> Optional[ParametricObject]:
        """Return the registry entry whose IFC type predicate matches ``element``."""
        for feature in cls.EDIT_TYPES:
            predicate = getattr(tool.Blender.Modifier, f"is_{feature.name}", None)
            if predicate is not None and predicate(element):
                return feature
        return None

    @classmethod
    def is_object_editing(cls, obj: bpy.types.Object, skip_name: Optional[str] = None) -> Optional[ParametricObject]:
        """Return the registry entry whose triad is active on ``obj``, or None.

        ``skip_name`` excludes one entry from the scan, for callers that want
        to know if a *different* type is editing."""
        for feature in cls.EDIT_TYPES:
            if feature.name == skip_name:
                continue
            if feature.is_editing(obj):
                return feature
        return None

    @classmethod
    def _validated_editing_feature(cls, obj: bpy.types.Object) -> Optional[ParametricObject]:
        """Return the active registry entry on ``obj``, validated against the
        per-type predicate. Returns None when no ``is_editing`` flag is set
        or when the flag is stale.

        Self-heals: a predicate mismatch clears the flag in place so the
        finish dispatch never re-picks up a phantom edit."""
        feature = cls.is_object_editing(obj)
        if feature is None:
            return None
        element = tool.Ifc.get_entity(obj)
        predicate = getattr(tool.Blender.Modifier, f"is_{feature.name}", None)
        if element is None or predicate is None or not predicate(element):
            getattr(obj, feature.props_attr).is_editing = False
            return None
        return feature

    @classmethod
    def heal_stale_edit_flags(cls) -> None:
        """Validate every scene object's ``is_editing`` flag against the
        per-type predicate, clearing stale flags in place.

        Run from ``load_post`` so a ``.blend`` saved with phantom flags
        (e.g. a save that bypassed the auto-commit flush) is consistent the
        moment it opens."""
        for obj in bpy.data.objects:
            cls._validated_editing_feature(obj)

    @classmethod
    def get_pending_edits(cls) -> list[tuple[bpy.types.Object, str]]:
        """``(object, finish_operator_bl_idname)`` pairs for every object
        with an in-progress parametric draft. Stale flags are cleared in
        place and excluded."""
        pending: list[tuple[bpy.types.Object, str]] = []
        for obj in bpy.data.objects:
            feature = cls._validated_editing_feature(obj)
            if feature is not None:
                pending.append((obj, feature.finish_op))
        return pending

    @classmethod
    def run_bim_op(cls, bl_idname: str) -> None:
        """Invoke a ``bim.*`` operator by ``bl_idname``.

        Asserts the operator is a ``tool.Ifc.Operator`` subclass — bypassing
        that wrap would mutate IFC outside Bonsai's transaction system."""
        verb = bl_idname.removeprefix("bim.")
        op_cls = getattr(bpy.types, f"BIM_OT_{verb}", None)
        assert op_cls is not None and issubclass(
            op_cls, tool.Ifc.Operator
        ), f"{bl_idname!r} must be a registered tool.Ifc.Operator subclass for undo-safe IFC mutation"
        getattr(bpy.ops.bim, verb)()

    @classmethod
    def commit_object_draft(cls, obj: bpy.types.Object, finish_op: str) -> bool:
        """Run ``finish_op`` scoped to ``obj`` alone. Returns False (with
        traceback printed) if the operator raised.

        Both ``temp_override`` and ``view_layer.objects.active`` are set:
        ``temp_override`` does not rebind ``objects.active``, and some finish
        operators read it directly."""
        view_layer = bpy.context.view_layer
        original_active = view_layer.objects.active
        try:
            with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
                view_layer.objects.active = obj
                try:
                    cls.run_bim_op(finish_op)
                    return True
                except Exception as e:
                    print(f"Bonsai: commit of {obj.name!r} via {finish_op} failed: {e}")
                    traceback.print_exc()
                    return False
        finally:
            view_layer.objects.active = original_active

    @classmethod
    def commit_pending_edits(cls) -> tuple[int, list[bpy.types.Object]]:
        """Run each pending draft's finish operator scoped to its object.

        A per-object failure does not abort the loop — remaining drafts
        still flush, otherwise the auto-commit would ship the exact silent
        desync it exists to prevent."""
        committed = 0
        failed: list[bpy.types.Object] = []
        for obj, finish_op in cls.get_pending_edits():
            if cls.commit_object_draft(obj, finish_op):
                committed += 1
            else:
                failed.append(obj)
        return committed, failed

    @classmethod
    def commit_pending_edits_for_selection(
        cls, names: Optional[tuple[str, ...]] = None
    ) -> tuple[int, list[bpy.types.Object]]:
        """Selection-scoped variant. ``names`` filters which registry entries
        to consider; ``None`` considers every type."""
        committed = 0
        failed: list[bpy.types.Object] = []
        for obj in tool.Blender.get_selected_objects():
            feature = cls._validated_editing_feature(obj)
            if feature is None:
                continue
            if names is not None and feature.name not in names:
                continue
            if cls.commit_object_draft(obj, feature.finish_op):
                committed += 1
            else:
                failed.append(obj)
        return committed, failed

    @classmethod
    def register_object_properties(cls, prop_module) -> None:
        """Attach ``bpy.types.Object.BIM<Name>Properties`` for every registered
        parametric type. Skips entries whose ``PropertyGroup`` is absent."""
        for feature in cls.EDIT_TYPES:
            prop_cls = getattr(prop_module, feature.props_attr, None)
            if prop_cls is None:
                continue
            setattr(bpy.types.Object, feature.props_attr, bpy.props.PointerProperty(type=prop_cls))

    @classmethod
    def unregister_object_properties(cls) -> None:
        for feature in cls.EDIT_TYPES:
            if hasattr(bpy.types.Object, feature.props_attr):
                delattr(bpy.types.Object, feature.props_attr)

    @classmethod
    def iter_gizmo_preference_classes(cls, ui_module) -> list[type]:
        """Shared ``GizmoPreferencesFeature`` class as a one-element list, or
        empty if absent. Must register before ``GizmoPreferences``."""
        shared = getattr(ui_module, "GizmoPreferencesFeature", None)
        return [shared] if shared is not None else []
