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

"""Forward-compat guard for the parametric-edit drift class of bug.

Operators named ``(Enable|Finish|Cancel)Editing<Type>`` whose lifecycle is NOT
inherited from ``ParametricEditMixinBase`` (i.e. standalone — Stair and Wall
today) must commit / restore ``matrix_world`` ↔ IFC ``ObjectPlacement``
explicitly. Without it, an in-edit drag is silently dropped on Finish, or an
uncommitted move snaps back on Cancel — the exact bug class the mixin fixes
by inheritance.

The contract: each standalone operator's ``_execute`` body must call at least
one of ``tool.Geometry.commit_placement_if_moved`` (Enable / Finish),
``tool.Geometry.restore_or_rebaseline_placement`` (Cancel — the canonical
gate-and-restore-or-rebaseline helper), ``tool.Geometry.restore_placement_from_ifc``
(low-level Cancel when the caller has already gated), or
``tool.Geometry.record_object_position``.

Adding a new standalone product-level edit operator that bypasses all three
names fails this test. The fix is to call the appropriate hook OR (if the
operator does not edit a directly-placed product) whitelist it in
``_DRIFT_HOOK_NOT_REQUIRED`` with a justifying comment."""

import ast
import importlib
import inspect
import pkgutil
import re
import textwrap

import pytest

pytestmark = pytest.mark.model


_OPERATOR_NAME_RE = re.compile(r"^(Enable|Finish|Cancel)Editing\w+$")
_DRIFT_CALLS = {
    "commit_placement_if_moved",
    "restore_placement_from_ifc",
    "restore_or_rebaseline_placement",
    "record_object_position",
}

_DRIFT_HOOK_NOT_REQUIRED: set[str] = {
    # Path-editing edit lifecycles operate on an "Axis" representation, not the host
    # product's placement. The host matrix_world is read but never mutated.
    "EnableEditingRailingPath",
    "CancelEditingRailingPath",
    "FinishEditingRailingPath",
    "EnableEditingRoofPath",
    "CancelEditingRoofPath",
    "FinishEditingRoofPath",
    # Profile / axis sub-edit operators edit profile geometry, not placement.
    "EnableEditingSketchExtrusionProfile",
    "EnableEditingExtrusionProfile",
    "EnableEditingExtrusionAxis",
    # Array sub-edits — operate on array layer math, not on a host placement.
    "EnableEditingArrayItem",
    "EnableEditingParametric",
    # Array edit lifecycle — the array's IFC placement is derived from its parent
    # host's placement (via IfcRelDecomposes), not stored independently. A
    # drag of the array object is meaningless without also dragging the parent;
    # the drift-and-restore semantic does not map onto this edit pattern.
    "EnableEditingArray",
    "FinishEditingArray",
    "CancelEditingArray",
}


def _called_names(fn_node):
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                yield func.attr
            elif isinstance(func, ast.Name):
                yield func.id


def test_standalone_edit_operators_handle_matrix_world_drift():
    from bonsai.bim import parametric_lifecycle
    from bonsai.bim.module import model as model_pkg

    offenders: list[str] = []
    skipped: list[str] = []

    for _finder, mod_name, _is_pkg in pkgutil.iter_modules(model_pkg.__path__):
        full_name = f"{model_pkg.__name__}.{mod_name}"
        try:
            mod = importlib.import_module(full_name)
        except Exception:
            continue
        for cls_name in dir(mod):
            if not _OPERATOR_NAME_RE.match(cls_name):
                continue
            cls = getattr(mod, cls_name)
            if not isinstance(cls, type):
                continue
            if issubclass(cls, parametric_lifecycle.ParametricEditMixinBase):
                continue
            if cls_name in _DRIFT_HOOK_NOT_REQUIRED:
                skipped.append(cls_name)
                continue
            execute = cls.__dict__.get("_execute") or cls.__dict__.get("execute")
            if execute is None:
                # Inherited from a non-mixin base — walk the MRO for the first
                # owner of _execute / execute and pull its source.
                for base in cls.__mro__[1:]:
                    if "_execute" in base.__dict__:
                        execute = base.__dict__["_execute"]
                        break
                    if "execute" in base.__dict__:
                        execute = base.__dict__["execute"]
                        break
            if execute is None:
                continue
            try:
                src = textwrap.dedent(inspect.getsource(execute))
            except (OSError, TypeError):
                continue
            calls = set(_called_names(ast.parse(src)))
            if not calls & _DRIFT_CALLS:
                offenders.append(cls_name)

    assert not offenders, (
        f"Standalone parametric-edit operators missing matrix_world drift handling: "
        f"{sorted(offenders)}. Each must call one of {sorted(_DRIFT_CALLS)} in its "
        f"_execute body, OR be whitelisted in _DRIFT_HOOK_NOT_REQUIRED with a "
        f"justifying comment. Skipped via whitelist: {sorted(skipped)}."
    )
