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

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import bpy
import ifcopenshell
import pytest

import bonsai
import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.blender import Blender as subject
from test.bim.bootstrap import NewFile

if TYPE_CHECKING:
    import bpy.stub_internal.rna_enums as rna_enums


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Blender)


class TestCopyNodeGraph(NewFile):
    def test_run(self):
        material_to = bpy.data.materials.new("material_to")
        tool.Style.set_use_nodes(material_to, True)
        assert material_to.node_tree
        material_to_nodes = material_to.node_tree.nodes
        assert len(material_to_nodes) == 2
        for node in material_to_nodes:
            material_to_nodes.remove(node)
        assert len(material_to_nodes) == 0

        material_from = bpy.data.materials.new("material_from")
        tool.Style.set_use_nodes(material_from, True)

        subject.copy_node_graph(material_to, material_from)
        assert len(material_to_nodes) == 2


class TestSortPanelsForRegister(NewFile):
    def test_run(self):
        items = ["A", "B", "C", "D"]
        items_to_parents = {"A": "D", "D": "C", "C": "B"}
        sorted_items = subject.sort_panels_for_register(items, items_to_parents)
        assert tuple(sorted_items) == ("B", "C", "D", "A")

        with pytest.raises(AssertionError):
            subject.sort_panels_for_register(items, {"A": "K"})

        with pytest.raises(AssertionError):
            subject.sort_panels_for_register(items, {"J": "A"})


class TestBlenderErrorMessageExtraction(NewFile):
    def test_extract_operator_reports(self) -> None:

        ERROR_REPORTS = ["ERROR!!!\nERROR", "ERROR"]

        class OBJECT_OT_test_fail_operator(bpy.types.Operator):
            bl_idname = "object.test_fail_operator"
            bl_label = "Test Fail Operator"

            def execute(self, context) -> "set[rna_enums.OperatorReturnItems]":
                self.report({"INFO"}, "Info message.")
                subject.report_operator_errors(self, ERROR_REPORTS)
                return {"FINISHED"}

        bpy.utils.register_class(OBJECT_OT_test_fail_operator)

        try:
            bpy.ops.object.test_fail_operator()
        except RuntimeError as e:
            error_reports = subject.extract_error_reports(e)
            assert error_reports == ERROR_REPORTS

        bpy.utils.unregister_class(OBJECT_OT_test_fail_operator)

    def test_ignore_actual_runtime_errors_from_operators(self) -> None:

        class OBJECT_OT_test_fail_operator(bpy.types.Operator):
            bl_idname = "object.test_fail_operator"
            bl_label = "Test Fail Operator"

            def execute(self, context):
                raise RuntimeError("Intentional runtime error.")

        bpy.utils.register_class(OBJECT_OT_test_fail_operator)

        try:
            bpy.ops.object.test_fail_operator()
        except RuntimeError as e:
            error_reports = subject.extract_error_reports(e)
            assert error_reports == []

        bpy.utils.unregister_class(OBJECT_OT_test_fail_operator)


class TestGetSelectedFiles(NewFile):
    def test_get_a_single_file(self) -> None:
        with tempfile.NamedTemporaryFile() as f:
            file = type("", (object,), {"name": f.name})()
            assert subject.get_selected_files(Path(f.name).parent, [file]) == [f.name]

    def test_get_multiple_files(self) -> None:
        with tempfile.NamedTemporaryFile() as f:
            with tempfile.NamedTemporaryFile() as g:
                file = type("", (object,), {"name": f.name})()
                file2 = type("", (object,), {"name": g.name})()
                assert subject.get_selected_files(Path(f.name).parent, [file, file2]) == [f.name, g.name]

    def test_exclude_directories(self) -> None:
        with tempfile.NamedTemporaryFile() as f:
            with tempfile.TemporaryDirectory() as d:
                file = type("", (object,), {"name": f.name})()
                directory = type("", (object,), {"name": d})()
                assert subject.get_selected_files(Path(f.name).parent, [file, directory]) == [f.name]

    def test_get_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".ifc") as f:
                tool.Ifc.set_path(str(f.name))
                with tempfile.NamedTemporaryFile(dir=tmp_dir) as g:
                    file = type("", (object,), {"name": g.name})
                    assert subject.get_selected_files(Path(g.name).parent, [file], use_relative_path=True) == [
                        Path(g.name).name
                    ]


