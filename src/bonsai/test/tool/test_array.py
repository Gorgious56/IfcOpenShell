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

"""Unit tests for ``tool.Array`` helpers.

Pinned contracts:

* ``get_parametric_propagation_targets`` filters out type-occurrences that
  no longer share a Bonsai array root with the modified element. This is
  what insulates an "independent former child" (post-``RemoveArray`` with
  Keep Objects) from parametric edits made to its former siblings.
* The non-arrayed pathway is preserved: when neither the modified element
  nor its peers carry a ``BBIM_Array`` pset, type-occurrence sharing still
  applies so bulk-edit-by-type continues to work for standalone parametric
  elements.
"""

from unittest.mock import MagicMock, patch

import pytest

from bonsai.tool.array import Array as subject

pytestmark = pytest.mark.array


def _mock_element(guid: str, pset: dict | None = None) -> MagicMock:
    """An ``ifcopenshell.entity_instance`` stand-in with a stable GlobalId."""
    e = MagicMock(name=f"element_{guid}")
    e.GlobalId = guid
    e._pset = pset
    return e


def _pset_lookup_fn(*elements: MagicMock):
    """Return a ``get_pset(element, name)`` substitute that reads ``_pset``
    from the recorded mocks. Unknown elements raise — the test fixture
    must register every entity it expects to be queried."""
    by_guid = {e.GlobalId: e for e in elements}

    def get_pset(element, name):
        if name != "BBIM_Array":
            return None
        return by_guid[element.GlobalId]._pset

    return get_pset


def _by_guid_fn(*elements: MagicMock):
    """``ifc_file.by_guid`` stand-in: GUID → mock element, raises RuntimeError
    when missing (matches the real API's contract)."""
    by_guid = {e.GlobalId: e for e in elements}

    def by_guid_(g):
        if g not in by_guid:
            raise RuntimeError(f"Unknown GUID {g}")
        return by_guid[g]

    return by_guid_


def test_root_guid_for_unparented_element_is_element_itself():
    e = _mock_element("E", pset=None)
    with patch("ifcopenshell.util.element.get_pset", _pset_lookup_fn(e)):
        assert subject.get_array_root_guid(e) == "E"


def test_root_guid_walks_parent_chain_to_top():
    root = _mock_element("ROOT", pset=None)
    mid = _mock_element("MID", pset={"Parent": "ROOT"})
    leaf = _mock_element("LEAF", pset={"Parent": "MID"})
    ifc_file = MagicMock()
    ifc_file.by_guid = _by_guid_fn(root, mid, leaf)
    with (
        patch("ifcopenshell.util.element.get_pset", _pset_lookup_fn(root, mid, leaf)),
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
    ):
        assert subject.get_array_root_guid(leaf) == "ROOT"


def test_root_guid_short_circuits_self_referential_parent():
    """A child whose ``BBIM_Array.Parent`` points to its own GUID terminates
    immediately. The check prevents infinite loops in corrupt-data files
    without requiring the helper to raise."""
    e = _mock_element("X", pset={"Parent": "X"})
    with patch("ifcopenshell.util.element.get_pset", _pset_lookup_fn(e)):
        assert subject.get_array_root_guid(e) == "X"


def test_root_guid_handles_unresolvable_parent_guid_gracefully():
    """When ``by_guid`` raises (the parent GUID is no longer in the file),
    the helper returns the deepest element it actually walked to instead
    of propagating the RuntimeError. Matches the existing
    ``get_parent_element`` resilience contract."""
    child = _mock_element("C", pset={"Parent": "MISSING"})
    ifc_file = MagicMock()
    ifc_file.by_guid = _by_guid_fn()  # empty
    with (
        patch("ifcopenshell.util.element.get_pset", _pset_lookup_fn(child)),
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
    ):
        assert subject.get_array_root_guid(child) == "C"


def test_propagation_targets_for_non_array_element_excludes_array_peers():
    """When the modified element has no ``BBIM_Array``, occurrences that
    *do* carry one are dropped — they belong to a different (active) array
    and must not be edited by a non-array peer's modification."""
    standalone = _mock_element("S", pset=None)
    other_standalone = _mock_element("OS", pset=None)
    arrayed_peer = _mock_element("AP", pset={"Parent": "ROOT"})
    with (
        patch(
            "bonsai.tool.Ifc.get_all_element_occurrences",
            return_value=[standalone, other_standalone, arrayed_peer],
        ),
        patch("ifcopenshell.util.element.get_pset", _pset_lookup_fn(standalone, other_standalone, arrayed_peer)),
    ):
        result = subject.get_parametric_propagation_targets(standalone)

    assert standalone in result and other_standalone in result
    assert arrayed_peer not in result


def test_propagation_targets_for_array_member_includes_only_same_family():
    """The modified element is a child of array root ``ROOT``. Same-family
    siblings and the parent itself are included; an independent former
    child (no ``BBIM_Array`` pset) is excluded; a peer from a different
    array family (``OTHER`` root) is excluded."""
    parent = _mock_element("ROOT", pset={"Parent": "ROOT"})
    sibling = _mock_element("SIB", pset={"Parent": "ROOT"})
    modified = _mock_element("MOD", pset={"Parent": "ROOT"})
    independent = _mock_element("IND", pset=None)
    foreign_parent = _mock_element("OTHER", pset={"Parent": "OTHER"})
    foreign_child = _mock_element("OC", pset={"Parent": "OTHER"})
    ifc_file = MagicMock()
    ifc_file.by_guid = _by_guid_fn(parent, sibling, modified, independent, foreign_parent, foreign_child)
    with (
        patch(
            "bonsai.tool.Ifc.get_all_element_occurrences",
            return_value=[parent, sibling, modified, independent, foreign_child],
        ),
        patch(
            "ifcopenshell.util.element.get_pset",
            _pset_lookup_fn(parent, sibling, modified, independent, foreign_parent, foreign_child),
        ),
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
    ):
        result = subject.get_parametric_propagation_targets(modified)

    assert parent in result
    assert sibling in result
    assert modified in result
    assert independent not in result
    assert foreign_child not in result
