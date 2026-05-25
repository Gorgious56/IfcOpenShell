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

# This file was generated with the assistance of an AI coding tool.

import bpy
import ifcopenshell
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.system
import ifcopenshell.util.system

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.duplicate import DecompositionRecord
from bonsai.tool.duplicate import Duplicate as subject
from test.bim.bootstrap import NewFile


def _add_segment_with_ports(ifc, n_ports=2):
    """Create an IfcDuctSegment with ``n_ports`` ports attached via IfcRelNests."""
    segment = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
    for _ in range(n_ports):
        ifcopenshell.api.system.add_port(ifc, element=segment)
    return segment


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Duplicate)


class TestGetDecompositionRelationships(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        element = ifc.createIfcWall()
        opening = ifc.createIfcOpeningElement()
        fill = ifc.createIfcWindow()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=element)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=fill)

        obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(fill, obj)

        assert subject.get_decomposition_relationships([obj]) == {
            fill: DecompositionRecord(type="fill", element=element)
        }


class TestGetPortConnectionRelationships(NewFile):
    def test_returns_empty_snapshot_for_non_mep_objects(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        wall = ifc.createIfcWall()
        obj = bpy.data.objects.new("Wall", None)
        tool.Ifc.link(wall, obj)
        snapshot = subject.get_port_connection_relationships([obj])
        assert snapshot.by_element == {}
        assert snapshot.port_counts == {}

    def test_captures_pair_between_mep_elements_with_direction(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        seg_a = _add_segment_with_ports(ifc, n_ports=2)
        seg_b = _add_segment_with_ports(ifc, n_ports=2)
        ports_a = ifcopenshell.util.system.get_ports(seg_a)
        ports_b = ifcopenshell.util.system.get_ports(seg_b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[1], port2=ports_b[0], direction="SOURCE")

        obj_a = bpy.data.objects.new("A", None)
        obj_b = bpy.data.objects.new("B", None)
        tool.Ifc.link(seg_a, obj_a)
        tool.Ifc.link(seg_b, obj_b)
        snapshot = subject.get_port_connection_relationships([obj_a, obj_b])

        assert snapshot.port_counts == {seg_a: 2, seg_b: 2}
        # Exactly one record total (symmetric pair deduplicated).
        total_records = sum(len(records) for records in snapshot.by_element.values())
        assert total_records == 1
        # Direction is preserved from the captured FlowDirection.
        record = next(iter(snapshot.by_element.values()))[0]
        assert record.direction == "SOURCE"

    def test_skips_connections_to_elements_outside_input_set(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        seg_a = _add_segment_with_ports(ifc, n_ports=2)
        seg_b = _add_segment_with_ports(ifc, n_ports=2)
        ports_a = ifcopenshell.util.system.get_ports(seg_a)
        ports_b = ifcopenshell.util.system.get_ports(seg_b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[1], port2=ports_b[0])

        # Only seg_a is in the input set — connection to seg_b is dropped.
        obj_a = bpy.data.objects.new("A", None)
        tool.Ifc.link(seg_a, obj_a)
        snapshot = subject.get_port_connection_relationships([obj_a])
        assert snapshot.by_element == {}
        assert snapshot.port_counts == {seg_a: 2}


class TestRecreatePortConnections(NewFile):
    def test_wires_duplicates(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        # Source pair.
        seg_a = _add_segment_with_ports(ifc, n_ports=2)
        seg_b = _add_segment_with_ports(ifc, n_ports=2)
        ports_a = ifcopenshell.util.system.get_ports(seg_a)
        ports_b = ifcopenshell.util.system.get_ports(seg_b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[1], port2=ports_b[0], direction="SOURCE")

        obj_a = bpy.data.objects.new("A", None)
        obj_b = bpy.data.objects.new("B", None)
        tool.Ifc.link(seg_a, obj_a)
        tool.Ifc.link(seg_b, obj_b)
        snapshot = subject.get_port_connection_relationships([obj_a, obj_b])

        # Manually duplicate (no Blender duplicate flow involved).
        new_a = _add_segment_with_ports(ifc, n_ports=2)
        new_b = _add_segment_with_ports(ifc, n_ports=2)
        old_to_new = {seg_a: [new_a], seg_b: [new_b]}

        # Pre-condition: new ports have no IfcRelConnectsPorts.
        new_ports_a = ifcopenshell.util.system.get_ports(new_a)
        new_ports_b = ifcopenshell.util.system.get_ports(new_b)
        assert ifcopenshell.util.system.get_connected_port(new_ports_a[1]) is None

        subject.recreate_port_connections(snapshot, old_to_new)

        # Post-condition: duplicates wired to each other on the same positional
        # ports, with direction restored.
        assert ifcopenshell.util.system.get_connected_port(new_ports_a[1]) == new_ports_b[0]
        assert new_ports_a[1].FlowDirection == "SOURCE"
        assert new_ports_b[0].FlowDirection == "SINK"

    def test_skips_when_port_count_diverges_from_snapshot(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        seg_a = _add_segment_with_ports(ifc, n_ports=2)
        seg_b = _add_segment_with_ports(ifc, n_ports=2)
        ports_a = ifcopenshell.util.system.get_ports(seg_a)
        ports_b = ifcopenshell.util.system.get_ports(seg_b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[1], port2=ports_b[0])

        obj_a = bpy.data.objects.new("A", None)
        obj_b = bpy.data.objects.new("B", None)
        tool.Ifc.link(seg_a, obj_a)
        tool.Ifc.link(seg_b, obj_b)
        snapshot = subject.get_port_connection_relationships([obj_a, obj_b])

        # Duplicate seg_a with 3 ports instead of 2 — port_counts guard
        # should trip and skip the reconnect.
        new_a = _add_segment_with_ports(ifc, n_ports=3)
        new_b = _add_segment_with_ports(ifc, n_ports=2)
        old_to_new = {seg_a: [new_a], seg_b: [new_b]}

        subject.recreate_port_connections(snapshot, old_to_new)

        new_ports_a = ifcopenshell.util.system.get_ports(new_a)
        # All new ports remain unconnected because the snapshot's positional
        # mapping was deemed unsafe.
        for port in new_ports_a:
            assert ifcopenshell.util.system.get_connected_port(port) is None


class TestRecreateConnectionsRestoresPriorities(NewFile):
    def test_priorities_carry_over_to_duplicate_rel(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        wall_a = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        wall_b = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        rel = ifcopenshell.api.geometry.connect_path(
            ifc,
            relating_element=wall_a,
            related_element=wall_b,
            relating_connection="ATEND",
            related_connection="ATSTART",
        )
        rel.RelatingPriorities = [1, 2, 3]
        rel.RelatedPriorities = [4, 5]

        obj_a = bpy.data.objects.new("A", None)
        tool.Ifc.link(wall_a, obj_a)
        snapshot = subject.get_connection_relationships([obj_a])

        new_a = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        new_b = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        subject.recreate_connections(snapshot, {wall_a: [new_a], wall_b: [new_b]})

        # The new wall must have a path connection with the same priorities.
        new_rels = [r for r in new_a.ConnectedTo if r.is_a("IfcRelConnectsPathElements")]
        assert len(new_rels) == 1
        assert tuple(new_rels[0].RelatingPriorities) == (1, 2, 3)
        assert tuple(new_rels[0].RelatedPriorities) == (4, 5)
