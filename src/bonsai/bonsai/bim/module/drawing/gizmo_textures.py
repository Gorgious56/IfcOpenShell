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

"""GPU texture cache + IMAGE_COLOR shader for icon-class gizmos backed by
``bim/data/icons/<icon_name>.png``.

Textures are pre-loaded eagerly from addon ``register()`` via
``preload_for_registered_gizmos``. ``get_icon_texture`` is a pure cache
lookup — it never touches ``bpy.data`` — so it's safe to call from gizmo
``draw()`` callbacks. Cache must be cleared on addon ``unregister()`` and
on ``load_post`` because ``bpy.types.Image`` references go stale across
blend-file reloads.

Loaded ``bpy.types.Image`` data-blocks are namespaced under the
``BONSAI_GIZMO_`` name prefix so cleanup can identify addon-owned entries
without colliding with images a user may have loaded by the same filepath.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import bpy
import gpu

_ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "icons"
_IMAGE_NAME_PREFIX = "BONSAI_GIZMO_"

_texture_cache: dict[str, gpu.types.GPUTexture] = {}
_loaded_images: set[bpy.types.Image] = set()
_shader: Optional[gpu.types.GPUShader] = None


def get_shader() -> gpu.types.GPUShader:
    """Returns the built-in IMAGE_COLOR shader (lazy)."""
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("IMAGE_COLOR")
    return _shader


def get_icon_texture(icon_name: str) -> Optional[gpu.types.GPUTexture]:
    """Cache lookup for the texture of ``bim/data/icons/<icon_name>.png``.

    Pure — no I/O, no ``bpy.data`` mutation. Safe from gizmo ``draw()``.
    Returns ``None`` for an empty name or any icon that wasn't pre-loaded
    via ``preload_for_registered_gizmos``; callers must treat ``None`` as
    a signal to fall back to vector geometry."""
    if not icon_name:
        return None
    return _texture_cache.get(icon_name)


def preload_for_registered_gizmos() -> None:
    """Eagerly load every PNG referenced by a registered ``TexturedQuadGizmoMixin``
    subclass. Must be called from addon ``register()`` (or any non-draw
    context); never from a gizmo ``draw`` callback."""
    from bonsai.bim.module.drawing.gizmos import TexturedQuadGizmoMixin

    seen: set[type] = set()
    pending: list[type] = [TexturedQuadGizmoMixin]
    while pending:
        cls = pending.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            pending.append(sub)
            icon_name = getattr(sub, "icon_name", "")
            if icon_name:
                _load_icon_texture(icon_name)


def _load_icon_texture(icon_name: str) -> Optional[gpu.types.GPUTexture]:
    """Internal — performs the actual ``bpy.data.images.load`` + GPU upload.
    Must run in a non-draw context."""
    cached = _texture_cache.get(icon_name)
    if cached is not None:
        return cached
    filepath = _ICONS_DIR / f"{icon_name}.png"
    if not filepath.is_file():
        return None
    try:
        # check_existing=False so we never collide with a user-loaded image
        # at the same filepath. We rename to the BONSAI_GIZMO_ prefix so the
        # cleanup pass can identify addon-owned data-blocks unambiguously.
        image = bpy.data.images.load(str(filepath), check_existing=False)
        image.name = f"{_IMAGE_NAME_PREFIX}{icon_name}"
        texture = gpu.texture.from_image(image)
    except Exception:
        return None
    _loaded_images.add(image)
    _texture_cache[icon_name] = texture
    return texture


def clear_cache() -> None:
    """Drops the texture cache and removes the Image data-blocks this module
    loaded. Safe to call from ``load_post`` even when the tracked Image
    references are already stale — the cleanup is best-effort."""
    _texture_cache.clear()
    for image in list(_loaded_images):
        try:
            bpy.data.images.remove(image, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    _loaded_images.clear()
