# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Bonsai contributors
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

# This file was generated with the assistance of an AI coding tool.

import sys
from unittest.mock import MagicMock

# tool/aggregate.py imports bpy at module load; stub it so the pure
# get_highlight_ancestor helper can be unit-tested without Blender.
sys.modules.setdefault("bpy", MagicMock())
sys.modules.setdefault("bpy.types", MagicMock())

from bonsai.tool.aggregate import Aggregate


class TestGetHighlightAncestor:
    def test_returns_none_when_no_ancestor_aggregates(self):
        """Regression: the aggregate decorator raised IndexError every frame
        when a selected IfcElement had no parent aggregate.
        """
        assert Aggregate.get_highlight_ancestor([], editing_aggregate=None) is None

    def test_returns_deepest_when_outside_aggregate_mode(self):
        chain = ["leaf_parent", "mid", "root"]
        assert Aggregate.get_highlight_ancestor(chain, editing_aggregate=None) == "root"

    def test_returns_predecessor_when_in_aggregate_mode(self):
        chain = ["leaf_parent", "mid", "root"]
        assert Aggregate.get_highlight_ancestor(chain, editing_aggregate="mid") == "leaf_parent"

    def test_returns_none_when_editing_aggregate_is_deepest(self):
        chain = ["leaf_parent", "mid", "root"]
        assert Aggregate.get_highlight_ancestor(chain, editing_aggregate="leaf_parent") is None

    def test_returns_none_when_editing_aggregate_not_in_chain(self):
        """Defensive: previously raised ValueError from list.index when the
        editing aggregate was from an unrelated selection.
        """
        chain = ["leaf_parent", "mid", "root"]
        assert Aggregate.get_highlight_ancestor(chain, editing_aggregate="unrelated") is None

    def test_returns_none_when_chain_empty_and_in_aggregate_mode(self):
        assert Aggregate.get_highlight_ancestor([], editing_aggregate="anything") is None
