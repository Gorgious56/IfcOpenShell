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

"""Registration smoke test for `tool.Parametric.EDIT_TYPES`.

The registry is the single source of truth for which parametric element types
exist. Every consumer (auto-commit on save, finish/cancel chains, the
``PointerProperty`` attachment, the ``GizmoPreferences<X>`` registration) derives
identifiers from each entry's short ``name`` token. Forget any downstream
registration and the silent-desync the framework exists to prevent will ship.

These tests pin the registry-to-runtime contract: for every entry the operator
``bl_idname``s resolve to registered ``bpy.ops.bim.*`` callables, the
``PropertyGroup`` class is attached to ``bpy.types.Object``, and the per-type
predicate exists on `tool.Blender.Modifier`."""

import types

import bpy
import pytest

pytestmark = pytest.mark.model


@pytest.fixture
def registry():
    from bonsai import tool

    return tool.Parametric.EDIT_TYPES


def test_registry_is_non_empty(registry):
    assert len(registry) >= 1


def test_every_entry_has_enable_op_registered(registry):
    missing = [e.enable_op for e in registry if not hasattr(bpy.ops.bim, e.enable_op.removeprefix("bim."))]
    assert not missing, f"Missing enable operators: {missing}"


def test_every_entry_has_finish_op_registered(registry):
    missing = [e.finish_op for e in registry if not hasattr(bpy.ops.bim, e.finish_op.removeprefix("bim."))]
    assert not missing, f"Missing finish operators: {missing}"


def test_every_entry_has_cancel_op_registered(registry):
    missing = [e.cancel_op for e in registry if not hasattr(bpy.ops.bim, e.cancel_op.removeprefix("bim."))]
    assert not missing, f"Missing cancel operators: {missing}"


def test_every_entry_has_property_group_attached(registry):
    # ``register_object_properties`` runs at addon enable; if any entry's
    # PropertyGroup class is missing on prop module the attribute is skipped.
    missing = [e.props_attr for e in registry if not hasattr(bpy.types.Object, e.props_attr)]
    assert not missing, (
        f"bpy.types.Object missing attributes: {missing} — "
        f"verify the matching PropertyGroup classes exist in bim.module.model.prop"
    )


def test_every_entry_has_modifier_predicate(registry):
    from bonsai import tool

    missing = [e.name for e in registry if getattr(tool.Blender.Modifier, f"is_{e.name}", None) is None]
    assert not missing, f"tool.Blender.Modifier missing is_<name> predicates: {missing}"


def test_every_predicate_does_not_raise_on_non_matching_element(registry):
    """Each ``is_<name>`` predicate must be **total**: accept any IFC entity
    and return a truthy/falsy value, never raise.

    The registry iterates every predicate against the active IFC element on
    save; a raising predicate (e.g. ``AttributeError`` from a missing pset
    accessor when handed a non-matching element type) propagates upward and
    breaks the save path for *all* parametric types, not just its own.
    This test probes each predicate with an ``IfcAnnotation`` (an element
    that carries none of the BBIM_<Type> psets the predicates look up) and
    asserts the call does not raise. Falsy returns are acceptable — the
    registry treats them as 'no match'. What's forbidden is raising."""
    import ifcopenshell

    from bonsai import tool

    probe = ifcopenshell.file(schema="IFC4").create_entity("IfcAnnotation")

    raised = []
    for feature in registry:
        predicate = getattr(tool.Blender.Modifier, f"is_{feature.name}", None)
        if predicate is None:
            continue
        try:
            predicate(probe)
        except Exception as e:
            raised.append((feature.name, type(e).__name__, str(e)))
    assert not raised, (
        f"is_<name> predicates raised on a non-matching IfcAnnotation: {raised}. "
        f"Predicates must be total — return bool, never raise. Add an "
        f"`if not element.is_a('IfcXxx'): return False` short-circuit or guard the pset lookup."
    )


