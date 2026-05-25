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

"""Regression tests for the ``ProfileDecorator`` draw handler's precondition guard.

The decorator is installed via ``SpaceView3D.draw_handler_add`` and fires on every
viewport redraw. Its first action reads ``context.active_object.mode``; when the
active object is ``None`` (no selection, scene swap, undo past install, deletion of
the editing target, …) this raised ``AttributeError`` once per region per redraw and
spammed the Blender console. The contract pinned here: ``obj is None`` is treated
the same as "not in EDIT mode" — the decorator uninstalls itself and fires the
exit callback.
"""

import bpy
import pytest

from bonsai.bim.module.model.decorator import ProfileDecorator

pytestmark = pytest.mark.model


class TestProfileDecoratorActiveObjectGuard:
    def test_no_active_object_triggers_exit_callback_instead_of_crashing(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        assert bpy.context.active_object is None

        try:
            callback_calls: list[bool] = []
            handler = ProfileDecorator()

            handler(bpy.context, exit_edit_mode_callback=lambda: callback_calls.append(True))

            assert callback_calls == [True]
        finally:
            ProfileDecorator.uninstall()