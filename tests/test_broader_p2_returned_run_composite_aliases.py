"""Composite-provenance adversarial tests for the returned-run architecture guard."""

from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent, indent
from typing import Literal, NamedTuple

import pytest

from tests import p2_returned_run_architecture_guard as architecture

_ROOT = Path(__file__).resolve().parents[1]
_RETURNED_PATH = _ROOT / "research_decision_engine" / "benchmarks" / "broader_returned_run.py"
_HELPER_PATH = (
    _ROOT / "research_decision_engine" / "benchmarks" / "broader_calibration_selector_replay.py"
)
_RETURNED_SOURCE = _RETURNED_PATH.read_text(encoding="utf-8")
_HELPER_SOURCE = _HELPER_PATH.read_text(encoding="utf-8")

_FAIL_SIGNATURE = "def _fail(category: ValidationCategory, path: str, detail: str) -> Never:"
_FAIL_ANCHOR = f"{_FAIL_SIGNATURE}\n    code = ("

_PROTECTED_REGISTRY_ORIGIN = "research_decision_engine.benchmarks.broader_worlds.CANDIDATES_BY_ID"
_PROTECTED_CLASS_ORIGIN = "research_decision_engine.benchmarks.broader_runner.ArmAction"
_FORBIDDEN_WORKLOAD_ORIGIN = "research_decision_engine.benchmarks.broader_runner.run_arm"
_RETURNED_PROJECTION_ORIGIN = (
    "research_decision_engine.benchmarks.broader_returned_run.ReturnedRunProjection"
)


class _MaliciousCase(NamedTuple):
    identifier: str
    placement: Literal["function", "module"]
    snippet: str
    finding_code: str
    finding_symbol: str
    failed_check: str
    call_spelling: str | None = None
    call_target: str | None = None
    additional_findings: tuple[tuple[str, str], ...] = ()
    additional_calls: tuple[tuple[str, str], ...] = ()
    additional_references: tuple[tuple[str, str], ...] = ()
    exact_call_targets: bool = False


class _BenignCase(NamedTuple):
    identifier: str
    snippet: str


class _WriteMaliciousCase(NamedTuple):
    identifier: str
    snippet: str
    finding_code: str
    finding_symbol: str
    failed_check: str
    expected_calls: tuple[tuple[str, str], ...] = ()
    expected_bindings: tuple[tuple[str, str], ...] = ()
    expected_findings: tuple[tuple[str, str], ...] = ()
    expected_sensitive_calls: tuple[tuple[str, str], ...] = ()


def _inject_into_fail(snippet: str) -> str:
    assert _RETURNED_SOURCE.count(_FAIL_ANCHOR) == 1
    body = indent(dedent(snippet).strip(), "    ")
    replacement = f"{_FAIL_SIGNATURE}\n{body}\n    code = ("
    return _RETURNED_SOURCE.replace(_FAIL_ANCHOR, replacement, 1)


def _append_at_module_scope(snippet: str) -> str:
    return f"{_RETURNED_SOURCE}\n\n{dedent(snippet).strip()}\n"


def _source_for_case(case: _MaliciousCase) -> str:
    if case.placement == "function":
        return _inject_into_fail(case.snippet)
    return _append_at_module_scope(case.snippet)


def _failed_returned_checks(
    source: str,
    analysis: architecture.QualifiedSymbolAnalysis,
) -> set[str]:
    return {
        name
        for name, passed in architecture.returned_run_architecture_checks(
            source,
            analysis=analysis,
        )
        if not passed
    }


def _assert_finding(
    analysis: architecture.QualifiedSymbolAnalysis,
    *,
    code: str,
    symbol: str,
) -> None:
    assert any(
        finding.code == code and symbol in finding.symbol for finding in analysis.findings
    ), (code, symbol, analysis.findings)