def _fake_editing_obj(registry, editing_names: set[str]):
    """Build a SimpleNamespace that mimics a bpy.types.Object — one
    ``BIM<Name>Properties`` attribute per registry entry, with ``is_editing``
    set True only for entries named in ``editing_names``."""
    obj = types.SimpleNamespace()
    for entry in registry:
        setattr(obj, entry.props_attr, types.SimpleNamespace(is_editing=entry.name in editing_names))
    return obj


def test_is_object_editing_returns_active_entry(registry):
    """``is_object_editing`` returns the registry entry whose triad is active."""
    from bonsai import tool

    target = registry[0]
    obj = _fake_editing_obj(registry, editing_names={target.name})
    assert tool.Parametric.is_object_editing(obj) is target


def test_is_object_editing_returns_none_when_no_edit_active(registry):
    """No triad active → ``None``."""
    from bonsai import tool

    obj = _fake_editing_obj(registry, editing_names=set())
    assert tool.Parametric.is_object_editing(obj) is None


def test_get_pending_edits_self_heals_stale_is_editing_on_duplicates(registry, monkeypatch):
    """Root-cause regression for the user-reported auto-commit infinite
    loop: ``bpy.types.Object.copy()`` (called from
    ``tool.Geometry.duplicate_ifc_objects`` via ``tool.Model.regenerate_array``)
    propagates ``BIM<Name>Properties.is_editing=True`` from source to
    duplicate. The duplicate is then picked up by ``get_pending_edits`` on
    every save, the finish operator early-returns on the per-type predicate
    mismatch (e.g. array CHILD vs. array PARENT), nonetheless reports
    FINISHED, and ``commit_object_draft`` counts it as a successful commit
    forever.

    Fix: ``get_pending_edits`` validates each ``is_editing=True`` object
    against its registered type's predicate and self-heals (clears the flag,
    skips the entry) when the predicate fails — typical of a duplicate whose
    IFC element doesn't match the source's type."""
    from unittest import mock

    from bonsai import tool

    valid_feature = registry[0]
    phantom_feature = registry[1] if len(registry) > 1 else registry[0]

    valid_obj = _fake_editing_obj(registry, editing_names={valid_feature.name})
    valid_obj.name = "valid"
    phantom_obj = _fake_editing_obj(registry, editing_names={phantom_feature.name})
    phantom_obj.name = "phantom"

    monkeypatch.setattr(tool.Ifc, "get_entity", lambda obj: object())
    monkeypatch.setattr(tool.Blender.Modifier, f"is_{valid_feature.name}", lambda _elem: True)
    if phantom_feature.name != valid_feature.name:
        monkeypatch.setattr(tool.Blender.Modifier, f"is_{phantom_feature.name}", lambda _elem: False)

    with mock.patch("bonsai.tool.parametric.bpy.data") as mock_data:
        mock_data.objects = [valid_obj, phantom_obj]
        pending = tool.Parametric.get_pending_edits()

    assert pending == [(valid_obj, valid_feature.finish_op)]
    if phantom_feature.name != valid_feature.name:
        # Self-heal contract: phantom's stale flag was cleared so subsequent
        # saves don't keep re-picking it up.
        assert getattr(phantom_obj, phantom_feature.props_attr).is_editing is False


def test_orphan_object_self_heals_stale_is_editing(registry, monkeypatch):
    """Orphan object (Blender-side object whose IFC link was severed) with
    a stale ``is_editing=True`` flag must self-heal: when the IFC entity
    lookup returns None, the registry clears the flag and excludes the
    object from any subsequent commit dispatch."""
    from bonsai import tool

    feature = registry[0]
    obj = _fake_editing_obj(registry, editing_names={feature.name})
    obj.name = "orphan"
    monkeypatch.setattr(tool.Ifc, "get_entity", lambda _obj: None)

    assert tool.Parametric._validated_editing_feature(obj) is None
    assert getattr(obj, feature.props_attr).is_editing is False


