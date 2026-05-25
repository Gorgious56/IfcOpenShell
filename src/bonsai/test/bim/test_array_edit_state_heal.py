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

"""``BIMArrayProperties`` edit-state invariant on load.

``is_editing=True`` must be paired with a selected layer
(``editing_item_index >= 0``). The opposite pair is only producible by
Blender coercing a legacy integer value during PropertyGroup load, and the
load_post helper must reset it so no phantom gizmo group polls in."""

from types import SimpleNamespace

import pytest

from bonsai.bim.handler import heal_inconsistent_array_edit_state

pytestmark = pytest.mark.array


def _fake_obj(is_editing: bool, editing_item_index: int) -> SimpleNamespace:
    return SimpleNamespace(
        BIMArrayProperties=SimpleNamespace(
            is_editing=is_editing,
            editing_item_index=editing_item_index,
        )
    )


def test_inconsistent_pair_is_reset():
    obj = _fake_obj(is_editing=True, editing_item_index=-1)
    heal_inconsistent_array_edit_state([obj])
    assert obj.BIMArrayProperties.is_editing is False


def test_consistent_editing_pair_is_preserved():
    obj = _fake_obj(is_editing=True, editing_item_index=0)
    heal_inconsistent_array_edit_state([obj])
    assert obj.BIMArrayProperties.is_editing is True
    assert obj.BIMArrayProperties.editing_item_index == 0


def test_non_editing_object_is_untouched():
    obj = _fake_obj(is_editing=False, editing_item_index=-1)
    heal_inconsistent_array_edit_state([obj])
    assert obj.BIMArrayProperties.is_editing is False
    assert obj.BIMArrayProperties.editing_item_index == -1


def test_only_inconsistent_objects_are_reset_in_mixed_batch():
    inconsistent = _fake_obj(is_editing=True, editing_item_index=-1)
    consistent = _fake_obj(is_editing=True, editing_item_index=2)
    inactive = _fake_obj(is_editing=False, editing_item_index=-1)

    heal_inconsistent_array_edit_state([inconsistent, consistent, inactive])

    assert inconsistent.BIMArrayProperties.is_editing is False
    assert consistent.BIMArrayProperties.is_editing is True
    assert consistent.BIMArrayProperties.editing_item_index == 2
    assert inactive.BIMArrayProperties.is_editing is False
