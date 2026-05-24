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

"""Contract tests for the shared decorator cache module.

The cache token + persistent handler are the only thing protecting cached
``bpy.types.Object`` refs in dependent decorators from being dereferenced
after the underlying object is freed. These tests pin that contract:

- The 4-hook invalidation list (depsgraph/undo/redo/load) is symmetrically
  managed by install/uninstall. A future edit that drops a hook from one
  side without the other lands as a Blender segfault — the regression must
  surface as a test failure first.
- The handler increments the token and accepts Blender's variadic args."""

import bpy
import pytest

from bonsai.bim import decorator_cache

pytestmark = pytest.mark.model


@pytest.fixture(autouse=True)
def _reset_cache_token():
    """Fresh token between tests so the bump-count assertions are stable."""
    decorator_cache._DECORATOR_CACHE_TOKEN = 0
    yield


def test_install_and_uninstall_manage_all_invalidation_hooks():
    """install_decorator_cache_handlers() must register the bump handler in
    every hook the dependent decorators rely on; uninstall must remove it
    from every hook install touched. Catches the regression class where
    a hook is dropped from one side and not the other."""
    expected_hooks = (
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
        bpy.app.handlers.load_post,
    )

    # Defensive cleanup in case a previous addon-init run left the handler
    # registered — the test must observe a clean slate before install().
    for hook in expected_hooks:
        while decorator_cache._bump_decorator_cache_token in hook:
            hook.remove(decorator_cache._bump_decorator_cache_token)

    try:
        decorator_cache.install_decorator_cache_handlers()
        for hook in expected_hooks:
            assert decorator_cache._bump_decorator_cache_token in hook, (
                "install_decorator_cache_handlers() must register the bump "
                "handler in every hook a dependent cache relies on"
            )
        decorator_cache.uninstall_decorator_cache_handlers()
        for hook in expected_hooks:
            assert decorator_cache._bump_decorator_cache_token not in hook, (
                "uninstall_decorator_cache_handlers() must remove the bump " "handler from every hook install touched"
            )
    finally:
        # Make sure the test never leaves the handler dangling.
        for hook in expected_hooks:
            while decorator_cache._bump_decorator_cache_token in hook:
                hook.remove(decorator_cache._bump_decorator_cache_token)


def test_install_is_idempotent():
    """Calling install twice must not double-register the bump handler —
    the addon-init path may run on script reload and we don't want to
    invalidate the cache twice per event."""
    hook = bpy.app.handlers.depsgraph_update_post

    while decorator_cache._bump_decorator_cache_token in hook:
        hook.remove(decorator_cache._bump_decorator_cache_token)

    try:
        decorator_cache.install_decorator_cache_handlers()
        decorator_cache.install_decorator_cache_handlers()
        appearances = sum(1 for h in hook if h is decorator_cache._bump_decorator_cache_token)
        assert appearances == 1, "install must not double-register"
    finally:
        decorator_cache.uninstall_decorator_cache_handlers()


def test_bump_handler_increments_token():
    """The handler that depsgraph/undo/redo/load hooks call must increment
    the module-level cache token. If it doesn't move, stale Object refs
    survive in dependent caches."""
    decorator_cache._bump_decorator_cache_token()
    assert decorator_cache._DECORATOR_CACHE_TOKEN == 1
    # Blender's hook lists pass positional args (scene, depsgraph, …). The
    # handler must accept them without raising — it's registered against
    # four event types with different signatures.
    decorator_cache._bump_decorator_cache_token("scene", "depsgraph")
    assert decorator_cache._DECORATOR_CACHE_TOKEN == 2


def test_get_decorator_cache_token_reads_current_value():
    """``get_decorator_cache_token()`` is the public read interface — it must
    reflect the current token, not a captured-at-import-time value."""
    initial = decorator_cache.get_decorator_cache_token()
    decorator_cache._bump_decorator_cache_token()
    assert decorator_cache.get_decorator_cache_token() == initial + 1
