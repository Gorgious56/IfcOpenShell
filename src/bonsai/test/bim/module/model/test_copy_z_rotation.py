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

import math
from unittest.mock import Mock, patch

import pytest

from bonsai.core.product import Z_ROTATION_ALIGNMENT_TOLERANCE, _z_rotation_diff

pytestmark = pytest.mark.model


@pytest.mark.parametrize(
    "target_z,source_z,expected",
    [
        (0.0, 0.0, 0.0),
        (1.0, 0.5, 0.5),
        (-0.5, 0.5, -1.0),
        (math.pi, -math.pi, 0.0),
        (-math.pi, math.pi, 0.0),
        (math.pi - 0.01, -math.pi + 0.01, -0.02),
    ],
)
def test_z_rotation_diff_normalises_to_signed_half_turn(target_z, source_z, expected):
    assert _z_rotation_diff(target_z, source_z) == pytest.approx(expected, abs=Z_ROTATION_ALIGNMENT_TOLERANCE)


def test_z_rotation_diff_is_antisymmetric_modulo_wrap():
    a, b = 0.7, 0.3
    assert _z_rotation_diff(a, b) == pytest.approx(-_z_rotation_diff(b, a), abs=Z_ROTATION_ALIGNMENT_TOLERANCE)


def test_z_rotation_diff_skips_at_wraparound_boundary():
    assert abs(_z_rotation_diff(math.pi, -math.pi)) < Z_ROTATION_ALIGNMENT_TOLERANCE
    assert abs(_z_rotation_diff(-math.pi, math.pi)) < Z_ROTATION_ALIGNMENT_TOLERANCE
    assert abs(_z_rotation_diff(3 * math.pi, math.pi)) < Z_ROTATION_ALIGNMENT_TOLERANCE


def _eligibility(active_entity_ifc_class, selection_size):
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
    assert _eligibility(active_entity_ifc_class="IfcWall", selection_size=2) is True


def test_is_eligible_object_false_when_active_is_non_wall_ifc():
    assert _eligibility(active_entity_ifc_class="IfcColumn", selection_size=2) is False


def test_is_eligible_object_false_when_active_lacks_ifc_entity():
    assert _eligibility(active_entity_ifc_class=None, selection_size=2) is False


@pytest.mark.parametrize("selection_size", [0, 1, 3])
def test_is_eligible_object_false_when_selection_size_not_two(selection_size):
    assert _eligibility(active_entity_ifc_class="IfcWall", selection_size=selection_size) is False


def test_copy_z_rotation_to_selected_tooltip_mentions_shift_flip():
    from bonsai.bim.module.model.product import CopyZRotationToSelected

    description = CopyZRotationToSelected.bl_description.lower()
    assert "shift" in description and (
        "flip" in description or "180" in description
    ), f"bl_description must mention the Shift-flip affordance: {CopyZRotationToSelected.bl_description!r}"