class TestGetDebugInfo(NewFile):
    # Only keys that are safe to set if Bonsai fails to load.
    EXPECTED_KEYS = {
        "os",
        "os_version",
        "python_version",
        "architecture",
        "machine",
        "processor",
        "blender_version",
        "bonsai_version",
        "bonsai_commit_hash",
        "bonsai_commit_date",
        "last_actions",
        "last_error",
    }

    def test_failed_to_load_returns_only_base_keys(self):
        info = bonsai.get_debug_info(bonsai_failed_to_load=True)
        assert set(info.keys()) == self.EXPECTED_KEYS


class TestIsViewTopDown(NewFile):
    """Pin the default threshold of ``is_view_top_down`` against synthetic view
    matrices. Drivers that lay out icons or gate gizmos against world-Z rely on
    this cone width to switch behaviour; a silent default change would shift
    those callers without their tests noticing."""

    @staticmethod
    def _ctx(view_matrix):
        from types import SimpleNamespace

        return SimpleNamespace(region_data=SimpleNamespace(view_matrix=view_matrix))

    def test_returns_false_when_region_data_is_none(self):
        from types import SimpleNamespace

        ctx = SimpleNamespace(region_data=None)
        assert subject.is_view_top_down(ctx) is False

    def test_true_for_exact_top_view(self):
        from mathutils import Matrix

        # Identity view-matrix: camera Z aligns with world Z exactly.
        ctx = self._ctx(Matrix.Identity(4))
        assert subject.is_view_top_down(ctx) is True

    def test_true_for_view_inside_default_cone(self):
        import math

        from mathutils import Matrix

        # 10° tilt → |view_forward.z| = cos(10°) ≈ 0.985 > 0.9659 default threshold.
        # Inside the narrow plan-view cone — vertical-intent gizmos should switch
        # to screen-space (or hide) at this view angle.
        ctx = self._ctx(Matrix.Rotation(math.radians(10), 4, "X"))
        assert subject.is_view_top_down(ctx) is True

    def test_false_for_view_outside_default_cone(self):
        import math

        from mathutils import Matrix

        # 20° tilt → |view_forward.z| = cos(20°) ≈ 0.94 < 0.9659 default threshold.
        # Outside the cone — Z still projects to ~34% of its world length on
        # screen, so vertical-intent gizmos remain readable here and should stay
        # in their world-space positions.
        ctx = self._ctx(Matrix.Rotation(math.radians(20), 4, "X"))
        assert subject.is_view_top_down(ctx) is False

    def test_false_for_45_degree_tilt(self):
        import math

        from mathutils import Matrix

        # 45° tilt → cos(45°) ≈ 0.707; well outside the cone at any reasonable
        # threshold. Regression guard: a refactor that accidentally widens the
        # cone past ~45° would silently degrade the typical 3D-orbit experience.
        ctx = self._ctx(Matrix.Rotation(math.radians(45), 4, "X"))
        assert subject.is_view_top_down(ctx) is False

    def test_false_for_side_view(self):
        import math

        from mathutils import Matrix

        # 90° tilt = front/back view → |view_forward.z| = 0.
        ctx = self._ctx(Matrix.Rotation(math.radians(90), 4, "X"))
        assert subject.is_view_top_down(ctx) is False

    def test_threshold_parameter_overrides_default(self):
        import math

        from mathutils import Matrix

        # A 45° tilt that fails the default cone passes when the cone is widened.
        ctx = self._ctx(Matrix.Rotation(math.radians(45), 4, "X"))
        assert subject.is_view_top_down(ctx, threshold=0.5) is True


