# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

import math

import bpy
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.util.geolocation
import numpy as np
import pytest
from mathutils import Matrix

import bonsai.core.tool
import bonsai.tool as tool
import test.bim.bootstrap
from bonsai.tool import Surveyor as subject


class TestImplementsTool(test.bim.bootstrap.NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Surveyor)


class TestGetGlobalMatrix(test.bim.bootstrap.NewFile):
    def test_getting_an_absolute_matrix_if_no_blender_offset(self):
        props = tool.Georeference.get_georeference_props()
        props.has_blender_offset = False
        obj = bpy.data.objects.new("Object", None)
        assert (subject.get_absolute_matrix(obj) == np.array(obj.matrix_world)).all()

    def test_applying_an_object_placement_blender_offset(self):
        ifc = ifcopenshell.file()
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        unit = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT", prefix="MILLI")
        ifcopenshell.api.unit.assign_unit(ifc, units=[unit])
        tool.Ifc.set(ifc)
        props = tool.Georeference.get_georeference_props()
        props.has_blender_offset = True
        props.blender_offset_x = "1000"
        props.blender_offset_y = "2000"
        props.blender_offset_z = "3000"
        props.blender_x_axis_abscissa = "0"
        props.blender_x_axis_ordinate = "1"
        obj = bpy.data.objects.new("Object", None)
        props = tool.Blender.get_object_bim_props(obj)
        props.blender_offset_type = "OBJECT_PLACEMENT"
        matrix = ifcopenshell.util.geolocation.local2global(np.array(obj.matrix_world), 1.0, 2.0, 3.0, 0.0, 1.0)
        assert (subject.get_absolute_matrix(obj) == matrix).all()


class TestZRotationRoundTrip(test.bim.bootstrap.NewFile):
    def test_get_returns_zero_for_identity_matrix(self):
        obj = bpy.data.objects.new("Object", None)
        assert subject.get_z_rotation(obj) == pytest.approx(0.0)

    # Round-trip precision is bounded by Blender's internal float32 matrix storage
    # (bpy.types.Object.matrix_world drops to single precision on write/read), not by
    # mathutils's double-precision math. Drift observed at ~6e-8; 1e-6 is the safe assert.
    MATRIX_ROUNDTRIP_TOLERANCE = 1e-6

    @pytest.mark.parametrize("z", [0.0, 0.5, 1.0, -0.5, math.pi / 4, math.pi / 2])
    def test_set_then_get_round_trips_the_z_value(self, z):
        obj = bpy.data.objects.new("Object", None)
        subject.set_z_rotation(obj, z)
        assert subject.get_z_rotation(obj) == pytest.approx(z, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)

    def test_set_preserves_translation(self):
        obj = bpy.data.objects.new("Object", None)
        obj.matrix_world = Matrix.Translation((1.0, 2.0, 3.0))
        subject.set_z_rotation(obj, 0.7)
        loc, _rot, _scale = obj.matrix_world.decompose()
        assert loc.x == pytest.approx(1.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)
        assert loc.y == pytest.approx(2.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)
        assert loc.z == pytest.approx(3.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)

    def test_set_preserves_scale(self):
        obj = bpy.data.objects.new("Object", None)
        obj.matrix_world = Matrix.Diagonal((2.0, 3.0, 4.0, 1.0))
        subject.set_z_rotation(obj, 0.7)
        _loc, _rot, scale = obj.matrix_world.decompose()
        assert scale.x == pytest.approx(2.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)
        assert scale.y == pytest.approx(3.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)
        assert scale.z == pytest.approx(4.0, abs=self.MATRIX_ROUNDTRIP_TOLERANCE)

    def test_pi_wraparound_round_trips_modulo_two_pi(self):
        # Blender's Euler decomposition may return -π for an input of +π or vice versa;
        # the contract is that the difference is 0 modulo 2π.
        obj = bpy.data.objects.new("Object", None)
        subject.set_z_rotation(obj, math.pi)
        result = subject.get_z_rotation(obj)
        diff = (result - math.pi + math.pi) % (2 * math.pi) - math.pi
        assert abs(diff) < 1e-6