def test_predicate_is_not_consulted_when_no_is_editing_flag_set(registry, monkeypatch):
    """Object with no ``is_editing`` flag set on any registered type takes
    the fast path: the per-type predicate must NOT be invoked. Saves are
    common; predicate calls on every untouched object would multiply
    save-time cost by the number of registered parametric types."""
    from bonsai import tool

    obj = _fake_editing_obj(registry, editing_names=set())  # no flag set anywhere

    def _exploding_predicate(_elem):
        raise AssertionError("predicate must not be called when no is_editing flag is set")

    monkeypatch.setattr(tool.Ifc, "get_entity", lambda _obj: object())
    for entry in registry:
        monkeypatch.setattr(tool.Blender.Modifier, f"is_{entry.name}", _exploding_predicate)

    assert tool.Parametric._validated_editing_feature(obj) is None


def test_missing_per_type_predicate_self_heals_stale_is_editing(registry, monkeypatch):
    """Defensive: if a registry entry's ``is_<name>`` predicate isn't
    registered on ``tool.Blender.Modifier`` (partial init at addon enable,
    extension swap, etc.), the registry treats the ``is_editing`` flag as
    stale rather than crashing the save path."""
    from bonsai import tool

    feature = registry[0]
    obj = _fake_editing_obj(registry, editing_names={feature.name})
    monkeypatch.setattr(tool.Ifc, "get_entity", lambda _obj: object())
    # Remove the predicate so getattr(..., None) returns None.
    monkeypatch.delattr(tool.Blender.Modifier, f"is_{feature.name}", raising=False)

    assert tool.Parametric._validated_editing_feature(obj) is None
    assert getattr(obj, feature.props_attr).is_editing is False


def test_commit_pending_edits_for_selection_self_heals_stale_is_editing(registry, monkeypatch):
    """Selection-scoped commit must skip phantom duplicates the same way
    the save-time path does — a stale ``is_editing=True`` on a selected
    object must NOT dispatch the finish operator and the flag must be
    cleared. Pins the contract for the second call site of
    `_validated_editing_feature` so a refactor that drops the helper call
    from this method gets caught."""
    from unittest import mock

    from bonsai import tool

    valid_feature = registry[0]
    phantom_feature = registry[1] if len(registry) > 1 else registry[0]

    valid_obj = _fake_editing_obj(registry, editing_names={valid_feature.name})
    valid_obj.name = "valid"
    phantom_obj = _fake_editing_obj(registry, editing_names={phantom_feature.name})
    phantom_obj.name = "phantom"

    monkeypatch.setattr(tool.Ifc, "get_entity", lambda _obj: object())
    monkeypatch.setattr(tool.Blender.Modifier, f"is_{valid_feature.name}", lambda _elem: True)
    if phantom_feature.name != valid_feature.name:
        monkeypatch.setattr(tool.Blender.Modifier, f"is_{phantom_feature.name}", lambda _elem: False)
    monkeypatch.setattr(tool.Blender, "get_selected_objects", lambda: [valid_obj, phantom_obj])

    commit_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        tool.Parametric,
        "commit_object_draft",
        classmethod(lambda _cls, obj, op: commit_calls.append((obj, op)) or True),
    )

    committed, failed = tool.Parametric.commit_pending_edits_for_selection()

    assert committed == 1
    assert failed == []
    assert commit_calls == [(valid_obj, valid_feature.finish_op)]
    if phantom_feature.name != valid_feature.name:
        # Self-heal: phantom's stale flag was cleared by `_validated_editing_feature`
        # before the type-name filter / dispatch.
        assert getattr(phantom_obj, phantom_feature.props_attr).is_editing is False