_MALICIOUS_CASES = (
    _MaliciousCase(
        "m02-tuple-negative-index-clear",
        "function",
        """
        holders = (object(), CANDIDATES_BY_ID)
        holders[-1].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        "holders[-1].clear",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
    ),
    _MaliciousCase(
        "m03-nested-tuple-static-slice-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        nested = ((forbidden_workload,),)
        selected = nested[0][0:1]
        selected[0]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "selected[0]",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        exact_call_targets=True,
    ),
    _MaliciousCase(
        "m04-tuple-concatenation-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = (abs,) + (forbidden_workload,)
        calls[1]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "calls[1]",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        exact_call_targets=True,
    ),
    _MaliciousCase(
        "m05-conditional-dynamic-slice-and-index-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = (abs, forbidden_workload) if category else (forbidden_workload, abs)
        selected = calls[path:detail]
        selected[category]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "selected[category]",
        _FORBIDDEN_WORKLOAD_ORIGIN,
    ),
    _MaliciousCase(
        "m06-starred-tuple-through-alias-update",
        "function",
        """
        holders = (*[CANDIDATES_BY_ID],)
        alias = holders
        alias[0].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        "alias[0].update",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
    ),
    _MaliciousCase(
        "m07-list-concatenation-direct-index-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = [abs] + [forbidden_workload]
        calls[1]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "calls[1]",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        exact_call_targets=True,
    ),
    _MaliciousCase(
        "m08-nested-list-clear",
        "function",
        """
        holders = [[CANDIDATES_BY_ID]]
        holders[0][0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        "holders[0][0].clear",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
    ),
    _MaliciousCase(
        "m09-list-alias-two-hop-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = [forbidden_workload]
        values = calls
        invoke = values[0]
        second = invoke
        second()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "second",
        _FORBIDDEN_WORKLOAD_ORIGIN,
    ),
    _MaliciousCase(
        "m10-list-unknown-index-update",
        "function",
        """
        holders = [{}, CANDIDATES_BY_ID]
        holders[category].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        "holders[category].update",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
    ),
    _MaliciousCase(
        "m11-list-retrieved-append-receiver",
        "function",
        """
        holders = [CANDIDATES_BY_ID]
        holders[0].append(object())
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.append",
        "no-forbidden-qualified-call",
        "holders[0].append",
        f"{_PROTECTED_REGISTRY_ORIGIN}.append",
    ),
    _MaliciousCase(
        "m12-mapping-string-key-update",
        "function",
        """
        values = {"registry": CANDIDATES_BY_ID}
        values["registry"].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        "values['registry'].update",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
    ),
    _MaliciousCase(
        "m13-mapping-numeric-key-collision-subscript-assignment",
        "function",
        """
        values = {-0.0: {}, 0: CANDIDATES_BY_ID}
        values[-0.0]["x"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m14-nested-mapping-clear",
        "function",
        """
        nested = {"registry": (CANDIDATES_BY_ID,)}
        nested["registry"][0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        "nested['registry'][0].clear",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
    ),
    _MaliciousCase(
        "m15-mapping-unknown-key-update",
        "function",
        """
        values = {"safe": {}, "registry": CANDIDATES_BY_ID}
        values[category].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        "values[category].update",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
    ),
    _MaliciousCase(
        "m16-tuple-numeric-key-collision-through-alias-delete",
        "function",
        """
        values = {(-0.0,): {}, (0.0,): CANDIDATES_BY_ID}
        alias = values
        del alias[(-0.0,)]["x"]
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m17-mapping-callable-by-key",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = {"run": forbidden_workload}
        invoke = calls["run"]
        invoke()
        callbacks = (forbidden_workload,)
        min((1,), key=callbacks[0])
        min((1,), key=detail[0])
        min((1,), key=detail.callback)
        callback = detail[0]
        min((1,), key=callback)
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "invoke",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        exact_call_targets=True,
        additional_findings=(
            ("unresolved-sensitive-provenance", "callback:detail[0]"),
            ("unresolved-sensitive-provenance", "callback:detail.callback"),
            ("unresolved-sensitive-provenance", "callback:callback"),
        ),
        additional_references=(("callbacks[0]", _FORBIDDEN_WORKLOAD_ORIGIN),),
    ),
    _MaliciousCase(
        "m18-single-element-destructuring-mutation",
        "function",
        """
        (registry,) = (CANDIDATES_BY_ID,)
        registry["x"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m19-multiple-target-destructuring-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        safe, invoke = (abs, forbidden_workload)
        invoke()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "invoke",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        exact_call_targets=True,
    ),
    _MaliciousCase(
        "m20-nested-destructuring-update",
        "function",
        """
        safe, (registry,) = (0, (CANDIDATES_BY_ID,))
        registry.update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        "registry.update",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
    ),
    _MaliciousCase(
        "m21-starred-tail-clear",
        "function",
        """
        head, *tail = (0, CANDIDATES_BY_ID)
        tail[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        "tail[0].clear",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
    ),
    _MaliciousCase(
        "m22-unknown-length-destructuring-sensitive-use",
        "function",
        """
        head, *tail = detail
        head.clear()
        """,
        "unresolved-sensitive-provenance",
        "call:head.clear",
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m23-local-helper-direct-return-call",
        "function",
        """
        from .broader_runner import run_arm as forbidden_workload
        def get_call():
            return forbidden_workload
        get_call()()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        "get_call()",
        _FORBIDDEN_WORKLOAD_ORIGIN,
    ),
    _MaliciousCase(
        "m24-helper-starred-copy-before-benign-redefinition",
        "function",
        """
        from .broader_runner import run_arm as parameter_workload
        def get_holder():
            return (CANDIDATES_BY_ID, detail)
        holders = (*get_holder(),)
        holders[0]["protected"] = None
        holders[1]["unknown"] = None
        def get_holder():
            return ({}, {})
        def get_conditional_registry():
            return CANDIDATES_BY_ID
        if False:
            def get_conditional_registry():
                return {}
        conditional_registry = get_conditional_registry()
        conditional_registry.update({})
        def late_lookup():
            return {}
        def wrapper():
            return late_lookup()
        def late_lookup():
            return CANDIDATES_BY_ID
        late_registry = wrapper()
        late_registry.clear()
        if category:
            def conditional_call():
                return abs
        conditional_call()(-1)
        before_call()(-1)
        def before_call():
            return abs
        def inner_future_call():
            future_call()(-1)
        inner_future_call()
        def future_call():
            return abs
        def mutate_parameter(value):
            parameter_holders = list((value,))
            parameter_holders[0]["x"] = None
        mutate_parameter(CANDIDATES_BY_ID)
        named_holder = detail.registry
        named_holder["x"] = None
        async def awaited_holder():
            return detail
        async def consume_awaited_holder():
            awaited = await awaited_holder()
            awaited["x"] = None
        def mutate_default(default_registry=(CANDIDATES_BY_ID,)[0]):
            default_registry["x"] = None
        mutate_default()
        def mutate_kw_default(*, kw_default_registry=(CANDIDATES_BY_ID,)[0]):
            kw_default_registry["x"] = None
        mutate_kw_default()
        def mutate_argument(argument_registry):
            argument_registry["x"] = None
        mutate_argument((CANDIDATES_BY_ID,)[0])
        def mutate_keyword(keyword_registry):
            keyword_registry["x"] = None
        mutate_keyword(keyword_registry=(CANDIDATES_BY_ID,)[0])
        def invoke_argument(callable_argument):
            callable_argument()
        invoke_argument((parameter_workload,)[0])
        def forwarded_mutation_sink(forwarded_registry):
            forwarded_registry["x"] = None
        def forward_mutation(forward_input):
            forwarded_mutation_sink(forward_input)
        forward_mutation(CANDIDATES_BY_ID)
        def forwarded_callable_sink(forwarded_callback):
            forwarded_callback()
        def forward_callable(callback_input):
            forwarded_callable_sink(callback_input)
        forward_callable(parameter_workload)
        class LocalOpen:
            def open():
                return abs
            def exploit():
                calls = (open,)
                calls[0]("path")
        LocalOpen.exploit()
        class ClassBodyLookup:
            body_calls = (open,)
            body_calls[0]("path")
            def open():
                return abs
        class ConditionalClassBodyLookup:
            if False:
                def open():
                    return abs
            conditional_calls = (open,)
            conditional_calls[0]("path")
        class OuterClassLookup:
            open = abs
            class InnerClassLookup:
                def exploit():
                    nested_class_calls = (open,)
                    nested_class_calls[0]("path")
        OuterClassLookup.InnerClassLookup.exploit()
        class PatternHolder:
            __match_args__ = ("value",)
        dict = PatternHolder
        def consume_shadowed_pattern(subject):
            match subject:
                case dict(shadow_registry):
                    shadow_registry["x"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
        additional_findings=(
            ("unresolved-sensitive-provenance", "mutation:holders[1]"),
            ("forbidden-qualified-call", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
            ("forbidden-qualified-call", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("unresolved-sensitive-provenance", "call:conditional_call()"),
            ("unresolved-sensitive-provenance", "call:before_call()"),
            ("unresolved-sensitive-provenance", "call:future_call()"),
            ("unresolved-sensitive-provenance", "mutation:parameter_holders[0]"),
            ("unresolved-sensitive-provenance", "mutation:named_holder['x']"),
            ("unresolved-sensitive-provenance", "mutation:awaited['x']"),
            ("qualified-state-mutation", _PROTECTED_REGISTRY_ORIGIN),
            ("unresolved-sensitive-provenance", "mutation:shadow_registry['x']"),
            ("forbidden-qualified-call", "builtins.open"),
            ("forbidden-qualified-call", _FORBIDDEN_WORKLOAD_ORIGIN),
        ),
        additional_calls=(
            ("conditional_registry.update", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
            ("late_registry.clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("calls[0]", "builtins.open"),
            ("body_calls[0]", "builtins.open"),
            ("conditional_calls[0]", "builtins.open"),
            ("nested_class_calls[0]", "builtins.open"),
            ("callable_argument", _FORBIDDEN_WORKLOAD_ORIGIN),
            ("forwarded_callback", _FORBIDDEN_WORKLOAD_ORIGIN),
        ),
        additional_references=(
            ("default_registry", _PROTECTED_REGISTRY_ORIGIN),
            ("kw_default_registry", _PROTECTED_REGISTRY_ORIGIN),
            ("argument_registry", _PROTECTED_REGISTRY_ORIGIN),
            ("keyword_registry", _PROTECTED_REGISTRY_ORIGIN),
            ("forward_input", _PROTECTED_REGISTRY_ORIGIN),
            ("forwarded_registry", _PROTECTED_REGISTRY_ORIGIN),
            ("callback_input", _FORBIDDEN_WORKLOAD_ORIGIN),
        ),
    ),
    _MaliciousCase(
        "m25-composite-class-attribute-assignment",
        "function",
        """
        holders = (ArmAction,)
        holders[0].NEW_ATTRIBUTE = None
        """,
        "qualified-state-mutation",
        _PROTECTED_CLASS_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m26-composite-registry-augmented-assignment",
        "function",
        """
        holders = (CANDIDATES_BY_ID,)
        holders[0] |= {}
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m27-composite-add-receiver",
        "function",
        """
        holders = (CANDIDATES_BY_ID,)
        holders[0].add(None)
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.add",
        "no-forbidden-qualified-call",
        "holders[0].add",
        f"{_PROTECTED_REGISTRY_ORIGIN}.add",
    ),
    _MaliciousCase(
        "m28-composite-dunder-setitem-receiver",
        "function",
        """
        holders = (CANDIDATES_BY_ID,)
        holders[0].__setitem__("x", None)
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.__setitem__",
        "no-forbidden-qualified-call",
        "holders[0].__setitem__",
        f"{_PROTECTED_REGISTRY_ORIGIN}.__setitem__",
    ),
    _MaliciousCase(
        "m29-loop-match-and-comprehension-scope-provenance",
        "function",
        """
        for registry in (CANDIDATES_BY_ID,):
            registry.clear()
        match (CANDIDATES_BY_ID,):
            case (matched,):
                matched.update({})
        for iterated in iter((CANDIDATES_BY_ID,)):
            iterated.popitem()
        match CANDIDATES_BY_ID:
            case dict(class_matched):
                class_matched.setdefault("x", None)
        def mutate_unresolved_iteration(values):
            for indirect in values:
                indirect["x"] = None
        mutate_unresolved_iteration((CANDIDATES_BY_ID,))
        async def mutate_async_iteration(values):
            async for async_registry in values:
                async_registry["x"] = None
        class Wrapper:
            pass
        match CANDIDATES_BY_ID:
            case Wrapper(general_capture):
                general_capture["x"] = None
        _ = [None for CANDIDATES_BY_ID in ()]
        CANDIDATES_BY_ID["forbidden"] = None
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        "registry.clear",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        additional_findings=(
            ("forbidden-qualified-call", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
            ("forbidden-qualified-call", f"{_PROTECTED_REGISTRY_ORIGIN}.popitem"),
            ("forbidden-qualified-call", f"{_PROTECTED_REGISTRY_ORIGIN}.setdefault"),
            ("qualified-state-mutation", _PROTECTED_REGISTRY_ORIGIN),
            ("unresolved-sensitive-provenance", "mutation:indirect['x']"),
            ("unresolved-sensitive-provenance", "mutation:async_registry['x']"),
            ("unresolved-sensitive-provenance", "mutation:general_capture['x']"),
        ),
        additional_calls=(
            ("matched.update", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
            ("iterated.popitem", f"{_PROTECTED_REGISTRY_ORIGIN}.popitem"),
            ("class_matched.setdefault", f"{_PROTECTED_REGISTRY_ORIGIN}.setdefault"),
        ),
    ),
    _MaliciousCase(
        "m30-comprehension-walrus-provenance-escapes-to-enclosing-scope",
        "function",
        """
        _ = [(registry := CANDIDATES_BY_ID) for item in (None,)]
        registry["forbidden"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m32-forbidden-parameter-binding",
        "function",
        """
        def local(ReturnedRunReader: object) -> None:
            pass
        """,
        "forbidden-later-stage-binding",
        "ReturnedRunReader",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m33-container-derived-walrus-binding",
        "function",
        """
        if (CalibrationSelectionProjection := (ReturnedRunProjection,)[0]):
            pass
        """,
        "forbidden-later-stage-binding",
        "CalibrationSelectionProjection",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m34-static-forbidden-export",
        "module",
        '__all__ = ("WorkerResultOrderProjection",)',
        "unresolved-sensitive-provenance",
        "export:WorkerResultOrderProjection",
        "no-forbidden-later-stage-export",
    ),
    _MaliciousCase(
        "m35-module-getattr-composite-result",
        "module",
        """
        def __getattr__(name: str) -> object:
            if name == "ExecutorAttestationProjection":
                values = ({"projection": ReturnedRunProjection},)
                return values[0]["projection"]
            raise AttributeError(name)
        """,
        "dynamic-module-hook",
        "__getattr__",
        "no-module-dynamic-hooks",
    ),
    _MaliciousCase(
        "m36-forbidden-import-alias",
        "function",
        """
        from .broader_returned_run import (
            ReturnedRunProjection as ReturnedResultsProjection,
        )
        """,
        "forbidden-later-stage-binding",
        "ReturnedResultsProjection",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m37-forbidden-local-function-binding",
        "function",
        """
        def ExecutionIdentityProjection() -> None:
            pass
        """,
        "forbidden-later-stage-binding",
        "ExecutionIdentityProjection",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m38-forbidden-local-class-binding",
        "function",
        """
        class ReturnedRunPersistence:
            pass
        """,
        "forbidden-later-stage-binding",
        "ReturnedRunPersistence",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m39-forbidden-comprehension-target",
        "function",
        "_ = [None for WorkerIdentityProjection in ()]",
        "forbidden-later-stage-binding",
        "WorkerIdentityProjection",
        "no-forbidden-later-stage-binding",
    ),
    _MaliciousCase(
        "m40-unresolved-helper-result-used-as-callable",
        "function",
        """
        def get_lambda():
            return lambda: None
        get_lambda()()
        def get_comprehension():
            return [item for item in detail]
        get_comprehension()[0].clear()
        def get_formatted():
            return f"{detail}"
        get_formatted().clear()
        """,
        "unresolved-sensitive-provenance",
        "call:get_lambda()",
        "no-dynamic-indirection",
        additional_findings=(
            ("unresolved-sensitive-provenance", "mutation:get_comprehension()[0]"),
            ("unresolved-sensitive-provenance", "mutation:get_formatted()"),
        ),
    ),
    _MaliciousCase(
        "m41-getattr-result-used-as-mutation-receiver",
        "function",
        """
        holder = getattr(CANDIDATES_BY_ID, path)
        holder.clear()
        """,
        "unresolved-sensitive-provenance",
        "call:holder.clear",
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m42-sensitive-helper-composite-exact-retrieval-mutation",
        "function",
        """
        def get_holder():
            return (CANDIDATES_BY_ID, detail)

        protected = get_holder()[0]
        unresolved = get_holder()[1]
        protected["forbidden"] = None
        unresolved["forbidden"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
        additional_findings=(
            ("unresolved-sensitive-provenance", "mutation:unresolved['forbidden']"),
        ),
    ),
    _MaliciousCase(
        "m43-unresolved-parameter-used-as-mutation-target",
        "function",
        """
        def mutate_unknown(unresolved_registry):
            unresolved_registry["forbidden"] = None
        """,
        "unresolved-sensitive-provenance",
        "mutation:unresolved_registry['forbidden']",
        "no-dynamic-indirection",
    ),
    _MaliciousCase(
        "m44-unresolved-parameter-used-as-callable",
        "function",
        """
        def invoke_unknown(unresolved_callback):
            unresolved_callback()
        """,
        "unresolved-sensitive-provenance",
        "call:unresolved_callback",
        "no-dynamic-indirection",
    ),
)

_BENIGN_CASES = (
    _BenignCase(
        "b01-ordinary-composites-and-forbidden-looking-strings",
        """
        tuple_data = (1, "ReturnedResultProjection", None)
        list_data = [True, 3.5, b"data"]
        mapping_data = {"name": "ExecutionIdentityProjection", 7: (1, 2)}
        set_data = {1, 2, 3}
        """,
    ),
    _BenignCase(
        "b02-benign-local-collection-mutation",
        """
        local_mapping = {"x": 1}
        local_mapping["y"] = 2
        local_mapping.update({"z": 3})
        local_list = [1]
        local_list.append(2)
        """,
    ),
    _BenignCase(
        "b03-safe-helper-sibling-after-redefinition",
        """
        def get_helpers():
            return (detail, abs)
        def get_helpers():
            return (abs, detail)
        result = get_helpers()[0](-1)
        class ClassBodyHelper:
            open = abs
            calls = (open,)
            class_result = calls[0](-1)
        """,
    ),
    _BenignCase(
        "b04-nested-benign-structure-mutation",
        """
        nested = ({"items": [{}]},)
        nested[0]["items"][0].clear()
        """,
    ),
    _BenignCase(
        "b05-benign-nested-and-starred-destructuring",
        """
        first, (second, third) = (1, (2, 3))
        head, *tail = (4, 5, 6)
        """,
    ),
    _BenignCase(
        "b06-unused-unknown-index-result",
        """
        values = (1, 2, 3)
        selected = values[category]
        retained = selected
        """,
    ),
)

_WRITE_MALICIOUS_CASES = (
    _WriteMaliciousCase(
        "w01-list-known-index-write",
        """
        holders = [{}]
        holders[0] = CANDIDATES_BY_ID
        holders[0]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w02-list-negative-index-write",
        """
        holders = [{}, {}]
        holders[-1] = CANDIDATES_BY_ID
        holders[-1].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders[-1].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w03-list-unknown-index-write",
        """
        holders = [{}, {}]
        holders[category] = CANDIDATES_BY_ID
        holders[0]["review"] = None
        out_of_range = []
        out_of_range[3] = CANDIDATES_BY_ID
        out_of_range[0].clear()
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
        expected_sensitive_calls=(
            ("out_of_range[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
        ),
    ),
    _WriteMaliciousCase(
        "w04-list-nested-write",
        """
        nested = [[{}]]
        nested[0][0] = CANDIDATES_BY_ID
        nested[0][0].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.update",
        "no-forbidden-qualified-call",
        expected_calls=(("nested[0][0].update", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),),
    ),
    _WriteMaliciousCase(
        "w05-list-alias-write-original-read",
        """
        holders = [{}]
        alias = holders
        alias[0] = CANDIDATES_BY_ID
        holders[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w06-list-original-write-two-hop-alias-read",
        """
        holders = [{}]
        alias = holders
        alias2 = alias
        holders[0] = CANDIDATES_BY_ID
        alias2[0]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w07-mapping-known-string-key-write",
        """
        holders = {"target": {}}
        holders["target"] = CANDIDATES_BY_ID
        holders["target"]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w08-mapping-known-integer-key-write",
        """
        holders = {7: {}}
        holders[7] = CANDIDATES_BY_ID
        holders[7].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders[7].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w09-mapping-unknown-key-write",
        """
        holders = {"first": {}, "second": {}}
        holders[path] = CANDIDATES_BY_ID
        holders["first"]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w10-mapping-nested-write",
        """
        nested = {"outer": {"target": {}}}
        nested["outer"]["target"] = CANDIDATES_BY_ID
        nested["outer"]["target"].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("nested['outer']['target'].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
        ),
    ),
    _WriteMaliciousCase(
        "w11-mapping-alias-write-original-read",
        """
        holders = {"target": {}}
        alias = holders
        alias["target"] = CANDIDATES_BY_ID
        holders["target"]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w12-mapping-original-write-alias-read",
        """
        holders = {"target": {}}
        alias = holders
        holders["target"] = CANDIDATES_BY_ID
        alias["target"].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("alias['target'].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w13-list-append-write-then-call",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = []
        calls.append(forbidden_workload)
        calls[0]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        expected_calls=(("calls[0]", _FORBIDDEN_WORKLOAD_ORIGIN),),
    ),
    _WriteMaliciousCase(
        "w14-list-extend-write",
        """
        holders = []
        holders.extend((CANDIDATES_BY_ID,))
        holders[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w15-list-insert-write",
        """
        holders = [{}]
        holders.insert(0, CANDIDATES_BY_ID)
        holders[0]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w16-list-dunder-and-slice-writes",
        """
        holders = [{}]
        holders.__setitem__(0, CANDIDATES_BY_ID)
        holders[0].clear()
        sliced = [{}, {}]
        sliced[0:1] = [CANDIDATES_BY_ID]
        sliced[0].update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("sliced[0].update", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
        ),
    ),
    _WriteMaliciousCase(
        "w17-dict-update-mapping-and-pairs-write-then-call",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = {}
        calls.update({"run": forbidden_workload})
        calls["run"]()
        pair_calls = {}
        pair_calls.update((("run", forbidden_workload),))
        pair_calls["run"]()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        expected_calls=(
            ("calls['run']", _FORBIDDEN_WORKLOAD_ORIGIN),
            ("pair_calls['run']", _FORBIDDEN_WORKLOAD_ORIGIN),
        ),
    ),
    _WriteMaliciousCase(
        "w18-dict-setdefault-write",
        """
        holders = {}
        holders.setdefault("target", CANDIDATES_BY_ID)
        holders["target"]["review"] = None
        uncertain = {}
        uncertain.update(detail)
        uncertain[path]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
        expected_findings=(("unresolved-sensitive-provenance", "mutation:uncertain[path]"),),
    ),
    _WriteMaliciousCase(
        "w19-dict-dunder-setitem-write",
        """
        holders = {"target": {}}
        holders.__setitem__("target", CANDIDATES_BY_ID)
        holders["target"].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders['target'].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w20-removals-make-later-sensitive-reads-unresolved",
        """
        cleared = [CANDIDATES_BY_ID]
        cleared.clear()
        cleared[0]["review"] = None
        popped = [CANDIDATES_BY_ID]
        popped.pop()
        popped[0]["review"] = None
        removed = [CANDIDATES_BY_ID]
        removed.remove(CANDIDATES_BY_ID)
        removed[0]["review"] = None
        cleared_mapping = {"target": CANDIDATES_BY_ID}
        cleared_mapping.clear()
        cleared_mapping["target"]["review"] = None
        popped_mapping = {"target": CANDIDATES_BY_ID}
        popped_mapping.pop("target")
        popped_mapping["target"]["review"] = None
        popitem_mapping = {"target": CANDIDATES_BY_ID}
        popitem_mapping.popitem()
        popitem_mapping["target"]["review"] = None
        dunder_deleted_mapping = {"target": CANDIDATES_BY_ID}
        dunder_deleted_mapping.__delitem__("target")
        dunder_deleted_mapping["target"]["review"] = None
        deleted_mapping = {"target": CANDIDATES_BY_ID}
        del deleted_mapping["target"]
        deleted_mapping["target"]["review"] = None
        unknown_pop_mapping = {"target": CANDIDATES_BY_ID}
        unknown_pop_mapping.pop(path)
        unknown_pop_mapping["target"]["review"] = None
        """,
        "unresolved-sensitive-provenance",
        "mutation:cleared[0]",
        "no-dynamic-indirection",
        expected_findings=(
            ("unresolved-sensitive-provenance", "mutation:popped[0]"),
            ("unresolved-sensitive-provenance", "mutation:removed[0]"),
            (
                "unresolved-sensitive-provenance",
                "mutation:cleared_mapping['target']",
            ),
            (
                "unresolved-sensitive-provenance",
                "mutation:popped_mapping['target']",
            ),
            (
                "unresolved-sensitive-provenance",
                "mutation:popitem_mapping['target']",
            ),
            (
                "unresolved-sensitive-provenance",
                "mutation:dunder_deleted_mapping['target']",
            ),
            (
                "unresolved-sensitive-provenance",
                "mutation:deleted_mapping['target']",
            ),
            ("qualified-state-mutation", _PROTECTED_REGISTRY_ORIGIN),
        ),
    ),
    _WriteMaliciousCase(
        "w21-protected-write-in-one-if-branch",
        """
        holders = [{}]
        if category:
            holders[0] = CANDIDATES_BY_ID
        holders[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w22-branch-different-locations-and-try-join",
        """
        holders = [{}, {}]
        if category:
            holders[0] = CANDIDATES_BY_ID
        else:
            holders[1] = CANDIDATES_BY_ID
        holders[category].clear()
        try_holders = [{}]
        try:
            try_holders[0] = CANDIDATES_BY_ID
        except ValueError:
            try_holders[0] = {}
        finally:
            marker = None
        try_holders[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("holders[category].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("try_holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
        ),
    ),
    _WriteMaliciousCase(
        "w23-conditional-alias-match-and-loop-joins",
        """
        holders = [{}]
        alias = holders
        if category:
            alias[0] = {}
        else:
            holders[0] = CANDIDATES_BY_ID
        alias[0].clear()
        matched = [{}]
        match category:
            case ValidationCategory.STRUCTURAL:
                matched[0] = CANDIDATES_BY_ID
            case _:
                matched[0] = {}
        matched[0].clear()
        looped = [{}]
        for _item in (0,):
            looped[0] = CANDIDATES_BY_ID
        looped[0].clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("alias[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("matched[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("looped[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
        ),
    ),
    _WriteMaliciousCase(
        "w24-retained-value-alias-survives-benign-overwrite",
        """
        holders = [CANDIDATES_BY_ID]
        registry = holders[0]
        holders[0] = {}
        registry["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
    ),
    _WriteMaliciousCase(
        "w25-retained-element-survives-container-rebind",
        """
        holders = [CANDIDATES_BY_ID]
        alias = holders
        alias = []
        holders[0].clear()
        mapping = {"target": CANDIDATES_BY_ID}
        registry = mapping["target"]
        mapping = {"target": {}}
        registry.update({})
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("registry.update", f"{_PROTECTED_REGISTRY_ORIGIN}.update"),
        ),
    ),
    _WriteMaliciousCase(
        "w26-nested-retained-value-alias",
        """
        nested = [{"items": [CANDIDATES_BY_ID]}]
        registry = nested[0]["items"][0]
        nested[0]["items"][0] = {}
        registry.clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(("registry.clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),),
    ),
    _WriteMaliciousCase(
        "w27-list-write-then-two-hop-call",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = [lambda: None]
        calls[0] = forbidden_workload
        invoke = calls[0]
        invoke2 = invoke
        invoke2()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        expected_calls=(("invoke2", _FORBIDDEN_WORKLOAD_ORIGIN),),
    ),
    _WriteMaliciousCase(
        "w28-mapping-write-then-aliased-call",
        """
        from .broader_runner import run_arm as forbidden_workload
        calls = {"run": lambda: None}
        calls["run"] = forbidden_workload
        invoke = calls["run"]
        invoke()
        """,
        "forbidden-qualified-call",
        _FORBIDDEN_WORKLOAD_ORIGIN,
        "no-forbidden-qualified-call",
        expected_calls=(("invoke", _FORBIDDEN_WORKLOAD_ORIGIN),),
    ),
    _WriteMaliciousCase(
        "w29-list-mapping-and-branch-derived-forbidden-bindings",
        """
        list_types = [object]
        list_types[0] = ReturnedRunProjection
        ReturnedResultProjection = list_types[0]
        mapping_types = {"value": object}
        mapping_types["value"] = ReturnedRunProjection
        ExecutionInstanceProjection = mapping_types["value"]
        branch_types = [object]
        if category:
            branch_types[0] = ReturnedRunProjection
        else:
            branch_types[0] = object
        CalibrationSelectionProjection = branch_types[0]
        """,
        "forbidden-later-stage-binding",
        "ReturnedResultProjection",
        "no-forbidden-later-stage-binding",
        expected_bindings=(
            ("ReturnedResultProjection", _RETURNED_PROJECTION_ORIGIN),
            ("ExecutionInstanceProjection", _RETURNED_PROJECTION_ORIGIN),
            ("CalibrationSelectionProjection", _RETURNED_PROJECTION_ORIGIN),
        ),
    ),
    _WriteMaliciousCase(
        "w30-helper-direct-nested-and-binding-writes",
        """
        def install(values):
            values[0] = CANDIDATES_BY_ID
        holders = [{}]
        install(holders)
        holders[0].clear()
        def install_nested(values):
            values[0]["items"][0] = CANDIDATES_BY_ID
        nested = [{"items": [{}]}]
        install_nested(nested)
        nested[0]["items"][0].clear()
        def install_type(values):
            values[0] = ReturnedRunProjection
        types = [object]
        install_type(types)
        WorkerIdentityProjection = types[0]
        def assign(values, item):
            values[0] = item
        def install_and_return(values, item):
            assign(values, item)
            return values[0]
        transitive = [{}]
        transitive_registry = install_and_return(transitive, CANDIDATES_BY_ID)
        transitive_registry.clear()
        def install_default(values, item=CANDIDATES_BY_ID):
            values[0] = item
            return values[0]
        defaulted = [{}]
        default_registry = install_default(defaulted)
        default_registry.clear()
        """,
        "forbidden-qualified-call",
        f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
        "no-forbidden-qualified-call",
        expected_calls=(
            ("holders[0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("nested[0]['items'][0].clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("transitive_registry.clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
            ("default_registry.clear", f"{_PROTECTED_REGISTRY_ORIGIN}.clear"),
        ),
        expected_bindings=(("WorkerIdentityProjection", _RETURNED_PROJECTION_ORIGIN),),
    ),
    _WriteMaliciousCase(
        "w31-unresolved-and-recursive-helper-effects-fail-closed",
        """
        def indirect_install(values, writer):
            writer(values)
        holders = [{}]
        indirect_install(holders, detail)
        holders[0].clear()
        def recursive_install(values):
            recursive_install(values)
        recursive_holders = [{}]
        recursive_install(recursive_holders)
        recursive_holders[0].clear()
        """,
        "unresolved-sensitive-provenance",
        "call:holders[0].clear",
        "no-dynamic-indirection",
        expected_findings=(("unresolved-sensitive-provenance", "call:recursive_holders[0].clear"),),
    ),
    _WriteMaliciousCase(
        "w32-augmented-assignment-and-nested-delete",
        """
        augmented = [CANDIDATES_BY_ID]
        augmented[0] += {}
        augmented[0]["review"] = None
        nested = {"outer": {"target": CANDIDATES_BY_ID}}
        del nested["outer"]["target"]
        nested["outer"]["target"]["review"] = None
        """,
        "qualified-state-mutation",
        _PROTECTED_REGISTRY_ORIGIN,
        "no-dynamic-indirection",
        expected_findings=(
            (
                "unresolved-sensitive-provenance",
                "mutation:nested['outer']['target']",
            ),
        ),
    ),
)

_WRITE_BENIGN_CASES = (
    _BenignCase(
        "wb01-benign-list-element-replacement",
        """
        values = [{}]
        values[0] = {"review": None}
        values[0]["extra"] = 1
        """,
    ),
    _BenignCase(
        "wb02-benign-mapping-entry-replacement",
        """
        values = {"target": {}}
        values["target"] = {"review": None}
        values["target"]["extra"] = 1
        """,
    ),
    _BenignCase(
        "wb03-benign-append-and-update",
        """
        values = []
        values.append({})
        values[0]["review"] = None
        mapping = {}
        mapping.update({"target": {}})
        mapping["target"]["review"] = None
        """,
    ),
    _BenignCase(
        "wb04-exact-protected-to-benign-strong-update",
        """
        holders = [CANDIDATES_BY_ID]
        holders[0] = {}
        holders[0]["review"] = None
        """,
    ),
    _BenignCase(
        "wb05-alias-rebinds-to-new-benign-container",
        """
        holders = [CANDIDATES_BY_ID]
        alias = holders
        alias = []
        alias.append({})
        alias[0]["review"] = None
        """,
    ),
    _BenignCase(
        "wb06-helper-proven-benign-strong-update",
        """
        def install(values):
            values[0] = {}
        holders = [CANDIDATES_BY_ID]
        install(holders)
        holders[0]["review"] = None
        def observe(values):
            return None
        observed = [{}]
        observe(observed)
        observed[0]["review"] = None
        """,
    ),
    _BenignCase(
        "wb07-ordinary-local-container-mutators",
        """
        values = [{}]
        values.extend(({},))
        values.insert(0, {})
        values.__setitem__(0, {})
        values[0:1] = [{}]
        values.remove({})
        mapping = {}
        mapping.setdefault("first", {})
        mapping.__setitem__("second", {})
        mapping.update((("third", {}),))
        mapping.pop("third")
        mapping.__delitem__("second")
        """,
    ),
    _BenignCase(
        "wb08-every-branch-strongly-writes-same-benign-value",
        """
        holders = [CANDIDATES_BY_ID]
        if category:
            holders[0] = {}
        else:
            holders[0] = {}
        holders[0]["review"] = None
        """,
    ),
)

assert len(_MALICIOUS_CASES) == 42
assert len(_BENIGN_CASES) == 6
assert len(_WRITE_MALICIOUS_CASES) == 32
assert len(_WRITE_BENIGN_CASES) == 8


def test_composite_alias_provenance_reaches_protected_mutation() -> None:
    source = _inject_into_fail(
        """
        holders = (CANDIDATES_BY_ID,)
        registry = holders[0]
        registry["forbidden"] = object()
        def recursive_holder():
            return recursive_registry
        recursive_registry = recursive_holder()
        recursive_registry["cycle"] = object()
        """
    )

    analysis = architecture.analyze_qualified_symbols(source)
    _assert_finding(
        analysis,
        code="qualified-state-mutation",
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )
    _assert_finding(
        analysis,
        code="alias-cycle",
        symbol="recursive_registry",
    )
    failed_checks = _failed_returned_checks(source, analysis)
    assert failed_checks
    assert "no-dynamic-indirection" in failed_checks


def test_composite_alias_cannot_create_local_later_stage_projection_binding() -> None:
    source = _inject_into_fail(
        """
        ReturnedResultProjection = ReturnedRunProjection
        values = (ReturnedRunProjection,)
        ExecutionInstanceProjection = values[0]
        """
    )

    analysis = architecture.analyze_qualified_symbols(source)
    _assert_finding(
        analysis,
        code="forbidden-later-stage-binding",
        symbol="ReturnedResultProjection",
    )
    _assert_finding(
        analysis,
        code="forbidden-later-stage-binding",
        symbol="ExecutionInstanceProjection",
    )
    failed_checks = _failed_returned_checks(source, analysis)
    assert failed_checks
    assert "no-forbidden-later-stage-binding" in failed_checks


def test_duplicate_approved_unresolved_mutation_fails_exact_surface() -> None:
    anchor = "    cache[projection.lineage] = lineage\n"
    assert _RETURNED_SOURCE.count(anchor) == 1
    source = _RETURNED_SOURCE.replace(anchor, f"{anchor}{anchor}", 1)

    analysis = architecture.analyze_qualified_symbols(source)
    matching_mutations = tuple(
        mutation
        for mutation in analysis.unresolved_mutations
        if mutation.scope == ("_construct_returned_run_s3",)
        and mutation.spelling == "cache[projection.lineage]"
    )
    assert len(matching_mutations) == 2
    assert "exact-unresolved-mutation-surface" in _failed_returned_checks(source, analysis)


def test_list_element_write_updates_protected_provenance() -> None:
    source = _inject_into_fail(
        """
        holders = [{}]
        holders[0] = CANDIDATES_BY_ID
        holders[0]["review"] = None
        """
    )

    analysis = architecture.analyze_qualified_symbols(source)
    failed_checks = _failed_returned_checks(source, analysis)

    assert analysis.findings
    assert failed_checks
    _assert_finding(
        analysis,
        code="qualified-state-mutation",
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )
    assert "no-dynamic-indirection" in failed_checks


def test_mapping_entry_write_updates_protected_provenance() -> None:
    source = _inject_into_fail(
        """
        holders = {"target": {}}
        holders["target"] = CANDIDATES_BY_ID
        holders["target"].clear()
        """
    )

    analysis = architecture.analyze_qualified_symbols(source)
    failed_checks = _failed_returned_checks(source, analysis)

    assert analysis.findings
    assert failed_checks
    _assert_finding(
        analysis,
        code="forbidden-qualified-call",
        symbol=f"{_PROTECTED_REGISTRY_ORIGIN}.clear",
    )
    assert "no-forbidden-qualified-call" in failed_checks
    assert any(
        call.spelling == "holders['target'].clear"
        and call.targets == {f"{_PROTECTED_REGISTRY_ORIGIN}.clear"}
        for call in analysis.calls
    )


def test_aliased_container_write_updates_all_alias_views() -> None:
    source = _inject_into_fail(
        """
        holders = [{}]
        alias = holders
        alias[0] = CANDIDATES_BY_ID
        holders[0]["review"] = None
        """
    )

    analysis = architecture.analyze_qualified_symbols(source)
    failed_checks = _failed_returned_checks(source, analysis)

    assert analysis.findings
    assert failed_checks
    _assert_finding(
        analysis,
        code="qualified-state-mutation",
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )
    assert "no-dynamic-indirection" in failed_checks


@pytest.mark.parametrize("case", _WRITE_MALICIOUS_CASES, ids=lambda case: case.identifier)
def test_malicious_composite_write_flow_is_rejected(case: _WriteMaliciousCase) -> None:
    source = _inject_into_fail(case.snippet)
    analysis = architecture.analyze_qualified_symbols(source)

    _assert_finding(
        analysis,
        code=case.finding_code,
        symbol=case.finding_symbol,
    )
    for finding_code, finding_symbol in case.expected_findings:
        _assert_finding(
            analysis,
            code=finding_code,
            symbol=finding_symbol,
        )
    assert case.failed_check in _failed_returned_checks(source, analysis)
    for call_spelling, call_target in case.expected_calls:
        assert any(
            call.spelling == call_spelling and call_target in call.targets
            for call in analysis.calls
        ), (call_spelling, call_target, analysis.calls)
    for call_spelling, call_target in case.expected_sensitive_calls:
        matching_calls = tuple(call for call in analysis.calls if call.spelling == call_spelling)
        assert matching_calls, (call_spelling, analysis.calls)
        assert any(
            call.sensitive_unresolved or call_target in call.targets for call in matching_calls
        ), (call_spelling, call_target, matching_calls)
    for binding_name, binding_origin in case.expected_bindings:
        _assert_finding(
            analysis,
            code="forbidden-later-stage-binding",
            symbol=binding_name,
        )
        assert any(
            binding.name == binding_name and binding_origin in binding.origins
            for binding in analysis.binding_events
        ), (binding_name, binding_origin, analysis.binding_events)


@pytest.mark.parametrize("case", _WRITE_BENIGN_CASES, ids=lambda case: case.identifier)
def test_benign_composite_write_flow_is_allowed(case: _BenignCase) -> None:
    source = _inject_into_fail(case.snippet)
    analysis = architecture.analyze_qualified_symbols(source)
    checks = dict(architecture.returned_run_architecture_checks(source, analysis=analysis))

    assert not analysis.findings
    assert checks["no-dynamic-indirection"] is True
    assert checks["no-forbidden-qualified-call"] is True
    assert checks["no-forbidden-later-stage-binding"] is True


@pytest.mark.parametrize("case", _MALICIOUS_CASES, ids=lambda case: case.identifier)
def test_malicious_composite_alias_is_rejected(case: _MaliciousCase) -> None:
    source = _source_for_case(case)
    analysis = architecture.analyze_qualified_symbols(source)

    _assert_finding(
        analysis,
        code=case.finding_code,
        symbol=case.finding_symbol,
    )
    for finding_code, finding_symbol in case.additional_findings:
        _assert_finding(
            analysis,
            code=finding_code,
            symbol=finding_symbol,
        )
    assert case.failed_check in _failed_returned_checks(source, analysis)
    if case.call_spelling is not None:
        assert case.call_target is not None
        matching_calls = tuple(
            call for call in analysis.calls if call.spelling == case.call_spelling
        )
        assert any(case.call_target in call.targets for call in matching_calls), (
            case.call_spelling,
            case.call_target,
            analysis.calls,
        )
        if case.exact_call_targets:
            assert all(call.targets == {case.call_target} for call in matching_calls), (
                case.call_spelling,
                case.call_target,
                matching_calls,
            )
    for call_spelling, call_target in case.additional_calls:
        assert any(
            call.spelling == call_spelling and call_target in call.targets
            for call in analysis.calls
        ), (call_spelling, call_target, analysis.calls)
    for reference_spelling, reference_target in case.additional_references:
        assert any(
            reference.spelling == reference_spelling and reference_target in reference.targets
            for reference in analysis.references
        ), (reference_spelling, reference_target, analysis.references)


@pytest.mark.parametrize("case", _BENIGN_CASES, ids=lambda case: case.identifier)
def test_benign_composite_alias_is_allowed(case: _BenignCase) -> None:
    source = _inject_into_fail(case.snippet)
    analysis = architecture.analyze_qualified_symbols(source)
    checks = dict(architecture.returned_run_architecture_checks(source, analysis=analysis))

    assert not analysis.findings
    assert checks["no-dynamic-indirection"] is True
    assert checks["no-forbidden-qualified-call"] is True
    assert checks["no-forbidden-later-stage-binding"] is True


def test_real_returned_run_source_remains_allowed() -> None:
    analysis = architecture.analyze_qualified_symbols(_RETURNED_SOURCE)

    assert not analysis.findings
    assert all(
        passed
        for _name, passed in architecture.returned_run_architecture_checks(
            _RETURNED_SOURCE,
            analysis=analysis,
        )
    )
    with pytest.raises(ValueError, match="does not match"):
        architecture.returned_run_architecture_checks(
            f"{_RETURNED_SOURCE}\n",
            analysis=analysis,
        )


def test_real_selector_replay_helper_source_remains_allowed() -> None:
    analysis = architecture.analyze_qualified_symbols(
        _HELPER_SOURCE,
        module_name=architecture.CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
    )

    assert not analysis.findings
    assert all(
        passed
        for _name, passed in architecture.selector_replay_helper_architecture_checks(
            _HELPER_SOURCE,
            analysis=analysis,
        )
    )
    with pytest.raises(ValueError, match="does not match"):
        architecture.selector_replay_helper_architecture_checks(
            f"{_HELPER_SOURCE}\n",
            analysis=analysis,
        )


def _analyze_full_union_snippet(
    snippet: str,
) -> tuple[str, architecture.QualifiedSymbolAnalysis, dict[str, bool]]:
    source = _inject_into_fail(snippet)
    analysis = architecture.analyze_qualified_symbols(source)
    checks = dict(architecture.returned_run_architecture_checks(source, analysis=analysis))
    return source, analysis, checks


def _assert_protected_union_mutation(
    source: str,
    analysis: architecture.QualifiedSymbolAnalysis,
    checks: dict[str, bool],
    marker: str,
) -> None:
    _assert_finding_at_marker(
        analysis,
        source,
        marker,
        codes=frozenset({"qualified-state-mutation"}),
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )
    assert checks["no-dynamic-indirection"] is False


def _assert_clean_union_analysis(
    analysis: architecture.QualifiedSymbolAnalysis,
    checks: dict[str, bool],
) -> None:
    assert not analysis.findings
    assert checks["no-dynamic-indirection"] is True
    assert checks["no-forbidden-qualified-call"] is True
    assert checks["no-forbidden-later-stage-binding"] is True


def test_dict_ior_level_a_exact_retained_alias_p0_is_rejected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        holders = {}
        alias = holders
        holders |= {"target": CANDIDATES_BY_ID}
        alias.setdefault("target", {})
        alias["target"]["review"] = None
        """
    )

    _assert_protected_union_mutation(source, analysis, checks, 'alias["target"]["review"]')


def test_dict_ior_level_a_subscript_held_inner_dictionary_is_rejected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        outer = {"holder": {}}
        alias = outer["holder"]
        outer["holder"] |= {"target": CANDIDATES_BY_ID}
        alias["target"]["review"] = None
        """
    )

    _assert_protected_union_mutation(source, analysis, checks, 'alias["target"]["review"]')


def test_dict_ior_level_a_exact_protected_to_benign_update_is_allowed() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        holders = {"target": CANDIDATES_BY_ID}
        holders |= {"target": {}}
        holders["target"]["review"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_dict_ior_level_a_retained_old_value_alias_is_rejected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        holders = {"target": CANDIDATES_BY_ID}
        registry = holders["target"]
        holders |= {"target": {}}
        registry["review"] = None
        """
    )

    _assert_protected_union_mutation(source, analysis, checks, 'registry["review"]')


def test_dict_ior_level_a_benign_exact_union_is_allowed() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        holders = {}
        alias = holders
        holders |= {"target": {}}
        alias["target"]["review"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_dict_ior_level_a_non_in_place_union_does_not_mutate_left_alias() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        left = {}
        right = {"target": CANDIDATES_BY_ID}
        alias = left
        left = left | right
        alias["review"] = None

        other = {}
        other_alias = other
        other = {"target": CANDIDATES_BY_ID} | other
        other_alias["review"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_dict_ior_level_a_branch_protected_possibility_is_rejected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        holders = {}
        if category:
            holders |= {"target": CANDIDATES_BY_ID}
        else:
            holders |= {"target": {}}
        holders["target"]["review"] = None
        """
    )

    _assert_protected_union_mutation(
        source,
        analysis,
        checks,
        'holders["target"]["review"]',
    )


def _unique_source_line(source: str, marker: str) -> int:
    matches = tuple(
        lineno for lineno, line in enumerate(source.splitlines(), start=1) if marker in line
    )
    assert len(matches) == 1, (marker, matches)
    return matches[0]


def _assert_finding_at_marker(
    analysis: architecture.QualifiedSymbolAnalysis,
    source: str,
    marker: str,
    *,
    codes: frozenset[str],
    symbol: str | None = None,
) -> None:
    lineno = _unique_source_line(source, marker)
    assert any(
        finding.lineno == lineno
        and finding.code in codes
        and (symbol is None or symbol in finding.symbol)
        for finding in analysis.findings
    ), (marker, lineno, codes, symbol, analysis.findings)


def test_dict_ior_level_b_alias_and_nested_malicious_batch() -> None:
    source = dedent(
        """
        from research_decision_engine.benchmarks.broader_returned_run import ReturnedRunProjection
        from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID

        def case_two_hop_alias():
            holders = {}
            first = holders
            second = first
            holders |= {"target": CANDIDATES_BY_ID}
            second["target"]["case_two_hop_alias"] = None

        def case_union_through_alias():
            holders = {}
            alias = holders
            alias |= {"target": CANDIDATES_BY_ID}
            holders["target"]["case_union_through_alias"] = None

        def case_union_through_original():
            holders = {}
            alias = holders
            holders |= {"target": CANDIDATES_BY_ID}
            alias["target"]["case_union_through_original"] = None

        def case_protected_replacement():
            holders = {"target": {}}
            alias = holders
            holders |= {"target": CANDIDATES_BY_ID}
            alias["target"]["case_protected_replacement"] = None

        def case_bounded_nested_inner():
            outer = {"first": {"second": {}}}
            alias = outer["first"]["second"]
            outer["first"]["second"] |= {"target": CANDIDATES_BY_ID}
            alias["target"]["case_bounded_nested_inner"] = None
        """
    )
    analysis = architecture.analyze_qualified_symbols(source)

    for marker in (
        'second["target"]["case_two_hop_alias"]',
        'holders["target"]["case_union_through_alias"]',
        'alias["target"]["case_union_through_original"]',
        'alias["target"]["case_protected_replacement"]',
        'alias["target"]["case_bounded_nested_inner"]',
    ):
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"qualified-state-mutation"}),
            symbol=_PROTECTED_REGISTRY_ORIGIN,
        )


def test_dict_ior_level_b_uncertainty_capability_and_loop_malicious_batch() -> None:
    source = dedent(
        """
        from research_decision_engine.benchmarks.broader_returned_run import ReturnedRunProjection
        from research_decision_engine.benchmarks.broader_runner import run_arm
        from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID

        def case_unknown_rhs(updates):
            holders = {"known": {}}
            holders |= updates
            holders["target"]["case_unknown_rhs"] = None

        def case_unknown_rhs_unpack(key):
            updates = {}
            updates[key] = CANDIDATES_BY_ID
            holders = {"target": {}}
            holders |= {**updates}
            holders["target"]["case_unknown_rhs_unpack"] = None

        def case_unknown_rhs_dict_copy(key):
            updates = {}
            updates[key] = CANDIDATES_BY_ID
            holders = {"target": {}}
            holders |= dict(updates)
            holders["target"]["case_unknown_rhs_dict_copy"] = None

        def case_setdefault_after_possible_delete(flag):
            holders = {}
            holders |= {"target": {}}
            if flag:
                del holders["target"]
            selected = holders.setdefault("target", CANDIDATES_BY_ID)
            selected["case_setdefault_after_possible_delete"] = None

        def case_uncertain_receiver(flag):
            first = {}
            second = {}
            holders = first if flag else second
            holders |= {"target": CANDIDATES_BY_ID}
            first["target"]["case_uncertain_receiver"] = None

        def case_union_forbidden_callable():
            calls = {}
            calls |= {"invoke": run_arm}
            calls["invoke"]()

        def case_union_later_binding():
            holders = {}
            holders |= {"projection": ReturnedRunProjection}
            ExecutionInstanceProjection = holders["projection"]
            return ExecutionInstanceProjection

        def case_loop_fixed_point():
            holders = {}
            for _index in (0, 1):
                holders |= {"target": CANDIDATES_BY_ID}
            holders["target"]["case_loop_fixed_point"] = None
        """
    )
    analysis = architecture.analyze_qualified_symbols(source)

    _assert_finding_at_marker(
        analysis,
        source,
        'holders["target"]["case_unknown_rhs"]',
        codes=frozenset({"unresolved-sensitive-provenance"}),
    )
    for marker in (
        'holders["target"]["case_unknown_rhs_unpack"]',
        'holders["target"]["case_unknown_rhs_dict_copy"]',
        'selected["case_setdefault_after_possible_delete"]',
    ):
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"qualified-state-mutation", "unresolved-sensitive-provenance"}),
            symbol=_PROTECTED_REGISTRY_ORIGIN,
        )
    _assert_finding_at_marker(
        analysis,
        source,
        'first["target"]["case_uncertain_receiver"]',
        codes=frozenset({"qualified-state-mutation", "unresolved-sensitive-provenance"}),
    )
    _assert_finding_at_marker(
        analysis,
        source,
        'calls["invoke"]()',
        codes=frozenset({"forbidden-qualified-call"}),
        symbol=_FORBIDDEN_WORKLOAD_ORIGIN,
    )
    _assert_finding_at_marker(
        analysis,
        source,
        "ExecutionInstanceProjection =",
        codes=frozenset({"forbidden-later-stage-binding"}),
        symbol="ExecutionInstanceProjection",
    )
    _assert_finding_at_marker(
        analysis,
        source,
        'holders["target"]["case_loop_fixed_point"]',
        codes=frozenset({"qualified-state-mutation"}),
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )
    assert any(
        call.scope == ("case_union_forbidden_callable",)
        and call.spelling == "calls['invoke']"
        and _FORBIDDEN_WORKLOAD_ORIGIN in call.targets
        for call in analysis.calls
    )
    assert any(
        binding.scope == ("case_union_later_binding",)
        and binding.name == "ExecutionInstanceProjection"
        and _RETURNED_PROJECTION_ORIGIN in binding.origins
        for binding in analysis.binding_events
    )


def test_dict_ior_level_b_operator_classification_batch() -> None:
    source = dedent(
        """
        from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID

        def case_direct_dict_ior():
            holders = {}
            dict.__ior__(holders, {"target": CANDIDATES_BY_ID})
            holders["target"]["case_direct_dict_ior"] = None

        def case_aliased_dict_ior():
            holders = {}
            operation = dict.__ior__
            operation(holders, {"target": CANDIDATES_BY_ID})
            holders["target"]["case_aliased_dict_ior"] = None

        def case_bound_dict_ior():
            holders = {}
            operation = holders.__ior__
            operation({"target": CANDIDATES_BY_ID})
            holders["target"]["case_bound_dict_ior"] = None

        def case_set_ior():
            values = set()
            values |= {ReturnedRunProjection}
            selected = next(iter(values))
            selected.case_set_ior = None

        def case_list_iadd():
            values = []
            alias = values
            values += [CANDIDATES_BY_ID]
            alias[0]["case_list_iadd"] = None

        class CustomIor:
            def __ior__(self, other):
                return self

            def __setitem__(self, key, value):
                return None

        def case_user_defined_ior():
            value = CustomIor()
            value |= CANDIDATES_BY_ID
            value["case_user_defined_ior"] = None
        """
    )
    analysis = architecture.analyze_qualified_symbols(source)

    for marker in (
        "dict.__ior__(holders",
        "operation(holders",
    ):
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"forbidden-qualified-call"}),
            symbol="builtins.dict.__ior__",
        )
    for marker in (
        'holders["target"]["case_direct_dict_ior"]',
        'holders["target"]["case_aliased_dict_ior"]',
        'holders["target"]["case_bound_dict_ior"]',
        "selected.case_set_ior",
        'alias[0]["case_list_iadd"]',
        'value["case_user_defined_ior"]',
    ):
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"qualified-state-mutation", "unresolved-sensitive-provenance"}),
        )
    assert any(
        call.scope == ("case_bound_dict_ior",)
        and call.spelling == "operation"
        and call.modeled_bound_mutator
        for call in analysis.calls
    )


