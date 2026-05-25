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

"""Static AST guards that pin structural invariants in
``bonsai.bim.module.model.wall``.

Each guard catches a class of bug that's expensive to find via user reports
because the visible failure mode is far from the regressed code:

- ``test_every_wall_mutating_caller_pairs_with_resync`` — non-edit-mode wall
  gizmos read coordinates from a cached draft. Any new wall-mutating call must
  re-prime that draft, otherwise the gizmos trip on stale geometry.
- ``test_wall_gizmo_z_routes_through_slope_aware_helper`` — wall gizmo
  positioning must convert ``props.height`` (vertical) into wall-local Z via
  ``core.extrusion_depth_from_vertical_height`` so icons land on the slanted
  top edge of sloped walls.
- ``test_wall_split_uses_extent_predicates`` — ``DumbWallJoiner.split`` must
  call the three ``opening_*_cut`` predicates rather than inlining the
  inequalities. The predicates are the single source of truth for the strict-
  vs-non-strict boundary contract; inlining a non-strict form would silently
  drop openings from both walls on a degenerate extent.

These tests run in the BIM lane because ``inspect.getsource`` requires the
module to import, and the wall module pulls in ``bpy`` / ``ifcopenshell`` at
load time. The AST traversal itself is pure Python."""

import ast
import inspect

import pytest

pytestmark = pytest.mark.wall


def _called_names(fn_node):
    """Yield every ``ast.Call``'s attribute or function name in ``fn_node``."""
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                yield node.func.attr
            elif isinstance(node.func, ast.Name):
                yield node.func.id


def test_every_wall_mutating_caller_pairs_with_resync():
    """Forward-compat guard for the stale-props class of bug.

    Walks every function / method in ``bonsai.bim.module.model.wall``; for any
    whose body contains a known wall-IFC-mutating call (regenerates extrusion
    geometry, re-joins endpoints, flips direction, offsets layer set, etc.),
    asserts the same body also calls ``_resync_walls_after_mutation`` or
    ``_maybe_resync_wall_props_from_ifc``. The two are paired: mutate the IFC,
    then re-prime the cached draft so the always-visible gizmos read fresh
    coordinates.

    Known-OK exemptions (whitelisted by qualified name) are listed in
    ``_WALL_MUTATING_WITHOUT_RESYNC_OK``. Each exemption documents *why* the
    resync is unnecessary at that site (e.g., fresh walls with no draft yet,
    or a pure helper whose caller owns the resync). Removing an exemption
    requires a comment justifying the new contract.

    Adding a wall-mutating call name to ``MUTATING_CALLS`` is how new wall
    operations get put under the contract. Each entry's comment names the
    mutation shape that requires the paired resync."""
    from bonsai.bim.module.model import wall as wall_module

    # Names of wall-mutating call shapes. Any function in wall.py that calls
    # one of these without a paired resync is flagged. Add new entries when a
    # new wall-IFC-mutating method ships — that's how the contract widens.
    MUTATING_CALLS = {
        # tool.Model.recalculate_walls(...) — regenerates extrusion geometry,
        # may shorten the wall via re-joining with neighbours.
        "recalculate_walls",
        # DumbWallJoiner().set_length(obj, length) — direct length mutation.
        "set_length",
        # DumbWallJoiner().flip(obj) — reverses direction sense, swaps anchor
        # X for the opposite end.
        "flip",
        # core.offset_walls(...) — changes the wall's offset baseline, may
        # invalidate cached anchor_x.
        "offset_walls",
        # core.align_walls(...) — aligns walls to a reference; may flip the
        # wall (internally calls DumbWallJoiner().flip).
        "align_walls",
    }

    RESYNC_CALLS = {"_resync_walls_after_mutation", "_maybe_resync_wall_props_from_ifc"}

    _WALL_MUTATING_WITHOUT_RESYNC_OK = {
        # Re-runs recalculate for every wall sharing a layer set; called from
        # material-layer edit paths whose own _execute is the resync owner.
        "regenerate_from_layer_set",
        # Creates fresh walls and recalculates / connects them in the same
        # loop. The new walls have no pre-existing BIMWallProperties draft,
        # so there is no cached state to be stale — the draft is populated
        # lazily on the first edit-mode enable for each wall.
        "create_walls_from_polyline",
        # Internal DumbWallAligner helpers. Both may call DumbWallJoiner().flip
        # on the wall they are aligning, but they are pure helpers — the only
        # caller is core.align_walls, which is itself called from the
        # bim.align_wall operator (AlignWall.execute), and that operator owns
        # the resync for every wall it touched.
        "align_last_layer",
        "align_first_layer",
    }

    source = inspect.getsource(wall_module)
    tree = ast.parse(source)

    offenders: list[tuple[str, set[str]]] = []
    for fn_node in ast.walk(tree):
        if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn_node.name in _WALL_MUTATING_WITHOUT_RESYNC_OK:
            continue
        calls = set(_called_names(fn_node))
        triggered = calls & MUTATING_CALLS
        if not triggered:
            continue
        if calls & RESYNC_CALLS:
            continue
        offenders.append((fn_node.name, triggered))

    assert not offenders, (
        "Functions in wall.py mutate a wall's IFC without a paired "
        "_resync_walls_after_mutation / _maybe_resync_wall_props_from_ifc "
        f"call in the same body: {offenders}. The non-edit-mode wall gizmos "
        "read positions from a cached draft BIMWallProperties; without the "
        "resync, the draft holds pre-mutation length / anchor_x / height / "
        "x_angle and the gizmos trip the in_range gate mid-wall. Add the "
        "resync call after the mutation, or whitelist the site with a "
        "justifying comment in _WALL_MUTATING_WITHOUT_RESYNC_OK if no draft "
        "can be stale at that point."
    )


