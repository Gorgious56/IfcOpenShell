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

"""Structural invariants for the open/closed padlock glyph data.

The glyphs are pure triangle tuples, so a headless test pins the shape
signature instead of rendered pixels: a closed padlock keeps every shackle
vertex within the body width, while an open padlock lifts at least one
shackle vertex beyond it. Thresholds are derived from the glyph data so
the test survives a uniform glyph resize.
"""

import types

import bpy
import pytest

pytestmark = pytest.mark.drawing

EPS = 1e-3


@pytest.fixture(autouse=True)
def _require_real_bpy():
    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")


def _body_geometry(tris: tuple) -> tuple[float, float]:
    """Return (body_half_width, body_top_y) inferred from the lock-body
    rectangle in the glyph data."""
    y_baseline = min(v[1] for v in tris)
    body_half_width = max(abs(v[0]) for v in tris if v[1] <= y_baseline + EPS)
    body_top_y = max(v[1] for v in tris if abs(abs(v[0]) - body_half_width) < EPS)
    return body_half_width, body_top_y


def _shackle_vertices(tris: tuple, body_top_y: float) -> list:
    return [v for v in tris if v[1] > body_top_y + EPS]


def test_lock_tris_closed_shackle_stays_within_body_width():
    """Closed padlock: every shackle vertex must sit within the body width."""
    from bonsai.bim.module.drawing.gizmos import LOCK_TRIS_CLOSED

    body_half_width, body_top_y = _body_geometry(LOCK_TRIS_CLOSED)
    shackle = _shackle_vertices(LOCK_TRIS_CLOSED, body_top_y)
    assert shackle, "closed lock has no shackle vertices above the body top"
    over = [v for v in shackle if abs(v[0]) > body_half_width + EPS]
    assert not over, (
        f"closed-lock shackle vertices extend beyond body width "
        f"(|x| > {body_half_width:.3f}): {over[:3]}"
    )


def test_lock_tris_open_shackle_extends_beyond_body_width():
    """Open padlock: at least one shackle vertex must sit beyond the body."""
    from bonsai.bim.module.drawing.gizmos import LOCK_TRIS_OPEN

    body_half_width, body_top_y = _body_geometry(LOCK_TRIS_OPEN)
    shackle = _shackle_vertices(LOCK_TRIS_OPEN, body_top_y)
    assert shackle, "open lock has no shackle vertices above the body top"
    lifted = [v for v in shackle if abs(v[0]) > body_half_width + EPS]
    assert lifted, (
        f"open-lock shackle has no vertex beyond body width "
        f"(|x| > {body_half_width:.3f}); shape would render as closed"
    )


def test_gizmo_lock_classes_bind_matching_glyph_data():
    """The gizmo registered as ``VIEW3D_GT_lock_open`` must draw the open
    glyph, and likewise for closed — otherwise a renamed binding would
    silently invert the visible state across every consumer."""
    from bonsai.bim.module.drawing.gizmos import (
        LOCK_TRIS_CLOSED,
        LOCK_TRIS_OPEN,
        GizmoLockClosed,
        GizmoLockOpen,
    )

    assert GizmoLockOpen.tris is LOCK_TRIS_OPEN
    assert GizmoLockClosed.tris is LOCK_TRIS_CLOSED