def test_dict_ior_level_b_benign_batch() -> None:
    source = dedent(
        """
        from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID

        def case_existing_setdefault():
            mapping = {"target": {}}
            selected = mapping.setdefault("target", CANDIDATES_BY_ID)
            selected["case_existing_setdefault"] = None

        def case_absent_setdefault():
            mapping = {}
            default = {}
            selected = mapping.setdefault("target", default)
            selected["case_absent_setdefault"] = None
            mapping["target"]["installed"] = None

        def case_benign_alias_observation():
            mapping = {}
            alias = mapping
            mapping |= {"target": {}}
            alias["target"]["case_benign_alias_observation"] = None

        def case_alias_rebind():
            mapping = {"target": CANDIDATES_BY_ID}
            alias = mapping
            alias = {}
            alias["case_alias_rebind"] = None

        def case_all_benign_branches(flag):
            mapping = {}
            if flag:
                mapping |= {"target": {}}
            else:
                mapping |= {"target": {}}
            mapping["target"]["case_all_benign_branches"] = None

        def case_ordinary_local_dictionary():
            mapping = {}
            mapping.update({"first": {}})
            mapping.setdefault("second", {})
            mapping["first"]["case_ordinary_local_dictionary"] = None

        def case_multi_receiver_existing_setdefault(flag):
            first = {"target": {}}
            second = {"target": {}}
            mapping = first if flag else second
            selected = mapping.setdefault("target", CANDIDATES_BY_ID)
            selected["case_multi_receiver_existing_setdefault"] = None
        """
    )
    analysis = architecture.analyze_qualified_symbols(source)

    assert not analysis.findings
    expected_functions = {
        "case_existing_setdefault",
        "case_absent_setdefault",
        "case_benign_alias_observation",
        "case_alias_rebind",
        "case_all_benign_branches",
        "case_ordinary_local_dictionary",
        "case_multi_receiver_existing_setdefault",
    }
    assert expected_functions <= {
        binding.name
        for binding in analysis.bindings
        if binding.top_level and binding.kind == "function"
    }


