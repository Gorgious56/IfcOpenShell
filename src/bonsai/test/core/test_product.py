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

import math
from unittest.mock import patch

import bonsai.core.product as subject
from test.core.bootstrap import geometry, ifc, surveyor


class TestCopyZRotationToSelected:
    def test_skips_already_aligned_targets(self, ifc, geometry, surveyor):
        surveyor.get_z_rotation("active").should_be_called().will_return(1.0)
        surveyor.get_z_rotation("aligned_target").should_be_called().will_return(1.0)
        rotated = subject.copy_z_rotation_to_selected(
            ifc, geometry, surveyor, active="active", targets=["aligned_target"]
        )
        assert rotated == 0

    def test_rotates_non_ifc_target_without_ifc_sync(self, ifc, geometry, surveyor):
        surveyor.get_z_rotation("active").should_be_called().will_return(0.0)
        surveyor.get_z_rotation("plain").should_be_called().will_return(1.5)
        surveyor.set_z_rotation("plain", 0.0).should_be_called()
        ifc.get_entity("plain").should_be_called().will_return(None)
        rotated = subject.copy_z_rotation_to_selected(ifc, geometry, surveyor, active="active", targets=["plain"])
        assert rotated == 1

    def test_rotates_ifc_target_and_delegates_to_edit_object_placement(self, ifc, geometry, surveyor):
        # Patches ``edit_object_placement`` rather than predicting its internals — keeps the
        # test focused on this verb's delegation contract, not on the inner verb's call chain.
        # See M2 in the /expertise report for the rationale; convention is acceptable when
        # testing verb-to-verb delegation across core boundaries.
        surveyor.get_z_rotation("active").should_be_called().will_return(0.0)
        surveyor.get_z_rotation("target").should_be_called().will_return(1.5)
        surveyor.set_z_rotation("target", 0.0).should_be_called()
        ifc.get_entity("target").should_be_called().will_return("element")
        with patch("bonsai.core.geometry.edit_object_placement") as mock_eop:
            rotated = subject.copy_z_rotation_to_selected(ifc, geometry, surveyor, active="active", targets=["target"])
        mock_eop.assert_called_once_with(ifc, geometry, surveyor, obj="target")
        assert rotated == 1

    def test_flip_adds_pi_to_source_before_writing(self, ifc, geometry, surveyor):
        surveyor.get_z_rotation("active").should_be_called().will_return(0.0)
        surveyor.get_z_rotation("target").should_be_called().will_return(0.0)
        surveyor.set_z_rotation("target", math.pi).should_be_called()
        ifc.get_entity("target").should_be_called().will_return(None)
        rotated = subject.copy_z_rotation_to_selected(
            ifc, geometry, surveyor, active="active", targets=["target"], flip=True
        )
        assert rotated == 1

    def test_returns_zero_when_targets_empty(self, ifc, geometry, surveyor):
        surveyor.get_z_rotation("active").should_be_called().will_return(0.0)
        rotated = subject.copy_z_rotation_to_selected(ifc, geometry, surveyor, active="active", targets=[])
        assert rotated == 0
