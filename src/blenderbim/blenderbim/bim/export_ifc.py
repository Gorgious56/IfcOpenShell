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

import os
import bpy
import json
import numpy as np
import datetime
import zipfile
import tempfile
import addon_utils
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.placement
import blenderbim.tool as tool
import blenderbim.core.aggregate
import blenderbim.core.spatial
import blenderbim.core.style
from blenderbim.bim.ifc import IfcStore


class IfcExporter:
    def __init__(self, ifc_export_settings):
        self.ifc_export_settings = ifc_export_settings

    def export(self):
        self.file = IfcStore.get_file()
        self.set_header()
        if bpy.context.scene.BIMProjectProperties.is_authoring:
            self.sync_object_placements_and_deletions()
            self.sync_edited_objects()
        extension = self.ifc_export_settings.output_file.split(".")[-1]
        if extension == "ifczip":
            with tempfile.TemporaryDirectory() as unzipped_path:
                filename, ext = os.path.splitext(os.path.basename(self.ifc_export_settings.output_file))
                tmp_name = "{}.ifc".format(filename)
                tmp_file = os.path.join(unzipped_path, tmp_name)
                self.file.write(tmp_file)
                with zipfile.ZipFile(
                    self.ifc_export_settings.output_file, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
                ) as zf:
                    zf.write(tmp_file)
        elif extension == "ifc":
            self.file.write(self.ifc_export_settings.output_file)
        elif extension == "ifcjson":
            import ifcjson

            if self.ifc_export_settings.json_version == "4":
                jsonData = ifcjson.IFC2JSON4(self.file, self.ifc_export_settings.json_compact).spf2Json()
                with open(self.ifc_export_settings.output_file, "w") as outfile:
                    json.dump(jsonData, outfile, indent=None if self.ifc_export_settings.json_compact else 4)
            elif self.ifc_export_settings.json_version == "5a":
                jsonData = ifcjson.IFC2JSON5a(self.file, self.ifc_export_settings.json_compact).spf2Json()
                with open(self.ifc_export_settings.output_file, "w") as outfile:
                    json.dump(jsonData, outfile, indent=None if self.ifc_export_settings.json_compact else 4)

    def set_header(self):
        self.file.wrapped_data.header.file_name.name = os.path.basename(self.ifc_export_settings.output_file)
        self.file.wrapped_data.header.file_name.time_stamp = (
            datetime.datetime.utcnow()
            .replace(tzinfo=datetime.timezone.utc)
            .astimezone()
            .replace(microsecond=0)
            .isoformat()
        )
        self.file.wrapped_data.header.file_name.preprocessor_version = "IfcOpenShell {}".format(ifcopenshell.version)
        self.file.wrapped_data.header.file_name.originating_system = "{} {}".format(
            self.get_application_name(), self.get_application_version()
        )

    def sync_object_placements_and_deletions(self):
        self.unit_scale = ifcopenshell.util.unit.calculate_unit_scale(self.file)
        to_delete = []

        for ifc_definition_id, obj in IfcStore.id_map.items():
            try:
                if isinstance(obj, bpy.types.Material):
                    continue
                self.sync_object_placement(obj)
                self.sync_object_container(ifc_definition_id, obj)
            except ReferenceError:
                pass  # The object is likely deleted
            if self.should_delete(obj):
                to_delete.append(ifc_definition_id)

        for ifc_definition_id in to_delete:
            product = self.file.by_id(ifc_definition_id)
            IfcStore.unlink_element(product)
            ifcopenshell.api.run("root.remove_product", self.file, **{"product": product})

    def sync_edited_objects(self):
        for obj in IfcStore.edited_objs.copy():
            if not obj:
                continue
            try:
                if isinstance(obj, bpy.types.Material):
                    blenderbim.core.style.update_style_colours(tool.Ifc, tool.Style, obj=obj)
                else:
                    bpy.ops.bim.update_representation(obj=obj.name)
            except ReferenceError:
                pass  # The object is likely deleted
        IfcStore.edited_objs.clear()

    def sync_object_placement(self, obj):
        blender_matrix = np.array(obj.matrix_world)
        element = self.file.by_id(obj.BIMObjectProperties.ifc_definition_id)
        if not hasattr(element, "ObjectPlacement"):
            return
        ifc_matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
        ifc_matrix[0][3] *= self.unit_scale
        ifc_matrix[1][3] *= self.unit_scale
        ifc_matrix[2][3] *= self.unit_scale

        props = bpy.context.scene.BIMGeoreferenceProperties
        if props.has_blender_offset and obj.BIMObjectProperties.blender_offset_type == "OBJECT_PLACEMENT":
            ifc_matrix = ifcopenshell.util.geolocation.global2local(
                ifc_matrix,
                float(props.blender_eastings) * self.unit_scale,
                float(props.blender_northings) * self.unit_scale,
                float(props.blender_orthogonal_height) * self.unit_scale,
                float(props.blender_x_axis_abscissa),
                float(props.blender_x_axis_ordinate),
            )
        if not np.allclose(ifc_matrix, blender_matrix, atol=0.0001):
            blenderbim.core.geometry.edit_object_placement(tool.Ifc, tool.Surveyor, obj=obj)

    def sync_object_container(self, guid, obj):
        element = self.file.by_id(obj.BIMObjectProperties.ifc_definition_id)
        element_collection = bpy.data.collections.get(obj.name)

        if self.file.schema == "IFC2X3":
            if element.is_a("IfcProject"):
                return
        elif element.is_a("IfcContext"):
            return

        if (
            (element.is_a("IfcElement") and element_collection)
            or element.is_a("IfcSpatialStructureElement")
            or element.is_a("IfcGrid")
        ):
            try:
                parent_collection = [c for c in bpy.data.collections if c.children.get(element_collection.name)][0]
            except:
                return  # Out of the spatial tree
        else:
            parent_collection = obj.users_collection[0]

        parent_obj = bpy.data.objects.get(parent_collection.name)
        if not parent_obj or not parent_obj.BIMObjectProperties.ifc_definition_id:
            return
        parent = self.file.by_id(parent_obj.BIMObjectProperties.ifc_definition_id)

        if parent.is_a("IfcSpatialStructureElement") and not element.is_a("IfcSpatialStructureElement"):
            if parent != ifcopenshell.util.element.get_container(element):
                blenderbim.core.spatial.assign_container(
                    tool.Ifc, tool.Collector, tool.Container, structure_obj=parent_obj, element_obj=obj
                )
        elif parent != ifcopenshell.util.element.get_aggregate(element):
            blenderbim.core.aggregate.assign_object(
                tool.Ifc, tool.Aggregate, tool.Collector, relating_obj=parent_obj, related_obj=obj
            )

    def should_delete(self, obj):
        try:
            # This will throw an exception if the Blender object no longer exists
            foo = obj.name
            foo
            return False
        except:
            return True

    def get_application_name(self):
        return "BlenderBIM"

    def get_application_version(self):
        return ".".join(
            [
                str(x)
                for x in [
                    addon.bl_info.get("version", (-1, -1, -1))
                    for addon in addon_utils.modules()
                    if addon.bl_info["name"] == "BlenderBIM"
                ][0]
            ]
        )


class IfcExportSettings:
    def __init__(self):
        self.logger = None
        self.output_file = None

    @staticmethod
    def factory(context, output_file, logger):
        settings = IfcExportSettings()
        settings.output_file = output_file
        settings.logger = logger
        return settings