def _pure_flow_analyzer() -> architecture._QualifiedSymbolAnalyzer:
    analyzer = object.__new__(architecture._QualifiedSymbolAnalyzer)
    analyzer.flow_mutated_locations = set()
    return analyzer


def _test_static_key(value: str) -> architecture._StaticKey:
    return architecture._StaticKey("str", repr(value))


def _test_origin_value(origin: str) -> architecture.ResolvedValue:
    return architecture._direct_value(frozenset({origin}))


def _test_dictionary_state(
    location: architecture._AbstractLocation,
    entries: tuple[tuple[architecture._StaticKey, architecture.ResolvedValue], ...],
    *,
    unknown: architecture.ResolvedValue | None = None,
    uncertain: bool = False,
    masks: frozenset[architecture._StaticKey] = frozenset(),
) -> architecture._FlowState:
    container = architecture._AbstractContainerState(
        "dict",
        mapping_entries=tuple(sorted(entries)),
        unknown_value=architecture.ResolvedValue() if unknown is None else unknown,
        uncertain=uncertain,
        masked_mapping_keys=masks,
    )
    return architecture._FlowState(store=architecture._AbstractStore(((location, container),)))


def _test_dictionary_reference(
    location: architecture._AbstractLocation,
) -> architecture.ResolvedValue:
    return architecture.ResolvedValue(locations=frozenset({location}))