def test_heal_stale_edit_flags_runs_validation_over_all_objects(registry, monkeypatch):
    """``heal_stale_edit_flags`` is the load-time entry to the registry's
    self-heal contract: a ``.blend`` saved with ``is_editing=True`` carries
    the phantom flag on disk. The load-post pass clears phantoms so the
    next save doesn't re-pick them up and the UI doesn't show editing
    affordances on objects whose IFC element doesn't match the registered
    type."""
    from unittest import mock

    from bonsai import tool

    feature = registry[0]
    # Two objects with is_editing=True; configure predicates so the first
    # is valid (flag preserved) and the second is phantom (flag cleared).
    valid_obj = _fake_editing_obj(registry, editing_names={feature.name})
    valid_obj.name = "valid"
    phantom_obj = _fake_editing_obj(registry, editing_names={feature.name})
    phantom_obj.name = "phantom"
    # Stub the predicate to discriminate by object identity.
    monkeypatch.setattr(tool.Ifc, "get_entity", lambda obj: obj)
    monkeypatch.setattr(tool.Blender.Modifier, f"is_{feature.name}", lambda elem: elem is valid_obj)

    with mock.patch("bonsai.tool.parametric.bpy.data") as mock_data:
        mock_data.objects = [valid_obj, phantom_obj]
        tool.Parametric.heal_stale_edit_flags()

    # Valid object's flag preserved (legitimate in-progress edit).
    assert getattr(valid_obj, feature.props_attr).is_editing is True
    # Phantom's stale flag cleared.
    assert getattr(phantom_obj, feature.props_attr).is_editing is False


@pytest.mark.parametrize(
    "name,expected",
    [
        # Single-token names round-trip identically.
        ("door", "BIMDoorProperties"),
        ("window", "BIMWindowProperties"),
        ("stair", "BIMStairProperties"),
        ("railing", "BIMRailingProperties"),
        ("roof", "BIMRoofProperties"),
        ("wall", "BIMWallProperties"),
        ("array", "BIMArrayProperties"),
        # Snake-case names CamelCase correctly. Pins the new contract so a
        # future ``str.capitalize()`` regression doesn't yield
        # ``BIMPipe_segmentProperties`` and silently break the registry
        # auto-discovery in ``register_object_properties``.
        ("pipe_segment", "BIMPipeSegmentProperties"),
        ("duct_segment", "BIMDuctSegmentProperties"),
        ("multi_word_thing", "BIMMultiWordThingProperties"),
    ],
)
def test_props_attr_derives_camel_case_from_name(name, expected):
    from bonsai.tool.parametric import ParametricObject

    assert ParametricObject(name).props_attr == expected


@pytest.mark.parametrize(
    "invalid_name",
    [
        "_door",  # Leading underscore
        "door_",  # Trailing underscore
        "pipe__segment",  # Double underscore
        "PipeSegment",  # Uppercase
        "pipe segment",  # Whitespace
        "1pipe",  # Leading digit
        "",  # Empty
    ],
)
def test_invalid_names_are_rejected_at_construction(invalid_name):
    """Names that would produce empty CamelCase segments or break the
    Bonsai naming convention must raise at construction, not silently
    derive a malformed class name."""
    from bonsai.tool.parametric import ParametricObject

    with pytest.raises(ValueError, match="must match"):
        ParametricObject(invalid_name)


def test_is_object_editing_skip_name_excludes_matching_entry(registry):
    """``skip_name`` masks the named entry even when its triad is active."""
    from bonsai import tool

    target = registry[0]
    obj = _fake_editing_obj(registry, editing_names={target.name})
    assert tool.Parametric.is_object_editing(obj, skip_name=target.name) is None


def test_is_object_editing_skip_name_does_not_mask_other_entry(registry):
    """``skip_name`` only excludes the named entry — others still match."""
    from bonsai import tool

    if len(registry) < 2:
        pytest.skip("Need at least 2 registry entries to test selective skip")
    target = registry[1]
    skip = registry[0]
    obj = _fake_editing_obj(registry, editing_names={target.name})
    assert tool.Parametric.is_object_editing(obj, skip_name=skip.name) is target


