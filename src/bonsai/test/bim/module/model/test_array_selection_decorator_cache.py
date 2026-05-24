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

"""Unit tests for ArraySelectionHighlightDecorator's family-resolution cache.

The decorator runs every POST_VIEW redraw (60+ FPS while the user rotates
the viewport). These tests pin that the IFC graph traversal which resolves
``(parent_obj, siblings)`` only runs on cache miss — not on every redraw —
so a future regression that re-walks the array family per frame is caught
by a focused assertion rather than by manual viewport testing."""

import contextlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from bonsai import tool
from bonsai.bim import decorator_cache
from bonsai.bim.module.model import decorator as decorator_module
from bonsai.bim.module.model.decorator import ArraySelectionHighlightDecorator
from test.bim.module.model.conftest import make_element, make_obj

pytestmark = pytest.mark.model


def _make_prefs() -> SimpleNamespace:
    # decorator_color_special / _unselected are RGBA-ish iterables; the decorator
    # only slices [:3]. Tuples are enough — no Blender Color needed in tests.
    return SimpleNamespace(
        decorator_color_special=(1.0, 0.5, 0.0, 1.0),
        decorator_color_unselected=(0.5, 0.5, 0.5, 1.0),
    )


@pytest.fixture(autouse=True)
def _reset_cache_token():
    """Reset the shared decorator cache token before each test so cached
    state from a prior test cannot bleed into the next one. Test independence
    is now visible at fixture scope instead of repeated on every test's first
    line."""
    decorator_cache._DECORATOR_CACHE_TOKEN = 0
    yield


@pytest.fixture
def patched_draw_env(patched_tool):
    """Context-manager factory for the ArraySelectionHighlightDecorator.draw()
    patch stack. Composes the shared ``patched_tool`` fixture (viewport-state
    + modifier predicates) with the decorator-specific stubs for
    ``tool.Model.get_array_props`` and the two GPU-touching module helpers.
    Use as::

        with patched_draw_env(is_array_child=True, is_array=False):
            _run_draw(decorator, obj, element)"""

    @contextlib.contextmanager
    def _factory(is_array_child: bool, is_array: bool, props_is_editing: bool = False):
        prefs = _make_prefs()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patched_tool(
                    viewport_gizmos=True,
                    addon_prefs=prefs,
                    modifier_predicates={"is_array_child": is_array_child, "is_array": is_array},
                )
            )
            stack.enter_context(
                patch.object(
                    tool.Model,
                    "get_array_props",
                    return_value=SimpleNamespace(is_editing=props_is_editing),
                )
            )
            # Replace the GPU call with a no-op so tests don't touch a real GL context.
            stack.enter_context(patch.object(decorator_module, "draw_polyline_segments", return_value=None))
            # bbox_world_edges is fine to call (it only reads obj.bound_box) but our
            # Mock objects have no bound_box, so stub it to a known segment list.
            stack.enter_context(
                patch.object(decorator_module, "bbox_world_edges", return_value=[((0, 0, 0), (1, 0, 0))])
            )
            yield

    return _factory


def _run_draw(decorator: ArraySelectionHighlightDecorator, obj: Mock, element: Mock) -> None:
    """Invoke draw() with stubbed get_entity. The decorator reads element from
    tool.Ifc.get_entity(obj), which we stub on a per-call basis."""
    context = SimpleNamespace(active_object=obj)
    with patch.object(tool.Ifc, "get_entity", return_value=element):
        decorator.draw(context)


def test_family_cache_hits_on_repeated_draw_for_same_child(monkeypatch, patched_draw_env):
    """Two consecutive draws for the same selected child must only resolve the
    array family once — repeated IFC graph traversal is the lag the cache
    exists to prevent."""
    decorator = ArraySelectionHighlightDecorator()

    obj = make_obj(session_uid=10)
    element = make_element(step_id=100)
    parent_obj = make_obj(session_uid=20)
    siblings = [make_obj(session_uid=30), make_obj(session_uid=31)]

    collect = Mock(return_value=(parent_obj, siblings))
    monkeypatch.setattr(decorator, "_collect_family_from_child", collect)

    with patched_draw_env(is_array_child=True, is_array=False):
        _run_draw(decorator, obj, element)
        _run_draw(decorator, obj, element)
        _run_draw(decorator, obj, element)

    assert collect.call_count == 1, "cache should hit on identical active object + token"


