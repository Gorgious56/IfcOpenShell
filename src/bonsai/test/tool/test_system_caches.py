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

"""Unit tests for tool.System.get_decoration_data's per-frame cache.

The cached dict is reused across redraws until the shared decorator cache
token bumps. This eliminates the per-redraw vertex/edge rebuild that lags
``SystemDecorator`` at 20+ MEP elements."""

from unittest.mock import Mock

import pytest

from bonsai import tool
from bonsai.bim import decorator_cache
from bonsai.bim.module.system import data as system_data

pytestmark = pytest.mark.system


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with empty caches + token=0 so call-count
    assertions are stable across the file."""
    tool.System._decoration_data_cache_key = None
    tool.System._decoration_data_cache = None
    decorator_cache.reset_for_test()
    yield
    tool.System._decoration_data_cache_key = None
    tool.System._decoration_data_cache = None


def test_decoration_data_cache_reuses_dict_on_steady_token(monkeypatch):
    """get_decoration_data() must reuse the cached dict when the token and
    the decorated-elements set identity both match — the rebuild does N×
    get_object + per-port world transforms per redraw at scale."""
    elements_set = {Mock(name="elem-a"), Mock(name="elem-b")}
    monkeypatch.setattr(system_data.SystemDecorationData, "is_loaded", True)
    monkeypatch.setattr(
        system_data.SystemDecorationData,
        "data",
        {"decorated_elements": elements_set},
    )
    monkeypatch.setattr(system_data.ObjectSystemData, "is_loaded", True)

    sentinel = {
        "all_vertices": [],
        "preview_edges": [],
        "special_vertices": [],
        "selected_edges": [],
        "selected_vertices": [],
    }
    build = Mock(return_value=sentinel)
    monkeypatch.setattr(tool.System, "_build_decoration_data", build)

    result_a = tool.System.get_decoration_data()
    result_b = tool.System.get_decoration_data()

    assert build.call_count == 1, "decoration data must be cached across redraws when nothing structural changed"
    assert result_a is result_b is sentinel


def test_decoration_data_cache_misses_on_token_bump(monkeypatch):
    """Any depsgraph / undo / redo / load event bumps the shared decorator
    cache token. The next get_decoration_data() must rebuild — the cached
    arrays hold world-space positions composed from obj.matrix_world, which
    has just changed."""
    elements_set = {Mock(name="elem")}
    monkeypatch.setattr(system_data.SystemDecorationData, "is_loaded", True)
    monkeypatch.setattr(
        system_data.SystemDecorationData,
        "data",
        {"decorated_elements": elements_set},
    )
    monkeypatch.setattr(system_data.ObjectSystemData, "is_loaded", True)

    build = Mock(return_value={})
    monkeypatch.setattr(tool.System, "_build_decoration_data", build)

    tool.System.get_decoration_data()
    decorator_cache._bump_decorator_cache_token()
    tool.System.get_decoration_data()

    assert build.call_count == 2, "token bump must invalidate the decoration data cache"


def test_decoration_data_cache_misses_on_set_change(monkeypatch):
    """When SystemDecorationData.load() produces a new decorated-elements
    set (e.g. the user toggled to a different system), the cache key's
    set-identity check must miss and force a rebuild."""
    monkeypatch.setattr(system_data.SystemDecorationData, "is_loaded", True)
    monkeypatch.setattr(system_data.ObjectSystemData, "is_loaded", True)

    build = Mock(return_value={})
    monkeypatch.setattr(tool.System, "_build_decoration_data", build)

    monkeypatch.setattr(
        system_data.SystemDecorationData,
        "data",
        {"decorated_elements": {Mock(name="elem-a")}},
    )
    tool.System.get_decoration_data()

    monkeypatch.setattr(
        system_data.SystemDecorationData,
        "data",
        {"decorated_elements": {Mock(name="elem-b")}},
    )
    tool.System.get_decoration_data()

    assert build.call_count == 2, "different decorated-elements set must rebuild"