def _test_setdefault(
    analyzer: architecture._QualifiedSymbolAnalyzer,
    state: architecture._FlowState,
    receiver: architecture.ResolvedValue,
    default: architecture.ResolvedValue,
) -> tuple[architecture.ResolvedValue, architecture._FlowState]:
    call = ast.parse('mapping.setdefault("target", default)', mode="eval").body
    assert isinstance(call, ast.Call)
    materialized = analyzer._materialize_flow_value(receiver, state.store)
    return analyzer._flow_apply_mutator(
        call,
        materialized,
        (architecture.ResolvedValue(static_key=_test_static_key("target")), default),
        (),
        architecture._unknown_value(sensitive=True),
        state,
    )


def test_dict_ior_level_c_exact_merge_masks_replaced_key() -> None:
    analyzer = _pure_flow_analyzer()
    location = architecture._AbstractLocation(("level_c",), "dict", 1, 0)
    target = _test_static_key("target")
    untouched = _test_static_key("untouched")
    added = _test_static_key("added")
    stale = _test_origin_value("test.stale")
    replacement = _test_origin_value("test.replacement")
    new_value = _test_origin_value("test.new")
    untouched_value = _test_origin_value("test.untouched")
    state = _test_dictionary_state(
        location,
        ((target, _test_origin_value("test.old")), (untouched, untouched_value)),
        unknown=stale,
        uncertain=True,
    )
    receiver = analyzer._materialize_flow_value(
        _test_dictionary_reference(location),
        state.store,
    )
    right = architecture._mapping_value(((target, replacement), (added, new_value)))

    result, updated = analyzer._flow_inplace_mapping_union(receiver, right, state)
    container = dict(updated.store.entries)[location]
    entries = dict(container.mapping_entries or ())

    assert result.locations == {location}
    assert entries[target] == replacement
    assert entries[untouched] == untouched_value
    assert entries[added] == new_value
    assert {target, added} <= container.masked_mapping_keys
    selected = analyzer._flow_subscript_value(
        analyzer._materialize_flow_value(result, updated.store),
        ast.Constant(value="target"),
    )
    assert "test.replacement" in selected.direct_origins
    assert "test.stale" not in selected.aggregate_origins


