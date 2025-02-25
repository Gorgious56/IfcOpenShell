# BlenderBIM Add-on - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of BlenderBIM Add-on.
#
# BlenderBIM Add-on is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BlenderBIM Add-on is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BlenderBIM Add-on.  If not, see <http://www.gnu.org/licenses/>.

import bpy
import ifcopenshell
import ifcopenshell.api
from blenderbim.bim.ifc import IfcStore
from blenderbim.bim.module.qto import helper
from ifcopenshell.api.pset.data import Data as PsetData


class CalculateEdgeLengths(bpy.types.Operator):
    bl_idname = "bim.calculate_edge_lengths"
    bl_label = "Calculate Edge Lengths"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.active_object

    def execute(self, context):
        result = helper.calculate_edges_lengths([o for o in context.selected_objects if o.type == "MESH"], context)
        context.scene.BIMQtoProperties.qto_result = str(round(result, 3))
        return {"FINISHED"}


class CalculateFaceAreas(bpy.types.Operator):
    bl_idname = "bim.calculate_face_areas"
    bl_label = "Calculate Face Areas"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.active_object

    def execute(self, context):
        result = helper.calculate_faces_areas([o for o in context.selected_objects if o.type == "MESH"], context)
        context.scene.BIMQtoProperties.qto_result = str(round(result, 3))
        return {"FINISHED"}


class CalculateObjectVolumes(bpy.types.Operator):
    bl_idname = "bim.calculate_object_volumes"
    bl_label = "Calculate Object Volumes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.active_object

    def execute(self, context):
        result = helper.calculate_volumes([o for o in context.selected_objects if o.type == "MESH"], context)
        context.scene.BIMQtoProperties.qto_result = str(round(result, 3))
        return {"FINISHED"}


class ExecuteQtoMethod(bpy.types.Operator):
    bl_idname = "bim.execute_qto_method"
    bl_label = "Execute Qto Method"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        selected_mesh_objects = [o for o in context.selected_objects if o.type == "MESH"]
        props = context.scene.BIMQtoProperties
        result = 0
        if props.qto_methods == "HEIGHT":
            for obj in selected_mesh_objects:
                result += helper.calculate_height(obj)
        elif props.qto_methods == "VOLUME":
            result = helper.calculate_volumes(selected_mesh_objects, context)
        elif props.qto_methods == "FORMWORK":
            result = helper.calculate_formwork_area(selected_mesh_objects, context)
        props.qto_result = str(round(result, 3))
        return {"FINISHED"}


class QuantifyObjects(bpy.types.Operator):
    bl_idname = "bim.quantify_objects"
    bl_label = "Quantify Objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return IfcStore.get_file() and context.selected_objects

    def execute(self, context):
        return IfcStore.execute_ifc_operator(self, context)

    def _execute(self, context):
        props = context.scene.BIMQtoProperties
        self.file = IfcStore.get_file()
        for obj in (o for o in context.selected_objects if o.type == "MESH"):
            if not obj.BIMObjectProperties.ifc_definition_id:
                continue
            result = 0
            if props.qto_methods == "HEIGHT":
                result = helper.calculate_height(obj)
            elif props.qto_methods == "VOLUME":
                result = helper.calculate_volumes([obj], context)
            elif props.qto_methods == "FORMWORK":
                result = helper.calculate_formwork_area([obj], context)
            if not result:
                continue
            result = round(result, 3)
            qto = ifcopenshell.api.run(
                "pset.add_qto",
                self.file,
                product=self.file.by_id(obj.BIMObjectProperties.ifc_definition_id),
                name=props.qto_name,
            )
            ifcopenshell.api.run("pset.edit_qto", self.file, qto=qto, properties={props.prop_name: result})
            PsetData.load(self.file, obj.BIMObjectProperties.ifc_definition_id)
        return {"FINISHED"}
