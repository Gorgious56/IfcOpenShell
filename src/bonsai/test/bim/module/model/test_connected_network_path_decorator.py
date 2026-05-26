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

"""Pin the template-method contract for the connected-network-path decorator
base. The base class defines three abstract hooks (`_is_seed_element`,
`_walk`, `_build_geometry`) and an `__init_subclass__` that rejects any
subclass which leaves a hook un-overridden. Without this guard, a forgotten
override would only surface as `NotImplementedError` on the first redraw
that hit the missing hook — long after the class declaration."""

import pytest

pytestmark = pytest.mark.model


_GOOD_HOOKS = {
    "_is_seed_element": lambda self, element: False,
    "_walk": lambda self, start_element: [],
    "_build_geometry": lambda self, connected: ([], []),
}


def _build_subclass(name, omit=()):
    from bonsai.bim.module.model.decorator import _ConnectedNetworkPathDecorator

    namespace = {name: fn for name, fn in _GOOD_HOOKS.items() if name not in omit}
    return type(name, (_ConnectedNetworkPathDecorator,), namespace)


@pytest.mark.parametrize("missing_hook", sorted(_GOOD_HOOKS))
def test_subclass_missing_any_single_hook_raises(missing_hook):
    with pytest.raises(TypeError, match="must override abstract hook"):
        _build_subclass(f"DecoratorMissing_{missing_hook}", omit=(missing_hook,))


def test_subclass_missing_all_hooks_raises_naming_each():
    with pytest.raises(TypeError) as excinfo:
        _build_subclass("DecoratorMissingEverything", omit=tuple(_GOOD_HOOKS))
    message = str(excinfo.value)
    for hook in _GOOD_HOOKS:
        assert hook in message, f"missing-hook error must name {hook!r}"


def test_fully_overridden_subclass_is_accepted():
    cls = _build_subclass("DecoratorWithAllHooks")
    assert cls.__name__ == "DecoratorWithAllHooks"
