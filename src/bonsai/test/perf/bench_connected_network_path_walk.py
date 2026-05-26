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

"""Wall-clock benchmark for the BFS walk that ``_ConnectedNetworkPathDecorator``
runs on cache miss.

Not collected by pytest (lives under ``test/perf/``, not ``test/bim/``);
invoke directly when proposing perf work on the network-path overlay or
when validating that a refactor of ``tool.Wall.walk_connected_walls`` has
not regressed scaling::

    blender -b -P src/bonsai/test/perf/bench_connected_network_path_walk.py

For each N in (10, 100, 1000, 5000) the script builds a fresh IFC file
with N walls connected in a chain via ``IfcRelConnectsPathElements``, then
times ``tool.Wall.walk_connected_walls(walls[0])`` over R repeats. The
5000-row matches the in-code BFS cap, so the largest run also stresses
the cap-stopping path.

The walk is the dominant cost on cache miss inside the decorator's draw
path: every selection change in a connected wall network triggers it,
blocking the redraw until it returns. Subsequent draws (same selection)
hit the cache and are O(1) — not measured here."""

import statistics
import time

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.guid

import bonsai.tool as tool


def _make_chain_of_n_walls(n: int) -> list[ifcopenshell.entity_instance]:
    """N IfcWall entities connected in a chain via IfcRelConnectsPathElements.
    No representations — the walk only reads inverse refs."""
    ifc_file = ifcopenshell.file()
    walls = [ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"W{i}") for i in range(n)]
    for a, b in zip(walls, walls[1:]):
        ifcopenshell.api.geometry.connect_path(
            ifc_file,
            relating_element=a,
            related_element=b,
            relating_connection="ATEND",
            related_connection="ATSTART",
        )
    return walls


def _time_walk(seed: ifcopenshell.entity_instance, repeats: int) -> tuple[list[float], int]:
    samples = []
    walked = 0
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = tool.Wall.walk_connected_walls(seed)
        samples.append(time.perf_counter() - t0)
        walked = len(result)
    return samples, walked


def main():
    repeats = 5
    print("\n" + "=" * 78)
    print(f"tool.Wall.walk_connected_walls benchmark — {repeats} repeats per N, ms")
    print("=" * 78)
    print(f"{'N':>5}  {'walked':>7}  {'median':>9}  {'min':>9}  {'max':>9}  {'samples (ms)':<30}")
    print("-" * 78)
    for n in [10, 100, 1000, 5000]:
        walls = _make_chain_of_n_walls(n)
        samples, walked = _time_walk(walls[0], repeats=repeats)
        samples_ms = [s * 1000 for s in samples]
        median_ms = statistics.median(samples_ms)
        print(
            f"{n:>5}  {walked:>7}  {median_ms:>8.2f}ms  {min(samples_ms):>8.2f}ms  {max(samples_ms):>8.2f}ms"
            f"  [{', '.join(f'{s:.2f}' for s in samples_ms)}]"
        )
    print("=" * 78 + "\n")


main()