def test_dict_ior_level_c_unknown_and_unresolved_rhs_widen() -> None:
    analyzer = _pure_flow_analyzer()
    for lineno, right in (
        (
            2,
            architecture._unknown_value(
                frozenset({_PROTECTED_REGISTRY_ORIGIN}),
                sensitive=True,
            ),
        ),
        (3, _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)),
    ):
        location = architecture._AbstractLocation(("level_c",), "dict", lineno, 0)
        known = _test_static_key("known")
        state = _test_dictionary_state(
            location,
            ((known, _test_origin_value("test.known")),),
            masks=frozenset({known}),
        )
        receiver = analyzer._materialize_flow_value(
            _test_dictionary_reference(location),
            state.store,
        )

        result, updated = analyzer._flow_inplace_mapping_union(receiver, right, state)
        container = dict(updated.store.entries)[location]

        assert known in dict(container.mapping_entries or ())
        assert container.uncertain
        assert not container.masked_mapping_keys
        assert _PROTECTED_REGISTRY_ORIGIN in container.unknown_value.aggregate_origins
        selected = analyzer._flow_subscript_value(
            analyzer._materialize_flow_value(result, updated.store),
            ast.Constant(value="target"),
        )
        assert selected.sensitive_unknown
        assert _PROTECTED_REGISTRY_ORIGIN in selected.aggregate_origins


def test_dict_ior_level_c_multiple_receiver_locations_update_weakly() -> None:
    analyzer = _pure_flow_analyzer()
    first = architecture._AbstractLocation(("level_c",), "dict", 4, 0)
    second = architecture._AbstractLocation(("level_c",), "dict", 5, 0)
    target = _test_static_key("target")
    first_old = _test_origin_value("test.first_old")
    second_old = _test_origin_value("test.second_old")
    rhs = _test_origin_value("test.rhs")
    first_container = architecture._AbstractContainerState(
        "dict",
        mapping_entries=((target, first_old),),
    )
    second_container = architecture._AbstractContainerState(
        "dict",
        mapping_entries=((target, second_old),),
    )
    state = architecture._FlowState(
        store=architecture._AbstractStore(
            tuple(sorted(((first, first_container), (second, second_container))))
        )
    )
    receiver = architecture.ResolvedValue(
        locations=frozenset({first, second}),
        location_uncertain=True,
    )
    right = architecture._mapping_value(((target, rhs),))

    result, updated = analyzer._flow_inplace_mapping_union(receiver, right, state)

    assert result.locations == {first, second}
    assert result.location_uncertain
    for location, old_origin in (
        (first, "test.first_old"),
        (second, "test.second_old"),
    ):
        container = dict(updated.store.entries)[location]
        value = dict(container.mapping_entries or ())[target]
        assert container.uncertain
        assert old_origin in value.aggregate_origins
        assert "test.rhs" in value.aggregate_origins


def test_dict_ior_level_c_setdefault_present_absent_and_uncertain() -> None:
    analyzer = _pure_flow_analyzer()
    target = _test_static_key("target")
    default = _test_origin_value("test.default")

    present_location = architecture._AbstractLocation(("level_c",), "dict", 6, 0)
    protected = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)
    present_state = _test_dictionary_state(
        present_location,
        ((target, protected),),
        masks=frozenset({target}),
    )
    present_result, present_after = _test_setdefault(
        analyzer,
        present_state,
        _test_dictionary_reference(present_location),
        default,
    )
    assert present_after.store is present_state.store
    assert _PROTECTED_REGISTRY_ORIGIN in present_result.direct_origins
    assert "test.default" not in present_result.aggregate_origins

    absent_location = architecture._AbstractLocation(("level_c",), "dict", 7, 0)
    absent_state = _test_dictionary_state(absent_location, ())
    absent_result, absent_after = _test_setdefault(
        analyzer,
        absent_state,
        _test_dictionary_reference(absent_location),
        default,
    )
    assert absent_result == default
    absent_container = dict(absent_after.store.entries)[absent_location]
    assert dict(absent_container.mapping_entries or ())[target] == default

    uncertain_location = architecture._AbstractLocation(("level_c",), "dict", 8, 0)
    uncertain_state = _test_dictionary_state(
        uncertain_location,
        ((target, protected),),
        unknown=architecture._unknown_value(
            frozenset({"test.unknown_entry"}),
            sensitive=True,
        ),
        uncertain=True,
    )
    uncertain_result, uncertain_after = _test_setdefault(
        analyzer,
        uncertain_state,
        _test_dictionary_reference(uncertain_location),
        default,
    )
    assert uncertain_after.store is not uncertain_state.store
    assert _PROTECTED_REGISTRY_ORIGIN in uncertain_result.aggregate_origins
    assert "test.default" in uncertain_result.aggregate_origins
    uncertain_container = dict(uncertain_after.store.entries)[uncertain_location]
    assert uncertain_container.uncertain
    uncertain_reread = analyzer._flow_subscript_value(
        analyzer._materialize_flow_value(
            _test_dictionary_reference(uncertain_location),
            uncertain_after.store,
        ),
        ast.Constant(value="target"),
    )
    assert _PROTECTED_REGISTRY_ORIGIN in uncertain_reread.aggregate_origins
    assert "test.default" in uncertain_reread.aggregate_origins

    optional_location = architecture._AbstractLocation(("level_c",), "dict", 9, 0)
    optional_present = _test_dictionary_state(
        optional_location,
        ((target, _test_origin_value("test.existing")),),
        masks=frozenset({target}),
    )
    optional_deleted = _test_dictionary_state(
        optional_location,
        (),
        masks=frozenset({target}),
    )
    optional_state = analyzer._flow_join((optional_present, optional_deleted))
    optional_container = dict(optional_state.store.entries)[optional_location]
    assert optional_container.uncertain
    assert target not in optional_container.masked_mapping_keys
    optional_result, optional_after = _test_setdefault(
        analyzer,
        optional_state,
        _test_dictionary_reference(optional_location),
        default,
    )
    assert "test.existing" in optional_result.aggregate_origins
    assert "test.default" in optional_result.aggregate_origins
    optional_reread = analyzer._flow_subscript_value(
        analyzer._materialize_flow_value(
            _test_dictionary_reference(optional_location),
            optional_after.store,
        ),
        ast.Constant(value="target"),
    )
    assert "test.existing" in optional_reread.aggregate_origins
    assert "test.default" in optional_reread.aggregate_origins


def test_dict_ior_level_c_location_identity_retained_alias_and_cache_fingerprint() -> None:
    analyzer = _pure_flow_analyzer()
    analyzer._building_composite_flow = False
    analyzer._resolving_flow_snapshot = False
    analyzer.flow_node_values = {}
    analyzer._post_flow_resolution_cache = {}
    analyzer._post_flow_resolution_cache_hits = 0
    analyzer._post_flow_resolution_cache_misses = 0
    location = architecture._AbstractLocation(("level_c",), "dict", 10, 0)
    target = _test_static_key("target")
    protected = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)
    benign = _test_origin_value("test.benign")
    reference = _test_dictionary_reference(location)
    initial = _test_dictionary_state(location, ((target, protected),))._replace(
        bindings=(("mapping", reference),),
    )
    name_node = ast.parse("mapping", mode="eval").body
    assert isinstance(name_node, ast.Name)
    scope = architecture._Scope(("level_c",), None)
    analyzer.flow_write_target_node_ids = {id(name_node)}
    analyzer.flow_node_states = {id(name_node): initial}
    receiver = analyzer._resolve_expression(name_node, scope)
    retained = analyzer._flow_subscript_value(
        receiver,
        ast.Constant(value="target"),
    )
    right = architecture._mapping_value(((target, benign),))

    result, updated = analyzer._flow_inplace_mapping_union(receiver, right, initial)
    analyzer.flow_node_states[id(name_node)] = updated
    post_union = analyzer._resolve_expression(name_node, scope)
    cached_post_union = analyzer._resolve_expression(name_node, scope)
    repeated_receiver = analyzer._materialize_flow_value(result, updated.store)
    repeated_result, repeated = analyzer._flow_inplace_mapping_union(
        repeated_receiver,
        right,
        updated,
    )

    assert result.locations == receiver.locations == {location}
    assert repeated_result.locations == {location}
    assert repeated.store is updated.store
    current = dict(dict(updated.store.entries)[location].mapping_entries or ())[target]
    assert current == benign
    assert _PROTECTED_REGISTRY_ORIGIN in retained.direct_origins
    assert _PROTECTED_REGISTRY_ORIGIN not in current.aggregate_origins
    post_union_value = analyzer._flow_subscript_value(
        post_union,
        ast.Constant(value="target"),
    )
    assert _PROTECTED_REGISTRY_ORIGIN not in post_union_value.aggregate_origins
    assert "test.benign" in post_union_value.aggregate_origins
    assert cached_post_union == post_union
    assert analyzer._post_flow_resolution_cache_misses == 2
    assert analyzer._post_flow_resolution_cache_hits == 1
    before_fingerprint = architecture._flow_store_fingerprint(initial.store)
    after_fingerprint = architecture._flow_store_fingerprint(updated.store)
    assert before_fingerprint != after_fingerprint


def test_ordered_mapping_unpack_uses_last_exact_value() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        protected_part = {"target": CANDIDATES_BY_ID}
        benign_part = {"target": {}}
        rhs = {**protected_part, **benign_part}
        holders = {}
        holders |= rhs
        holders["target"]["ordered_last_exact"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_ordered_mapping_unpack_reverse_order_remains_protected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        benign_part = {"target": {}}
        protected_part = {"target": CANDIDATES_BY_ID}
        rhs = {**benign_part, **protected_part}
        holders = {}
        holders |= rhs
        holders["target"]["ordered_reverse_protected"] = None
        """
    )

    assert analysis.findings
    assert _failed_returned_checks(source, analysis)
    _assert_protected_union_mutation(
        source,
        analysis,
        checks,
        'holders["target"]["ordered_reverse_protected"]',
    )


def test_unknown_unpack_then_exact_key_masks_target_only() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        unknown_mapping = {}
        unknown_mapping[path] = CANDIDATES_BY_ID
        rhs = {
            **unknown_mapping,
            "target": {},
        }
        holders = {}
        holders |= rhs
        holders["target"]["unknown_then_exact_target"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_retained_source_value_alias_remains_protected() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        def case_reverse_unpack():
            benign_part = {"target": {}}
            protected_part = {"target": CANDIDATES_BY_ID}
            rhs = {**benign_part, **protected_part}
            rhs["target"]["case_reverse_unpack"] = None

        def case_reverse_direct():
            rhs = {
                "target": {},
                "target": CANDIDATES_BY_ID,
            }
            rhs["target"]["case_reverse_direct"] = None

        def case_exact_then_protected_unpack():
            protected_part = {"target": CANDIDATES_BY_ID}
            rhs = {"target": {}, **protected_part}
            rhs["target"]["case_exact_then_protected_unpack"] = None

        def case_later_unknown_unpack(key):
            unknown_mapping = {}
            unknown_mapping[key] = CANDIDATES_BY_ID
            rhs = {"target": {}, **unknown_mapping}
            rhs["target"]["case_later_unknown_unpack"] = None

        def case_retained_source_alias():
            protected_part = {"target": CANDIDATES_BY_ID}
            registry = protected_part["target"]
            rhs = {**protected_part, "target": {}}
            registry["case_retained_source_alias"] = None

        def case_source_mapping_preserved():
            protected_part = {"target": CANDIDATES_BY_ID}
            rhs = {**protected_part, "target": {}}
            protected_part["target"]["case_source_mapping_preserved"] = None

        def case_protected_union():
            result = {"target": {}} | {"target": CANDIDATES_BY_ID}
            result["target"]["case_protected_union"] = None

        def case_protected_inplace_union():
            result = {"target": {}}
            result |= {"target": CANDIDATES_BY_ID}
            result["target"]["case_protected_inplace_union"] = None

        def case_protected_update():
            result = {}
            result.update({"target": {}}, target=CANDIDATES_BY_ID)
            result["target"]["case_protected_update"] = None

        def case_protected_constructor():
            result = dict({"target": {}}, target=CANDIDATES_BY_ID)
            result["target"]["case_protected_constructor"] = None

        def case_multiple_unknown_unpacks(first_key, second_key):
            first = {}
            first[first_key] = {}
            second = {}
            second[second_key] = CANDIDATES_BY_ID
            rhs = {"target": {}, **first, **second}
            rhs["target"]["case_multiple_unknown_unpacks"] = None

        def case_unresolved_custom_mapping(custom_mapping):
            rhs = {"target": {}, **custom_mapping}
            rhs["target"]["case_unresolved_custom_mapping"] = None

        def case_multiple_possible_mappings(flag):
            protected_part = {"target": CANDIDATES_BY_ID}
            benign_part = {"target": {}}
            selected = protected_part if flag else benign_part
            rhs = {"target": {}, **selected}
            rhs["target"]["case_multiple_possible_mappings"] = None
        """
    )

    protected_markers = (
        'rhs["target"]["case_reverse_unpack"]',
        'rhs["target"]["case_reverse_direct"]',
        'rhs["target"]["case_exact_then_protected_unpack"]',
        'rhs["target"]["case_later_unknown_unpack"]',
        'registry["case_retained_source_alias"]',
        'protected_part["target"]["case_source_mapping_preserved"]',
        'result["target"]["case_protected_union"]',
        'result["target"]["case_protected_inplace_union"]',
        'result["target"]["case_protected_update"]',
        'result["target"]["case_protected_constructor"]',
        'rhs["target"]["case_multiple_unknown_unpacks"]',
        'rhs["target"]["case_multiple_possible_mappings"]',
    )
    for marker in protected_markers:
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"qualified-state-mutation", "unresolved-sensitive-provenance"}),
            symbol=_PROTECTED_REGISTRY_ORIGIN,
        )
    _assert_finding_at_marker(
        analysis,
        source,
        'rhs["target"]["case_unresolved_custom_mapping"]',
        codes=frozenset({"unresolved-sensitive-provenance"}),
    )
    failed_checks = _failed_returned_checks(source, analysis)
    assert analysis.findings
    assert failed_checks
    assert "no-dynamic-indirection" in failed_checks
    assert checks["no-dynamic-indirection"] is False