def test_gizmo_preferences_attached_for_every_registry_entry(registry):
    """Every registry entry must have a matching ``<name>`` ``PointerProperty``
    on ``ui.GizmoPreferences``. The prefs UI loop iterates ``EDIT_TYPES`` and
    reads ``getattr(self.gizmos, feature.name)`` to render the per-feature
    checkbox; a missing field silently drops the checkbox.

    Checks ``__annotations__`` rather than ``hasattr`` because Blender's
    PropertyGroup syntax (``field: bpy.props.PointerProperty(...)``) is an
    annotation-only assignment — the attribute only materialises on the
    class after Blender's metaclass installs the bpy_struct descriptor,
    which depends on registration timing. Reading ``__annotations__``
    pins the source-level contract independently of when register() ran."""
    from bonsai.bim import ui

    annotations = getattr(ui.GizmoPreferences, "__annotations__", {})
    missing = [feature.name for feature in registry if feature.name not in annotations]
    assert not missing, (
        f"ui.GizmoPreferences missing PointerProperty field(s) for EDIT_TYPES: {missing} — "
        f"each registry entry needs a ``<name>: PointerProperty(type=GizmoPreferencesFeature)`` "
        f"field on ``ui.GizmoPreferences`` so the per-feature checkbox renders."
    )


def test_gizmo_pref_name_matches_registry(registry):
    """Every parametric gizmo group's ``gizmo_pref_name`` class attribute must
    match an ``EDIT_TYPES`` entry. A typo silently disables the runtime
    ``getattr(prefs.gizmos, gizmo_pref_name)`` lookup — the checkbox does
    nothing, the gizmos always render."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    registry_names = {feature.name for feature in registry}
    bad = [
        (cls.__name__, cls.gizmo_pref_name)
        for cls in BaseParametricGizmoGroup.REGISTRY
        if getattr(cls, "gizmo_pref_name", None) is not None and cls.gizmo_pref_name not in registry_names
    ]
    assert not bad, (
        f"Gizmo group(s) declare ``gizmo_pref_name`` not in EDIT_TYPES: {bad} — "
        f"each name must match a registry entry, or the runtime "
        f"``getattr(prefs.gizmos, gizmo_pref_name)`` lookup misses."
    )


# ----------------------------------------------------------------------------
# tool.Parametric.GenerationKeyedCache — the shared primitive that both the
# wall edit gizmo group and the wall-offset gizmos (door/window) use to
# memoise per-IFC-commit reads. Pin the invalidation contract: cached
# values survive within one generation, get dropped en bloc when the
# generation counter advances, and ``None`` is a legitimate stored value
# (a "failed compute" that should NOT re-run within the same generation).
# ----------------------------------------------------------------------------


def test_generation_keyed_cache_loader_runs_on_first_get():
    from bonsai import tool

    cache = tool.Parametric.GenerationKeyedCache()
    calls: list[int] = []
    result = cache.get_or_compute("k", lambda: (calls.append(1), "v")[1])
    assert result == "v"
    assert calls == [1]


def test_generation_keyed_cache_loader_skipped_on_second_get_same_generation():
    from bonsai import tool

    cache = tool.Parametric.GenerationKeyedCache()
    cache.get_or_compute("k", lambda: "first")
    result = cache.get_or_compute("k", lambda: pytest.fail("loader must not be re-run within one generation"))
    assert result == "first"


def test_generation_keyed_cache_drops_entries_on_generation_bump():
    from bonsai import tool

    original_gen = tool.Parametric._geom_generation
    try:
        cache = tool.Parametric.GenerationKeyedCache()
        cache.get_or_compute("k", lambda: "first")
        tool.Parametric._geom_generation = original_gen + 1
        result = cache.get_or_compute("k", lambda: "second")
        assert result == "second"
    finally:
        tool.Parametric._geom_generation = original_gen


def test_generation_keyed_cache_treats_none_as_a_cached_value():
    # A loader that legitimately returns ``None`` (e.g. "no host wall for this
    # filling") must not be re-invoked within the same generation — that's
    # the whole point of the cache for negative results.
    from bonsai import tool

    cache = tool.Parametric.GenerationKeyedCache()
    cache.get_or_compute("k", lambda: None)
    result = cache.get_or_compute("k", lambda: pytest.fail("None must be cached, not treated as a miss"))
    assert result is None


def test_generation_keyed_cache_clear_drops_entries():
    from bonsai import tool

    cache = tool.Parametric.GenerationKeyedCache()
    cache.get_or_compute("k", lambda: "first")
    cache.clear()
    result = cache.get_or_compute("k", lambda: "second")
    assert result == "second"