def test_family_cache_misses_when_active_object_changes(monkeypatch, patched_draw_env):
    decorator = ArraySelectionHighlightDecorator()

    obj_a = make_obj(session_uid=10)
    obj_b = make_obj(session_uid=11)
    element_a = make_element(step_id=100)
    element_b = make_element(step_id=101)
    parent_obj = make_obj(session_uid=20)

    collect = Mock(return_value=(parent_obj, []))
    monkeypatch.setattr(decorator, "_collect_family_from_child", collect)

    with patched_draw_env(is_array_child=True, is_array=False):
        _run_draw(decorator, obj_a, element_a)
        _run_draw(decorator, obj_b, element_b)

    assert collect.call_count == 2, "different active object must re-resolve"


def test_family_cache_misses_when_token_bumps(monkeypatch, patched_draw_env):
    """Structural changes (depsgraph/undo/redo/load) bump the module token. The
    next draw must re-resolve so stale bpy.types.Object refs are not used."""
    decorator = ArraySelectionHighlightDecorator()

    obj = make_obj(session_uid=10)
    element = make_element(step_id=100)
    parent_obj = make_obj(session_uid=20)

    collect = Mock(return_value=(parent_obj, []))
    monkeypatch.setattr(decorator, "_collect_family_from_child", collect)

    with patched_draw_env(is_array_child=True, is_array=False):
        _run_draw(decorator, obj, element)
        # Simulate the handler firing — a deletion, undo, or array edit.
        decorator_cache._bump_decorator_cache_token()
        _run_draw(decorator, obj, element)

    assert collect.call_count == 2, "token bump must invalidate the cache"


def test_negative_family_result_is_cached(monkeypatch, patched_draw_env):
    """If the family can't be resolved (broken pset, deleted parent, etc.) the
    None result is cached too — otherwise the decorator would re-query the IFC
    graph every redraw for an unresolvable family."""
    decorator = ArraySelectionHighlightDecorator()

    obj = make_obj(session_uid=10)
    element = make_element(step_id=100)

    collect = Mock(return_value=None)
    monkeypatch.setattr(decorator, "_collect_family_from_child", collect)

    with patched_draw_env(is_array_child=True, is_array=False):
        _run_draw(decorator, obj, element)
        _run_draw(decorator, obj, element)

    assert collect.call_count == 1, "negative result must also be cached"


def test_parent_and_child_modes_have_separate_cache_entries(monkeypatch, patched_draw_env):
    """The cache key tags 'parent' vs 'child' mode so a parent-selected draw
    after a child-selected draw on objects that happen to share a session_uid
    + element id (degenerate but possible after undo cycles) does not pick up
    the wrong cached value."""
    decorator = ArraySelectionHighlightDecorator()

    obj_child = make_obj(session_uid=10)
    element_child = make_element(step_id=100)
    obj_parent = make_obj(session_uid=11)
    element_parent = make_element(step_id=101)

    collect_family = Mock(return_value=(make_obj(session_uid=20), []))
    collect_children = Mock(return_value=[])
    monkeypatch.setattr(decorator, "_collect_family_from_child", collect_family)
    monkeypatch.setattr(decorator, "_collect_children", collect_children)

    with patched_draw_env(is_array_child=True, is_array=False):
        _run_draw(decorator, obj_child, element_child)

    with patched_draw_env(is_array_child=False, is_array=True):
        _run_draw(decorator, obj_parent, element_parent)
        _run_draw(decorator, obj_parent, element_parent)

    assert collect_family.call_count == 1
    assert collect_children.call_count == 1, "parent-mode cache should hit on second draw"
