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

"""Array operators must report cleanly, not crash, when invoked on a
non-IFC active object.

The gizmo dispatch path keeps the active object IFC-linked, but F3 search,
the Python console, and scripted callers can land on a plain Blender object.
Reaching ``get_pset`` with a ``None`` element is an AttributeError —
operators must short-circuit with a ``{"CANCELLED"}`` + user-facing report
instead.
"""

from unittest.mock import MagicMock, patch

import bpy
import pytest

pytestmark = pytest.mark.array


def _make_fake_self() -> MagicMock:
    fake = MagicMock(name="fake_self")
    fake.report = MagicMock(name="report")
    return fake


def _make_context_with_active(obj) -> MagicMock:
    ctx = MagicMock(spec=bpy.types.Context, name="context")
    ctx.active_object = obj
    return ctx


def _call_unbound(operator_class, method_name: str, fake_self, *args, **kwargs):
    return getattr(operator_class, method_name)(fake_self, *args, **kwargs)


def test_array_parent_gizmo_click_children_mode_reports_when_object_not_ifc_linked():
    from bonsai.bim.module.model.array import ArrayParentGizmoClick

    obj = MagicMock(spec=bpy.types.Object, name="plain_object")
    ctx = _make_context_with_active(obj)
    fake_self = _make_fake_self()
    fake_self.mode = "CHILDREN"

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=None),
        patch("ifcopenshell.util.element.get_pset") as get_pset,
    ):
        result = _call_unbound(ArrayParentGizmoClick, "execute", fake_self, ctx)

    assert result == {"CANCELLED"}
    fake_self.report.assert_called_once()
    report_args = fake_self.report.call_args.args
    assert report_args[0] == {"ERROR"}
    get_pset.assert_not_called()


def test_edit_array_from_child_reports_when_object_not_ifc_linked():
    from bonsai.bim.module.model.array import EditArrayFromChild

    obj = MagicMock(spec=bpy.types.Object, name="plain_object")
    ctx = _make_context_with_active(obj)
    fake_self = _make_fake_self()

    with (
        patch("bonsai.tool.Ifc.get_entity", return_value=None),
        patch("ifcopenshell.util.element.get_pset") as get_pset,
    ):
        result = _call_unbound(EditArrayFromChild, "execute", fake_self, ctx)

    assert result == {"CANCELLED"}
    fake_self.report.assert_called_once()
    report_args = fake_self.report.call_args.args
    assert report_args[0] == {"ERROR"}
    get_pset.assert_not_called()
