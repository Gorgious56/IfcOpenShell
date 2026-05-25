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

"""Unit tests for MEPSystemPathDecorator's second-tier geometry cache.

The decorator already caches the BFS walk on selection change. These tests
pin the SECOND-tier cache: the resolved ``(lines, port_positions)`` arrays
built from each walk pass. The cache eliminates the per-element
``get_object`` / per-port ``get_port_world_position`` loop on every redraw
that follows a no-mutation viewport navigation — the dominant per-frame
cost at 20+ elements."""

import contextlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from bonsai import tool
from bonsai.bim import decorator_cache
from bonsai.bim.module.model import decorator as decorator_module
from bonsai.bim.module.model.decorator import MEPSystemPathDecorator

pytestmark = pytest.mark.model


@pytest.fixture(autouse=True)
def _reset_cache_token():
    decorator_cache.reset_for_test()
    yield


@pytest.fixture
def patched_draw_env():
    """Stack the patches MEPSystemPathDecorator.draw() needs to run without
    a real IFC file or GPU context. Use as::

        with patched_draw_env(show=True, selected=[obj], entity_for=lambda o: element):
            decorator.draw(context)"""

    @contextlib.contextmanager
    def _factory(show: bool, selected: list, entity_for, walk_result):
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    tool.Model,
                    "get_model_props",
                    return_value=SimpleNamespace(show_paths=show),
                )
            )
            stack.enter_context(patch.object(tool.Ifc, "get", return_value=Mock(name="ifc_file")))
            stack.enter_context(patch.object(tool.Ifc, "get_entity", side_effect=entity_for))
            stack.enter_context(patch.object(tool.System, "is_mep_element", return_value=True))
            stack.enter_context(patch.object(tool.System, "walk_connected_mep_elements", return_value=walk_result))
            stack.enter_context(
                patch.object(
                    tool.Blender,
                    "get_addon_preferences",
                    return_value=SimpleNamespace(decorator_color_selected=(1.0, 0.5, 0.0, 1.0)),
                )
            )
            # No-op the GPU + segment stroke paths.
            stack.enter_context(patch.object(decorator_module, "_stroke_lines_alpha", return_value=None))
            stack.enter_context(patch.object(decorator_module, "batch_for_shader", return_value=Mock(draw=Mock())))
            stack.enter_context(patch.object(decorator_module.gpu.shader, "from_builtin", return_value=Mock()))
            stack.enter_context(patch.object(decorator_module.gpu.state, "point_size_set"))
            stack.enter_context(patch.object(decorator_module.gpu.state, "blend_set"))
            yield context_for(selected=selected)

    return _factory


def context_for(*, selected):
    return SimpleNamespace(selected_objects=selected)


def _make_selected(element):
    obj = Mock()
    obj.session_uid = id(element)
    return obj, element


def test_geometry_cache_hits_when_token_steady(patched_draw_env, monkeypatch):
    """Two consecutive draws with the same walk + token must call
    _build_geometry once. This is the cache that eliminates the dominant
    per-frame cost (N× get_object + per-port get_port_world_position)."""
    decorator = MEPSystemPathDecorator()
    element = Mock()
    element.GlobalId = "guid-abc"
    obj, _ = _make_selected(element)

    build = Mock(return_value=([((0, 0, 0), (1, 0, 0))], [(0, 0, 0), (1, 0, 0)]))
    monkeypatch.setattr(decorator, "_build_geometry", build)

    with patched_draw_env(
        show=True,
        selected=[obj],
        entity_for=lambda o: element if o is obj else None,
        walk_result=[element],
    ) as ctx:
        decorator.draw(ctx)
        decorator.draw(ctx)
        decorator.draw(ctx)

    assert build.call_count == 1, "geometry cache must reuse arrays when nothing structurally changed"


def test_geometry_cache_misses_when_token_bumps(patched_draw_env, monkeypatch):
    """A depsgraph/undo/redo/load event bumps the shared token. The next
    draw must rebuild the geometry — the cache holds bpy.types.Object refs
    indirectly via the world coordinates, so they could be stale."""
    decorator = MEPSystemPathDecorator()
    element = Mock()
    element.GlobalId = "guid-abc"
    obj, _ = _make_selected(element)

    build = Mock(return_value=([], []))
    monkeypatch.setattr(decorator, "_build_geometry", build)

    with patched_draw_env(
        show=True,
        selected=[obj],
        entity_for=lambda o: element if o is obj else None,
        walk_result=[element],
    ) as ctx:
        decorator.draw(ctx)
        decorator_cache._bump_decorator_cache_token()
        decorator.draw(ctx)

    assert build.call_count == 2, "token bump must invalidate the geometry cache"


def test_geometry_cache_misses_on_selection_change(patched_draw_env, monkeypatch):
    """A new selection changes the start GUID; the geometry-cache key includes
    ``start_guid`` so the new walk forces a rebuild even when the token is
    unchanged."""
    decorator = MEPSystemPathDecorator()
    element_a = Mock()
    element_a.GlobalId = "guid-a"
    element_b = Mock()
    element_b.GlobalId = "guid-b"
    obj_a, _ = _make_selected(element_a)
    obj_b, _ = _make_selected(element_b)

    build = Mock(return_value=([], []))
    monkeypatch.setattr(decorator, "_build_geometry", build)

    with patched_draw_env(
        show=True,
        selected=[obj_a],
        entity_for=lambda o: element_a,
        walk_result=[element_a],
    ) as ctx_a:
        decorator.draw(ctx_a)

    with patched_draw_env(
        show=True,
        selected=[obj_b],
        entity_for=lambda o: element_b,
        walk_result=[element_b],
    ) as ctx_b:
        decorator.draw(ctx_b)

    assert build.call_count == 2, "selection change must rebuild geometry"


def test_show_paths_off_short_circuits(patched_draw_env, monkeypatch):
    """When the toggle is off, draw() must return before doing any work.
    Cheap gate — one attribute read per redraw."""
    decorator = MEPSystemPathDecorator()
    build = Mock()
    monkeypatch.setattr(decorator, "_build_geometry", build)

    with patched_draw_env(
        show=False,
        selected=[],
        entity_for=lambda o: None,
        walk_result=[],
    ) as ctx:
        decorator.draw(ctx)

    assert build.call_count == 0, "toggle-off must short-circuit before geometry build"