def test_direct_duplicate_mapping_key_uses_last_value() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        def case_ordered_known_unpacks():
            protected_part = {"target": CANDIDATES_BY_ID}
            benign_part = {"target": {}}
            rhs = {**protected_part, **benign_part}
            rhs["target"]["case_ordered_known_unpacks"] = None

        def case_direct_duplicate():
            rhs = {
                "target": CANDIDATES_BY_ID,
                "target": {},
            }
            rhs["target"]["case_direct_duplicate"] = None

        def case_unpack_then_exact():
            protected_part = {"target": CANDIDATES_BY_ID}
            rhs = {**protected_part, "target": {}}
            rhs["target"]["case_unpack_then_exact"] = None

        def case_unknown_then_exact(key):
            unknown_mapping = {}
            unknown_mapping[key] = CANDIDATES_BY_ID
            rhs = {**unknown_mapping, "target": {}}
            rhs["target"]["case_unknown_then_exact"] = None

        def case_protected_unknown_benign(key):
            protected_part = {"target": CANDIDATES_BY_ID}
            unknown_mapping = {}
            unknown_mapping[key] = CANDIDATES_BY_ID
            rhs = {**protected_part, **unknown_mapping, "target": {}}
            rhs["target"]["case_protected_unknown_benign"] = None

        def case_benign_union():
            left = {"target": CANDIDATES_BY_ID}
            right = {"target": {}}
            result = left | right
            result["target"]["case_benign_union"] = None

        def case_benign_inplace_union():
            result = {"target": CANDIDATES_BY_ID}
            result |= {"target": {}}
            result["target"]["case_benign_inplace_union"] = None

        def case_benign_update():
            result = {}
            result.update({"target": CANDIDATES_BY_ID}, target={})
            result["target"]["case_benign_update"] = None

        def case_benign_constructor():
            result = dict({"target": CANDIDATES_BY_ID}, target={})
            result["target"]["case_benign_constructor"] = None

        def case_numeric_equivalent_inplace_union():
            rhs = {
                0: CANDIDATES_BY_ID,
                -0.0: {},
            }
            holders = {}
            holders |= rhs
            holders[0]["case_numeric_equivalent_inplace_union"] = None

        def case_bool_integer_equivalent_union():
            rhs = {False: CANDIDATES_BY_ID, 0: {}}
            left = {}
            holders = left | rhs
            holders[False]["case_bool_integer_equivalent_union"] = None

        def case_float_complex_equivalent_unpack():
            rhs = {-0.0: CANDIDATES_BY_ID, -0j: {}}
            holders = {**rhs}
            holders[0j]["case_float_complex_equivalent_unpack"] = None

        def case_tuple_numeric_equivalent_update():
            rhs = {(0.0,): CANDIDATES_BY_ID, (-0.0,): {}}
            holders = {}
            holders.update(rhs)
            holders[(0.0,)]["case_tuple_numeric_equivalent_update"] = None

        def case_nested_tuple_numeric_equivalent_constructor():
            rhs = {((False,),): CANDIDATES_BY_ID, ((0.0,),): {}}
            holders = dict(rhs)
            holders[((0j,),)]["case_nested_tuple_numeric_equivalent_constructor"] = None
        """
    )

    _assert_clean_union_analysis(analysis, checks)


def test_mapping_unpack_then_exact_key_masks_prior_provenance() -> None:
    analyzer = _pure_flow_analyzer()
    target = _test_static_key("target")
    integer = architecture._StaticKey("int", repr(7))
    protected = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)
    benign_location = architecture._AbstractLocation(("level_c",), "dict", 11, 0)
    benign = architecture.ResolvedValue(locations=frozenset({benign_location}))
    unknown = architecture._unknown_value(
        frozenset({_PROTECTED_REGISTRY_ORIGIN}),
        sensitive=True,
    )

    repeated = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        (
            architecture._OrderedMappingWrite(((target, protected),)),
            architecture._OrderedMappingWrite(((target, benign),)),
            architecture._OrderedMappingWrite(((integer, protected), (integer, benign))),
        ),
    )
    repeated_entries = dict(repeated.mapping_entries or ())
    assert repeated_entries[target] == benign
    assert repeated_entries[integer] == benign
    assert {target, integer} <= repeated.masked_mapping_keys
    assert _PROTECTED_REGISTRY_ORIGIN not in repeated_entries[target].aggregate_origins
    assert repeated_entries[target].locations == {benign_location}

    masked = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        (
            architecture._OrderedMappingWrite(unknown_value=unknown),
            architecture._OrderedMappingWrite(((target, benign),)),
        ),
    )
    projected = architecture._resolved_mapping_value(masked)
    selected = analyzer._flow_subscript_value(projected, ast.Constant(value="target"))
    unrelated = analyzer._flow_subscript_value(projected, ast.Constant(value="other"))
    assert target in masked.masked_mapping_keys
    assert _PROTECTED_REGISTRY_ORIGIN in masked.unknown_value.aggregate_origins
    assert _PROTECTED_REGISTRY_ORIGIN not in selected.aggregate_origins
    assert _PROTECTED_REGISTRY_ORIGIN in unrelated.aggregate_origins


def test_exact_key_then_unknown_unpack_restores_uncertainty() -> None:
    analyzer = _pure_flow_analyzer()
    target = _test_static_key("target")
    benign = _test_origin_value("test.benign")
    first_unknown = architecture._unknown_value(
        frozenset({"test.first_unknown"}),
        sensitive=True,
    )
    protected_unknown = architecture._unknown_value(
        frozenset({_PROTECTED_REGISTRY_ORIGIN}),
        sensitive=True,
    )

    result = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        (
            architecture._OrderedMappingWrite(((target, benign),)),
            architecture._OrderedMappingWrite(unknown_value=first_unknown),
            architecture._OrderedMappingWrite(unknown_value=protected_unknown),
        ),
    )
    projected = architecture._resolved_mapping_value(result)
    selected = analyzer._flow_subscript_value(projected, ast.Constant(value="target"))

    assert result.uncertain
    assert target not in result.masked_mapping_keys
    assert "test.first_unknown" in result.unknown_value.aggregate_origins
    assert _PROTECTED_REGISTRY_ORIGIN in result.unknown_value.aggregate_origins
    assert "test.benign" in selected.aggregate_origins
    assert _PROTECTED_REGISTRY_ORIGIN in selected.aggregate_origins
    assert selected.sensitive_unknown


def test_source_mapping_provenance_is_not_mutated_by_unpack() -> None:
    target = _test_static_key("target")
    nested_location = architecture._AbstractLocation(("source",), "dict", 12, 0)
    retained = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)._replace(
        locations=frozenset({nested_location})
    )
    source = architecture._AbstractContainerState(
        "dict",
        mapping_entries=((target, retained),),
        masked_mapping_keys=frozenset({target}),
    )
    source_snapshot = source
    middle_unknown = architecture._unknown_value(
        frozenset({"test.middle_unknown"}),
        sensitive=True,
    )
    benign_location = architecture._AbstractLocation(("result",), "dict", 13, 0)
    benign = architecture.ResolvedValue(locations=frozenset({benign_location}))

    result = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        (
            architecture._OrderedMappingWrite(source.mapping_entries or ()),
            architecture._OrderedMappingWrite(unknown_value=middle_unknown),
            architecture._OrderedMappingWrite(((target, benign),)),
        ),
    )
    result_target = dict(result.mapping_entries or ())[target]
    source_target = dict(source.mapping_entries or ())[target]

    assert source == source_snapshot
    assert source_target is retained
    assert source_target.locations == {nested_location}
    assert _PROTECTED_REGISTRY_ORIGIN in source_target.direct_origins
    assert result_target == benign
    assert result_target.locations == {benign_location}
    assert target in result.masked_mapping_keys
    assert "test.middle_unknown" in result.unknown_value.aggregate_origins
    assert _PROTECTED_REGISTRY_ORIGIN not in result_target.aggregate_origins


def _assert_pair_protected_mutation(
    source: str,
    analysis: architecture.QualifiedSymbolAnalysis,
    checks: dict[str, bool],
    marker: str,
) -> None:
    failed = {name for name, passed in checks.items() if not passed}
    assert analysis.findings
    assert failed
    assert "no-dynamic-indirection" in failed
    _assert_finding_at_marker(
        analysis,
        source,
        marker,
        codes=frozenset({"qualified-state-mutation"}),
        symbol=_PROTECTED_REGISTRY_ORIGIN,
    )


def test_pair_update_numeric_equivalent_later_benign_wins() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        pairs = (
            (0, CANDIDATES_BY_ID),
            (-0.0, {}),
        )
        holders = {}
        holders.update(pairs)
        holders[0]["pair_update_later_benign"] = None
        """
    )

    assert not analysis.findings
    assert all(checks.values())


