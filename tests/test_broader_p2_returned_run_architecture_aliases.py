"""Adversarial alias tests for the test-owned returned-run architecture guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import p2_returned_run_architecture_guard as architecture

_ROOT = Path(__file__).resolve().parents[1]
_RETURNED_PATH = _ROOT / "research_decision_engine" / "benchmarks" / "broader_returned_run.py"
_HELPER_PATH = (
    _ROOT / "research_decision_engine" / "benchmarks" / "broader_calibration_selector_replay.py"
)
_RETURNED_SOURCE = _RETURNED_PATH.read_text(encoding="utf-8")
_HELPER_SOURCE = _HELPER_PATH.read_text(encoding="utf-8")


def _returned_checks(extra_source: str) -> dict[str, bool]:
    source = f"{_RETURNED_SOURCE}\n{extra_source}\n"
    return dict(architecture.returned_run_architecture_checks(source))


def _helper_checks(source: str) -> dict[str, bool]:
    return dict(architecture.selector_replay_helper_architecture_checks(source))


@pytest.mark.parametrize(
    ("source", "intended_check"),
    (
        (
            "ReturnedResultProjection = ReturnedRunProjection",
            "no-projection-class-alias",
        ),
        (
            "Alias = ReturnedRunProjection\nReturnedResultProjection = Alias",
            "no-projection-class-alias",
        ),
        (
            "ReturnedResultProjection: type = ReturnedRunProjection",
            "no-projection-class-alias",
        ),
        (
            "ReturnedResultProjection, other = ReturnedRunProjection, 1",
            "no-projection-class-alias",
        ),
        (
            "if (ReturnedResultProjection := ReturnedRunProjection):\n    pass",
            "no-projection-class-alias",
        ),
        (
            "type ReturnedResultProjection = ReturnedRunProjection",
            "no-projection-class-alias",
        ),
        (
            "if True:\n    class UnexpectedStageProjection:\n        pass",
            "exact-34-class-surface",
        ),
        (
            '__all__ = ("ReturnedResultProjection",)',
            "no-forbidden-later-stage-export",
        ),
        (
            "def __getattr__(name: str) -> object:\n"
            "    if name == 'ReturnedResultProjection':\n"
            "        return ReturnedRunProjection\n"
            "    raise AttributeError(name)",
            "no-module-dynamic-hooks",
        ),
        (
            'ExecutionIdentity = "execution/forbidden"',
            "no-forbidden-later-stage-binding",
        ),
    ),
)
def test_projection_alias_and_later_stage_bindings_fail_the_intended_guard(
    source: str,
    intended_check: str,
) -> None:
    checks = _returned_checks(source)

    assert checks[intended_check] is False


def test_unexpected_helper_class_is_rejected_by_the_closed_helper_surface() -> None:
    checks = _helper_checks(f"{_HELPER_SOURCE}\nclass HelperProjection:\n    pass\n")

    assert checks["no-helper-class"] is False
    assert checks["exact-helper-function-surface"] is True


@pytest.mark.parametrize(
    "extra_source",
    (
        "async def ExecutionIdentity() -> None:\n    pass",
        "for ExecutionIdentity in ():\n    pass",
    ),
)
def test_helper_later_stage_bindings_are_rejected_for_every_binding_kind(
    extra_source: str,
) -> None:
    checks = _helper_checks(f"{_HELPER_SOURCE}\n{extra_source}\n")

    assert checks["no-helper-later-stage-binding"] is False
    assert checks["exact-helper-binding-events"] is False


def test_conditional_helper_function_redefinition_is_rejected() -> None:
    changed = (
        f"{_HELPER_SOURCE}\n"
        "if True:\n"
        "    def raw_effect_sha256(effect: MatchedEffectObservation) -> str:\n"
        "        return '0' * 64\n"
    )

    checks = _helper_checks(changed)
    assert checks["exact-helper-binding-events"] is False
    assert checks["exact-all-helper-function-definitions"] is False


@pytest.mark.parametrize(
    ("source", "intended_check"),
    (
        (
            "if True:\n    class ReturnedRunProjection:\n        pass",
            "no-top-level-rebinding",
        ),
        (
            "def ReturnedRunProjection() -> None:\n    pass",
            "exact-protected-binding-kinds",
        ),
        (
            "for _MISSING_CONTEXT in (ReturnedRunProjection,):\n    pass",
            "exact-protected-binding-kinds",
        ),
        (
            "def FutureResultProjection() -> None:\n    pass",
            "no-forbidden-later-stage-binding",
        ),
        (
            "def innocently_named_stage_api() -> None:\n    pass",
            "exact-top-level-function-surface",
        ),
        ("del ReturnedRunProjection", "no-module-delete-or-augassign"),
        ("_CANDIDATE_SCHEMA += ()", "no-module-delete-or-augassign"),
    ),
)
def test_existing_returned_bindings_cannot_be_shadowed_or_rebound(
    source: str,
    intended_check: str,
) -> None:
    assert _returned_checks(source)[intended_check] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "def bind_global_projection() -> None:\n"
        "    global ReturnedResultProjection\n"
        "    ReturnedResultProjection = ReturnedRunProjection",
        "def outer() -> None:\n"
        "    alias = ReturnedRunProjection\n"
        "    def inner() -> None:\n"
        "        nonlocal alias\n"
        "        alias = ReturnedRunProjection",
    ),
)
def test_global_and_nonlocal_rebinding_fail_closed(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["no-dynamic-indirection"] is False


@pytest.mark.parametrize("mode", ("decorator", "metaclass"))
def test_projection_classes_reject_custom_binding_transformations(mode: str) -> None:
    if mode == "decorator":
        changed = _RETURNED_SOURCE.replace(
            "@dataclass(frozen=True, slots=True)\nclass ProvenanceValueProjection:",
            "def alias_class(_value: object) -> type[ReturnedRunProjection]:\n"
            "    return ReturnedRunProjection\n\n"
            "@alias_class\n"
            "class ProvenanceValueProjection:",
            1,
        )
    else:
        changed = _RETURNED_SOURCE.replace(
            "class ProvenanceValueProjection:",
            "class ProvenanceValueProjection(metaclass=type):",
            1,
        )

    checks = dict(architecture.returned_run_architecture_checks(changed))
    assert checks["exact-direct-class-definitions"] is False


@pytest.mark.parametrize(
    "source",
    (
        "from .broader_runner import run_arm as validate\nvalidate()",
        "import research_decision_engine.benchmarks.broader_runner as br\n"
        "execute = br.run_arm\nexecute()",
        "from . import broader_runner as br\nexecute = br.run_arm\nexecute()",
        "from .broader_runner import run_arm\ng = run_arm\ng()",
        "from .broader_runner import run_arm\ng = run_arm\nh = g\nh()",
        "def innocent() -> None:\n"
        "    from .broader_runner import run_arm as validate\n"
        "    execute = validate\n"
        "    execute()",
        "from .broader_execution import execute_deterministic_map as validate\nvalidate()",
        "from .broader_validation_evidence import _register_fixture_plan as remember\nremember()",
        "mutate = CANDIDATES_BY_ID.update\nmutate({})",
        "import subprocess as harmless\nlaunch = harmless.run\nlaunch(())",
    ),
)
def test_forbidden_workload_registry_and_io_aliases_resolve_to_denied_targets(
    source: str,
) -> None:
    checks = _returned_checks(source)

    assert checks["no-forbidden-qualified-call"] is False


def test_registry_mutator_passed_as_a_builtin_callback_is_rejected() -> None:
    checks = _returned_checks("min(('evil',), key=CANDIDATES_BY_ID.setdefault)")

    assert checks["no-forbidden-qualified-call"] is False


def test_registry_mutator_callback_cannot_be_laundered_through_cast() -> None:
    checks = _returned_checks("min(('evil',), key=cast(object, CANDIDATES_BY_ID).setdefault)")

    assert checks["no-forbidden-qualified-call"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "def route(values: tuple[object, ...]) -> object:\n    return min(values, key=_decide)",
        "def invoke_again() -> object:\n    decide_again = _decide\n    return decide_again()",
    ),
)
def test_sensitive_approved_policy_callables_have_exact_sites(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["exact-sensitive-approved-call-and-reference-sites"] is False


def test_registry_mutation_target_taint_survives_cast_and_a_local_alias() -> None:
    checks = _returned_checks(
        "def mutate_registry() -> None:\n"
        "    mutable = cast(object, CANDIDATES_BY_ID)\n"
        "    mutable['evil'] = None"
    )

    assert checks["no-dynamic-indirection"] is False


@pytest.mark.parametrize(
    ("extra_source", "intended_check"),
    (
        ("hashlib.sha256(b'additional')", "one-resolved-sha256-call"),
        (
            "extra_sha256 = hashlib.sha256\nextra_sha256(b'additional')",
            "no-sensitive-hash-alias",
        ),
        (
            "digest = hashlib.sha256\nsecond = digest\nsecond(b'additional')",
            "no-sensitive-hash-alias",
        ),
        (
            "hash_module = hashlib\nraw = hash_module.sha256\nraw(b'additional')",
            "no-sensitive-hash-alias",
        ),
        (
            "raw = protocol_hash\nraw('raw-is-not-framed', {})",
            "no-sensitive-hash-alias",
        ),
        (
            "protocol_hash(CALIBRATION_SELECTION_VERSION, {})",
            "one-exact-selection-protocol-hash",
        ),
        (
            "selected_digest = hashlib.sha256 if choose_hash else protocol_hash\n"
            "selected_digest(b'runtime-selected')",
            "no-sensitive-hash-alias",
        ),
    ),
)
def test_extra_hash_and_protocol_hash_aliases_fail_closed(
    extra_source: str,
    intended_check: str,
) -> None:
    checks = _helper_checks(f"{_HELPER_SOURCE}\n{extra_source}\n")

    assert checks[intended_check] is False


def test_raw_digest_signature_cannot_accept_a_caller_selected_algorithm() -> None:
    changed = _HELPER_SOURCE.replace(
        "def raw_effect_sha256(effect: MatchedEffectObservation) -> str:",
        "def raw_effect_sha256(\n"
        "    effect: MatchedEffectObservation, digest=hashlib.sha256\n"
        ") -> str:",
        1,
    )

    assert _helper_checks(changed)["one-exact-raw-digest-function"] is False


def test_replay_signature_cannot_accept_an_unused_caller_selected_digest() -> None:
    changed = _HELPER_SOURCE.replace(
        "    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,\n"
        ") -> CalibrationHistorySelection:",
        "    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,\n"
        "    digest=hashlib.sha256,\n"
        ") -> CalibrationHistorySelection:",
        1,
    )

    checks = _helper_checks(changed)
    assert checks["exact-replay-entry-point-signature"] is False
    assert checks["exact-helper-hash-callable-reference-surface"] is False


def test_helper_rejects_an_unapproved_method_call_on_supplied_records() -> None:
    changed = _HELPER_SOURCE.replace(
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        "    expected_effects[0].mutate()\n\n"
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        1,
    )

    assert _helper_checks(changed)["exact-helper-unresolved-call-surface"] is False


def test_helper_rejects_composite_assignment_into_supplied_records() -> None:
    changed = _HELPER_SOURCE.replace(
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        "    (expected_effects[0], other) = (expected_effects[0], None)\n\n"
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        1,
    )

    assert _helper_checks(changed)["no-helper-mutation-target"] is False


def test_helper_entry_point_cannot_be_changed_into_a_generator() -> None:
    changed = _HELPER_SOURCE.replace(
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        "    if False:\n        yield None\n\n"
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        1,
    )

    assert _helper_checks(changed)["no-helper-generator-function-surface"] is False


@pytest.mark.parametrize(
    "changed",
    (
        _HELPER_SOURCE.replace("import statistics", "import statistics.evil", 1),
        _HELPER_SOURCE.replace(
            "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
            "    import statistics\n\n"
            "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
            1,
        ),
    ),
)
def test_helper_import_inventory_preserves_requested_module_scope_and_multiplicity(
    changed: str,
) -> None:
    assert _helper_checks(changed)["exact-helper-import-bindings"] is False


def test_returned_import_inventory_preserves_the_requested_plain_module() -> None:
    changed = _RETURNED_SOURCE.replace("import statistics", "import statistics.evil", 1)

    checks = dict(architecture.returned_run_architecture_checks(changed))
    assert checks["exact-qualified-import-bindings"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "del raw_effect_sha256",
        "del replay_calibration_history_selection",
        "raw_effect_sha256 += replacement",
    ),
)
def test_helper_runtime_surface_cannot_be_deleted_or_augmented(extra_source: str) -> None:
    checks = _helper_checks(f"{_HELPER_SOURCE}\n{extra_source}\n")

    assert checks["no-helper-module-delete-or-augassign"] is False


def test_helper_rejects_uninventoryed_top_level_executable_statements() -> None:
    checks = _helper_checks(f"{_HELPER_SOURCE}\nwhile False:\n    pass\n")

    assert checks["closed-helper-top-level-statement-surface"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "dict.update(CANDIDATES_BY_ID, {'x': None})",
        "dict.__init__(CANDIDATES_BY_ID)",
        "list.__setitem__(records, 0, None)",
        "object.__setattr__(record, 'value', None)",
    ),
)
def test_builtin_mutation_descriptors_are_forbidden(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["no-forbidden-qualified-call"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "type.__new__(type, 'ReturnedResultProjection', (), {})",
        "type.__call__(type, 'ReturnedResultProjection', (), {})",
    ),
)
def test_type_descriptors_cannot_construct_dynamic_classes(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["no-dynamic-indirection"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "CANDIDATES_BY_ID['x'] = None",
        "del CANDIDATES_BY_ID['x']",
        "CANDIDATES_BY_ID |= {}",
        "(CANDIDATES_BY_ID['x'], other) = (None, None)",
        "ArmAction.NEW_ATTRIBUTE = None",
        "cast(object, CANDIDATES_BY_ID)['x'] = None",
    ),
)
def test_direct_registry_mutations_are_rejected(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["no-dynamic-indirection"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "def mutate(records: object) -> None:\n    records.clear()",
        "def invoke(fn=ArmAction.some_capability) -> None:\n    fn()",
    ),
)
def test_new_unresolved_calls_fail_the_exact_returned_call_surface(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["exact-unresolved-call-surface"] is False


@pytest.mark.parametrize(
    ("insertion", "intended_check"),
    (
        (
            "    @hashlib.sha256\n    def nested() -> None:\n        pass\n\n",
            "closed-helper-implicit-execution-surface",
        ),
        (
            "    references = (hashlib.sha256, protocol_hash)\n\n",
            "exact-helper-hash-callable-reference-surface",
        ),
        (
            "    min((b'extra',), key=hashlib.__dict__['sha256'])\n\n",
            "exact-helper-hash-callable-reference-surface",
        ),
        (
            "    min(expected_effects, key=raw_effect_sha256)\n\n",
            "exact-helper-internal-call-and-reference-sites",
        ),
        (
            "    with context:\n        pass\n\n",
            "closed-helper-implicit-execution-surface",
        ),
    ),
)
def test_helper_implicit_calls_and_unused_hash_references_fail_closed(
    insertion: str,
    intended_check: str,
) -> None:
    changed = _HELPER_SOURCE.replace(
        "    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        f"{insertion}    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:",
        1,
    )

    assert _helper_checks(changed)[intended_check] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "@CANDIDATES_BY_ID.clear\ndef harmless() -> None:\n    pass",
        "with context:\n    pass",
    ),
)
def test_returned_run_implicit_capability_surfaces_are_closed(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["closed-implicit-execution-surface"] is False


def test_returned_run_rejects_uninventoryed_top_level_executable_statements() -> None:
    checks = _returned_checks("while False:\n    pass")

    assert checks["closed-top-level-statement-surface"] is False


def test_authorized_function_namespace_cannot_supply_a_hidden_callback() -> None:
    checks = _returned_checks(
        "min(('pyproject.toml',), key=protocol_hash.__globals__['__builtins__']['open'])"
    )

    assert checks["no-dynamic-indirection"] is False


@pytest.mark.parametrize(
    "extra_source",
    (
        "min((record,), key=object.__getattribute__)",
        "min(('prompt',), key=input)",
    ),
)
def test_reflective_and_io_builtin_callbacks_are_denied(extra_source: str) -> None:
    checks = _returned_checks(extra_source)

    assert checks["no-forbidden-qualified-call"] is False


@pytest.mark.parametrize(
    ("source", "intended_check"),
    (
        (
            "a = b\nb = a",
            "no-alias-cycle",
        ),
        (
            "dynamic = getattr(CANDIDATES_BY_ID, 'update')\ndynamic({})",
            "no-dynamic-indirection",
        ),
        (
            "globals()['ReturnedResultProjection'] = ReturnedRunProjection",
            "no-dynamic-indirection",
        ),
        (
            "ReturnedResultProjection = type('ReturnedResultProjection', (), {})",
            "no-dynamic-indirection",
        ),
        (
            "def construct_dynamic_class() -> type:\n"
            "    return type(*('ReturnedResultProjection', (), {}))",
            "no-dynamic-indirection",
        ),
        (
            "def _identity(value: object) -> object:\n"
            "    return value\n"
            "_MISSING_CONTEXT = _identity(ReturnedRunProjection)",
            "no-dynamic-indirection",
        ),
        (
            "def __dir__() -> list[str]:\n    return ['ReturnedResultProjection']",
            "no-module-dynamic-hooks",
        ),
    ),
)
def test_dynamic_indirection_and_alias_cycles_fail_closed(
    source: str,
    intended_check: str,
) -> None:
    checks = _returned_checks(source)

    assert checks[intended_check] is False


def test_relative_multi_import_and_nested_aliases_have_absolute_call_origins() -> None:
    source = (
        "from .broader_runner import ArmAction, run_arm as validate\n"
        "import subprocess as process\n"
        "def nested() -> None:\n"
        "    first = validate\n"
        "    second = first\n"
        "    second()\n"
        "    launch = process.run\n"
        "    launch(())\n"
    )
    analysis = architecture.analyze_qualified_symbols(source)
    import_origins = {
        (binding.name, origin) for binding in analysis.imports for origin in binding.origins
    }
    call_targets = {target for call in analysis.calls for target in call.targets}

    assert (
        "validate",
        "research_decision_engine.benchmarks.broader_runner.run_arm",
    ) in import_origins
    assert (
        "ArmAction",
        "research_decision_engine.benchmarks.broader_runner.ArmAction",
    ) in import_origins
    assert "research_decision_engine.benchmarks.broader_runner.run_arm" in call_targets
    assert "subprocess.run" in call_targets


def test_current_sources_pass_the_full_alias_aware_closed_surfaces() -> None:
    returned_analysis = architecture.analyze_qualified_symbols(_RETURNED_SOURCE)
    helper_analysis = architecture.analyze_qualified_symbols(
        _HELPER_SOURCE,
        module_name=architecture.CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
    )

    assert all(
        passed for _name, passed in architecture.returned_run_architecture_checks(_RETURNED_SOURCE)
    )
    assert all(
        passed
        for _name, passed in architecture.selector_replay_helper_architecture_checks(_HELPER_SOURCE)
    )
    assert architecture.top_level_class_names(_RETURNED_SOURCE) == set(
        architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES
    )
    assert len(architecture.top_level_class_names(_RETURNED_SOURCE)) == 34
    assert not returned_analysis.findings
    assert not helper_analysis.findings
    assert len(helper_analysis.imports) == 20
    assert len([binding for binding in helper_analysis.bindings if binding.top_level]) == 21
