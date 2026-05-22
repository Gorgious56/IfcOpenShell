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

"""Unit tests for door swing-arc matrix composition.

``GizmoArc`` renders a single canonical (LEFT-direction) shape and the door's
gizmo group applies a flip-X matrix to obtain the RIGHT visual. The flip-arc
preview always adds a Y mirror so it reads as the alternate swing direction
the toggle operator would commit. Two consumers must show the right matrix
for each combination of ``"RIGHT" in door_type`` × {door_type, flip_arc}.
"""

import types

import pytest
from mathutils import Matrix

pytestmark = pytest.mark.model

# Tolerance for matrix element comparison — floating-point sin/cos round-trips.
_TOL = 1e-6


def _matrix_close(a: Matrix, b: Matrix) -> bool:
    for row_a, row_b in zip(a, b):
        for va, vb in zip(row_a, row_b):
            if abs(va - vb) > _TOL:
                return False
    return True


def _make_props(door_type: str, overall_width: float = 1.0, lining_offset: float = 0.0):
    return types.SimpleNamespace(
        door_type=door_type,
        overall_width=overall_width,
        lining_offset=lining_offset,
    )


def test_swing_arc_matrices_left_door_type_no_flip_x():
    """LEFT door_type ⇒ flip_x is identity; door_type_matrix is base * I."""
    from bonsai.bim.module.model.door import GizmoDoorEdition

    mw = Matrix.Identity(4)
    props = _make_props("SINGLE_SWING_LEFT", overall_width=1.0)

    door_type_matrix, _flip_arc_matrix = GizmoDoorEdition._compute_swing_arc_matrices(mw, props)

    # Pivot at the LEFT jamb (x=0); a vertex at (1, 0, 0) on the canonical
    # LEFT arc lands at the right jamb after the unit-width scale.
    landed = door_type_matrix @ Matrix.Translation((1.0, 0.0, 0.0)).to_translation()
    assert abs(landed.x - 1.0) < _TOL
    assert abs(landed.y - 0.0) < _TOL


def test_swing_arc_matrices_right_door_type_applies_flip_x():
    """RIGHT door_type ⇒ flip_x flips X; pivot shifts to overall_width.

    Combined: the canonical LEFT arc (x∈[0,1]) gets mirrored to x∈[-1,0]
    then scaled by overall_width, then translated by overall_width — so a
    vertex at canonical (1, 0, 0) lands at world x = 0 (the left jamb)."""
    from bonsai.bim.module.model.door import GizmoDoorEdition

    mw = Matrix.Identity(4)
    props = _make_props("SINGLE_SWING_RIGHT", overall_width=2.0)

    door_type_matrix, _flip_arc_matrix = GizmoDoorEdition._compute_swing_arc_matrices(mw, props)

    # Canonical LEFT-arc tip at (1, 0, 0) → flip_x → (-1, 0, 0) → scale 2 →
    # (-2, 0, 0) → translate (2, lining_offset, 0) → (0, 0, 0).
    canonical_tip = door_type_matrix @ Matrix.Translation((1.0, 0.0, 0.0)).to_translation()
    assert abs(canonical_tip.x - 0.0) < _TOL


def test_swing_arc_matrices_flip_arc_adds_y_mirror_on_left_door():
    """flip_arc_matrix = door_type_matrix @ mirror_y. A vertex at (0, 1, 0)
    must end up at negative Y after the mirror."""
    from bonsai.bim.module.model.door import GizmoDoorEdition

    mw = Matrix.Identity(4)
    props = _make_props("SINGLE_SWING_LEFT", overall_width=1.0)

    door_type_matrix, flip_arc_matrix = GizmoDoorEdition._compute_swing_arc_matrices(mw, props)
    expected_flip = door_type_matrix @ Matrix.Scale(-1, 4, (0, 1, 0))
    assert _matrix_close(flip_arc_matrix, expected_flip)


def test_swing_arc_matrices_world_transform_pre_composes():
    """``mw`` left-multiplies the swing transform. Door at world (10, 20, 0)
    should see its swing-arc matrices translated accordingly."""
    from bonsai.bim.module.model.door import GizmoDoorEdition

    world_offset = (10.0, 20.0, 0.0)
    mw = Matrix.Translation(world_offset)
    props = _make_props("SINGLE_SWING_LEFT", overall_width=1.0)

    door_type_matrix, flip_arc_matrix = GizmoDoorEdition._compute_swing_arc_matrices(mw, props)

    # Door pivots at the local origin (0, 0, 0); under mw, that lands at
    # world (10, 20, 0). Both door_type and flip_arc share the same pivot.
    assert abs(door_type_matrix.to_translation().x - world_offset[0]) < _TOL
    assert abs(door_type_matrix.to_translation().y - world_offset[1]) < _TOL
    assert abs(flip_arc_matrix.to_translation().x - world_offset[0]) < _TOL
    assert abs(flip_arc_matrix.to_translation().y - world_offset[1]) < _TOL