def test_pair_update_numeric_equivalent_later_protected_wins() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        pairs = (
            (-0.0, {}),
            (0, CANDIDATES_BY_ID),
        )
        holders = {}
        holders.update(pairs)
        holders[0]["pair_update_later_protected"] = None
        """
    )

    _assert_pair_protected_mutation(
        source,
        analysis,
        checks,
        'holders[0]["pair_update_later_protected"]',
    )


def test_pair_constructor_numeric_equivalent_later_benign_wins() -> None:
    _source, analysis, checks = _analyze_full_union_snippet(
        """
        pairs = (
            (0, CANDIDATES_BY_ID),
            (-0.0, {}),
        )
        holders = dict(pairs)
        holders[0]["pair_constructor_later_benign"] = None
        """
    )

    assert not analysis.findings
    assert all(checks.values())


def test_pair_constructor_numeric_equivalent_later_protected_wins() -> None:
    source, analysis, checks = _analyze_full_union_snippet(
        """
        pairs = (
            (-0.0, {}),
            (0, CANDIDATES_BY_ID),
        )
        holders = dict(pairs)
        holders[0]["pair_constructor_later_protected"] = None
        """
    )

    _assert_pair_protected_mutation(
        source,
        analysis,
        checks,
        'holders[0]["pair_constructor_later_protected"]',
    )


@pytest.fixture(scope="module")
def pair_iterable_malicious_batch() -> tuple[
    str, architecture.QualifiedSymbolAnalysis, dict[str, bool]
]:
    return _analyze_full_union_snippet(
        """
        def case_pair_reverse_update():
            pairs = ((-0.0, {}), (0, CANDIDATES_BY_ID))
            holders = {}
            holders.update(pairs)
            holders[0]["pair_batch_reverse_update"] = None

        def case_pair_reverse_constructor():
            pairs = ((-0.0, {}), (0, CANDIDATES_BY_ID))
            holders = dict(pairs)
            holders[0]["pair_batch_reverse_constructor"] = None

        def case_pair_recursive_protected_last():
            pairs = (
                ((False, (1, -0.0)), {}),
                ((0, (1.0, 0j)), CANDIDATES_BY_ID),
            )
            holders = dict(pairs)
            holders[(0, (1, 0))]["pair_batch_recursive_protected"] = None

        def case_unknown_pair_iterable(pairs):
            holders = {}
            holders.update(pairs)
            holders[0]["pair_batch_unknown_iterable"] = None

        def case_malformed_pair_iterable():
            pairs = ((0, {}), (1, {}, None))
            holders = {}
            holders.update(pairs)
            holders[0]["pair_batch_malformed"] = None

        def case_pair_keyword_protected_override():
            pairs = (("target", {}),)
            holders = {}
            holders.update(pairs, target=CANDIDATES_BY_ID)
            holders["target"]["pair_batch_keyword_protected"] = None

        def case_pair_update_retained_source_alias():
            source = {0: CANDIDATES_BY_ID}
            registry = source[0]
            pairs = ((0, source[0]), (-0.0, {}))
            holders = {}
            holders.update(pairs)
            registry["pair_batch_update_retained_alias"] = None

        def case_pair_constructor_retained_source_alias():
            source = {0: CANDIDATES_BY_ID}
            registry = source[0]
            pairs = ((0, source[0]), (-0.0, {}))
            holders = dict(pairs)
            registry["pair_batch_constructor_retained_alias"] = None

        def case_pair_update_source_sequence_preserved():
            pairs = ((0, CANDIDATES_BY_ID), (-0.0, {}))
            holders = {}
            holders.update(pairs)
            pairs[0][1]["pair_batch_update_source_preserved"] = None

        def case_pair_constructor_source_sequence_preserved():
            pairs = ((0, CANDIDATES_BY_ID), (-0.0, {}))
            holders = dict(pairs)
            pairs[0][1]["pair_batch_constructor_source_preserved"] = None
        """
    )


@pytest.fixture(scope="module")
def pair_iterable_benign_batch() -> tuple[
    str, architecture.QualifiedSymbolAnalysis, dict[str, bool]
]:
    return _analyze_full_union_snippet(
        """
        def case_pair_recursive_update_benign_last():
            pairs = (
                ((False, (1, -0.0)), CANDIDATES_BY_ID),
                ((0, (1.0, 0j)), {}),
            )
            holders = {}
            holders.update(pairs)
            holders[(0, (1, 0))]["pair_batch_recursive_update_benign"] = None

        def case_pair_recursive_constructor_benign_last():
            pairs = (
                ((False, (1, -0.0)), CANDIDATES_BY_ID),
                ((0, (1.0, 0j)), {}),
            )
            holders = dict(pairs)
            holders[(0, (1, 0))]["pair_batch_recursive_constructor_benign"] = None

        def case_pair_false_zero_list_of_tuples():
            pairs = [(False, CANDIDATES_BY_ID), (0, {})]
            holders = {}
            holders.update(pairs)
            holders[False]["pair_batch_false_zero"] = None

        def case_pair_one_float_tuple_of_lists():
            pairs = ([1, CANDIDATES_BY_ID], [1.0, {}])
            holders = dict(pairs)
            holders[1]["pair_batch_one_float"] = None

        def case_pair_complex_list_of_lists():
            pairs = [[0, CANDIDATES_BY_ID], [-0j, {}]]
            holders = {}
            holders.update(pairs)
            holders[0j]["pair_batch_complex_zero"] = None

        def case_pair_aliases_and_tuple_concatenation():
            first_pair = (0, CANDIDATES_BY_ID)
            second_pair = (-0.0, {})
            pairs = (first_pair,) + (second_pair,)
            first_alias = pairs
            second_alias = first_alias
            holders = {}
            holders.update(second_alias)
            holders[0]["pair_batch_two_aliases"] = None

        def case_pair_list_concatenation():
            first_pairs = [[0, CANDIDATES_BY_ID]]
            second_pairs = [[-0.0, {}]]
            pairs = first_pairs + second_pairs
            holders = dict(pairs)
            holders[0]["pair_batch_list_concatenation"] = None

        def case_pair_three_equivalent_keys():
            pairs = ((0, CANDIDATES_BY_ID), (-0.0, {}), (False, {}))
            holders = {}
            holders.update(pairs)
            holders[0]["pair_batch_three_equivalent"] = None

        def case_pair_distinct_numeric_keys():
            pairs = ((1, CANDIDATES_BY_ID), (2.0, {}))
            holders = dict(pairs)
            holders[2]["pair_batch_distinct_numeric"] = None

        def case_pair_update_keyword_benign_override():
            pairs = (("target", CANDIDATES_BY_ID),)
            holders = {}
            holders.update(pairs, target={})
            holders["target"]["pair_batch_update_keyword_benign"] = None

        def case_pair_constructor_keyword_benign_override():
            pairs = (("target", CANDIDATES_BY_ID),)
            holders = dict(pairs, target={})
            holders["target"]["pair_batch_constructor_keyword_benign"] = None
        """
    )


def test_pair_update_recursive_tuple_key_uses_canonical_identity(
    pair_iterable_benign_batch: tuple[
        str,
        architecture.QualifiedSymbolAnalysis,
        dict[str, bool],
    ],
) -> None:
    _source, analysis, checks = pair_iterable_benign_batch

    assert not analysis.findings
    assert all(checks.values())


def test_pair_constructor_recursive_tuple_key_uses_canonical_identity(
    pair_iterable_benign_batch: tuple[
        str,
        architecture.QualifiedSymbolAnalysis,
        dict[str, bool],
    ],
) -> None:
    source, analysis, checks = pair_iterable_benign_batch

    assert not analysis.findings
    assert all(checks.values())
    assert _unique_source_line(source, "pair_batch_recursive_constructor_benign") > 0


def test_pair_update_retained_source_alias_remains_protected(
    pair_iterable_malicious_batch: tuple[
        str,
        architecture.QualifiedSymbolAnalysis,
        dict[str, bool],
    ],
) -> None:
    source, analysis, checks = pair_iterable_malicious_batch
    protected_markers = (
        'holders[0]["pair_batch_reverse_update"]',
        'holders[0]["pair_batch_reverse_constructor"]',
        'holders[(0, (1, 0))]["pair_batch_recursive_protected"]',
        'holders["target"]["pair_batch_keyword_protected"]',
        'registry["pair_batch_update_retained_alias"]',
        'registry["pair_batch_constructor_retained_alias"]',
        'pairs[0][1]["pair_batch_update_source_preserved"]',
        'pairs[0][1]["pair_batch_constructor_source_preserved"]',
    )

    assert analysis.findings
    assert {name for name, passed in checks.items() if not passed}
    for marker in protected_markers:
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"qualified-state-mutation"}),
            symbol=_PROTECTED_REGISTRY_ORIGIN,
        )


def test_unknown_pair_iterable_fails_closed_at_sensitive_use(
    pair_iterable_malicious_batch: tuple[
        str,
        architecture.QualifiedSymbolAnalysis,
        dict[str, bool],
    ],
) -> None:
    source, analysis, checks = pair_iterable_malicious_batch
    failed = {name for name, passed in checks.items() if not passed}

    assert analysis.findings
    assert failed
    assert {"exact-unresolved-mutation-surface", "no-dynamic-indirection"} <= failed
    unresolved_cases = (
        (
            "case_unknown_pair_iterable",
            'holders[0]["pair_batch_unknown_iterable"]',
        ),
        (
            "case_malformed_pair_iterable",
            'holders[0]["pair_batch_malformed"]',
        ),
    )
    for function_name, marker in unresolved_cases:
        lineno = _unique_source_line(source, marker)
        _assert_finding_at_marker(
            analysis,
            source,
            marker,
            codes=frozenset({"unresolved-sensitive-provenance"}),
        )
        assert any(
            mutation.lineno == lineno and mutation.scope[-1] == function_name
            for mutation in analysis.unresolved_mutations
        ), (function_name, lineno, analysis.unresolved_mutations)


def _test_pair_sequence(
    *pairs: tuple[architecture.ResolvedValue, ...],
) -> architecture.ResolvedValue:
    return architecture._sequence_value(
        "tuple",
        tuple(architecture._sequence_value("tuple", pair) for pair in pairs),
    )


def test_pair_iterable_level_c_canonical_key_extraction_table() -> None:
    analyzer = _pure_flow_analyzer()
    equivalent_groups = (
        ("False", "0", "0.0", "0j", "-0.0", "-0j"),
        ("1", "1 + 0j"),
        ("(False, (1, -0.0))", "(0, (1.0, 0j))"),
    )

    for expressions in equivalent_groups:
        nodes = tuple(ast.parse(expression, mode="eval").body for expression in expressions)
        canonical = tuple(analyzer._static_key(node) for node in nodes)
        carried = tuple(
            analyzer._with_static_key(
                node,
                architecture.ResolvedValue(is_unknown=True, sensitive_unknown=True),
            ).static_key
            for node in nodes
        )
        assert canonical[0] is not None
        assert len(set(canonical)) == 1
        assert carried == canonical

    one = analyzer._static_key(ast.parse("1", mode="eval").body)
    two = analyzer._static_key(ast.parse("2", mode="eval").body)
    string_node = ast.parse("'target'", mode="eval").body
    bytes_node = ast.parse("b'target'", mode="eval").body
    string_key = analyzer._with_static_key(string_node, architecture.ResolvedValue()).static_key
    bytes_key = analyzer._with_static_key(bytes_node, architecture.ResolvedValue()).static_key
    assert one is not None
    assert two is not None
    assert one != two
    assert string_key is not None
    assert bytes_key is not None
    assert string_key != bytes_key


def test_pair_iterable_level_c_order_and_keyword_precedence() -> None:
    analyzer = _pure_flow_analyzer()
    zero = analyzer._static_key(ast.parse("0", mode="eval").body)
    assert zero is not None
    zero_value = architecture.ResolvedValue(static_key=zero)
    protected = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)
    benign = architecture.ResolvedValue(mapping_entries=())
    keyword = architecture.ResolvedValue(mapping_entries=())
    pairs = _test_pair_sequence(
        (zero_value, protected),
        (zero_value, benign),
    )
    source_snapshot = pairs
    pair_writes = architecture._resolved_pair_iterable_mapping_writes(pairs)

    assert len(pair_writes) == 2
    result = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        pair_writes,
    )
    assert dict(result.mapping_entries or ())[zero] is benign
    reverse = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        architecture._resolved_pair_iterable_mapping_writes(
            _test_pair_sequence((zero_value, benign), (zero_value, protected))
        ),
    )
    assert dict(reverse.mapping_entries or ())[zero] is protected
    with_keyword = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        (*pair_writes, architecture._ordered_direct_mapping_write(zero, keyword)),
    )
    assert dict(with_keyword.mapping_entries or ())[zero] is keyword
    assert pairs == source_snapshot


def test_pair_iterable_level_c_unknown_and_malformed_propagation() -> None:
    analyzer = _pure_flow_analyzer()
    zero = analyzer._static_key(ast.parse("0", mode="eval").body)
    assert zero is not None
    exact_key = architecture.ResolvedValue(static_key=zero)
    protected = _test_origin_value(_PROTECTED_REGISTRY_ORIGIN)
    unknown_value = architecture._unknown_value(sensitive=True)
    unknown_key = architecture._unknown_value(sensitive=True)
    benign = architecture.ResolvedValue(mapping_entries=())

    exact_unknown = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        architecture._resolved_pair_iterable_mapping_writes(
            _test_pair_sequence((exact_key, unknown_value))
        ),
    )
    exact_selected = dict(exact_unknown.mapping_entries or ())[zero]
    assert exact_selected.is_unknown
    assert exact_selected.sensitive_unknown

    unknown_protected = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        architecture._resolved_pair_iterable_mapping_writes(
            _test_pair_sequence((unknown_key, protected))
        ),
    )
    assert unknown_protected.uncertain
    assert unknown_protected.unknown_value.sensitive_unknown
    assert _PROTECTED_REGISTRY_ORIGIN in unknown_protected.unknown_value.aggregate_origins

    unknown_between_exact_writes = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        architecture._resolved_pair_iterable_mapping_writes(
            _test_pair_sequence(
                (exact_key, protected),
                (unknown_key, protected),
                (exact_key, benign),
            )
        ),
    )
    assert dict(unknown_between_exact_writes.mapping_entries or ())[zero] is benign
    assert zero in unknown_between_exact_writes.masked_mapping_keys
    assert _PROTECTED_REGISTRY_ORIGIN in (
        unknown_between_exact_writes.unknown_value.aggregate_origins
    )

    malformed = architecture._sequence_value(
        "tuple",
        (
            architecture._sequence_value("tuple", (exact_key, benign)),
            architecture._sequence_value("tuple", (exact_key,)),
        ),
    )
    malformed_writes = architecture._resolved_pair_iterable_mapping_writes(malformed)
    assert len(malformed_writes) == 2
    malformed_result = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        malformed_writes,
    )
    assert malformed_result.uncertain
    assert malformed_result.unknown_value.sensitive_unknown
    assert not malformed_result.unknown_value.aggregate_origins

    dynamic_result = architecture._apply_ordered_mapping_writes(
        architecture._AbstractContainerState("dict", mapping_entries=()),
        architecture._resolved_pair_iterable_mapping_writes(
            architecture._unknown_value(
                frozenset({_PROTECTED_REGISTRY_ORIGIN}),
                sensitive=True,
            )
        ),
    )
    assert dynamic_result.uncertain
    assert dynamic_result.unknown_value.sensitive_unknown
    assert _PROTECTED_REGISTRY_ORIGIN in dynamic_result.unknown_value.aggregate_origins