def test_wall_gizmo_z_routes_through_slope_aware_helper():
    """Forward-compat guard for the slope-aware Z conversion class of bug.

    The two wall gizmo positioning functions (``_position_cursor_anchored_gizmos``
    for the scissors / extend icons, ``_position_icon_row_extras`` for the
    validate / cancel / rotate / baseline / toggle-openings row) must both
    convert ``props.height`` (vertical / world-Z height) into a wall-local Z
    via ``core.extrusion_depth_from_vertical_height`` before composing
    ``mw @ Vector((..., local_z))``. Skipping the conversion drops the icon
    at world Z = ``cos(x_angle) * props.height`` on sloped walls — visually
    inside the wall body rather than on the slanted top edge.

    The helper's math is covered in the core lane; this test pins the
    *routing* at each call site so a future refactor that swaps the helper
    for a raw ``props.height`` regresses CI rather than silently misplacing
    the icons on slope-edited walls."""
    from bonsai.bim.module.model import wall as wall_module

    REQUIRED_HELPER = "extrusion_depth_from_vertical_height"
    REQUIRED_CALLERS = {"_position_cursor_anchored_gizmos", "_position_icon_row_extras"}

    source = inspect.getsource(wall_module)
    tree = ast.parse(source)

    missing: list[str] = []
    seen: set[str] = set()
    for fn_node in ast.walk(tree):
        if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn_node.name not in REQUIRED_CALLERS:
            continue
        seen.add(fn_node.name)
        if REQUIRED_HELPER not in set(_called_names(fn_node)):
            missing.append(fn_node.name)

    assert seen == REQUIRED_CALLERS, (
        f"Expected to find both {REQUIRED_CALLERS} in wall.py but only saw "
        f"{seen}. The function may have been renamed; update REQUIRED_CALLERS "
        "to match (and confirm the renamed function still converts vertical "
        f"height to local-Z via core.{REQUIRED_HELPER})."
    )
    assert not missing, (
        f"Wall gizmo positioning function(s) {missing} no longer route "
        f"props.height through core.{REQUIRED_HELPER}. Feeding props.height "
        "directly as a wall-local Z drops the icon below the slanted top "
        "edge by props.height * (1 - cos(x_angle)) on sloped walls. Restore "
        f"the call to core.{REQUIRED_HELPER}(props.height, props.x_angle), "
        "or whitelist the function explicitly if a different slope-aware "
        "conversion is in use."
    )


def test_wall_split_uses_extent_predicates():
    """Forward-compat guard for the wall-split cut-decision class of bug.

    The three predicates ``opening_is_past_cut`` / ``opening_is_before_cut`` /
    ``opening_straddles_cut`` in ``bonsai.core.model`` carry the strict-vs-
    non-strict inequality contract that decides which side of a wall split
    keeps each opening. ``DumbWallJoiner.split`` must call those predicates
    rather than inline the inequalities — inlining would let a future ``>=`` /
    ``<=`` regression bypass the predicate's unit tests entirely.

    The predicate behaviour itself is covered in the core lane; this test
    pins that production *calls* the predicate. If a future edit replaces
    ``core.opening_is_past_cut(...)`` with an inline ``min_t > cut`` the test
    fires before the bug ships."""
    from bonsai.bim.module.model import wall as wall_module

    REQUIRED_PREDICATES = {
        "opening_is_past_cut",
        "opening_is_before_cut",
        "opening_straddles_cut",
    }

    source = inspect.getsource(wall_module)
    tree = ast.parse(source)

    # Locate DumbWallJoiner.split and collect every name it calls. A method
    # lives one ClassDef down — walk the tree finding the class first, then
    # the method on it.
    split_node = None
    for class_node in ast.walk(tree):
        if not isinstance(class_node, ast.ClassDef) or class_node.name != "DumbWallJoiner":
            continue
        for child in class_node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "split":
                split_node = child
                break
        break

    assert split_node is not None, (
        "Could not locate DumbWallJoiner.split in wall.py. The class or method "
        "may have been renamed; update this guard so the predicate-call contract "
        "follows the new location."
    )

    calls_in_split = set(_called_names(split_node))
    missing = REQUIRED_PREDICATES - calls_in_split

    assert not missing, (
        f"DumbWallJoiner.split no longer calls {sorted(missing)} from "
        "bonsai.core.model. The three predicates are the single source of "
        "truth for the strict-vs-non-strict cut boundary; inlining the "
        "inequalities back into split() bypasses their unit tests and "
        "re-opens the degenerate-extent class of bug (opening dropped from "
        "both walls when its extent collapses onto the cut). Call the "
        "predicates via `core.opening_is_past_cut(...)` etc. — or, if the "
        "predicate truly needs to be inlined for a measured reason, delete "
        "this guard with a comment naming the replacement contract test."
    )
