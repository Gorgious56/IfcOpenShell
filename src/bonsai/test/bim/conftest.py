import pytest


class _FakePropsBase:
    """Base for parametric-edit PropertyGroup stand-ins used in lifecycle tests.

    The four lifecycle mixins (``FeatureModifierEditMixin``,
    ``PathPreservingEditMixin``, ``_RailingEditMixin``, ...) read/write
    a common contract:

    - ``is_editing`` (bool) — the registry flag the mixin must flip
    - ``last_kwargs`` (dict | None) — capture of the last data written
      via ``set_props_kwargs_from_ifc_data`` so tests can assert load shape
    - ``set_props_kwargs_from_ifc_data(data)`` — invoked on enable / finish
    - ``get_general_kwargs(convert_to_project_units=True)`` — read draft state

    Per-type stand-ins (door, railing, roof) subclass this base and add their
    own kwargs accessors and per-type fields. The array mixin has a different
    shape (direct attribute access on a list of layers, not get/set kwargs)
    so its stand-in does NOT derive from this base.
    """

    def __init__(self, general: dict | None = None):
        self.is_editing = False
        self.last_kwargs: dict | None = None
        # Shallow-copy ``general`` so a caller that passes a dict can't
        # later mutate it and have the mutation silently surface here.
        self.general = dict(general) if general is not None else {}

    def set_props_kwargs_from_ifc_data(self, data):
        self.last_kwargs = dict(data)

    def get_general_kwargs(self, convert_to_project_units=True):
        return dict(self.general)


class _FakePathProps(_FakePropsBase):
    """Stand-in for railing / roof property groups — general kwargs only,
    no lining/panel decomposition."""

    def __init__(self):
        super().__init__(general={"width": 200, "thickness": 10})


def make_lifecycle_obj(props, *, name="obj"):
    """Build a ``bpy.types.Object`` stand-in for parametric-lifecycle tests.

    The mixin code under test reads two surfaces: ``obj.props`` (the
    PropertyGroup stand-in) and ``obj.name`` (used in error reports).
    ``spec=bpy.types.Object`` catches typo'd attribute access at test time
    (e.g. ``obj.matrix_wrold``); ``props`` is an explicit test attribute
    populated below — assignment succeeds with or without spec.

    ``bpy`` is imported inside the function so this conftest stays importable
    when ``bpy`` is absent (the autouse ``_require_real_bpy`` fixture skips
    the affected tests cleanly)."""
    from unittest import mock

    import bpy

    obj = mock.Mock(spec=bpy.types.Object, name=name)
    obj.props = props
    obj.name = name
    return obj


# pytest by default doesn't print steps and where it failed. Let's fix that.


@pytest.hookimpl
def pytest_bdd_before_scenario(request, feature, scenario):
    print(f"\033[94m# {feature.name}\033[0m")
    print(f"\033[94m## {scenario.name}\033[0m")


@pytest.hookimpl(tryfirst=True)
def pytest_bdd_after_step(request, feature, scenario, step, step_func, step_func_args):
    print(f"\033[92m>>> {step.name}\033[0m")


@pytest.hookimpl(tryfirst=True)
def pytest_bdd_step_error(request, feature, scenario, step, step_func, step_func_args):
    print(f"\033[1;91m>>> {step.name} <-- FAILED\033[0m")


@pytest.fixture(autouse=True)
def _require_real_bpy():
    """Skip when run in a lane where ``bpy`` is mocked or absent.

    Tests under ``test/bim/`` are designed for Blender's bundled Python
    (via ``runpytest.py``). When invoked from the tooling Python lane
    ``bpy`` is either absent or replaced with a mock; this autouse
    fixture turns that state into a clean skip rather than letting
    failures cascade as ``AttributeError`` from accessing mocked
    Blender internals.

    Imports are local so this conftest stays importable even when
    ``bpy`` itself is not installed — collection still succeeds; the
    affected tests just skip."""
    import types

    import bpy

    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")
