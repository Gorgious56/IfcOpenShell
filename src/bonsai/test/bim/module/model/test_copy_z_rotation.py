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

"""Unit coverage for the Z-rotation copy gizmo's load-bearing helpers.

The operator's ``_execute`` path needs a full IFC + Blender scene to
exercise end-to-end (left for a later ``NewIfc``-fixture session); these
tests pin the *pure-logic* helpers it depends on:

- ``_z_rotation_diff``: signed Euler-Z difference wrapped to ``[-π, π]``.
  Drives the "already aligned" short-circuit in ``_execute`` — must
  correctly detect ``target_z = -π, source_z = +π`` as the same rotation.
"""

import math
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.model


# ---------------------------------------------------------------------------
# _z_rotation_diff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_z,source_z,expected",
    [
        # Identity: no rotation diff.
        (0.0, 0.0, 0.0),
        # Plain non-wrapping diff.
        (1.0, 0.5, 0.5),
        (-0.5, 0.5, -1.0),
        # ±π wraparound: same rotation expressed two ways → diff is 0.
        (math.pi, -math.pi, 0.0),
        (-math.pi, math.pi, 0.0),
        # Near-wraparound: target slightly under +π, source slightly over -π.
        # Naive abs(target - source) would give ≈ 2π; the wrapped diff is
        # the short way round, ≈ 0.02.
        (math.pi - 0.01, -math.pi + 0.01, -0.02),
    ],
)
def test_z_rotation_diff_normalises_to_signed_half_turn(target_z, source_z, expected):
    """The wrap-aware diff is the load-bearing piece of the operator's skip
    check — a regression here would re-introduce no-op IFC writes."""
    from bonsai.bim.module.model.product import _z_rotation_diff

    assert _z_rotation_diff(target_z, source_z) == pytest.approx(expected, abs=1e-9)


def test_z_rotation_diff_is_antisymmetric_modulo_wrap():
    """``diff(a, b) == -diff(b, a)`` away from the ±π boundary. Pins the
    "signed diff" contract the operator relies on (sign matters when
    extending the skip check to a tolerance-with-direction in the future).
    """
    from bonsai.bim.module.model.product import _z_rotation_diff

    a, b = 0.7, 0.3
    assert _z_rotation_diff(a, b) == pytest.approx(-_z_rotation_diff(b, a), abs=1e-9)


def test_z_rotation_diff_skips_at_wraparound_boundary():
    """The whole reason this helper exists: the skip check in ``_execute``
    must fire when target and source are the same rotation modulo 2π. Pin
    that the helper returns a value the ``abs(...) < 1e-9`` check accepts."""
    from bonsai.bim.module.model.product import _z_rotation_diff

    # Equivalent rotations at the wraparound boundary.
    assert abs(_z_rotation_diff(math.pi, -math.pi)) < 1e-9
    assert abs(_z_rotation_diff(-math.pi, math.pi)) < 1e-9
    # And the same modulo 2π.
    assert abs(_z_rotation_diff(3 * math.pi, math.pi)) < 1e-9


# ---------------------------------------------------------------------------
# GizmoCopyZRotation.is_eligible_object — wall-active gate
# ---------------------------------------------------------------------------


def _eligibility(active_entity_ifc_class, selection_size):
    """Drive ``GizmoCopyZRotation.is_eligible_object`` with the supplied
    selection size and active-object IFC class. Returns the predicate's
    boolean result with all tool boundaries patched."""
    from bonsai import tool
    from bonsai.bim.module.model.product import GizmoCopyZRotation

    active = object()
    selected = [active] + [object() for _ in range(selection_size - 1)] if selection_size else []
    if active_entity_ifc_class is None:
        element = None
    else:
        element = Mock()
        element.is_a.side_effect = lambda type_name: type_name == active_entity_ifc_class

    def get_entity(obj):
        return element if obj is active else None

    with (
        patch.object(tool.Blender, "get_selected_objects", return_value=selected),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
    ):
        return GizmoCopyZRotation.is_eligible_object(active)


def test_is_eligible_object_true_when_active_is_wall_and_two_selected():
    """The single passing case: exactly 2 selected objects and the active
    carries an IfcWall entity. Pins the wall-gate's positive branch."""
    assert _eligibility(active_entity_ifc_class="IfcWall", selection_size=2) is True


def test_is_eligible_object_false_when_active_is_non_wall_ifc():
    """An IFC element that isn't a wall (e.g. column) must not show the gizmo.
    Z-rotation alignment was intentionally gated to walls — surfacing it on
    arbitrary IFC pairs adds noise."""
    assert _eligibility(active_entity_ifc_class="IfcColumn", selection_size=2) is False


def test_is_eligible_object_false_when_active_lacks_ifc_entity():
    """A plain Blender object with no IFC binding must not show the gizmo.
    Even if it were a wall in Blender's sense, without an IFC entity the
    operator's IFC sync is a no-op."""
    assert _eligibility(active_entity_ifc_class=None, selection_size=2) is False


@pytest.mark.parametrize("selection_size", [0, 1, 3])
def test_is_eligible_object_false_when_selection_size_not_two(selection_size):
    """The "align rotation to the other object" affordance only has a single
    unambiguous referent when exactly 2 objects are selected. Pin that any
    other cardinality hides the gizmo even when the active is a wall."""
    assert _eligibility(active_entity_ifc_class="IfcWall", selection_size=selection_size) is False


# ---------------------------------------------------------------------------
# CopyZRotationToSelected — flip property + Shift-modifier invoke
# ---------------------------------------------------------------------------


def test_copy_z_rotation_to_selected_has_flip_property():
    """The Shift-click affordance is implemented as a first-class ``flip``
    BoolProperty so the REGISTER+UNDO redo panel exposes it (the user can
    toggle the flip from the redo panel without re-invoking with Shift).
    Pin that the property is declared and defaults to False."""
    from bonsai.bim.module.model.product import CopyZRotationToSelected

    annotations = getattr(CopyZRotationToSelected, "__annotations__", {})
    assert "flip" in annotations, "CopyZRotationToSelected.flip BoolProperty is missing — Shift-click cannot dispatch."


def test_copy_z_rotation_to_selected_tooltip_mentions_shift_flip():
    """The bl_description doubles as the gizmo tooltip. Surface the Shift
    affordance there so the user can discover the flip mode without
    reading the source. Tying the docstring to the bl_description keeps
    the discoverability invariant visible."""
    from bonsai.bim.module.model.product import CopyZRotationToSelected

    description = CopyZRotationToSelected.bl_description.lower()
    assert "shift" in description and (
        "flip" in description or "180" in description
    ), f"bl_description must mention the Shift-flip affordance: {CopyZRotationToSelected.bl_description!r}"