class TestGetScreenUpWorld(NewFile):
    """Pin the contract that ``get_screen_up_world`` returns the camera's up
    axis in world space, with a safe ``+Y`` fallback when no region is active."""

    @staticmethod
    def _ctx(view_matrix):
        from types import SimpleNamespace

        return SimpleNamespace(region_data=SimpleNamespace(view_matrix=view_matrix))

    def test_returns_plus_y_when_region_data_is_none(self):
        from types import SimpleNamespace

        from mathutils import Vector

        ctx = SimpleNamespace(region_data=None)
        assert subject.get_screen_up_world(ctx) == Vector((0.0, 1.0, 0.0))

    def test_identity_view_matrix_maps_screen_up_to_plus_y(self):
        from mathutils import Matrix, Vector

        ctx = self._ctx(Matrix.Identity(4))
        assert subject.get_screen_up_world(ctx) == Vector((0.0, 1.0, 0.0))


class TestAreViewportGizmosEnabled(NewFile):
    """``are_viewport_gizmos_enabled`` is the single read of the addon-preference
    toggle every Bonsai gizmo ``poll()`` and decorator ``draw()`` guards on.
    Pin the contract that it returns the underlying ``gizmos.draw_gizmos_in_3d_viewport``
    pref so callers can rely on one named function instead of inlining the path."""

    def test_returns_true_when_pref_enabled(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=True))
        with patch.object(subject, "get_addon_preferences", return_value=prefs):
            assert subject.are_viewport_gizmos_enabled() is True

    def test_returns_false_when_pref_disabled(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=False))
        with patch.object(subject, "get_addon_preferences", return_value=prefs):
            assert subject.are_viewport_gizmos_enabled() is False


class TestModifierPsetPredicatesReturnBool(NewFile):
    """``Modifier.is_door/window/roof/railing/stair`` are annotated ``-> bool``
    but delegate to ``tool.Pset.get_element_pset``, which returns
    ``Optional[entity_instance]``. The predicates MUST convert to a proper
    boolean so callers asserting ``is True`` / ``is False`` see what they
    expect — otherwise a missing pset surfaces as ``None`` and silently
    breaks identity-comparison assertions."""

    _PREDICATES = ["is_door", "is_window", "is_roof", "is_railing", "is_stair"]

    @pytest.mark.parametrize("predicate_name", _PREDICATES)
    def test_returns_false_when_pset_absent(self, predicate_name):
        from unittest.mock import patch

        predicate = getattr(subject.Modifier, predicate_name)
        with patch.object(tool.Pset, "get_element_pset", return_value=None):
            assert predicate(object()) is False

    @pytest.mark.parametrize("predicate_name", _PREDICATES)
    def test_returns_true_when_pset_present(self, predicate_name):
        from unittest.mock import patch

        predicate = getattr(subject.Modifier, predicate_name)
        sentinel_pset = object()
        with patch.object(tool.Pset, "get_element_pset", return_value=sentinel_pset):
            assert predicate(object()) is True


class TestViewportDecoratorRejectsMissingDrawMethod(NewFile):
    """``__init_subclass__`` pins the contract that any subclass declaring
    ``draw_method`` (or any entry in ``draw_methods``) names an attribute
    the class actually exposes. Without this guard a typo in the string
    defers the failure to the first redraw, far from the declaration."""

    def test_subclass_with_missing_single_draw_method_raises(self):
        with pytest.raises(TypeError, match="draw method"):
            type("DecoratorWithBadDrawMethod", (subject.ViewportDecorator,), {"draw_method": "no_such_method"})

    def test_subclass_with_missing_entry_in_draw_methods_raises(self):
        with pytest.raises(TypeError, match="draw method"):
            type(
                "DecoratorWithBadDrawMethods",
                (subject.ViewportDecorator,),
                {"draw_methods": (("missing_method", "POST_VIEW"),)},
            )

    def test_subclass_with_present_method_is_accepted(self):
        cls = type(
            "DecoratorWithValidDrawMethod",
            (subject.ViewportDecorator,),
            {"draw_method": "draw", "draw": lambda self, context: None},
        )
        assert cls.draw_method == "draw"
