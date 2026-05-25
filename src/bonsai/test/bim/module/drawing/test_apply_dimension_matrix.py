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

"""Pin the negative-value flip contract of ``_apply_dimension_matrix``.

The dim-gizmo plumbing reverses the gizmo basis 180° around Z whenever
``compute_value`` is negative — that's the lever ``wall_offset_gizmos`` (and
potentially future signed-value dim gizmos) pulls so a door rotated 180°
around Z renders its offset arrow in the correct world direction without
needing a per-frame dynamic axis.

If a future refactor of ``_apply_dimension_matrix`` changes that contract
(e.g. abs()-at-the-gizmo, removes the flip, swaps to a different axis) the
flipped-door arrows silently render the wrong way without any other test
catching it. These assertions are the safety net."""

from types import SimpleNamespace

import pytest
from mathutils import Matrix, Vector

from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

pytestmark = pytest.mark.drawing


def _call(value):
    """Invoke ``_apply_dimension_matrix`` as an unbound method against a fake
    self that carries the real ``FLIP_MATRIX`` class constant. Returns the
    ``matrix_basis`` written onto the gizmo stand-in."""
    gizmo = SimpleNamespace()
    fake_self = SimpleNamespace(FLIP_MATRIX=BaseParametricGizmoGroup.FLIP_MATRIX)
    BaseParametricGizmoGroup._apply_dimension_matrix(fake_self, gizmo, Matrix.Identity(4), Matrix.Identity(4), value)
    return gizmo.matrix_basis


def test_positive_value_writes_unflipped_basis():
    assert _call(1.5) == Matrix.Identity(4)


def test_zero_value_writes_unflipped_basis():
    # ``value == 0`` is not ``< 0``, so the flip path must not trigger.
    assert _call(0.0) == Matrix.Identity(4)


def test_none_value_writes_unflipped_basis():
    assert _call(None) == Matrix.Identity(4)


def test_negative_value_writes_flipped_basis():
    # With ``mw`` and ``base_matrix`` both identity, the result is just the
    # FLIP_MATRIX itself — the multiplication chain reduces to ``I @ I @ FLIP``.
    assert _call(-1.5) == BaseParametricGizmoGroup.FLIP_MATRIX


def test_flip_matrix_is_180_around_z():
    # ``wall_offset_gizmos`` depends on the flip being EXACTLY a Z-axis 180°
    # rotation — anything else would render the arrow rotated about the wrong
    # axis. Pin the axis-of-rotation and magnitude explicitly so a future
    # "flip on a different axis" refactor breaks here loudly.
    flip = BaseParametricGizmoGroup.FLIP_MATRIX
    assert (flip @ Vector((1.0, 0.0, 0.0))).x == pytest.approx(-1.0)
    assert (flip @ Vector((0.0, 1.0, 0.0))).y == pytest.approx(-1.0)
    assert (flip @ Vector((0.0, 0.0, 1.0))).z == pytest.approx(1.0)
