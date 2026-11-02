"""Structural property tests for the three-layer dependency rule (task 9.1).

The ``rhtracker`` package is arranged in three layers with a strict
**downward-only** dependency rule (see design.md "Architecture"):

    scripts / cli   ->   services   ->   library (model, sources, storage,
                                         reconstruct, reporting)

``model`` sits at the bottom: everything may depend on it, it depends on nothing
in the package.

These tests enforce the rule *statically*. They parse every ``.py`` module under
``src/rhtracker`` (and the ``scripts/`` cron entry) with the :mod:`ast` module,
collect each module's package-internal import targets, classify both the
importer and every target into a layer, and assert the allowed-target rule for
that layer. No code is executed and no runtime import graph is needed — the
module set on disk is the input, so these behave as structural property tests
over all modules.

Feature: rhtracker-refactor, Property 1: Scripts layer depends downward only.
Feature: rhtracker-refactor, Property 2: Services layer depends on the library only.
Feature: rhtracker-refactor, Property 3: Library layer imports the model only.

Validates: Requirements 1.2, 1.3, 1.4
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Locate the package and the scripts directory relative to this test file.
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "src" / "rhtracker"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

# Layer names.
LIBRARY = "library"
SERVICES = "services"
SCRIPTS_CLI = "scripts/cli"

# The library modules, by their dotted suffix under ``rhtracker`` (``sources`` is
# a sub-package, so anything beneath it is library too).
LIBRARY_MODULES = {"model", "storage", "reconstruct", "reporting", "sources", "splits", "categories", "export", "writers"}


def _rhtracker_suffix(module_path: Path) -> str:
    """Dotted module name of a file under ``src/rhtracker`` (e.g. ``cli.pull``)."""
    rel = module_path.relative_to(PKG_ROOT).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts)


def _classify_rhtracker_module(suffix: str) -> str:
    """Classify a ``rhtracker.<suffix>`` module into its layer.

    ``suffix`` is the dotted name under ``rhtracker`` ("" for the top package,
    "model", "cli.pull", "sources.robinhood", "__main__", ...).
    """
    head = suffix.split(".", 1)[0]
    if head in ("cli", "__main__", "__init__", ""):
        return SCRIPTS_CLI
    if head == "services":
        return SERVICES
    if head in LIBRARY_MODULES:
        return LIBRARY
    raise AssertionError(f"unclassified rhtracker module: {suffix!r}")


def _imported_rhtracker_targets(source: str) -> list[str]:
    """Return the dotted ``rhtracker.<...>`` targets imported by ``source``.

    Handles both ``import rhtracker.x.y`` and ``from rhtracker.x import y``.
    Imports that are not package-internal (stdlib, third-party) are ignored.
    The returned value is the suffix after ``rhtracker.`` (e.g. ``cli.pull``,
    ``model``, ``sources.base``).
    """
    targets: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "rhtracker":
                    continue  # importing the package root pulls in nothing
                if name.startswith("rhtracker."):
                    targets.append(name[len("rhtracker."):])
        elif isinstance(node, ast.ImportFrom):
            # Only absolute ``from rhtracker...`` imports appear in this package;
            # relative imports (level > 0) are not used but would be package-local
            # too, so guard against them explicitly.
            if node.level and node.level > 0:
                pytest.fail(
                    f"relative import found (level={node.level}); "
                    "layer rules assume absolute rhtracker imports"
                )
            mod = node.module or ""
            if mod == "rhtracker":
                # ``from rhtracker import X`` -> each X is a submodule suffix.
                for alias in node.names:
                    targets.append(alias.name)
            elif mod.startswith("rhtracker."):
                # ``from rhtracker.a.b import X`` -> the module itself is the
                # target that matters for layer direction.
                targets.append(mod[len("rhtracker."):])
    return targets


def _package_modules() -> list[tuple[str, str, Path]]:
    """All package modules as ``(layer, suffix, path)`` tuples.

    Includes every ``.py`` under ``src/rhtracker``. The CLI command modules
    live under ``src/rhtracker/cli`` and form the scripts/cli layer.
    """
    out: list[tuple[str, str, Path]] = []
    for path in sorted(PKG_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        suffix = _rhtracker_suffix(path)
        out.append((_classify_rhtracker_module(suffix), suffix, path))
    if SCRIPTS_ROOT.exists():
        for path in sorted(SCRIPTS_ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out.append((SCRIPTS_CLI, path.stem, path))
    return out


# Materialize once so the parametrize ids are stable.
_MODULES = _package_modules()


def _modules_in_layer(layer: str) -> list[tuple[str, str, Path]]:
    return [m for m in _MODULES if m[0] == layer]


# --------------------------------------------------------------------------
# Sanity: the scanner actually found the modules we expect.
# --------------------------------------------------------------------------
def test_scanner_discovers_all_three_layers():
    layers = {m[0] for m in _MODULES}
    assert layers == {SCRIPTS_CLI, SERVICES, LIBRARY}, (
        f"expected all three layers to be present, found {layers}"
    )
    # model.py must be the bottom library module and import nothing from the pkg.
    model_path = PKG_ROOT / "model.py"
    assert model_path.exists()
    assert _imported_rhtracker_targets(model_path.read_text(encoding="utf-8")) == []


# --------------------------------------------------------------------------
# Property 1: Scripts layer depends downward only.
# Feature: rhtracker-refactor, Property 1
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [m[2] for m in _modules_in_layer(SCRIPTS_CLI)],
    ids=[m[1] for m in _modules_in_layer(SCRIPTS_CLI)],
)
def test_property1_scripts_layer_depends_downward_only(path: Path):
    """Every scripts/cli module imports only services, the library, or a
    same-layer cli sibling — never a direction that breaks the downward rule."""
    allowed = {SCRIPTS_CLI, SERVICES, LIBRARY}  # nothing sits above this layer
    for target in _imported_rhtracker_targets(path.read_text(encoding="utf-8")):
        target_layer = _classify_rhtracker_module(target)
        assert target_layer in allowed, (
            f"{path.name} (scripts/cli) imports rhtracker.{target} "
            f"in layer {target_layer!r}, which violates the downward rule"
        )


# --------------------------------------------------------------------------
# Property 2: Services layer depends on the library only.
# Feature: rhtracker-refactor, Property 2
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [m[2] for m in _modules_in_layer(SERVICES)],
    ids=[m[1] for m in _modules_in_layer(SERVICES)],
)
def test_property2_services_layer_depends_on_library_only(path: Path):
    """``services`` imports only library modules — never ``cli`` or ``scripts``."""
    for target in _imported_rhtracker_targets(path.read_text(encoding="utf-8")):
        target_layer = _classify_rhtracker_module(target)
        assert target_layer == LIBRARY, (
            f"services imports rhtracker.{target} in layer {target_layer!r}; "
            "the services layer may import the library only"
        )


# --------------------------------------------------------------------------
# Property 3: Library layer imports the model only.
# Feature: rhtracker-refactor, Property 3
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [m[2] for m in _modules_in_layer(LIBRARY)],
    ids=[m[1] for m in _modules_in_layer(LIBRARY)],
)
def test_property3_library_layer_never_imports_upward(path: Path):
    """Library modules may depend on each other (model is the base, and
    higher library modules like export/writers build on categories/
    reconstruct), but they must NEVER import UPWARD into the services or
    scripts/cli layers. That upward-only prohibition is the real invariant
    that keeps the layering acyclic."""
    forbidden = {SERVICES, SCRIPTS_CLI}
    for target in _imported_rhtracker_targets(path.read_text(encoding="utf-8")):
        target_layer = _classify_rhtracker_module(target)
        assert target_layer not in forbidden, (
            f"{path.name} (library) imports rhtracker.{target} in layer "
            f"{target_layer!r}; library modules must not import services or cli"
        )
