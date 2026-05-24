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

"""Shared structural-change cache token for POST_VIEW decorators.

Decorators include the token in their cache key and rebuild on bump."""

from __future__ import annotations

from typing import Any

import bpy

_DECORATOR_CACHE_TOKEN = 0
_INSTALLED_HOOKS: tuple[Any, ...] = ()


def get_decorator_cache_token() -> int:
    return _DECORATOR_CACHE_TOKEN


@bpy.app.handlers.persistent
def _bump_decorator_cache_token(*_args: Any) -> None:
    global _DECORATOR_CACHE_TOKEN
    _DECORATOR_CACHE_TOKEN += 1


def _hooks() -> tuple[Any, ...]:
    # Four hooks cover every path that can free a bpy.types.Object out from
    # under a decorator cache.
    return (
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
        bpy.app.handlers.load_post,
    )


def install_decorator_cache_handlers() -> None:
    """Append the bump handler to each hook; idempotent."""
    global _INSTALLED_HOOKS
    hooks = _hooks()
    for hook in hooks:
        if _bump_decorator_cache_token not in hook:
            hook.append(_bump_decorator_cache_token)
    _INSTALLED_HOOKS = hooks


def uninstall_decorator_cache_handlers() -> None:
    global _INSTALLED_HOOKS
    for hook in _INSTALLED_HOOKS:
        try:
            hook.remove(_bump_decorator_cache_token)
        except ValueError:
            pass
    _INSTALLED_HOOKS = ()
