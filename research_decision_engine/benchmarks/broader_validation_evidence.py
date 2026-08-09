"""P2 Stage-1 plan authority for broader-replication validation evidence.

This module implements only the authority-free plan DAG and its in-process
capabilities.  It deliberately contains no execution, result, manifest, Reader,
or evidence-rendering path.
"""

from __future__ import annotations

import _contextvars
import _functools  # type: ignore[import-not-found]
import _thread
import builtins
import contextlib
import dataclasses
import functools
import hashlib
import inspect
import json
import os
import pathlib
import platform
import re
import secrets
import stat
import sys
import tempfile
import threading
import types
import unicodedata
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields, is_dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import BuiltinFunctionType, CodeType, FunctionType, MappingProxyType, ModuleType
from typing import Any, Final, Literal, NoReturn, SupportsIndex


def _install_runtime_bootstrap() -> tuple[
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Mapping[str, object],
    type[object],
    Any,
    Any,
    Any,
    Callable[[], None],
]:
    """Authenticate the primitive reflection/compiler boundary before project imports."""

    probe: Any = lambda: None  # noqa: E731
    dict_type: type[dict[object, object]] = {}.__class__
    function_type = probe.__class__
    code_type = probe.__code__.__class__
    builtin_callable_type: type[object] = [].append.__class__
    type_type = ().__class__.__class__
    object_type = ().__class__.__mro__[-1]
    module_type = sys.__class__
    builtin_namespace = probe.__builtins__
    if builtin_namespace.__class__ is not dict_type:
        raise RuntimeError("The interpreter builtins namespace is not an exact dictionary.")
    if (
        builtins is not sys.modules.get("builtins")
        or builtins.__dict__ is not builtin_namespace
        or builtins.__class__ is not module_type
        or builtins.__name__ != "builtins"
        or sys is not sys.modules.get("sys")
        or sys.__class__ is not module_type
        or sys.__name__ != "sys"
        or sys._getframe.__class__ is not builtin_callable_type
        or sys._getframe.__self__ is not sys  # type: ignore[attr-defined]
        or FunctionType is not function_type
        or CodeType is not code_type
        or BuiltinFunctionType is not builtin_callable_type
        or ModuleType is not module_type
        or type_type.__module__ != "builtins"
        or type_type.__name__ != "type"
        or object_type.__module__ != "builtins"
        or object_type.__name__ != "object"
    ):
        raise RuntimeError("The interpreter primitive type boundary was substituted.")

    def exact_builtin(name: str) -> Callable[..., object]:
        value = builtin_namespace.get(name)
        expected_module = "_io" if name == "open" else "builtins"
        expected_self = sys.modules.get(expected_module)
        if (
            value is not builtins.__dict__.get(name)
            or value.__class__ is not builtin_callable_type
            or value.__module__ != expected_module
            or value.__name__ != name
            or value.__self__ is not expected_self
        ):
            raise RuntimeError(f"The interpreter builtin was substituted: {name}.")
        return value

    def exact_static_type(name: str) -> type[object]:
        value = builtin_namespace.get(name)
        if (
            value is not builtins.__dict__.get(name)
            or value.__class__ is not type_type
            or value.__module__ != "builtins"
            or value.__name__ != name
            or value.__qualname__ != name
            or value.__flags__ & 512
        ):
            raise RuntimeError(f"The interpreter builtin type was substituted: {name}.")
        return value  # type: ignore[no-any-return]

    function_names = (
        "__build_class__",
        "__import__",
        "abs",
        "all",
        "any",
        "bin",
        "callable",
        "chr",
        "compile",
        "delattr",
        "dir",
        "divmod",
        "eval",
        "exec",
        "format",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "hex",
        "id",
        "input",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "locals",
        "max",
        "min",
        "next",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "repr",
        "round",
        "setattr",
        "sorted",
        "sum",
        "vars",
    )
    type_names = (
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BaseException",
        "BlockingIOError",
        "BrokenPipeError",
        "BufferError",
        "BytesWarning",
        "ChildProcessError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "DeprecationWarning",
        "EOFError",
        "Exception",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "FutureWarning",
        "GeneratorExit",
        "ImportError",
        "ImportWarning",
        "IndentationError",
        "IndexError",
        "InterruptedError",
        "IsADirectoryError",
        "KeyError",
        "KeyboardInterrupt",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "NotADirectoryError",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PendingDeprecationWarning",
        "PermissionError",
        "ProcessLookupError",
        "RecursionError",
        "ReferenceError",
        "ResourceWarning",
        "RuntimeError",
        "RuntimeWarning",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SyntaxWarning",
        "SystemError",
        "SystemExit",
        "TabError",
        "TimeoutError",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "UnicodeWarning",
        "UserWarning",
        "ValueError",
        "Warning",
        "ZeroDivisionError",
        "bool",
        "bytearray",
        "bytes",
        "classmethod",
        "complex",
        "dict",
        "enumerate",
        "filter",
        "float",
        "frozenset",
        "int",
        "list",
        "map",
        "memoryview",
        "object",
        "property",
        "range",
        "reversed",
        "set",
        "slice",
        "staticmethod",
        "str",
        "super",
        "tuple",
        "type",
        "zip",
    )
    trusted_values: dict[str, object] = {}
    for name in function_names:
        trusted_values[name] = exact_builtin(name)
    for name in type_names:
        trusted_values[name] = exact_static_type(name)
    mapping_proxy_type = type_type.__dict__.__class__
    if MappingProxyType is not mapping_proxy_type:  # type: ignore[comparison-overlap]
        raise RuntimeError("The interpreter mapping-proxy boundary was substituted.")
    trusted_builtins = mapping_proxy_type(trusted_values)
    compile_source: Any = trusted_builtins["compile"]
    get_attribute: Any = trusted_builtins["getattr"]
    instance_of: Any = trusted_builtins["isinstance"]
    namespace_of: Any = trusted_builtins["vars"]
    length_of: Any = trusted_builtins["len"]
    open_file: Any = trusted_builtins["open"]
    has_attribute: Any = trusted_builtins["hasattr"]
    expected_bindings = tuple(trusted_values.items())

    wrapper_type = _functools.__dict__.get("_lru_cache_wrapper")
    wrapper_namespace = None if wrapper_type is None else wrapper_type.__dict__
    method_descriptor_type = str.upper.__class__
    wrapper_descriptor_type = object_type.__repr__.__class__
    if (
        _functools is not sys.modules.get("_functools")
        or _functools.__class__ is not module_type
        or _functools.__name__ != "_functools"
        or wrapper_type is not functools.__dict__.get("_lru_cache_wrapper")
        or wrapper_type.__class__ is not type_type
        or wrapper_type.__module__ != "functools"
        or wrapper_type.__name__ != "_lru_cache_wrapper"
        or wrapper_type.__qualname__ != "_lru_cache_wrapper"
        or wrapper_type.__basicsize__ < 100
        or wrapper_namespace is None
        or wrapper_namespace.get("__call__").__class__ is not wrapper_descriptor_type
        or wrapper_namespace.get("__call__").__objclass__ is not wrapper_type
        or wrapper_namespace.get("cache_info").__class__ is not method_descriptor_type
        or wrapper_namespace.get("cache_info").__objclass__ is not wrapper_type
        or wrapper_namespace.get("cache_clear").__class__ is not method_descriptor_type
        or wrapper_namespace.get("cache_clear").__objclass__ is not wrapper_type
    ):
        raise RuntimeError("The native opaque-call boundary was substituted.")
    trusted_wrapper_type: Any = wrapper_type

    rlock_type = _thread.__dict__.get("RLock")
    rlock_namespace = None if rlock_type is None else rlock_type.__dict__
    if (
        _thread is not sys.modules.get("_thread")
        or _thread.__class__ is not module_type
        or _thread.__name__ != "_thread"
        or rlock_type is not threading.__dict__.get("_CRLock")
        or rlock_type.__class__ is not type_type
        or rlock_type.__module__ != "_thread"
        or rlock_type.__name__ != "RLock"
        or rlock_type.__qualname__ != "RLock"
        or rlock_type.__bases__ != (object_type,)
        or rlock_namespace is None
        or rlock_namespace.get("acquire").__class__ is not method_descriptor_type
        or rlock_namespace.get("acquire").__objclass__ is not rlock_type
        or rlock_namespace.get("release").__class__ is not method_descriptor_type
        or rlock_namespace.get("release").__objclass__ is not rlock_type
        or rlock_namespace.get("_is_owned").__class__ is not method_descriptor_type
        or rlock_namespace.get("_is_owned").__objclass__ is not rlock_type
    ):
        raise RuntimeError("The native production-lock boundary was substituted.")
    trusted_rlock_type: Any = rlock_type
    rlock_probe = trusted_rlock_type()
    if (
        rlock_probe.__class__ is not trusted_rlock_type
        or not rlock_probe.acquire(False)
        or not rlock_probe._is_owned()
    ):
        raise RuntimeError("The native production-lock boundary failed its known-answer check.")
    rlock_probe.release()
    if rlock_probe._is_owned():
        raise RuntimeError("The native production-lock boundary failed to release.")

    contextvar_type = _contextvars.__dict__.get("ContextVar")
    contextvar_namespace = None if contextvar_type is None else contextvar_type.__dict__
    if (
        _contextvars is not sys.modules.get("_contextvars")
        or _contextvars.__class__ is not module_type
        or _contextvars.__name__ != "_contextvars"
        or contextvar_type is not ContextVar
        or contextvar_type.__class__ is not type_type
        or contextvar_type.__module__ != "_contextvars"
        or contextvar_type.__name__ != "ContextVar"
        or contextvar_type.__qualname__ != "ContextVar"
        or contextvar_type.__bases__ != (object_type,)
        or contextvar_type.__flags__ & 512
        or contextvar_namespace is None
        or contextvar_namespace.get("get").__class__ is not method_descriptor_type
        or contextvar_namespace.get("get").__objclass__ is not contextvar_type
        or contextvar_namespace.get("set").__class__ is not method_descriptor_type
        or contextvar_namespace.get("set").__objclass__ is not contextvar_type
        or contextvar_namespace.get("reset").__class__ is not method_descriptor_type
        or contextvar_namespace.get("reset").__objclass__ is not contextvar_type
    ):
        raise RuntimeError("The native context-variable boundary was substituted.")
    trusted_contextvar_type: Any = contextvar_type
    context_default = object_type()
    context_value = object_type()
    context_probe = trusted_contextvar_type("rde_runtime_bootstrap", default=context_default)
    context_token = context_probe.set(context_value)
    if context_probe.get() is not context_value:
        raise RuntimeError("The native context-variable boundary failed its known-answer check.")
    context_probe.reset(context_token)
    if context_probe.get() is not context_default:
        raise RuntimeError("The native context-variable boundary failed to reset.")
    compiled_probe = compile_source(
        "bootstrap_value = 1",
        "<rde-runtime-bootstrap>",
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    if (
        compiled_probe.__class__ is not code_type
        or compiled_probe.co_filename != "<rde-runtime-bootstrap>"
    ):
        raise RuntimeError("The interpreter compiler failed its bootstrap known-answer check.")

    def wrapper_probe(value: object) -> object:
        return value

    probe_wrapper = trusted_wrapper_type(wrapper_probe, 0, False, None)
    if (
        probe_wrapper.__class__ is not trusted_wrapper_type
        or probe_wrapper("opaque-kat") != "opaque-kat"
        or has_attribute(probe_wrapper, "__wrapped__")
        or has_attribute(probe_wrapper, "__code__")
        or has_attribute(probe_wrapper, "__closure__")
    ):
        raise RuntimeError("The native opaque-call boundary failed its known-answer check.")

    def identity_cast(value: object) -> object:
        return value

    trusted_cast: Any = trusted_wrapper_type(identity_cast, 0, False, None)
    if (
        trusted_cast.__class__ is not trusted_wrapper_type
        or trusted_cast("cast-kat") != "cast-kat"
        or has_attribute(trusted_cast, "__wrapped__")
        or has_attribute(trusted_cast, "__code__")
        or has_attribute(trusted_cast, "__closure__")
    ):
        raise RuntimeError("The native runtime-cast boundary failed its known-answer check.")
    module_namespace = probe.__globals__

    def validate() -> None:
        changed = (
            probe.__class__ is not function_type
            or probe.__code__.__class__ is not code_type
            or probe.__builtins__ is not builtin_namespace
            or sys._getframe.__class__ is not builtin_callable_type
            or sys._getframe.__self__ is not sys
            or builtins is not sys.modules.get("builtins")
            or builtins.__dict__ is not builtin_namespace
            or _functools is not sys.modules.get("_functools")
            or _functools.__dict__.get("_lru_cache_wrapper") is not trusted_wrapper_type
            or functools.__dict__.get("_lru_cache_wrapper") is not trusted_wrapper_type
            or _thread is not sys.modules.get("_thread")
            or _thread.__dict__.get("RLock") is not trusted_rlock_type
            or threading.__dict__.get("_CRLock") is not trusted_rlock_type
            or _contextvars is not sys.modules.get("_contextvars")
            or _contextvars.__dict__.get("ContextVar") is not trusted_contextvar_type
            or module_namespace.get("ContextVar") is not trusted_contextvar_type
            or module_namespace.get("MappingProxyType") is not mapping_proxy_type
            or module_namespace.get("_TRUSTED_RLOCK_TYPE") is not trusted_rlock_type
            or module_namespace.get("_TRUSTED_CONTEXTVAR_TYPE") is not trusted_contextvar_type
            or module_namespace.get("_runtime_cast") is not trusted_cast
        )
        if not changed:
            for name, expected in expected_bindings:
                if (
                    builtin_namespace.get(name) is not expected
                    or builtins.__dict__.get(name) is not expected
                ):
                    changed = True
                    break
        if changed:
            raise RuntimeError("The authenticated interpreter primitive boundary changed.")

    return (
        compile_source,
        get_attribute,
        instance_of,
        namespace_of,
        length_of,
        open_file,
        trusted_builtins,
        trusted_wrapper_type,
        trusted_rlock_type,
        trusted_contextvar_type,
        trusted_cast,
        validate,
    )


(
    _TRUSTED_COMPILE,
    _TRUSTED_GETATTR,
    _TRUSTED_ISINSTANCE,
    _TRUSTED_VARS,
    _TRUSTED_LEN,
    _TRUSTED_OPEN,
    _TRUSTED_BUILTINS,
    _TRUSTED_LRU_WRAPPER_TYPE,
    _TRUSTED_RLOCK_TYPE,
    _TRUSTED_CONTEXTVAR_TYPE,
    _runtime_cast,
    _validate_runtime_bootstrap,
) = _install_runtime_bootstrap()
del _install_runtime_bootstrap


from research_decision_engine.benchmarks.broader_protocol import (  # noqa: E402
    PROTOCOL_CHECKPOINT,
    protocol_hash,
    repository_root,
)


def _validate_external_runtime_provenance() -> None:
    """Reject pre-seal substitutions for external functions that derive authority facts."""

    _validate_runtime_bootstrap()
    compile_source = _runtime_cast(_TRUSTED_COMPILE)
    get_attribute = _runtime_cast(_TRUSTED_GETATTR)
    namespace_of = _runtime_cast(_TRUSTED_VARS)
    open_file = _runtime_cast(_TRUSTED_OPEN)
    exact_function_type = (lambda: None).__class__
    exact_code_type = (lambda: None).__code__.__class__
    exact_module_type = sys.__class__
    exact_builtin_type: type[object] = [].append.__class__

    if (
        _runtime_cast(sys._getframe.__class__) is not exact_builtin_type
        or _runtime_cast(sys._getframe).__self__ is not sys
        or os.__class__ is not exact_module_type
        or os.__name__ != "os"
        or os.name not in {"nt", "posix"}
    ):
        raise RuntimeError("The trusted sys/os runtime boundary was substituted.")
    native_module = "nt" if os.name == "nt" else "posix"

    def require_builtin(
        value: object,
        *,
        modules: frozenset[str],
        names: frozenset[str],
        label: str,
    ) -> Any:
        if (
            value.__class__ is not exact_builtin_type
            or get_attribute(value, "__module__", None) not in modules
            or get_attribute(value, "__name__", None) not in names
        ):
            raise RuntimeError(f"Trusted external builtin was substituted before sealing: {label}.")
        return _runtime_cast(value)

    for name in (
        "close",
        "fstat",
        "fspath",
        "fsync",
        "getcwd",
        "getcwdb",
        "get_inheritable",
        "lseek",
        "lstat",
        "mkdir",
        "open",
        "read",
        "rmdir",
        "scandir",
        "set_inheritable",
        "stat",
        "unlink",
        "urandom",
        "write",
    ):
        require_builtin(
            get_attribute(os, name),
            modules=frozenset({native_module}),
            names=frozenset({name}),
            label=f"os.{name}",
        )
    filesystem_encoding = require_builtin(
        sys.getfilesystemencoding,
        modules=frozenset({"sys"}),
        names=frozenset({"getfilesystemencoding"}),
        label="sys.getfilesystemencoding",
    )()
    filesystem_errors = require_builtin(
        sys.getfilesystemencodeerrors,
        modules=frozenset({"sys"}),
        names=frozenset({"getfilesystemencodeerrors"}),
        label="sys.getfilesystemencodeerrors",
    )()

    stdlib_root = get_attribute(sys, "_stdlib_dir", None)
    separator = "\\" if os.name == "nt" else "/"
    if (
        stdlib_root.__class__ is not str
        or not stdlib_root
        or (os.name == "nt" and len(stdlib_root) < 3)
        or (os.name == "nt" and stdlib_root[1:3] != ":\\")
        or (os.name == "posix" and not stdlib_root.startswith("/"))
    ):
        raise RuntimeError("The interpreter has no exact physical standard-library root.")
    root_status = os.stat(stdlib_root, follow_symlinks=False)
    if root_status.st_mode & 0xF000 != 0x4000:
        raise RuntimeError("The interpreter standard-library root is not an exact directory.")

    def physical_path(relative: str) -> str:
        if relative.startswith(("/", "\\")) or ".." in relative.split("/"):
            raise RuntimeError("Invalid trusted standard-library relative path.")
        return stdlib_root.rstrip("/\\") + separator + relative.replace("/", separator)

    module_manifests: dict[
        ModuleType,
        tuple[str, dict[tuple[str, int], list[CodeType]]],
    ] = {}

    def normalized_code(code: CodeType) -> CodeType:
        return code.replace(
            co_filename="",
            co_consts=tuple(
                normalized_code(value) if value.__class__ is exact_code_type else value
                for value in code.co_consts
            ),
        )

    def require_source_module(
        module: object,
        *,
        name: str,
        relative: str,
    ) -> ModuleType:
        if (
            module.__class__ is not exact_module_type
            or module is not sys.modules.get(name)
            or get_attribute(module, "__name__", None) != name
        ):
            raise RuntimeError(f"Trusted external module was substituted before sealing: {name}.")
        source_path = physical_path(relative)
        source_name = get_attribute(module, "__file__", None)
        comparable_source = (
            source_name.casefold()
            if os.name == "nt" and source_name.__class__ is str
            else source_name
        )
        comparable_expected = source_path.casefold() if os.name == "nt" else source_path
        if comparable_source != comparable_expected:
            raise RuntimeError(f"Trusted external module escaped the stdlib root: {name}.")
        status = os.stat(source_path, follow_symlinks=False)
        if status.st_mode & 0xF000 != 0x8000:
            raise RuntimeError(f"Trusted external module source is not a regular file: {name}.")
        with open_file(source_path, "rb") as source_handle:
            raw_source = source_handle.read()
        module_code = compile_source(
            raw_source,
            source_path,
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
        compiled_by_location: dict[tuple[str, int], list[CodeType]] = {}
        pending = [module_code]
        while pending:
            parent = pending.pop()
            for constant in parent.co_consts:
                if constant.__class__ is exact_code_type:
                    pending.append(constant)
                    compiled_by_location.setdefault(
                        (constant.co_qualname, constant.co_firstlineno), []
                    ).append(constant)
        trusted_module = module
        module_manifests[trusted_module] = source_path, compiled_by_location
        return trusted_module

    expected_modules = (
        (contextlib, "contextlib", "contextlib.py"),
        (dataclasses, "dataclasses", "dataclasses.py"),
        (functools, "functools", "functools.py"),
        (hashlib, "hashlib", "hashlib.py"),
        (inspect, "inspect", "inspect.py"),
        (json, "json", "json/__init__.py"),
        (os, "os", "os.py"),
        (
            os.path,
            "ntpath" if os.name == "nt" else "posixpath",
            "ntpath.py" if os.name == "nt" else "posixpath.py",
        ),
        (pathlib, "pathlib", "pathlib.py"),
        (platform, "platform", "platform.py"),
        (re, "re", "re/__init__.py"),
        (secrets, "secrets", "secrets.py"),
        (stat, "stat", "stat.py"),
        (tempfile, "tempfile", "tempfile.py"),
        (threading, "threading", "threading.py"),
        (types, "types", "types.py"),
    )
    for module, name, relative in expected_modules:
        require_source_module(module, name=name, relative=relative)
    if (
        dataclass is not dataclasses.dataclass
        or field is not dataclasses.field
        or fields is not dataclasses.fields
        or is_dataclass is not dataclasses.is_dataclass
        or replace is not dataclasses.replace
        or lru_cache is not functools.lru_cache
        or contextmanager is not contextlib.contextmanager
        or Path is not pathlib.Path
    ):
        raise RuntimeError("A trusted imported stdlib helper alias was substituted before sealing.")
    encoder_module = require_source_module(
        sys.modules.get("json.encoder"),
        name="json.encoder",
        relative="json/encoder.py",
    )

    validated_functions: set[FunctionType] = set()
    source_function_defaults: dict[
        tuple[str, str],
        tuple[tuple[object, ...] | None, dict[str, object] | None],
    ] = {
        (os.path.__name__, name): (None, None)
        for name in (
            "dirname",
            "isjunction",
            "splitroot",
            "splitdrive",
            "normcase",
            "isabs",
            "join",
        )
    }
    source_function_defaults[(os.path.__name__, "realpath")] = (None, {"strict": False})
    source_function_defaults.update(
        {
            ("os", "fsencode"): (None, None),
            ("os", "fsdecode"): (None, None),
            ("platform", "python_build"): (None, None),
            ("platform", "python_compiler"): (None, None),
            ("platform", "python_implementation"): (None, None),
            ("platform", "python_version"): (None, None),
            ("platform", "_sys_version"): ((None,), None),
            ("re", "fullmatch"): ((0,), None),
            ("re", "_compile"): (None, None),
            ("tempfile", "gettempdir"): (None, None),
            ("tempfile", "mkdtemp"): ((None, None, None), None),
            ("tempfile", "_gettempdir"): (None, None),
            ("tempfile", "_get_default_tempdir"): (None, None),
            ("functools", "lru_cache"): ((128, False), None),
            ("contextlib", "contextmanager"): (None, None),
            ("inspect", "currentframe"): (None, None),
            ("dataclasses", "fields"): (None, None),
            ("dataclasses", "is_dataclass"): (None, None),
            ("dataclasses", "replace"): (None, None),
            ("threading", "RLock"): (None, None),
        }
    )

    def require_python_function(module: ModuleType, name: str) -> Any:
        value: Any = namespace_of(module).get(name)
        allowed_os_codec_closure = module is os and name in {"fsencode", "fsdecode"}
        if (
            value.__class__ is not exact_function_type
            or value.__globals__ is not namespace_of(module)
            or get_attribute(value, "__builtins__", None) is not builtins.__dict__
            or (value.__closure__ is not None and not allowed_os_codec_closure)
        ):
            raise RuntimeError(
                f"Trusted external Python function was substituted before sealing: "
                f"{module.__name__}.{name}."
            )
        function = _runtime_cast(value)
        if allowed_os_codec_closure and (
            function.__code__.co_freevars != ("encoding", "errors")
            or function.__closure__ is None
            or tuple(cell.cell_contents for cell in function.__closure__)
            != (filesystem_encoding, filesystem_errors)
        ):
            raise RuntimeError(f"Trusted os codec closure was substituted before sealing: {name}.")
        expected_defaults = source_function_defaults.get((module.__name__, name))
        if expected_defaults is not None and (
            function.__defaults__ != expected_defaults[0]
            or function.__kwdefaults__ != expected_defaults[1]
        ):
            raise RuntimeError(
                f"Trusted external Python function defaults differ from source: "
                f"{module.__name__}.{name}."
            )
        if function in validated_functions:
            return function
        source_path, compiled_by_location = module_manifests[module]
        code = function.__code__
        live_filename = code.co_filename
        comparable_live = live_filename.casefold() if os.name == "nt" else live_filename
        comparable_expected = {
            source_path.casefold() if os.name == "nt" else source_path,
            (
                f"<frozen {module.__name__}>".casefold()
                if os.name == "nt"
                else f"<frozen {module.__name__}>"
            ),
        }
        matches = compiled_by_location.get((code.co_qualname, code.co_firstlineno), [])
        if (
            function.__module__ != module.__name__
            or comparable_live not in comparable_expected
            or len(matches) != 1
            or normalized_code(code) != normalized_code(matches[0])
        ):
            raise RuntimeError(
                f"Trusted external Python function does not match its runtime source: "
                f"{module.__name__}.{name}."
            )
        validated_functions.add(function)
        source_defined_names = {
            qualname
            for qualname, _line in compiled_by_location
            if "." not in qualname and "<locals>" not in qualname
        }
        for referenced_name in code.co_names:
            referenced = namespace_of(module).get(referenced_name)
            if (
                referenced_name in source_defined_names
                and referenced.__class__ is exact_function_type
            ):
                require_python_function(module, referenced_name)
        return function

    exact_type = _runtime_cast(_TRUSTED_BUILTINS["type"])
    object_type = _runtime_cast(_TRUSTED_BUILTINS["object"])
    staticmethod_type = _runtime_cast(_TRUSTED_BUILTINS["staticmethod"])
    classmethod_type = _runtime_cast(_TRUSTED_BUILTINS["classmethod"])
    property_type = _runtime_cast(_TRUSTED_BUILTINS["property"])

    class _SlotProbe:
        __slots__ = ("value",)

    slot_descriptor_type = exact_type(namespace_of(_SlotProbe)["value"])

    def descriptor_functions(value: object) -> Any:
        value_type = exact_type(value)
        if value_type is exact_function_type:
            return (_runtime_cast(value),)
        if value_type in {staticmethod_type, classmethod_type}:
            function = get_attribute(value, "__func__", None)
            if exact_type(function) is not exact_function_type:
                raise RuntimeError("Trusted source class has a forged method descriptor.")
            return (_runtime_cast(function),)
        if value_type is property_type:
            functions = tuple(
                function
                for function in (
                    get_attribute(value, "fget", None),
                    get_attribute(value, "fset", None),
                    get_attribute(value, "fdel", None),
                )
                if function is not None
            )
            if any(exact_type(function) is not exact_function_type for function in functions):
                raise RuntimeError("Trusted source class has a forged property descriptor.")
            return _runtime_cast(functions)
        return ()

    def require_source_class(
        module: ModuleType,
        name: str,
        *,
        bases: tuple[type[object], ...],
        mro: tuple[type[object], ...],
        slots: tuple[str, ...] | None,
        allowed_nonmethods: frozenset[str] = frozenset(),
        expected_metaclass: type[object] | None = None,
        generated_nonmethods: frozenset[str] | None = None,
        expected_defaults: Mapping[
            str,
            tuple[tuple[object, ...] | None, dict[str, object] | None],
        ] = MappingProxyType({}),
    ) -> Any:
        candidate = namespace_of(module).get(name)
        metaclass = exact_type(candidate)
        if (
            (expected_metaclass is None and metaclass is not exact_type)
            or (expected_metaclass is not None and metaclass is not expected_metaclass)
            or get_attribute(candidate, "__module__", None) != module.__name__
            or get_attribute(candidate, "__name__", None) != name
            or get_attribute(candidate, "__qualname__", None) != name
            or get_attribute(candidate, "__bases__", None) != bases
            or get_attribute(candidate, "__mro__", None) != mro
        ):
            raise RuntimeError(f"Trusted source class was substituted before sealing: {name}.")
        candidate_type = _runtime_cast(candidate)
        namespace = namespace_of(candidate_type)
        if slots is None:
            if "__slots__" in namespace:
                raise RuntimeError(f"Trusted source class has unexpected slots: {name}.")
            generated_names = set(
                frozenset({"__dict__", "__weakref__"})
                if generated_nonmethods is None
                else generated_nonmethods
            )
        else:
            if namespace.get("__slots__") != slots:
                raise RuntimeError(f"Trusted source class slots differ from source: {name}.")
            generated_names = set(slots)
            for slot_name in slots:
                descriptor = namespace.get(slot_name)
                if (
                    exact_type(descriptor) is not slot_descriptor_type
                    or get_attribute(descriptor, "__objclass__", None) is not candidate_type
                ):
                    raise RuntimeError(
                        f"Trusted source class has a forged slot descriptor: {name}.{slot_name}."
                    )

        _source_path, compiled_by_location = module_manifests[module]
        expected_methods: dict[str, list[CodeType]] = {}
        prefix = name + "."
        for (qualname, _line), codes in compiled_by_location.items():
            if not qualname.startswith(prefix) or "<locals>" in qualname:
                continue
            remainder = qualname[len(prefix) :]
            if "." not in remainder:
                expected_methods.setdefault(remainder, []).extend(codes)
        if os.name == "nt" and name == "WindowsPath":
            expected_methods.pop("__new__", None)
        if os.name == "posix" and name == "PosixPath":
            expected_methods.pop("__new__", None)

        expected_names = (
            {"__module__", "__doc__"}
            | ({"__slots__"} if slots is not None else set())
            | generated_names
            | set(expected_methods)
            | set(allowed_nonmethods)
        )
        if set(namespace) != expected_names:
            raise RuntimeError(f"Trusted source class namespace differs from source: {name}.")
        module_namespace = namespace_of(module)
        for method_name, expected_codes in expected_methods.items():
            functions = descriptor_functions(namespace.get(method_name))
            if len(functions) != len(expected_codes):
                raise RuntimeError(
                    f"Trusted source class descriptor differs from source: {name}.{method_name}."
                )
            unmatched = list(expected_codes)
            for function in functions:
                if (
                    function.__globals__ is not module_namespace
                    or function.__builtins__ is not builtins.__dict__
                ):
                    raise RuntimeError(
                        f"Trusted source class method has foreign globals: {name}.{method_name}."
                    )
                if function.__code__.co_freevars:
                    closure = function.__closure__
                    if (
                        function.__code__.co_freevars != ("__class__",)
                        or closure is None
                        or len(closure) != 1
                        or closure[0].cell_contents is not candidate_type
                    ):
                        raise RuntimeError(
                            f"Trusted source class method has foreign closure state: "
                            f"{name}.{method_name}."
                        )
                elif function.__closure__ is not None:
                    raise RuntimeError(
                        f"Trusted source class method has foreign closure state: "
                        f"{name}.{method_name}."
                    )
                if method_name in expected_defaults and (
                    function.__defaults__ != expected_defaults[method_name][0]
                    or function.__kwdefaults__ != expected_defaults[method_name][1]
                ):
                    raise RuntimeError(
                        f"Trusted source class method defaults differ from source: "
                        f"{name}.{method_name}."
                    )
                matching = [
                    code
                    for code in unmatched
                    if code.co_qualname == function.__code__.co_qualname
                    and code.co_firstlineno == function.__code__.co_firstlineno
                    and normalized_code(code) == normalized_code(function.__code__)
                ]
                if len(matching) != 1:
                    raise RuntimeError(
                        f"Trusted source class method differs from source: {name}.{method_name}."
                    )
                unmatched.remove(matching[0])
            if unmatched:
                raise RuntimeError(
                    f"Trusted source class omitted source behavior: {name}.{method_name}."
                )
        return candidate_type

    pathlib_namespace = namespace_of(pathlib)
    pathlib_dependencies = {
        "fnmatch": require_source_module(
            pathlib_namespace.get("fnmatch"), name="fnmatch", relative="fnmatch.py"
        ),
        "io": require_source_module(pathlib_namespace.get("io"), name="io", relative="io.py"),
        "ntpath": require_source_module(
            pathlib_namespace.get("ntpath"), name="ntpath", relative="ntpath.py"
        ),
        "posixpath": require_source_module(
            pathlib_namespace.get("posixpath"), name="posixpath", relative="posixpath.py"
        ),
        "warnings": require_source_module(
            pathlib_namespace.get("warnings"), name="warnings", relative="warnings.py"
        ),
    }
    if (
        pathlib_namespace.get("os") is not os
        or pathlib_namespace.get("sys") is not sys
        or pathlib_namespace.get("re") is not re
        or pathlib_namespace.get("functools") is not functools
        or pathlib_namespace.get("io") is not pathlib_dependencies["io"]
        or pathlib_namespace.get("ntpath") is not pathlib_dependencies["ntpath"]
        or pathlib_namespace.get("posixpath") is not pathlib_dependencies["posixpath"]
        or pathlib_namespace.get("fnmatch") is not pathlib_dependencies["fnmatch"]
        or pathlib_namespace.get("warnings") is not pathlib_dependencies["warnings"]
        or namespace_of(pathlib_dependencies["io"]).get("open") is not _TRUSTED_OPEN
    ):
        raise RuntimeError("Trusted pathlib transitive module bindings were substituted.")
    for name in ("S_ISREG", "S_ISDIR", "S_ISLNK", "S_ISSOCK", "S_ISBLK", "S_ISCHR", "S_ISFIFO"):
        if pathlib_namespace.get(name) is not namespace_of(stat).get(name):
            raise RuntimeError(f"Trusted pathlib stat binding was substituted: {name}.")
    require_builtin(
        namespace_of(pathlib_dependencies["io"]).get("text_encoding"),
        modules=frozenset({"_io"}),
        names=frozenset({"text_encoding"}),
        label="io.text_encoding",
    )

    pure_path = _runtime_cast(pathlib_namespace.get("PurePath"))
    pure_posix_path = _runtime_cast(pathlib_namespace.get("PurePosixPath"))
    pure_windows_path = _runtime_cast(pathlib_namespace.get("PureWindowsPath"))
    path_class = _runtime_cast(pathlib_namespace.get("Path"))
    posix_path = _runtime_cast(pathlib_namespace.get("PosixPath"))
    windows_path = _runtime_cast(pathlib_namespace.get("WindowsPath"))
    pure_path_slots = (
        "_raw_paths",
        "_drv",
        "_root",
        "_tail_cached",
        "_str",
        "_str_normcase_cached",
        "_parts_normcase_cached",
        "_lines_cached",
        "_hash",
    )
    pure_path = require_source_class(
        pathlib,
        "PurePath",
        bases=(object_type,),
        mro=(pure_path, object_type),
        slots=pure_path_slots,
        allowed_nonmethods=frozenset({"_flavour"}),
        expected_defaults=MappingProxyType(
            {
                name: (None, None)
                for name in (
                    "__new__",
                    "__init__",
                    "__str__",
                    "__fspath__",
                    "__eq__",
                    "__hash__",
                    "__truediv__",
                    "joinpath",
                    "with_segments",
                    "as_posix",
                    "with_suffix",
                )
            }
            | {"relative_to": (None, {"walk_up": False})}
        ),
    )
    pure_posix_path = require_source_class(
        pathlib,
        "PurePosixPath",
        bases=(pure_path,),
        mro=(pure_posix_path, pure_path, object_type),
        slots=(),
        allowed_nonmethods=frozenset({"_flavour"}),
    )
    pure_windows_path = require_source_class(
        pathlib,
        "PureWindowsPath",
        bases=(pure_path,),
        mro=(pure_windows_path, pure_path, object_type),
        slots=(),
        allowed_nonmethods=frozenset({"_flavour"}),
    )
    path_class = require_source_class(
        pathlib,
        "Path",
        bases=(pure_path,),
        mro=(path_class, pure_path, object_type),
        slots=(),
        expected_defaults=MappingProxyType(
            {
                "__new__": (None, None),
                "__init__": (None, None),
                "resolve": ((False,), None),
                "read_bytes": (None, None),
                "open": (("r", -1, None, None, None), None),
                "stat": (None, {"follow_symlinks": True}),
                "lstat": (None, None),
                "is_file": (None, None),
                "is_symlink": (None, None),
                "is_junction": (None, None),
                "mkdir": ((511, False, False), None),
                "rmdir": (None, None),
                "unlink": ((False,), None),
            }
        ),
    )
    posix_path = require_source_class(
        pathlib,
        "PosixPath",
        bases=(path_class, pure_posix_path),
        mro=(posix_path, path_class, pure_posix_path, pure_path, object_type),
        slots=(),
    )
    windows_path = require_source_class(
        pathlib,
        "WindowsPath",
        bases=(path_class, pure_windows_path),
        mro=(windows_path, path_class, pure_windows_path, pure_path, object_type),
        slots=(),
    )
    if (
        namespace_of(pure_path).get("_flavour") is not os.path
        or namespace_of(pure_posix_path).get("_flavour") is not pathlib_dependencies["posixpath"]
        or namespace_of(pure_windows_path).get("_flavour") is not pathlib_dependencies["ntpath"]
    ):
        raise RuntimeError("Trusted pathlib flavour bindings were substituted.")

    pathlib_source = physical_path("pathlib.py")
    with open_file(pathlib_source, "rb") as pathlib_handle:
        expected_pathlib_bytes = pathlib_handle.read()
    concrete_path = windows_path if os.name == "nt" else posix_path
    path_probe = path_class(pathlib_source)
    resolved_probe = path_probe.resolve(strict=True)
    native_status = os.stat(pathlib_source, follow_symlinks=False)
    path_status = path_probe.stat(follow_symlinks=False)
    if (
        exact_type(path_probe) is not concrete_path
        or exact_type(resolved_probe) is not concrete_path
        or os.fspath(path_probe) != pathlib_source
        or os.path.normcase(os.fspath(resolved_probe)) != os.path.normcase(pathlib_source)
        or path_probe.read_bytes() != expected_pathlib_bytes
        or (path_status.st_dev, path_status.st_ino, path_status.st_mode)
        != (native_status.st_dev, native_status.st_ino, native_status.st_mode)
        or not path_probe.is_file()
        or path_probe.is_symlink()
        or path_probe.is_junction()
    ):
        raise RuntimeError("Trusted pathlib classes failed physical known-answer checks.")

    abc_module = require_source_module(
        sys.modules.get("abc"),
        name="abc",
        relative="abc.py",
    )
    abc_namespace = namespace_of(abc_module)
    abc_meta = _runtime_cast(abc_namespace.get("ABCMeta"))
    abc_base = _runtime_cast(abc_namespace.get("ABC"))
    abc_meta = require_source_class(
        abc_module,
        "ABCMeta",
        bases=(exact_type,),
        mro=(abc_meta, exact_type, object_type),
        slots=None,
        expected_metaclass=exact_type,
        generated_nonmethods=frozenset(),
    )
    abc_base = require_source_class(
        abc_module,
        "ABC",
        bases=(object_type,),
        mro=(abc_base, object_type),
        slots=(),
        allowed_nonmethods=frozenset({"__abstractmethods__", "_abc_impl"}),
        expected_metaclass=abc_meta,
    )

    contextlib_namespace = namespace_of(contextlib)
    generator_base = _runtime_cast(contextlib_namespace.get("_GeneratorContextManagerBase"))
    abstract_context = _runtime_cast(contextlib_namespace.get("AbstractContextManager"))
    context_decorator = _runtime_cast(contextlib_namespace.get("ContextDecorator"))
    generator_context = _runtime_cast(contextlib_namespace.get("_GeneratorContextManager"))
    generator_base = require_source_class(
        contextlib,
        "_GeneratorContextManagerBase",
        bases=(object_type,),
        mro=(generator_base, object_type),
        slots=None,
        expected_defaults=MappingProxyType(
            {"__init__": (None, None), "_recreate_cm": (None, None)}
        ),
    )
    abstract_context = require_source_class(
        contextlib,
        "AbstractContextManager",
        bases=(abc_base,),
        mro=(abstract_context, abc_base, object_type),
        slots=None,
        allowed_nonmethods=frozenset({"__class_getitem__", "__abstractmethods__", "_abc_impl"}),
        expected_metaclass=abc_meta,
        expected_defaults=MappingProxyType(
            {
                "__enter__": (None, None),
                "__exit__": (None, None),
                "__subclasshook__": (None, None),
            }
        ),
    )
    context_decorator = require_source_class(
        contextlib,
        "ContextDecorator",
        bases=(object_type,),
        mro=(context_decorator, object_type),
        slots=None,
        expected_defaults=MappingProxyType(
            {"_recreate_cm": (None, None), "__call__": (None, None)}
        ),
    )
    generator_context = require_source_class(
        contextlib,
        "_GeneratorContextManager",
        bases=(generator_base, abstract_context, context_decorator),
        mro=(
            generator_context,
            generator_base,
            abstract_context,
            abc_base,
            context_decorator,
            object_type,
        ),
        slots=None,
        allowed_nonmethods=frozenset({"__abstractmethods__", "_abc_impl"}),
        expected_metaclass=abc_meta,
        generated_nonmethods=frozenset(),
        expected_defaults=MappingProxyType({"__enter__": (None, None), "__exit__": (None, None)}),
    )
    trusted_contextmanager = require_python_function(contextlib, "contextmanager")
    if contextmanager is not trusted_contextmanager:
        raise RuntimeError("Trusted contextmanager alias was substituted before sealing.")
    context_marker = object_type()
    context_events: list[str] = []

    def context_probe() -> Iterator[object]:
        context_events.append("enter")
        try:
            yield context_marker
        finally:
            context_events.append("exit")

    context_factory = trusted_contextmanager(context_probe)
    context_instance = context_factory()
    if exact_type(context_instance) is not generator_context:
        raise RuntimeError("Trusted context-manager constructor crossed its source boundary.")
    with context_instance as entered_marker:
        if entered_marker is not context_marker or context_events != ["enter"]:
            raise RuntimeError("Trusted context-manager failed its entry known-answer check.")
    if context_events != ["enter", "exit"]:
        raise RuntimeError("Trusted context-manager failed its exit known-answer check.")

    sha1 = require_builtin(
        hashlib.sha1,
        modules=frozenset({"_hashlib", "_sha1"}),
        names=frozenset({"openssl_sha1", "sha1"}),
        label="hashlib.sha1",
    )
    sha256 = require_builtin(
        hashlib.sha256,
        modules=frozenset({"_hashlib", "_sha256"}),
        names=frozenset({"openssl_sha256", "sha256"}),
        label="hashlib.sha256",
    )
    normalize = require_builtin(
        unicodedata.normalize,
        modules=frozenset({"unicodedata"}),
        names=frozenset({"normalize"}),
        label="unicodedata.normalize",
    )
    decompress = require_builtin(
        zlib.decompress,
        modules=frozenset({"zlib"}),
        names=frozenset({"decompress"}),
        label="zlib.decompress",
    )
    for module, names in (
        (
            os.path,
            (
                "dirname",
                "isjunction",
                "realpath",
                "splitroot",
                "splitdrive",
                "normcase",
                "isabs",
                "join",
            ),
        ),
        (os, ("fsencode", "fsdecode")),
        (
            platform,
            (
                "python_build",
                "python_compiler",
                "python_implementation",
                "python_version",
                "_sys_version",
            ),
        ),
        (re, ("fullmatch", "_compile")),
        (tempfile, ("gettempdir", "mkdtemp", "_gettempdir", "_get_default_tempdir")),
        (json, ("dumps",)),
        (functools, ("lru_cache",)),
        (contextlib, ("contextmanager",)),
        (inspect, ("currentframe",)),
        (
            dataclasses,
            ("dataclass", "field", "fields", "is_dataclass", "replace", "make_dataclass"),
        ),
        (threading, ("RLock",)),
    ):
        for name in names:
            require_python_function(module, name)
    if os.name == "nt":
        ntpath_namespace = namespace_of(pathlib_dependencies["ntpath"])
        for name in ("_getfinalpathname", "_getvolumepathname"):
            require_builtin(
                ntpath_namespace.get(name),
                modules=frozenset({"nt"}),
                names=frozenset({name}),
                label=f"ntpath.{name}",
            )

    encoder_type = _runtime_cast(namespace_of(encoder_module).get("JSONEncoder"))
    if (
        encoder_type.__class__ is not ().__class__.__class__
        or encoder_type is not namespace_of(json).get("JSONEncoder")
        or encoder_type.__module__ != "json.encoder"
        or _runtime_cast(encoder_type).__qualname__ != "JSONEncoder"
    ):
        raise RuntimeError("Trusted JSON encoder type was substituted before sealing.")
    for name in ("__init__", "default", "encode", "iterencode"):
        method = namespace_of(encoder_type).get(name)
        if method.__class__ is not exact_function_type or method.__globals__ is not namespace_of(
            encoder_module
        ):
            raise RuntimeError(f"Trusted JSON encoder method was substituted: {name}.")
        source_path, compiled_by_location = module_manifests[encoder_module]
        matches = compiled_by_location.get(
            (method.__code__.co_qualname, method.__code__.co_firstlineno), []
        )
        if (
            method.__code__.co_filename != source_path
            or len(matches) != 1
            or normalized_code(method.__code__) != normalized_code(matches[0])
        ):
            raise RuntimeError(f"Trusted JSON encoder method differs from source: {name}.")
    require_python_function(encoder_module, "_make_iterencode")

    default_temp = _runtime_cast(get_attribute(tempfile, "_get_default_tempdir"))()
    if tempfile.tempdir is not None and (
        tempfile.tempdir.__class__ is not str or tempfile.tempdir != default_temp
    ):
        raise RuntimeError("The process temporary root was caller-overridden before sealing.")
    version_text = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    build_start = sys.version.find("(")
    build_end = sys.version.find(")", build_start + 1)
    compiler_start = sys.version.rfind("[")
    compiler_end = sys.version.rfind("]")
    if min(build_start, build_end, compiler_start, compiler_end) < 0:
        raise RuntimeError("The interpreter version string has no exact build/compiler boundary.")
    build_number, build_separator, build_date = sys.version[build_start + 1 : build_end].partition(
        ", "
    )
    if not build_separator:
        raise RuntimeError("The interpreter version string has no exact build date boundary.")
    build_date = build_date.replace(", ", " ", 1)
    implementation_name = {"cpython": "CPython", "pypy": "PyPy"}.get(sys.implementation.name)
    if implementation_name is None or (
        platform.python_version() != version_text
        or platform.python_implementation() != implementation_name
        or platform.python_compiler() != sys.version[compiler_start + 1 : compiler_end]
        or platform.python_build() != (build_number, build_date)
    ):
        raise RuntimeError("Trusted platform helpers failed their direct sys-value reconciliation.")
    protocol_module = sys.modules.get("research_decision_engine.benchmarks.broader_protocol")
    if protocol_module.__class__ is not exact_module_type:
        raise RuntimeError("Trusted protocol module is unavailable during production sealing.")
    protocol_json = get_attribute(protocol_module, "json", None)
    protocol_hashlib = get_attribute(protocol_module, "hashlib", None)
    protocol_path = get_attribute(protocol_module, "Path", None)
    if (
        protocol_json is not json
        or protocol_hashlib is not hashlib
        or protocol_path is not Path
        or get_attribute(protocol_module, "PROTOCOL_CHECKPOINT", None) != PROTOCOL_CHECKPOINT
        or get_attribute(protocol_module, "protocol_hash", None) is not protocol_hash
        or get_attribute(protocol_module, "repository_root", None) is not repository_root
    ):
        raise RuntimeError("Trusted protocol globals were substituted before sealing.")
    canonical_json_value = get_attribute(protocol_module, "canonical_json_bytes", None)
    if (
        canonical_json_value.__class__ is not exact_function_type
        or canonical_json_value.__globals__ is not namespace_of(protocol_module)
    ):
        raise RuntimeError("Trusted canonical JSON function was substituted before sealing.")
    canonical_json = _runtime_cast(canonical_json_value)
    if (
        canonical_json({"b": [2, 1], "a": "\u00e9"}) != b'{"a":"\xc3\xa9","b":[2,1]}'
        or protocol_hash("rde-provenance-kat/v1", {"b": [2, 1], "a": "\u00e9"})
        != "f5a1734c15caf696fb0a7331c9b8f85765a8e0bd54b88f7573567ac3e2b1aa2c"
    ):
        raise RuntimeError("Trusted canonical JSON/protocol known-answer check failed.")
    if (
        sha1(b"abc", usedforsecurity=False).hexdigest()
        != "a9993e364706816aba3e25717850c26c9cd0d89d"
        or sha256(b"abc").hexdigest()
        != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        or normalize("NFC", "e\u0301") != "\u00e9"
        or decompress(b"x\x9cKLJ\x06\x00\x02M\x01'") != b"abc"
    ):
        raise RuntimeError("Trusted external runtime known-answer checks failed.")


_validate_external_runtime_provenance()

EVIDENCE_CONTRACT_CHECKPOINT: Final = hashlib.sha256(
    b"RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1\0EVIDENCE_CONTRACT\0"
).hexdigest()[:40]
STUDY_ID: Final = "broader-closed-loop-replication/v1"
PERMITTED_FINAL_EVIDENCE_FILENAMES: Final = (
    "pytest-junit.xml",
    "SMOKE_VALIDATION_REPORT.md",
    "smoke_validation.json",
    "validation_bindings.json",
)

type TrustDomain = Literal["production", "fixture"]
type PlanKind = Literal["pytest", "oracle", "execution_specification"]
type PlanRole = Literal[
    "pytest",
    "oracle",
    "primary_smoke",
    "altered_order_replay",
    "fixture_primary",
    "fixture_replay",
]
type IssuerRole = Literal[
    "validation_authority",
    "pytest_plan",
    "oracle_plan",
    "execution_specification",
]
type BindingState = Literal["authority_unbound", "authority_bound", "stale"]
type RunState = Literal["reserved", "authority_bound", "terminal"]
type PreparationState = Literal["issued", "active", "tombstoned"]
type BindingFailurePoint = Literal[
    "after_run_reservation_before_ledger",
    "control_directory_acquisition_failure",
    "after_control_directory_creation_before_ledger",
    "after_executor_issuance_before_ledger",
    "junit_acquisition_failure",
    "after_junit_acquisition_before_identity",
    "after_junit_ownership_before_ledger",
    "after_plan_0_allocation",
    "after_plan_1_allocation",
    "after_plan_2_allocation",
    "after_plan_3_allocation",
    "after_plan_4_allocation",
    "after_plan_5_allocation",
    "after_authority_allocation_before_binding",
    "before_authority_construction",
    "validate_plan_0",
    "validate_plan_1",
    "validate_plan_2",
    "validate_plan_3",
    "validate_plan_4",
    "validate_plan_5",
    "after_authority_construction",
    "before_publication",
    "publication_failure",
    "after_publication",
]
type _DependencyEnvironmentIdentity = tuple[tuple[str, str, str, str], ...]

_H64_PATTERN = r"[0-9a-f]{64}\Z"
_GIT40_PATTERN = r"[0-9a-f]{40}\Z"


def _opaque_runtime_callable(function: Callable[..., object]) -> Callable[..., object]:
    """Hide production closure state behind a non-caching C call boundary."""

    _validate_runtime_bootstrap()
    source = _TRUSTED_GETATTR(function, "__wrapped__", function)
    if source.__class__ is not FunctionType:
        raise RuntimeError("Opaque runtime source attestation requires one Python function.")
    wrapper_constructor: Any = _TRUSTED_LRU_WRAPPER_TYPE
    wrapped = wrapper_constructor(function, 0, False, None)
    if wrapped.__class__ is not _TRUSTED_LRU_WRAPPER_TYPE:
        raise RuntimeError("Opaque runtime construction crossed its native trust boundary.")
    wrapped._rde_opaque_source = (  # type: ignore[attr-defined]
        source.__module__,
        source.__code__.co_qualname,
        source.__code__.co_firstlineno,
        source.__code__,
    )
    return _runtime_cast(wrapped)  # type: ignore[no-any-return]


class P2Stage1Error(ValueError):
    """Deterministic fail-closed Stage-1 validation failure."""

    def __init__(self, code: str, message: str, *, layer: str) -> None:
        super().__init__(message)
        self.error_code = code
        self.validation_layer = layer
        self.workload_started = False
        self.scoring_entered = False
        self.scientific_output_entered = False
        self.evidence_checkpointed = False
        self.independent_review_status = "pending"
        self.safe_for_full_replication = False
        self.full_replication_authorized = False


def _error(code: str, message: str, *, layer: str) -> NoReturn:
    raise P2Stage1Error(code, message, layer=layer)


@dataclass(frozen=True, slots=True)
class FileProjection:
    byte_count: int
    path: str
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"byte_count": self.byte_count, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ImplementationProjection:
    dependency_lock_sha256: str
    implementation_commit: str
    implementation_diff_sha256: str
    implementation_tree_sha256: str
    source_bundle_sha256: str
    test_bundle_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "implementation_commit": self.implementation_commit,
            "implementation_diff_sha256": self.implementation_diff_sha256,
            "implementation_tree_sha256": self.implementation_tree_sha256,
            "source_bundle_sha256": self.source_bundle_sha256,
            "test_bundle_sha256": self.test_bundle_sha256,
        }


@dataclass(frozen=True, slots=True)
class InterpreterIdentityProjection:
    cache_tag: str | None
    compiler: str
    executable_path: str
    executable_sha256: str
    implementation: str
    python_version: str

    def as_dict(self) -> dict[str, object]:
        return {
            "cache_tag": self.cache_tag,
            "compiler": self.compiler,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "implementation": self.implementation,
            "python_version": self.python_version,
        }


@dataclass(frozen=True, slots=True)
class PlatformIdentityProjection:
    machine: str
    platform: str
    release: str
    system: str
    version: str

    def as_dict(self) -> dict[str, object]:
        return {
            "machine": self.machine,
            "platform": self.platform,
            "release": self.release,
            "system": self.system,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class RuntimeProjection:
    base_interpreter: FileProjection
    interpreter: FileProjection
    interpreter_identity: InterpreterIdentityProjection
    interpreter_identity_sha256: str
    platform_identity: PlatformIdentityProjection
    platform_identity_sha256: str
    python_build_date: str
    python_build_number: str
    schema_version: str = "broader-replication-validation-runtime/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "base_interpreter": self.base_interpreter.as_dict(),
            "interpreter": self.interpreter.as_dict(),
            "interpreter_identity": self.interpreter_identity.as_dict(),
            "interpreter_identity_sha256": self.interpreter_identity_sha256,
            "platform_identity": self.platform_identity.as_dict(),
            "platform_identity_sha256": self.platform_identity_sha256,
            "python_build_date": self.python_build_date,
            "python_build_number": self.python_build_number,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CallableProjection:
    bytecode_sha256: str
    callable_type: str
    module_name: str
    qualname: str
    source: FileProjection
    schema_version: str = "broader-replication-validation-callable/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "bytecode_sha256": self.bytecode_sha256,
            "callable_type": self.callable_type,
            "module_name": self.module_name,
            "qualname": self.qualname,
            "schema_version": self.schema_version,
            "source": self.source.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class IssuerProjection:
    entry_point: str
    evidence_contract_checkpoint: str
    implementation: ImplementationProjection
    protocol_checkpoint: str
    role: IssuerRole
    runtime: RuntimeProjection
    runtime_identity: str
    trust_domain: TrustDomain
    schema_version: str = "broader-replication-validation-issuer/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "entry_point": self.entry_point,
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "implementation": self.implementation.as_dict(),
            "protocol_checkpoint": self.protocol_checkpoint,
            "role": self.role,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "trust_domain": self.trust_domain,
        }


@dataclass(frozen=True, slots=True)
class Layer0Context:
    implementation: ImplementationProjection
    runtime: RuntimeProjection
    runtime_identity: str
    validation_authority_issuer: IssuerProjection
    validation_authority_issuer_identity: str
    pytest_plan_issuer: IssuerProjection
    pytest_plan_issuer_identity: str
    oracle_plan_issuer: IssuerProjection
    oracle_plan_issuer_identity: str
    execution_specification_issuer: IssuerProjection
    execution_specification_issuer_identity: str
    evidence_generator: CallableProjection
    evidence_generator_entry_point: str
    evidence_generator_identity: str


@dataclass(frozen=True, slots=True)
class ValidationAuthorityProjection:
    evidence_contract_checkpoint: str
    evidence_generator_identity: str
    implementation: ImplementationProjection
    oracle_plan_id: str
    permitted_final_evidence_filenames: tuple[str, ...]
    primary_smoke_execution_specification_id: str
    production_fixture_execution_specification_ids: tuple[str, str]
    protocol_checkpoint: str
    pytest_plan_id: str
    replay_execution_specification_id: str
    runtime: RuntimeProjection
    runtime_identity: str
    validation_run_id: str
    schema_version: str = "broader-replication-validation-authority/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "evidence_generator_identity": self.evidence_generator_identity,
            "implementation": self.implementation.as_dict(),
            "oracle_plan_id": self.oracle_plan_id,
            "permitted_final_evidence_filenames": list(self.permitted_final_evidence_filenames),
            "primary_smoke_execution_specification_id": (
                self.primary_smoke_execution_specification_id
            ),
            "production_fixture_execution_specification_ids": list(
                self.production_fixture_execution_specification_ids
            ),
            "protocol_checkpoint": self.protocol_checkpoint,
            "pytest_plan_id": self.pytest_plan_id,
            "replay_execution_specification_id": self.replay_execution_specification_id,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "validation_run_id": self.validation_run_id,
        }


class _OpaqueCapability:
    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        if cls.__module__ == __name__:
            return
        raise TypeError("P2 Stage-1 capabilities cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("P2 Stage-1 capabilities cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("P2 Stage-1 capabilities cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("P2 Stage-1 capabilities cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("P2 Stage-1 capabilities cannot be serialized.")


class _ProductionPreparationCapability(_OpaqueCapability):
    """Exact one-shot authority that exists only inside the installed entry route."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Production preparation capabilities have no public constructor.")


class ValidationRun(_OpaqueCapability):
    """Opaque registry-backed P2 validation-run identity."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Production validation runs have no public constructor.")


class _FixtureValidationRun(_OpaqueCapability):
    """Disjoint nonproduction validation-run capability."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Fixture validation runs are issued only by the fixture registry.")


class ValidationAuthority(_OpaqueCapability):
    """Opaque production authority over one exact ordered six-plan set."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Validation authority has no public constructor.")


class _FixtureValidationAuthority(_OpaqueCapability):
    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Fixture validation authority has no public constructor.")


class _ProductionSessionToken(_OpaqueCapability):
    """Internal session owner; the installed production entry never returns it."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Production preparation sessions have no public constructor.")


@dataclass(frozen=True, slots=True)
class _PlanDraft:
    """Immutable, authority-free plan prepared before one atomic publication."""

    capability: object
    kind: PlanKind
    role: PlanRole
    persistent_id: str
    validation_run: ValidationRun | _FixtureValidationRun
    validation_run_id: str
    projection: object
    fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if re.fullmatch(_H64_PATTERN, self.persistent_id) is None:
            _error("PLAN_ID_MISMATCH", "Plan identity is not H64.", layer="plan_identities")
        as_dict = getattr(self.projection, "as_dict", None)
        if not callable(as_dict):
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "A plan draft requires one closed projection.",
                layer="live_issued_plan_binding",
            )
        projection_mapping = as_dict()
        if type(projection_mapping) is not dict:
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "A plan projection must render one defensive canonical mapping.",
                layer="live_issued_plan_binding",
            )
        object.__setattr__(
            self,
            "fingerprint",
            protocol_hash(
                "validation_evidence_live_plan_fingerprint/v1",
                {
                    "kind": self.kind,
                    "persistent_id": self.persistent_id,
                    "projection": projection_mapping,
                    "role": self.role,
                    "validation_run_id": self.validation_run_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class _SixPlanSet:
    pytest: _PlanDraft
    oracle: _PlanDraft
    primary_smoke: _PlanDraft
    altered_order_replay: _PlanDraft
    fixture_primary: _PlanDraft
    fixture_replay: _PlanDraft

    def ordered(self) -> tuple[_PlanDraft, ...]:
        return (
            self.pytest,
            self.oracle,
            self.primary_smoke,
            self.altered_order_replay,
            self.fixture_primary,
            self.fixture_replay,
        )


@dataclass(frozen=True, slots=True)
class _BindingRecord:
    capability: ValidationAuthority | _FixtureValidationAuthority
    projection: ValidationAuthorityProjection
    validation_authority_id: str
    validation_run_id: str
    plans: _SixPlanSet
    trust_domain: TrustDomain


@dataclass(frozen=True, slots=True, eq=False)
class _OwnedControlDirectory:
    path: Path
    device_id: int
    file_id: int

    def __copy__(self) -> NoReturn:
        raise TypeError("Owned control-directory records cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Owned control-directory records cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Owned control-directory records cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Owned control-directory records cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class _ProvisionalControlDirectory:
    """Exact internal token retained immediately after ``mkdtemp`` succeeds."""

    path: Path

    def __copy__(self) -> NoReturn:
        raise TypeError("Provisional control-directory records cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Provisional control-directory records cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Provisional control-directory records cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Provisional control-directory records cannot be serialized.")


type _PhysicalOwnershipState = Literal[
    "none",
    "acquiring",
    "acquired",
    "centrally_registered",
    "retained",
    "transferred_for_later_execution",
    "released",
    "cleanup_pending",
    "cleanup_complete",
]
type _AuthorityOwnershipState = Literal[
    "none",
    "allocating",
    "allocated",
    "bound",
    "published",
    "tombstoned",
]


@dataclass(frozen=True, slots=True)
class _GitIndexEntry:
    path: str
    mode: str
    object_id: str


@dataclass(frozen=True, slots=True)
class _GitSnapshot:
    commit: str
    root_tree: str
    index_sha256: str
    entries: tuple[_GitIndexEntry, ...]
    worktree_identities: tuple[tuple[str, str], ...]
    scoped_blobs: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True, slots=True)
class _SessionResources:
    token: _ProductionSessionToken
    control_directory: _OwnedControlDirectory
    control_directory_state: Literal["transferred_for_later_execution"]
    junit_handle: object
    junit_ownership_state: Literal["transferred_for_later_execution"]
    executor_implementation: object
    plan_capabilities: tuple[object, ...]
    published_authority: ValidationAuthority
    executor_invalidator: Callable[..., None]
    executor_is_current: Callable[[object], bool]
    junit_cleanup: Callable[..., None]
    junit_is_open: Callable[[object], bool]
    junit_is_cleaned: Callable[[object], bool]
    remove_control_directory: Callable[[object], None]


@dataclass(frozen=True, slots=True)
class _PendingSessionResources:
    token: _ProductionSessionToken
    control_directory: _OwnedControlDirectory | _ProvisionalControlDirectory | None
    control_directory_state: _PhysicalOwnershipState
    junit_handle: object | None
    junit_ownership_state: _PhysicalOwnershipState
    executor_implementation: object | None
    plan_allocation_intent: tuple[PlanKind, PlanRole] | None
    plan_capabilities: tuple[object, ...]
    plan_drafts: tuple[_PlanDraft, ...]
    authority_state: _AuthorityOwnershipState
    authority_capability: ValidationAuthority | None
    unpublished_binding: _BindingRecord | None
    logical_resources_tombstoned: bool
    generation: int
    executor_invalidator: Callable[..., None]
    executor_is_current: Callable[[object], bool]
    junit_cleanup: Callable[..., None]
    junit_is_open: Callable[[object], bool]
    junit_is_cleaned: Callable[[object], bool]
    remove_control_directory: Callable[[object], None]


@dataclass(frozen=True, slots=True)
class _ProductionComponentIssuers:
    executor_implementation: Callable[..., object]
    pytest_plan: Callable[..., tuple[_PlanDraft, object]]
    pytest_runtime_validate: Callable[[], None]
    oracle_plan: Callable[..., _PlanDraft]
    execution_plans: Callable[..., tuple[_PlanDraft, ...]]
    executor_invalidator: Callable[..., None]
    executor_is_current: Callable[[object], bool]
    junit_cleanup: Callable[..., None]
    junit_is_open: Callable[[object], bool]
    junit_is_cleaned: Callable[[object], bool]
    anchors: tuple[tuple[ModuleType, str, Callable[..., object], object], ...]
    value_anchors: tuple[tuple[ModuleType, str, object], ...] = ()
    source_anchors: tuple[tuple[Path, bytes], ...] = ()
    transitive_validate: Callable[[], None] | None = None

    def validate(self) -> None:
        for role, function in (
            ("executor_implementation", self.executor_implementation),
            ("pytest_plan", self.pytest_plan),
            ("pytest_runtime_validate", self.pytest_runtime_validate),
            ("oracle_plan", self.oracle_plan),
            ("execution_plans", self.execution_plans),
            ("executor_invalidator", self.executor_invalidator),
            ("executor_is_current", self.executor_is_current),
            ("junit_cleanup", self.junit_cleanup),
            ("junit_is_open", self.junit_is_open),
            ("junit_is_cleaned", self.junit_is_cleaned),
        ):
            if not _production_component_callable_is_registered(role, function):
                _error(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Unregistered production component callable rejected: {role}.",
                    layer="validation_authority",
                )
        self.pytest_runtime_validate()
        if self.transitive_validate is not None:
            self.transitive_validate()
        for module, name, function, code in self.anchors:
            if (
                getattr(module, name, None) is not function
                or getattr(function, "__code__", None) is not code
            ):
                _error(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted Stage-1 component issuer was replaced: {module.__name__}.{name}.",
                    layer="validation_authority",
                )
        for module, name, expected in self.value_anchors:
            if getattr(module, name, None) is not expected:
                _error(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted Stage-1 component value was replaced: {module.__name__}.{name}.",
                    layer="validation_authority",
                )
        for source_path, expected_bytes in self.source_anchors:
            try:
                current_bytes = source_path.read_bytes()
            except OSError as error:
                raise P2Stage1Error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Trusted Stage-1 component source became unreadable.",
                    layer="validation_authority",
                ) from error
            if current_bytes != expected_bytes:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted Stage-1 component source changed: {source_path}.",
                    layer="validation_authority",
                )


@dataclass(frozen=True, slots=True)
class _ProductionPreparationCollaborators:
    consume: Callable[..., None]
    derive_context: Callable[..., Layer0Context]
    reserve_run: Callable[[_ProductionPreparationCapability], ValidationRun]
    create_control_directory: Callable[..., _OwnedControlDirectory]
    begin_physical_resource: Callable[..., None]
    transition_physical_resource: Callable[..., None]
    allocate_executor_implementation: Callable[..., object]
    confirm_executor_implementation: Callable[..., None]
    six_plan_set: Callable[[Sequence[_PlanDraft]], _SixPlanSet]
    prepare_binding: Callable[..., _BindingRecord]
    allocate_authority: Callable[..., object]
    record_unpublished_binding: Callable[..., None]
    run_id: Callable[[ValidationRun], str]
    require_run: Callable[..., _ProductionRunRecord]
    publish_binding: Callable[..., None]
    record_resources: Callable[..., None]
    abort: Callable[..., None]
    remove_control_directory: Callable[[object], None]
    replace_record: Callable[..., _ProductionRunRecord]
    resources_type: type[_SessionResources]
    authority_type: type[ValidationAuthority]
    error_type: type[P2Stage1Error]
    validate: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _PreparationRecord:
    capability: _ProductionPreparationCapability
    session_token: _ProductionSessionToken
    state: PreparationState
    validation_run_id: str | None = None
    registry_guard: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _ProductionRunRecord:
    capability: ValidationRun
    validation_run_id: str
    preparation: _ProductionPreparationCapability
    state: RunState
    plans: _SixPlanSet | None = None
    binding: _BindingRecord | None = None
    resources: _SessionResources | None = None
    resources_cleaned: bool = False
    registry_guard: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _FixtureRunRecord:
    capability: _FixtureValidationRun
    validation_run_id: str
    state: RunState


@dataclass(frozen=True, slots=True)
class _FixturePlanRecord:
    draft: _PlanDraft
    active: bool = True


@dataclass(frozen=True, slots=True)
class _FixtureAuthorityRecord:
    binding: _BindingRecord
    validation_run: _FixtureValidationRun
    active: bool = True


@dataclass(frozen=True, slots=True)
class _ProductionRegistrySummary:
    reserved_runs: int
    current_bound_runs: int
    terminal_runs: int
    complete_bindings: int
    terminal_complete_bindings: int
    complete_binding_plan_slots: int
    partial_binding_records: int
    current_plan_count: int
    current_authority_count: int
    retained_junit_handle_count: int
    resources_cleaned_count: int


_FIXTURE_RUN_RECORDS: dict[_FixtureValidationRun, _FixtureRunRecord] = {}
_FIXTURE_PLAN_RECORDS: dict[object, _FixturePlanRecord] = {}
_FIXTURE_AUTHORITY_RECORDS: dict[_FixtureValidationAuthority, _FixtureAuthorityRecord] = {}
_FIXTURE_RUN_IDS: set[str] = set()
_FIXTURE_REGISTRY_LOCK = _TRUSTED_RLOCK_TYPE()


def callable_projection(function: Callable[..., object]) -> tuple[CallableProjection, str]:
    """Build the exact frozen callable projection without invoking the callable."""

    code = getattr(function, "__code__", None)
    source_name = inspect.getsourcefile(function)
    if code is None or source_name is None:
        _error(
            "CALLABLE_IDENTITY_MISMATCH",
            "A frozen callable needs Python bytecode and a regular source file.",
            layer="callable_identity",
        )
    source_path = _strict_path(Path(source_name), require_file=True)
    raw = source_path.read_bytes()
    projection = CallableProjection(
        bytecode_sha256=hashlib.sha256(code.co_code).hexdigest(),
        callable_type=f"{type(function).__module__}.{type(function).__qualname__}",
        module_name=function.__module__,
        qualname=function.__qualname__,
        source=FileProjection(len(raw), str(source_path), hashlib.sha256(raw).hexdigest()),
    )
    return projection, protocol_hash("validation_evidence_callable/v1", projection.as_dict())


def issuer_projection(
    *,
    context_implementation: ImplementationProjection,
    runtime: RuntimeProjection,
    runtime_identity: str,
    role: IssuerRole,
    entry_point: str,
    trust_domain: TrustDomain,
) -> tuple[IssuerProjection, str]:
    projection = IssuerProjection(
        entry_point=entry_point,
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        implementation=context_implementation,
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        role=role,
        runtime=runtime,
        runtime_identity=runtime_identity,
        trust_domain=trust_domain,
    )
    return projection, protocol_hash("validation_evidence_issuer/v1", projection.as_dict())


def _validate_run_id(validation_run_id: str) -> None:
    if (
        not isinstance(validation_run_id, str)
        or re.fullmatch(_H64_PATTERN, validation_run_id) is None
    ):
        _error(
            "VALIDATION_RUN_ID_INVALID",
            "validation_run_id must be exactly 64 lowercase hexadecimal characters.",
            layer="validation_run_issuance",
        )


def _single_assignment_publish[K, V](
    registry: dict[K, V],
    key: K,
    value: V,
    *,
    failure_point: BindingFailurePoint | None,
) -> None:
    """The sole publication primitive shared by production and fixture binding."""

    if failure_point == "publication_failure":
        _error(
            "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
            "Injected publication failure occurred before the single assignment.",
            layer="issued_plan_binding",
        )
    registry[key] = value
    if failure_point == "after_publication":
        _error(
            "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
            "Injected failure occurred after complete single-assignment publication.",
            layer="issued_plan_binding",
        )


def _compiled_nested_function(
    raw_source: bytes,
    *,
    source_path: Path,
    function_name: str,
) -> CodeType:
    module_code = compile(
        raw_source,
        str(source_path),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    pending = [module_code]
    matches: list[CodeType] = []
    while pending:
        current = pending.pop()
        for value in current.co_consts:
            if isinstance(value, CodeType):
                pending.append(value)
                if value.co_name == function_name:
                    matches.append(value)
    if len(matches) != 1:
        raise RuntimeError(
            f"Trusted source does not define exactly one {function_name} code object."
        )
    return matches[0]


def _compiled_qualified_function(
    raw_source: bytes,
    *,
    source_path: Path,
    qualname: str,
) -> CodeType:
    module_code = _runtime_cast(
        _TRUSTED_COMPILE(
            raw_source,
            str(source_path),
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
    )
    pending = [module_code]
    matches: list[CodeType] = []
    while pending:
        current = pending.pop()
        for value in current.co_consts:
            if isinstance(value, CodeType):
                pending.append(value)
                if value.co_qualname == qualname:
                    matches.append(value)
    if len(matches) != 1:
        raise RuntimeError(f"Trusted source does not define exactly one {qualname} code object.")
    return matches[0]


def _install_production_component_source_authority() -> tuple[
    Callable[[str, Callable[..., object]], Callable[..., object]],
    Callable[[str, Callable[..., object]], Callable[..., object]],
    Callable[[str, object], bool],
    Callable[..., None],
]:
    """Create and retain the real inner functions for every critical component slot."""

    compile_source = _runtime_cast(_TRUSTED_COMPILE)
    module_vars = _runtime_cast(_TRUSTED_VARS)
    runtime_modules = sys.modules
    path_type = Path
    opaque_wrapper_type: Any = _TRUSTED_LRU_WRAPPER_TYPE
    sort_items = _runtime_cast(_TRUSTED_BUILTINS["sorted"])
    exact_type = _runtime_cast(_TRUSTED_BUILTINS["type"])
    validate_bootstrap = _validate_runtime_bootstrap
    allowed_roles = frozenset(
        {
            "executor_implementation",
            "execution_plans",
            "executor_invalidator",
            "executor_is_current",
            "pytest_plan",
            "pytest_runtime_validate",
            "oracle_plan",
            "junit_cleanup",
            "junit_is_open",
            "junit_is_cleaned",
        }
    )
    lock = _TRUSTED_RLOCK_TYPE()
    records: dict[
        str,
        tuple[
            object,
            FunctionType,
            CodeType,
            tuple[object, ...] | None,
            tuple[tuple[str, object], ...] | None,
            tuple[object, ...],
        ],
    ] = {}

    def function_state(
        function: FunctionType,
    ) -> tuple[
        CodeType,
        tuple[object, ...] | None,
        tuple[tuple[str, object], ...] | None,
        tuple[object, ...],
    ]:
        keyword_defaults = function.__kwdefaults__
        closure_values: list[object] = []
        for cell in function.__closure__ or ():
            try:
                closure_values.append(cell.cell_contents)
            except ValueError:
                closure_values.append(cell)
        return (
            function.__code__,
            function.__defaults__,
            None if keyword_defaults is None else tuple(sort_items(keyword_defaults.items())),
            tuple(closure_values),
        )

    def keyword_defaults_match(
        current: tuple[tuple[str, object], ...] | None,
        expected: tuple[tuple[str, object], ...] | None,
    ) -> bool:
        if current is None or expected is None:
            return current is expected
        return len(current) == len(expected) and all(
            current_name == expected_name and current_value is expected_value
            for (current_name, current_value), (expected_name, expected_value) in zip(
                current,
                expected,
                strict=True,
            )
        )

    def validate_registration(role: str, function: FunctionType) -> None:
        validate_bootstrap()
        if (
            exact_type(role) is not str
            or role not in allowed_roles
            or exact_type(function) is not FunctionType
        ):
            raise RuntimeError("Invalid production component source registration.")
        module = runtime_modules.get(function.__module__)
        if (
            exact_type(module) is not ModuleType
            or not function.__module__.startswith("research_decision_engine.")
            or function.__globals__ is not module_vars(module)
            or function.__code__.co_filename.startswith("<")
        ):
            raise RuntimeError("Production component source is not one exact project function.")

    def store(role: str, public: object, function: FunctionType) -> None:
        if public is not function and public.__class__ is not opaque_wrapper_type:
            raise RuntimeError("Production component public boundary is not exact-issued.")
        code, defaults, keyword_defaults, closure_values = function_state(function)
        with lock:
            if role in records:
                raise RuntimeError(f"Production component role was already sealed: {role}.")
            records[role] = (
                public,
                function,
                code,
                defaults,
                keyword_defaults,
                closure_values,
            )

    def seal(role: str, function: Callable[..., object]) -> Callable[..., object]:
        validate_bootstrap()
        if exact_type(function) is not FunctionType:
            raise RuntimeError("Production component source is not an exact Python function.")
        source: FunctionType = _runtime_cast(function)
        validate_registration(role, source)
        wrapped = _runtime_cast(opaque_wrapper_type(source, 0, False, None))
        if wrapped.__class__ is not opaque_wrapper_type:
            raise RuntimeError("Production component crossed its native opaque boundary.")
        wrapped._rde_opaque_source = (
            source.__module__,
            source.__code__.co_qualname,
            source.__code__.co_firstlineno,
            source.__code__,
        )
        store(role, wrapped, source)
        return _runtime_cast(wrapped)  # type: ignore[no-any-return]

    def register(role: str, function: Callable[..., object]) -> Callable[..., object]:
        validate_bootstrap()
        if exact_type(function) is not FunctionType:
            raise RuntimeError("Production component source is not an exact Python function.")
        source: FunctionType = _runtime_cast(function)
        validate_registration(role, source)
        store(role, source, source)
        return source

    def is_registered(role: str, public: object) -> bool:
        validate_bootstrap()
        with lock:
            row = records.get(role)
            if row is None or row[0] is not public:
                return False
            function = row[1]
            if public is not function and public.__class__ is not opaque_wrapper_type:
                return False
            code, defaults, keyword_defaults, closure_values = function_state(function)
            return (
                code is row[2]
                and defaults is row[3]
                and keyword_defaults_match(keyword_defaults, row[4])
                and len(closure_values) == len(row[5])
                and all(
                    current is expected
                    for current, expected in zip(closure_values, row[5], strict=True)
                )
            )

    def validate_sources(*, root: Path, trusted_blobs: Mapping[str, bytes]) -> None:
        validate_bootstrap()
        with lock:
            rows = tuple(records.items())
        registered_roles = frozenset(role for role, _ in rows)
        if registered_roles != allowed_roles:
            raise P2Stage1Error(
                "CALLABLE_IDENTITY_MISMATCH",
                "The exact production component source set is incomplete.",
                layer="validation_authority",
            )
        compiled: dict[Path, dict[tuple[str, int], list[CodeType]]] = {}
        for role, row in rows:
            public, function, code, defaults, keyword_defaults, _closure_values = row
            if not is_registered(role, public):
                raise P2Stage1Error(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Production component source state changed: {role}.",
                    layer="validation_authority",
                )
            module = runtime_modules.get(function.__module__)
            if exact_type(module) is not ModuleType or function.__globals__ is not module_vars(
                module
            ):
                raise P2Stage1Error(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Production component defining module changed: {role}.",
                    layer="validation_authority",
                )
            try:
                source_path = path_type(code.co_filename).resolve(strict=True)
                relative = source_path.relative_to(root).as_posix()
            except (OSError, ValueError) as error:
                raise P2Stage1Error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Production component source escaped the trusted repository: {role}.",
                    layer="validation_authority",
                ) from error
            expected_bytes = trusted_blobs.get(relative)
            if expected_bytes is None or source_path.read_bytes() != expected_bytes:
                raise P2Stage1Error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Production component source differs from trusted Git: {role}.",
                    layer="validation_authority",
                )
            compiled_by_location = compiled.get(source_path)
            if compiled_by_location is None:
                module_code = compile_source(
                    expected_bytes,
                    str(source_path),
                    "exec",
                    dont_inherit=True,
                    optimize=sys.flags.optimize,
                )
                compiled_by_location = {}
                pending = [module_code]
                while pending:
                    parent = pending.pop()
                    for constant in parent.co_consts:
                        if exact_type(constant) is CodeType:
                            pending.append(constant)
                            compiled_by_location.setdefault(
                                (constant.co_qualname, constant.co_firstlineno), []
                            ).append(constant)
                compiled[source_path] = compiled_by_location
            matches = compiled_by_location.get((code.co_qualname, code.co_firstlineno), [])
            if (
                len(matches) != 1
                or matches[0] != code
                or function.__defaults__ is not defaults
                or not keyword_defaults_match(
                    None
                    if function.__kwdefaults__ is None
                    else tuple(sort_items(function.__kwdefaults__.items())),
                    keyword_defaults,
                )
            ):
                raise P2Stage1Error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Live production component code differs from trusted Git: {role}.",
                    layer="validation_authority",
                )

    def opaque(function: Callable[..., object]) -> Callable[..., object]:
        validate_bootstrap()
        wrapped: Callable[..., object] = _runtime_cast(
            opaque_wrapper_type(function, 0, False, None)
        )
        if wrapped.__class__ is not opaque_wrapper_type:
            raise RuntimeError("Component source authority crossed its opaque boundary.")
        return wrapped

    return (
        _runtime_cast(opaque(seal)),
        _runtime_cast(opaque(register)),
        _runtime_cast(opaque(is_registered)),
        _runtime_cast(opaque(validate_sources)),
    )


(
    _seal_production_component_callable,
    _register_production_component_callable,
    _production_component_callable_is_registered,
    _validate_production_component_sources,
) = _install_production_component_source_authority()
del _install_production_component_source_authority


def _make_transitive_integrity_validator(
    seed_modules: Sequence[ModuleType],
    *,
    excluded_names: Mapping[ModuleType, frozenset[str]],
) -> Callable[[], None]:
    """Seal module bindings, class behavior, function state, and frozen constants."""

    fail_closed = _error
    module_type = ModuleType
    function_type = FunctionType
    exact_type = type
    type_type = type
    staticmethod_type = staticmethod
    classmethod_type = classmethod
    property_type = property
    read_attribute = getattr
    module_vars = vars
    is_instance = isinstance
    callable_test = callable
    materialize_tuple = tuple
    materialize_frozenset = frozenset
    object_identity = id
    dataclass_fields = fields
    dataclass_test = is_dataclass
    mapping_type = Mapping
    project_prefix = "research_decision_engine."
    missing = object()

    module_rows: list[tuple[ModuleType, frozenset[str], tuple[tuple[str, object], ...]]] = []
    class_rows: list[tuple[type[object], frozenset[str], tuple[tuple[str, object], ...]]] = []
    function_rows: list[
        tuple[
            FunctionType,
            CodeType,
            tuple[object, ...] | None,
            tuple[tuple[str, object], ...] | None,
            tuple[object, ...],
        ]
    ] = []
    external_rows: list[tuple[ModuleType, tuple[tuple[str, object], ...]]] = []
    semantic_rows: list[tuple[ModuleType, str, object]] = []
    pending_modules = list(seed_modules)
    seen_modules: set[int] = set()
    seen_classes: set[int] = set()
    seen_functions: set[int] = set()
    external_modules: list[ModuleType] = [builtins]
    seen_external_modules: set[int] = set()

    def closure_values(function: FunctionType) -> tuple[object, ...]:
        values: list[object] = []
        for cell in function.__closure__ or ():
            try:
                values.append(cell.cell_contents)
            except ValueError:
                values.append(missing)
        return materialize_tuple(values)

    def add_function(
        function: object,
        *,
        follow_external_definition: bool = False,
    ) -> None:
        if exact_type(function) is not function_type or object_identity(function) in seen_functions:
            return
        trusted_function = _runtime_cast(function)
        seen_functions.add(object_identity(trusted_function))
        keyword_defaults = trusted_function.__kwdefaults__
        function_rows.append(
            (
                trusted_function,
                trusted_function.__code__,
                trusted_function.__defaults__,
                None
                if keyword_defaults is None
                else materialize_tuple(sorted(keyword_defaults.items())),
                closure_values(trusted_function),
            )
        )
        defining_module = sys.modules.get(trusted_function.__module__)
        if is_instance(defining_module, module_type):
            trusted_defining_module = _runtime_cast(defining_module)
            if trusted_function.__module__.startswith(project_prefix):
                pending_modules.append(trusted_defining_module)
            elif follow_external_definition:
                external_modules.append(trusted_defining_module)

    def descriptor_functions(value: object) -> tuple[object, ...]:
        if exact_type(value) in (staticmethod_type, classmethod_type):
            return (_runtime_cast(value).__func__,)
        if exact_type(value) is property_type:
            descriptor = _runtime_cast(value)
            return materialize_tuple(
                function
                for function in (descriptor.fget, descriptor.fset, descriptor.fdel)
                if function is not None
            )
        return (value,)

    def add_class(
        candidate: object,
        *,
        follow_external_definition: bool = False,
    ) -> None:
        if not is_instance(candidate, type_type) or object_identity(candidate) in seen_classes:
            return
        trusted_class = _runtime_cast(candidate)
        seen_classes.add(object_identity(trusted_class))
        namespace = module_vars(trusted_class)
        names = materialize_frozenset(namespace)
        bindings = materialize_tuple((name, namespace[name]) for name in sorted(names))
        class_rows.append((trusted_class, names, bindings))
        defining_module = sys.modules.get(trusted_class.__module__)
        if (
            follow_external_definition
            and is_instance(defining_module, module_type)
            and not trusted_class.__module__.startswith(project_prefix)
        ):
            external_modules.append(_runtime_cast(defining_module))
        for _, value in bindings:
            for function in descriptor_functions(value):
                add_function(
                    function,
                    follow_external_definition=follow_external_definition,
                )

    def integrity_snapshot(value: object, active: set[int] | None = None) -> object:
        if active is None:
            active = set()
        value_type = exact_type(value)
        if value is None or value_type in (bool, int, str, bytes):
            return (value_type, value)
        if value_type is float:
            return (float, _runtime_cast(value).hex())
        identity = object_identity(value)
        if identity in active:
            return ("cycle", identity)
        active.add(identity)
        try:
            if value_type in (tuple, list):
                sequence_value = _runtime_cast(value)
                return (
                    value_type,
                    materialize_tuple(integrity_snapshot(item, active) for item in sequence_value),
                )
            if value_type in (set, frozenset):
                set_value = _runtime_cast(value)
                return (
                    value_type,
                    materialize_frozenset(integrity_snapshot(item, active) for item in set_value),
                )
            if is_instance(value, mapping_type):
                mapping_value = _runtime_cast(value)
                return (
                    "mapping",
                    materialize_tuple(
                        (
                            integrity_snapshot(key, active),
                            integrity_snapshot(item, active),
                        )
                        for key, item in mapping_value.items()
                    ),
                )
            if dataclass_test(value) and not is_instance(value, type_type):
                return (
                    "dataclass",
                    value_type,
                    materialize_tuple(
                        (
                            definition.name,
                            integrity_snapshot(read_attribute(value, definition.name), active),
                        )
                        for definition in dataclass_fields(value)
                    ),
                )
            return ("identity", identity)
        finally:
            active.remove(identity)

    dynamic_constant_fragments = (
        "CACHE",
        "CAPABILIT",
        "CLEANED",
        "CLAIM",
        "HANDLES",
        "ISSUED",
        "LOCK",
        "OWNER",
        "RECORD",
        "REGISTRY",
        "RESULTS",
        "RUN_IDS",
        "STATE",
        "TOMBSTONE",
        "TRACKER",
        "USED",
    )

    while pending_modules:
        module = pending_modules.pop()
        if object_identity(module) in seen_modules:
            continue
        seen_modules.add(object_identity(module))
        namespace = module_vars(module)
        exclusions = excluded_names.get(module, frozenset())
        names = materialize_frozenset(
            name for name in namespace if not name.startswith("__") and name not in exclusions
        )
        bindings = materialize_tuple((name, namespace[name]) for name in sorted(names))
        module_rows.append((module, names, bindings))
        for name, value in bindings:
            add_function(value, follow_external_definition=True)
            add_class(value, follow_external_definition=True)
            if is_instance(value, module_type):
                if value.__name__.startswith(project_prefix):
                    pending_modules.append(value)
                else:
                    external_modules.append(value)
            normalized_name = name.lstrip("_")
            if (
                normalized_name.isupper()
                and not any(fragment in normalized_name for fragment in dynamic_constant_fragments)
                and is_instance(value, (tuple, list, set, frozenset, mapping_type))
            ):
                semantic_rows.append((module, name, integrity_snapshot(value)))

    while external_modules:
        module = external_modules.pop()
        if object_identity(module) in seen_external_modules:
            continue
        seen_external_modules.add(object_identity(module))
        namespace = module_vars(module)
        external_bindings: list[tuple[str, object]] = []
        for name, value in namespace.items():
            if name.startswith("__"):
                continue
            if (
                callable_test(value)
                or is_instance(value, module_type)
                or name.lstrip("_").isupper()
            ):
                external_bindings.append((name, value))
                add_function(value)
                add_class(value)
        external_rows.append((module, materialize_tuple(sorted(external_bindings))))

    sealed_excluded_names = MappingProxyType(dict(excluded_names))
    sealed_module_rows = materialize_tuple(module_rows)
    sealed_class_rows = materialize_tuple(class_rows)
    sealed_function_rows = materialize_tuple(function_rows)
    sealed_external_rows = materialize_tuple(external_rows)
    sealed_semantic_rows = materialize_tuple(semantic_rows)

    def validate() -> None:
        for module, expected_names, expected_bindings in sealed_module_rows:
            current = module_vars(module)
            exclusions = sealed_excluded_names.get(module, frozenset())
            current_names = materialize_frozenset(
                name for name in current if not name.startswith("__") and name not in exclusions
            )
            if current_names != expected_names or any(
                current.get(name, missing) is not expected for name, expected in expected_bindings
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted Stage-1 module namespace changed: {module.__name__}.",
                    layer="validation_authority",
                )
        for candidate, expected_names, expected_bindings in sealed_class_rows:
            current_class = module_vars(candidate)
            if materialize_frozenset(current_class) != expected_names or any(
                current_class.get(name, missing) is not expected
                for name, expected in expected_bindings
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted Stage-1 class behavior changed: "
                    f"{candidate.__module__}.{candidate.__qualname__}.",
                    layer="validation_authority",
                )
        for function, code, defaults, keyword_defaults, cells in sealed_function_rows:
            current_keyword_defaults = function.__kwdefaults__
            current_keyword_rows = (
                None
                if current_keyword_defaults is None
                else materialize_tuple(sorted(current_keyword_defaults.items()))
            )
            if (
                function.__code__ is not code
                or function.__defaults__ is not defaults
                or current_keyword_rows != keyword_defaults
                or any(
                    current is not expected
                    for current, expected in zip(closure_values(function), cells, strict=True)
                )
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted callable state changed: "
                    f"{function.__module__}.{function.__qualname__}.",
                    layer="validation_authority",
                )
        for module, expected_bindings in sealed_external_rows:
            if any(
                read_attribute(module, name, missing) is not expected
                for name, expected in expected_bindings
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted external dependency changed: {module.__name__}.",
                    layer="validation_authority",
                )
        for module, name, expected_snapshot in sealed_semantic_rows:
            semantic_value = read_attribute(module, name, missing)
            if semantic_value is missing or integrity_snapshot(semantic_value) != expected_snapshot:
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted frozen Stage-1 value changed: {module.__name__}.{name}.",
                    layer="validation_authority",
                )

    return validate


def _make_production_registry() -> tuple[
    Callable[..., None],
    Callable[..., None],
    Callable[[_ProductionPreparationCapability], ValidationRun],
    Callable[..., _ProductionRunRecord],
    Callable[..., None],
    Callable[..., None],
    Callable[[object], tuple[_PlanDraft, _ProductionRunRecord] | None],
    Callable[[object], tuple[_BindingRecord, _ProductionRunRecord] | None],
    Callable[[_ProductionPreparationCapability, _ProductionSessionToken], None],
    Callable[
        [Callable[..., object]],
        tuple[Callable[[], object], Callable[..., object]],
    ],
    Callable[..., object],
    Callable[[], _ProductionRegistrySummary],
    Callable[[Callable[..., object], _ProductionPreparationCollaborators], None],
    Callable[..., None],
    Callable[..., None],
    Callable[..., object],
    Callable[..., None],
    Callable[..., object],
    Callable[..., None],
    Callable[..., object],
    Callable[..., None],
]:
    """Create the non-importable mutable production authority state."""

    lock = _TRUSTED_RLOCK_TYPE()
    registry_guard = object()
    preparations: dict[_ProductionPreparationCapability, _PreparationRecord] = {}
    runs_by_id: dict[str, _ProductionRunRecord] = {}
    run_capabilities: dict[ValidationRun, str] = {}
    pending_resources: dict[_ProductionSessionToken, _PendingSessionResources] = {}
    failure_selector: ContextVar[BindingFailurePoint | None] = _TRUSTED_CONTEXTVAR_TYPE(
        "rde_p2_stage1_failure_point",
        default=None,
    )
    failure_points = frozenset(
        {
            "after_run_reservation_before_ledger",
            "control_directory_acquisition_failure",
            "after_control_directory_creation_before_ledger",
            "after_executor_issuance_before_ledger",
            "junit_acquisition_failure",
            "after_junit_acquisition_before_identity",
            "after_junit_ownership_before_ledger",
            "after_plan_0_allocation",
            "after_plan_1_allocation",
            "after_plan_2_allocation",
            "after_plan_3_allocation",
            "after_plan_4_allocation",
            "after_plan_5_allocation",
            "after_authority_allocation_before_binding",
            "before_authority_construction",
            "validate_plan_0",
            "validate_plan_1",
            "validate_plan_2",
            "validate_plan_3",
            "validate_plan_4",
            "validate_plan_5",
            "after_authority_construction",
            "before_publication",
            "publication_failure",
            "after_publication",
        }
    )
    installed_entrypoint: Callable[..., object] | None = None
    installed_code: object | None = None
    installed_gate: Callable[..., object] | None = None
    installed_public_entrypoint: Callable[..., object] | None = None
    sealed_preparer: Callable[..., object] | None = None
    sealed_preparer_code: object | None = None
    sealed_collaborators: _ProductionPreparationCollaborators | None = None
    sealed_collaborator_validator: Callable[[], None] | None = None
    sealed_component_validator: Callable[[], None] | None = None
    fail_closed = _error
    replace_record = replace
    validate_run_identity = _validate_run_id
    preparation_type = _runtime_cast(_ProductionPreparationCapability)
    session_token_type = _runtime_cast(_ProductionSessionToken)
    run_type = _runtime_cast(ValidationRun)
    preparation_record_type = _PreparationRecord
    run_record_type = _ProductionRunRecord
    pending_resources_type = _PendingSessionResources
    plan_draft_type = _PlanDraft
    plan_set_type = _SixPlanSet
    binding_record_type = _BindingRecord
    resources_type = _SessionResources
    authority_projection_type = ValidationAuthorityProjection
    authority_type = _runtime_cast(ValidationAuthority)
    provisional_control_directory_type = _ProvisionalControlDirectory
    owned_control_directory_type = _OwnedControlDirectory
    collaborators_type = _ProductionPreparationCollaborators
    component_issuers_type = _ProductionComponentIssuers
    stage1_error_type = P2Stage1Error
    inspect_module = inspect
    current_frame = inspect.currentframe
    compile_qualified = _compiled_qualified_function
    compile_qualified_code = compile_qualified.__code__
    path_type = Path
    runtime_modules = sys.modules
    os_fspath = os.fspath
    os_stat = os.stat
    allocate = object.__new__
    exact_type = type
    get_attribute = getattr
    module_vars = vars
    context_manager = contextmanager
    materialize_tuple = tuple
    next_value = next
    sum_values = sum
    value_length = len
    bytes_type = bytes
    base_exception_type = BaseException
    any_value = any
    instance_of = isinstance
    fullmatch = re.fullmatch
    h64_pattern = _H64_PATTERN
    module_type = ModuleType
    value_error_type = ValueError
    is_callable = callable
    trusted_repository = Path(__file__).resolve(strict=True).parents[2]
    trusted_smoke_source = (
        trusted_repository / "research_decision_engine" / "benchmarks" / "broader_smoke.py"
    ).resolve(strict=True)
    trusted_entry_code = _compiled_nested_function(
        trusted_smoke_source.read_bytes(),
        source_path=trusted_smoke_source,
        function_name="execute_bounded_validation_evidence",
    )
    entropy_module = os
    entropy = os.urandom
    entropy_origin = getattr(entropy, "__module__", None)
    if (
        type(entropy) is not BuiltinFunctionType
        or getattr(entropy, "__name__", None) != "urandom"
        or type(entropy_origin) is not str
    ):
        raise RuntimeError("The exact production OS-random authority is unavailable.")
    publish_once = _single_assignment_publish
    publish_once_code = publish_once.__code__
    callable_projector = callable_projection
    callable_projector_code = callable_projector.__code__
    hash_protocol = protocol_hash
    evidence_contract_checkpoint = EVIDENCE_CONTRACT_CHECKPOINT
    protocol_checkpoint = PROTOCOL_CHECKPOINT
    permitted_filenames = PERMITTED_FINAL_EVIDENCE_FILENAMES
    ordered_plan_slots: tuple[tuple[PlanKind, PlanRole], ...] = (
        ("pytest", "pytest"),
        ("oracle", "oracle"),
        ("execution_specification", "primary_smoke"),
        ("execution_specification", "altered_order_replay"),
        ("execution_specification", "fixture_primary"),
        ("execution_specification", "fixture_replay"),
    )
    opaque_runtime_callable = _opaque_runtime_callable
    collaborator_field_names = materialize_tuple(
        descriptor.name for descriptor in fields(collaborators_type)
    )
    component_field_names = materialize_tuple(
        descriptor.name for descriptor in fields(component_issuers_type)
    )

    def owned_control_directory_is_removed(control_directory: object) -> bool:
        if exact_type(control_directory) not in {
            owned_control_directory_type,
            provisional_control_directory_type,
        }:
            return False
        exact_control_directory = _runtime_cast(control_directory)
        try:
            os_stat(os_fspath(exact_control_directory.path), follow_symlinks=False)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False

    def exact_instance_validator(
        instance: object,
        *,
        expected_type: type[object],
        field_names: tuple[str, ...],
        semantic_validate: Callable[[], None],
    ) -> Callable[[], None]:
        expected_fields = materialize_tuple(
            (name, get_attribute(instance, name)) for name in field_names
        )

        def validate_exact_instance() -> None:
            if exact_type(instance) is not expected_type or any_value(
                get_attribute(instance, name, None) is not expected
                for name, expected in expected_fields
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    "A sealed production collaborator object was modified.",
                    layer="validation_authority",
                )
            semantic_validate()

        return validate_exact_instance

    def _run_for_capability(run: ValidationRun) -> _ProductionRunRecord | None:
        validation_run_identity = run_capabilities.get(run)
        if validation_run_identity is None:
            return None
        record = runs_by_id.get(validation_run_identity)
        if (
            record is None
            or exact_type(record) is not run_record_type
            or record.registry_guard is not registry_guard
            or record.capability is not run
            or record.validation_run_id != validation_run_identity
        ):
            return None
        return record

    def require_preparation(
        preparation: _ProductionPreparationCapability,
        *,
        validation_run: ValidationRun | None = None,
    ) -> None:
        with lock:
            preparation_record = preparations.get(preparation)
            run_record = None if validation_run is None else _run_for_capability(validation_run)
        if (
            exact_type(preparation) is not preparation_type
            or preparation_record is None
            or preparation_record.registry_guard is not registry_guard
            or preparation_record.capability is not preparation
            or preparation_record.state != "active"
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Exact current one-shot production preparation capability required.",
                layer="live_executor_implementation_issuance",
            )
        if validation_run is not None and (
            exact_type(validation_run) is not run_type
            or run_record is None
            or run_record.capability is not validation_run
            or run_record.preparation is not preparation
            or run_record.state != "reserved"
            or preparation_record.validation_run_id != run_record.validation_run_id
        ):
            fail_closed(
                "VALIDATION_RUN_STALE",
                "Production preparation and validation run are not one exact live pair.",
                layer="validation_run_issuance",
            )

    def consume_preparation(
        preparation: _ProductionPreparationCapability,
        session_token: _ProductionSessionToken,
    ) -> None:
        with lock:
            record = preparations.get(preparation)
            if (
                exact_type(preparation) is not preparation_type
                or exact_type(session_token) is not session_token_type
                or record is None
                or record.registry_guard is not registry_guard
                or record.capability is not preparation
                or record.session_token is not session_token
                or record.state != "issued"
            ):
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production preparation capability is forged, stale, or replayed.",
                    layer="live_executor_implementation_issuance",
                )
            preparations[preparation] = replace_record(record, state="active")

    def reserve_run(preparation: _ProductionPreparationCapability) -> ValidationRun:
        require_preparation(preparation)
        with lock:
            initial_preparation_record = preparations.get(preparation)
        if (
            initial_preparation_record is None
            or initial_preparation_record.registry_guard is not registry_guard
            or initial_preparation_record.validation_run_id is not None
        ):
            fail_closed(
                "VALIDATION_RUN_STALE",
                "A production preparation capability can reserve exactly one run.",
                layer="validation_run_issuance",
            )
        if (
            get_attribute(entropy_module, "urandom", None) is not entropy
            or exact_type(entropy) is not BuiltinFunctionType
            or get_attribute(entropy, "__name__", None) != "urandom"
            or get_attribute(entropy, "__module__", None) != entropy_origin
        ):
            fail_closed(
                "VALIDATION_RUN_CALLER_SUPPLIED",
                "The production OS-entropy authority was replaced.",
                layer="validation_run_issuance",
            )
        for _ in range(128):
            raw = entropy(32)
            if exact_type(raw) is not bytes_type or value_length(raw) != 32:
                fail_closed(
                    "VALIDATION_RUN_ID_INVALID",
                    "Production entropy did not return exactly 32 bytes.",
                    layer="validation_run_issuance",
                )
            validation_run_identity = raw.hex()
            validate_run_identity(validation_run_identity)
            with lock:
                preparation_record = preparations.get(preparation)
                if (
                    preparation_record is None
                    or preparation_record.registry_guard is not registry_guard
                    or preparation_record.state != "active"
                    or preparation_record.validation_run_id is not None
                ):
                    fail_closed(
                        "VALIDATION_RUN_STALE",
                        "Production preparation became stale or already reserved its run.",
                        layer="validation_run_issuance",
                    )
                if validation_run_identity in runs_by_id:
                    continue
                capability: ValidationRun = allocate(run_type)
                runs_by_id[validation_run_identity] = run_record_type(
                    capability=capability,
                    validation_run_id=validation_run_identity,
                    preparation=preparation,
                    state="reserved",
                    registry_guard=registry_guard,
                )
                run_capabilities[capability] = validation_run_identity
                preparations[preparation] = replace_record(
                    preparation_record,
                    validation_run_id=validation_run_identity,
                )
                return capability
        fail_closed(
            "VALIDATION_RUN_COLLISION",
            "Fresh production validation-run issuance exhausted collision retries.",
            layer="validation_run_issuance",
        )

    def require_run(run: ValidationRun, *, allow_bound: bool) -> _ProductionRunRecord:
        with lock:
            record = _run_for_capability(run)
        if exact_type(run) is not run_type or record is None or record.capability is not run:
            fail_closed(
                "VALIDATION_RUN_STALE",
                "Exact current production validation-run capability required.",
                layer="validation_run_issuance",
            )
        if record.state == "terminal" or (record.state == "authority_bound" and not allow_bound):
            fail_closed(
                "VALIDATION_RUN_STALE",
                "Production validation-run capability is stale for this operation.",
                layer="validation_run_issuance",
            )
        return record

    def publish_binding(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        prepare_complete_record: Callable[[_ProductionRunRecord], _ProductionRunRecord],
        validate_provenance: Callable[[], None],
        *,
        failure_point: BindingFailurePoint | None,
    ) -> None:
        # Phase A and the one Phase-B replacement share the authoritative lock.
        with lock:
            current = _run_for_capability(run)
            preparation_record = preparations.get(preparation)
            pending = (
                None
                if preparation_record is None
                else pending_resources.get(preparation_record.session_token)
            )
            if (
                current is None
                or current.capability is not run
                or current.preparation is not preparation
                or current.state != "reserved"
                or preparation_record is None
                or preparation_record.registry_guard is not registry_guard
                or preparation_record.state != "active"
                or preparation_record.validation_run_id != current.validation_run_id
                or pending is None
                or pending.logical_resources_tombstoned
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production binding did not receive one exact reserved run.",
                    layer="issued_plan_binding",
                )
            complete_record = prepare_complete_record(current)
            pending = pending_resources.get(preparation_record.session_token)
            if (
                sealed_collaborators is None
                or sealed_collaborator_validator is None
                or sealed_component_validator is None
                or pending is None
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production collaborators disappeared during atomic publication.",
                    layer="issued_plan_binding",
                )
            sealed_collaborator_validator()
            sealed_component_validator()
            plans_candidate = complete_record.plans
            binding_candidate = complete_record.binding
            resources_candidate = complete_record.resources
            if (
                exact_type(complete_record) is not run_record_type
                or complete_record.capability is not run
                or complete_record.preparation is not preparation
                or complete_record.state != "authority_bound"
                or exact_type(binding_candidate) is not binding_record_type
                or exact_type(plans_candidate) is not plan_set_type
                or exact_type(resources_candidate) is not resources_type
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production binding publication did not receive one complete replacement.",
                    layer="issued_plan_binding",
                )
            binding: _BindingRecord = _runtime_cast(binding_candidate)
            plans: _SixPlanSet = _runtime_cast(plans_candidate)
            resources: _SessionResources = _runtime_cast(resources_candidate)
            if (
                exact_type(binding.projection) is not authority_projection_type
                or exact_type(binding.capability) is not authority_type
                or binding.validation_run_id != current.validation_run_id
                or binding.plans is not plans
                or binding.trust_domain != "production"
                or resources.token is not preparation_record.session_token
                or pending.authority_state != "bound"
                or pending.authority_capability is not binding.capability
                or pending.unpublished_binding is not binding
                or pending.plan_allocation_intent is not None
                or len(pending.plan_capabilities) != 6
                or len(pending.plan_drafts) != 6
                or any_value(
                    pending_draft is not published_draft
                    or pending_capability is not published_draft.capability
                    for pending_draft, pending_capability, published_draft in zip(
                        pending.plan_drafts,
                        pending.plan_capabilities,
                        plans.ordered(),
                        strict=True,
                    )
                )
                or resources.plan_capabilities != pending.plan_capabilities
                or resources.published_authority is not binding.capability
                or resources.control_directory_state != "transferred_for_later_execution"
                or resources.junit_ownership_state != "transferred_for_later_execution"
                or not resources.executor_is_current(resources.executor_implementation)
                or not resources.junit_is_open(resources.junit_handle)
                or any_value(
                    exact_type(draft) is not plan_draft_type
                    or draft.capability is None
                    or draft.validation_run is not run
                    or draft.validation_run_id != current.validation_run_id
                    for draft in plans.ordered()
                )
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production binding publication did not receive exact inner records.",
                    layer="issued_plan_binding",
                )
            ordered = plans.ordered()
            projection = binding.projection
            if (
                materialize_tuple((draft.kind, draft.role) for draft in ordered)
                != (
                    ("pytest", "pytest"),
                    ("oracle", "oracle"),
                    ("execution_specification", "primary_smoke"),
                    ("execution_specification", "altered_order_replay"),
                    ("execution_specification", "fixture_primary"),
                    ("execution_specification", "fixture_replay"),
                )
                or projection.evidence_contract_checkpoint != evidence_contract_checkpoint
                or projection.protocol_checkpoint != protocol_checkpoint
                or projection.permitted_final_evidence_filenames != permitted_filenames
                or projection.validation_run_id != current.validation_run_id
                or projection.pytest_plan_id != ordered[0].persistent_id
                or projection.oracle_plan_id != ordered[1].persistent_id
                or projection.primary_smoke_execution_specification_id != ordered[2].persistent_id
                or projection.replay_execution_specification_id != ordered[3].persistent_id
                or projection.production_fixture_execution_specification_ids
                != (ordered[4].persistent_id, ordered[5].persistent_id)
                or binding.validation_authority_id
                != hash_protocol("validation_evidence_authority/v1", projection.as_dict())
                or any_value(
                    draft.fingerprint
                    != hash_protocol(
                        "validation_evidence_live_plan_fingerprint/v1",
                        {
                            "kind": draft.kind,
                            "persistent_id": draft.persistent_id,
                            "projection": get_attribute(draft.projection, "as_dict")(),
                            "role": draft.role,
                            "validation_run_id": draft.validation_run_id,
                        },
                    )
                    for draft in ordered
                )
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production binding failed independent complete-record reconciliation.",
                    layer="issued_plan_binding",
                )
            if get_attribute(publish_once, "__code__", None) is not publish_once_code:
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    "The atomic production publication primitive was replaced.",
                    layer="issued_plan_binding",
                )
            if failure_point == "before_publication":
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Injected failure occurred immediately before publication.",
                    layer="issued_plan_binding",
                )
            if not is_callable(validate_provenance):
                fail_closed(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Final production provenance validator is unavailable.",
                    layer="validation_authority",
                )
            validate_provenance()
            if (
                _run_for_capability(run) is not current
                or pending_resources.get(preparation_record.session_token) is not pending
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production ownership changed during final provenance validation.",
                    layer="issued_plan_binding",
                )
            publish_once(
                runs_by_id,
                current.validation_run_id,
                complete_record,
                failure_point=failure_point,
            )
            if pending_resources.get(preparation_record.session_token) is not pending:
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "The pending ownership ledger changed during atomic publication.",
                    layer="issued_plan_binding",
                )
            pending_resources.pop(preparation_record.session_token, None)

    def merge_pending_resources(
        session_token: _ProductionSessionToken,
        *,
        control_directory: _OwnedControlDirectory | _ProvisionalControlDirectory | None,
        junit_handle: object | None,
        executor_implementation: object | None,
        executor_invalidator: Callable[..., None],
        executor_is_current: Callable[[object], bool],
        junit_cleanup: Callable[..., None],
        junit_is_open: Callable[[object], bool],
        junit_is_cleaned: Callable[[object], bool],
        remove_control_directory: Callable[[object], None],
    ) -> _PendingSessionResources:
        """Merge a monotonic exact local snapshot into central pending ownership."""

        current = pending_resources.get(session_token)
        if current is not None and any_value(
            observed is not expected
            for observed, expected in (
                (current.token, session_token),
                (current.executor_invalidator, executor_invalidator),
                (current.executor_is_current, executor_is_current),
                (current.junit_cleanup, junit_cleanup),
                (current.junit_is_open, junit_is_open),
                (current.junit_is_cleaned, junit_is_cleaned),
                (current.remove_control_directory, remove_control_directory),
            )
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Production resource-ledger authorities changed during one session.",
                layer="live_executor_implementation_issuance",
            )

        def merge_exact[T](label: str, observed: T | None, candidate: T | None) -> T | None:
            if observed is None:
                return candidate
            if candidate is None or candidate is observed:
                return observed
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                f"Production resource ledger received two different {label} resources.",
                layer="live_executor_implementation_issuance",
            )

        def merge_centrally_owned_physical[T](observed: T | None, candidate: T | None) -> T | None:
            # Component promotion first replaces the provisional token in this
            # central ledger and only then updates the caller's local snapshot.
            # During that narrow callback gap, the central token is the exact
            # cleanup authority and the local token is its stale predecessor.
            return candidate if observed is None else observed

        merged_control_directory: _OwnedControlDirectory | _ProvisionalControlDirectory | None = (
            _runtime_cast(
                merge_centrally_owned_physical(
                    None if current is None else current.control_directory,
                    control_directory,
                )
            )
        )
        merged = pending_resources_type(
            token=session_token,
            control_directory=merged_control_directory,
            control_directory_state=(
                "none" if current is None else current.control_directory_state
            ),
            junit_handle=merge_centrally_owned_physical(
                None if current is None else current.junit_handle,
                junit_handle,
            ),
            junit_ownership_state=("none" if current is None else current.junit_ownership_state),
            executor_implementation=merge_exact(
                "executor",
                None if current is None else current.executor_implementation,
                executor_implementation,
            ),
            plan_allocation_intent=(None if current is None else current.plan_allocation_intent),
            plan_capabilities=() if current is None else current.plan_capabilities,
            plan_drafts=() if current is None else current.plan_drafts,
            authority_state="none" if current is None else current.authority_state,
            authority_capability=None if current is None else current.authority_capability,
            unpublished_binding=None if current is None else current.unpublished_binding,
            logical_resources_tombstoned=(
                False if current is None else current.logical_resources_tombstoned
            ),
            generation=1 if current is None else current.generation + 1,
            executor_invalidator=executor_invalidator,
            executor_is_current=executor_is_current,
            junit_cleanup=junit_cleanup,
            junit_is_open=junit_is_open,
            junit_is_cleaned=junit_is_cleaned,
            remove_control_directory=remove_control_directory,
        )
        pending_resources[session_token] = merged
        return merged

    def record_resources(
        preparation: _ProductionPreparationCapability,
        session_token: _ProductionSessionToken,
        run: ValidationRun,
        *,
        control_directory: _OwnedControlDirectory | _ProvisionalControlDirectory | None,
        junit_handle: object | None,
        executor_implementation: object | None,
        executor_invalidator: Callable[..., None],
        executor_is_current: Callable[[object], bool],
        junit_cleanup: Callable[..., None],
        junit_is_open: Callable[[object], bool],
        junit_is_cleaned: Callable[[object], bool],
        remove_control_directory: Callable[[object], None],
    ) -> None:
        require_preparation(preparation, validation_run=run)
        with lock:
            preparation_record = preparations.get(preparation)
            run_record = _run_for_capability(run)
            if (
                preparation_record is None
                or preparation_record.registry_guard is not registry_guard
                or preparation_record.session_token is not session_token
                or run_record is None
                or run_record.state != "reserved"
            ):
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production resource ownership requires one exact live session.",
                    layer="live_executor_implementation_issuance",
                )
            merge_pending_resources(
                session_token,
                control_directory=control_directory,
                junit_handle=junit_handle,
                executor_implementation=executor_implementation,
                executor_invalidator=executor_invalidator,
                executor_is_current=executor_is_current,
                junit_cleanup=junit_cleanup,
                junit_is_open=junit_is_open,
                junit_is_cleaned=junit_is_cleaned,
                remove_control_directory=remove_control_directory,
            )

    def require_pending_owner_locked(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        *,
        session_token: _ProductionSessionToken | None = None,
    ) -> tuple[_PreparationRecord, _ProductionRunRecord, _PendingSessionResources]:
        preparation_record = preparations.get(preparation)
        run_record = _run_for_capability(run)
        expected_token = None if preparation_record is None else preparation_record.session_token
        pending = None if expected_token is None else pending_resources.get(expected_token)
        if (
            preparation_record is None
            or preparation_record.registry_guard is not registry_guard
            or preparation_record.capability is not preparation
            or preparation_record.state != "active"
            or (session_token is not None and expected_token is not session_token)
            or run_record is None
            or run_record.capability is not run
            or run_record.preparation is not preparation
            or run_record.state != "reserved"
            or preparation_record.validation_run_id != run_record.validation_run_id
            or pending is None
            or pending.token is not expected_token
            or pending.logical_resources_tombstoned
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Production ownership transition requires one exact pending session.",
                layer="live_executor_implementation_issuance",
            )
        return preparation_record, run_record, pending

    def begin_physical_resource(
        preparation: _ProductionPreparationCapability,
        session_token: _ProductionSessionToken,
        run: ValidationRun,
        resource_name: Literal["control_directory", "junit"],
    ) -> None:
        if resource_name not in {"control_directory", "junit"}:
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Unknown Stage-1 physical resource acquisition.",
                layer="live_executor_implementation_issuance",
            )
        with lock:
            _, _, pending = require_pending_owner_locked(
                preparation,
                run,
                session_token=session_token,
            )
            current_state = (
                pending.control_directory_state
                if resource_name == "control_directory"
                else pending.junit_ownership_state
            )
            current_resource = (
                pending.control_directory
                if resource_name == "control_directory"
                else pending.junit_handle
            )
            if current_state != "none" or current_resource is not None:
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    f"Stage-1 {resource_name} acquisition is duplicate or out of order.",
                    layer="live_executor_implementation_issuance",
                )
            updated = (
                replace_record(
                    pending,
                    control_directory_state="acquiring",
                    generation=pending.generation + 1,
                )
                if resource_name == "control_directory"
                else replace_record(
                    pending,
                    junit_ownership_state="acquiring",
                    generation=pending.generation + 1,
                )
            )
            pending_resources[session_token] = updated

    def transition_physical_resource(
        preparation: _ProductionPreparationCapability,
        session_token: _ProductionSessionToken,
        run: ValidationRun,
        resource_name: Literal["control_directory", "junit"],
        resource: object | None,
        *,
        previous_resource: object | None,
        state: Literal["none", "centrally_registered", "retained"],
    ) -> None:
        with lock:
            _, _, pending = require_pending_owner_locked(
                preparation,
                run,
                session_token=session_token,
            )
            current_resource = (
                pending.control_directory
                if resource_name == "control_directory"
                else pending.junit_handle
            )
            current_state = (
                pending.control_directory_state
                if resource_name == "control_directory"
                else pending.junit_ownership_state
            )
            if state == "none":
                if (
                    current_state not in {"none", "acquiring"}
                    or current_resource is not None
                    or resource is not None
                    or previous_resource is not None
                ):
                    fail_closed(
                        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                        f"Stage-1 {resource_name} zero-acquisition transition is invalid.",
                        layer="live_executor_implementation_issuance",
                    )
                if current_state == "none":
                    return
                updated = (
                    replace_record(
                        pending,
                        control_directory_state="none",
                        generation=pending.generation + 1,
                    )
                    if resource_name == "control_directory"
                    else replace_record(
                        pending,
                        junit_ownership_state="none",
                        generation=pending.generation + 1,
                    )
                )
                pending_resources[session_token] = updated
                return
            expected_state = (
                "acquiring" if state == "centrally_registered" else "centrally_registered"
            )
            if (
                resource_name not in {"control_directory", "junit"}
                or resource is None
                or current_state != expected_state
                or current_resource is not previous_resource
                or (state == "centrally_registered" and previous_resource is not None)
                or (state == "retained" and previous_resource is None)
            ):
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    f"Stage-1 {resource_name} ownership transfer is incomplete or out of order.",
                    layer="live_executor_implementation_issuance",
                )
            if resource_name == "control_directory":
                exact_resource = _runtime_cast(resource)
                exact_previous_resource = _runtime_cast(previous_resource)
                if (
                    (
                        state == "centrally_registered"
                        and exact_type(resource) is not provisional_control_directory_type
                    )
                    or (
                        state == "retained"
                        and exact_type(resource) is not owned_control_directory_type
                    )
                    or (
                        state == "retained"
                        and exact_type(previous_resource) is provisional_control_directory_type
                        and exact_resource.path != exact_previous_resource.path
                    )
                ):
                    fail_closed(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Stage-1 control-directory ownership transition changed resources.",
                        layer="plan_identities",
                    )
                updated = replace_record(
                    pending,
                    control_directory=resource,
                    control_directory_state=state,
                    generation=pending.generation + 1,
                )
            else:
                updated = replace_record(
                    pending,
                    junit_handle=resource,
                    junit_ownership_state=state,
                    generation=pending.generation + 1,
                )
            pending_resources[session_token] = updated

    def allocate_executor_implementation(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        *,
        capability_type: type[object],
    ) -> object:
        """Centrally own the exact executor object before component registration."""

        with lock:
            preparation_record, _, pending = require_pending_owner_locked(preparation, run)
            if (
                pending.executor_implementation is not None
                or exact_type(capability_type) is not type
            ):
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production executor allocation is duplicate or malformed.",
                    layer="live_executor_implementation_issuance",
                )
            capability = allocate(capability_type)
            current = pending_resources.get(preparation_record.session_token)
            if current is not pending:
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production executor ownership changed during central allocation.",
                    layer="live_executor_implementation_issuance",
                )
            pending_resources[preparation_record.session_token] = replace_record(
                pending,
                executor_implementation=capability,
                generation=pending.generation + 1,
            )
            return capability

    def confirm_executor_implementation(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        capability: object,
    ) -> None:
        """Confirm central ownership immediately before component activation."""

        with lock:
            _, _, pending = require_pending_owner_locked(preparation, run)
            if pending.executor_implementation is not capability:
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Executor component registration lost its exact central owner.",
                    layer="live_executor_implementation_issuance",
                )

    def allocate_plan_capability(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        *,
        capability_type: type[object],
        kind: PlanKind,
        role: PlanRole,
        persistent_id: str,
    ) -> object:
        with lock:
            preparation_record, _, pending = require_pending_owner_locked(preparation, run)
            slot = len(pending.plan_capabilities)
            if (
                pending.plan_allocation_intent is not None
                or len(pending.plan_drafts) != slot
                or slot >= len(ordered_plan_slots)
                or ordered_plan_slots[slot] != (kind, role)
                or exact_type(persistent_id) is not str
                or fullmatch(h64_pattern, persistent_id) is None
                or any_value(draft.persistent_id == persistent_id for draft in pending.plan_drafts)
                or exact_type(capability_type) is not type
            ):
                fail_closed(
                    "ISSUED_PLAN_CAPABILITY_INVALID",
                    "Production plan allocation did not match the next exact ledger slot.",
                    layer="live_issued_plan_binding",
                )
            intent = replace_record(
                pending,
                plan_allocation_intent=(kind, role),
                generation=pending.generation + 1,
            )
            pending_resources[preparation_record.session_token] = intent
            capability = allocate(capability_type)
            current = pending_resources.get(preparation_record.session_token)
            if current is not intent:
                fail_closed(
                    "ISSUED_PLAN_CAPABILITY_INVALID",
                    "Production plan ownership changed during central allocation.",
                    layer="live_issued_plan_binding",
                )
            allocated = replace_record(
                intent,
                plan_allocation_intent=None,
                plan_capabilities=(*intent.plan_capabilities, capability),
                generation=intent.generation + 1,
            )
            pending_resources[preparation_record.session_token] = allocated
            if failure_selector.get() == f"after_plan_{slot}_allocation":
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    f"Injected failure occurred after central plan allocation {slot}.",
                    layer="issued_plan_binding",
                )
            return capability

    def record_plan_draft(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        draft: _PlanDraft,
    ) -> None:
        with lock:
            preparation_record, _, pending = require_pending_owner_locked(preparation, run)
            index = len(pending.plan_drafts)
            if (
                exact_type(draft) is not plan_draft_type
                or pending.plan_allocation_intent is not None
                or len(pending.plan_capabilities) != index + 1
                or index >= len(ordered_plan_slots)
                or ordered_plan_slots[index] != (draft.kind, draft.role)
                or pending.plan_capabilities[index] is not draft.capability
                or draft.validation_run is not run
            ):
                fail_closed(
                    "ISSUED_PLAN_CAPABILITY_INVALID",
                    "Production plan draft did not complete its exact allocated ledger slot.",
                    layer="live_issued_plan_binding",
                )
            pending_resources[preparation_record.session_token] = replace_record(
                pending,
                plan_drafts=(*pending.plan_drafts, draft),
                generation=pending.generation + 1,
            )

    def allocate_authority_capability(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        *,
        capability_type: type[object],
        validation_authority_id: str,
    ) -> object:
        with lock:
            preparation_record, _, pending = require_pending_owner_locked(preparation, run)
            if (
                pending.authority_state != "none"
                or pending.authority_capability is not None
                or pending.unpublished_binding is not None
                or pending.plan_allocation_intent is not None
                or len(pending.plan_capabilities) != len(ordered_plan_slots)
                or len(pending.plan_drafts) != len(ordered_plan_slots)
                or exact_type(capability_type) is not type
                or capability_type is not authority_type
                or exact_type(validation_authority_id) is not str
                or fullmatch(h64_pattern, validation_authority_id) is None
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production authority allocation requires six exact retained plans.",
                    layer="issued_plan_binding",
                )
            intent = replace_record(
                pending,
                authority_state="allocating",
                generation=pending.generation + 1,
            )
            pending_resources[preparation_record.session_token] = intent
            capability = allocate(capability_type)
            current = pending_resources.get(preparation_record.session_token)
            if current is not intent:
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Production authority ownership changed during central allocation.",
                    layer="issued_plan_binding",
                )
            allocated = replace_record(
                intent,
                authority_state="allocated",
                authority_capability=_runtime_cast(capability),
                generation=intent.generation + 1,
            )
            pending_resources[preparation_record.session_token] = allocated
            if failure_selector.get() == "after_authority_allocation_before_binding":
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Injected failure occurred after central unpublished-authority allocation.",
                    layer="issued_plan_binding",
                )
            return capability

    def record_unpublished_binding(
        preparation: _ProductionPreparationCapability,
        run: ValidationRun,
        binding: _BindingRecord,
    ) -> None:
        with lock:
            preparation_record, _, pending = require_pending_owner_locked(preparation, run)
            if (
                exact_type(binding) is not binding_record_type
                or binding.trust_domain != "production"
                or pending.authority_state != "allocated"
                or pending.authority_capability is not binding.capability
                or pending.unpublished_binding is not None
                or materialize_tuple(draft.capability for draft in pending.plan_drafts)
                != materialize_tuple(draft.capability for draft in binding.plans.ordered())
            ):
                fail_closed(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Unpublished authority binding did not match the central allocation ledger.",
                    layer="issued_plan_binding",
                )
            pending_resources[preparation_record.session_token] = replace_record(
                pending,
                authority_state="bound",
                unpublished_binding=binding,
                generation=pending.generation + 1,
            )

    def production_plan(capability: object) -> tuple[_PlanDraft, _ProductionRunRecord] | None:
        with lock:
            records = materialize_tuple(
                record
                for record in runs_by_id.values()
                if exact_type(record) is run_record_type and record.registry_guard is registry_guard
            )
        for run_record in records:
            if run_record.plans is None:
                continue
            for draft in run_record.plans.ordered():
                if draft.capability is capability:
                    return draft, run_record
        return None

    def production_authority(
        authority: object,
    ) -> tuple[_BindingRecord, _ProductionRunRecord] | None:
        with lock:
            records = materialize_tuple(
                record
                for record in runs_by_id.values()
                if exact_type(record) is run_record_type and record.registry_guard is registry_guard
            )
        for run_record in records:
            if run_record.binding is not None and run_record.binding.capability is authority:
                return run_record.binding, run_record
        return None

    def cleanup_session(session_token: _ProductionSessionToken) -> None:
        cleanup_record: _ProductionRunRecord | None = None
        preparation_to_close: _ProductionPreparationCapability | None = None
        pending: _PendingSessionResources | None = None
        with lock:
            pending = pending_resources.get(session_token)
            for validation_run_identity, record in materialize_tuple(runs_by_id.items()):
                if (
                    exact_type(record) is not run_record_type
                    or record.registry_guard is not registry_guard
                ):
                    continue
                preparation_record = preparations.get(record.preparation)
                if not (
                    (record.resources is not None and record.resources.token is session_token)
                    or (
                        preparation_record is not None
                        and preparation_record.session_token is session_token
                    )
                ):
                    continue
                if record.state == "terminal" and record.resources_cleaned and pending is None:
                    pending_resources.pop(session_token, None)
                    return
                cleanup_record = record
                preparation_to_close = record.preparation
                # Preserve a complete published binding as one immutable unit while
                # making all live capabilities stale before resource cleanup.
                if record.state != "terminal":
                    runs_by_id[validation_run_identity] = replace_record(record, state="terminal")
                break
            if preparation_to_close is not None:
                current_preparation = preparations.get(preparation_to_close)
                if current_preparation is not None:
                    preparations[preparation_to_close] = replace_record(
                        current_preparation, state="tombstoned"
                    )
            if pending is not None:
                pending = replace_record(
                    pending,
                    control_directory_state=(
                        "none" if pending.control_directory_state == "none" else "cleanup_pending"
                    ),
                    junit_ownership_state=(
                        "none" if pending.junit_ownership_state == "none" else "cleanup_pending"
                    ),
                    plan_allocation_intent=None,
                    authority_state="tombstoned",
                    logical_resources_tombstoned=True,
                    generation=pending.generation + 1,
                )
                pending_resources[session_token] = pending
        if cleanup_record is None and pending is None:
            return
        resources = None if cleanup_record is None else cleanup_record.resources
        cleanup_errors: list[BaseException] = []
        executor_implementation = (
            resources.executor_implementation
            if resources is not None
            else None
            if pending is None
            else pending.executor_implementation
        )
        executor_invalidator = (
            resources.executor_invalidator
            if resources is not None
            else None
            if pending is None
            else pending.executor_invalidator
        )
        executor_is_current = (
            resources.executor_is_current
            if resources is not None
            else None
            if pending is None
            else pending.executor_is_current
        )
        junit_handle = (
            resources.junit_handle
            if resources is not None
            else None
            if pending is None
            else pending.junit_handle
        )
        junit_cleanup = (
            resources.junit_cleanup
            if resources is not None
            else None
            if pending is None
            else pending.junit_cleanup
        )
        junit_is_cleaned = (
            resources.junit_is_cleaned
            if resources is not None
            else None
            if pending is None
            else pending.junit_is_cleaned
        )
        control_directory = (
            resources.control_directory
            if resources is not None
            else None
            if pending is None
            else pending.control_directory
        )
        remove_control_directory = (
            resources.remove_control_directory
            if resources is not None
            else None
            if pending is None
            else pending.remove_control_directory
        )
        if (
            pending is not None
            and pending.control_directory_state != "none"
            and control_directory is None
        ):
            cleanup_errors.append(
                stage1_error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Control-directory acquisition has no centrally recoverable owner.",
                    layer="plan_identities",
                )
            )
        if pending is not None and pending.junit_ownership_state != "none" and junit_handle is None:
            cleanup_errors.append(
                stage1_error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "JUnit acquisition has no centrally recoverable owner.",
                    layer="plan_identities",
                )
            )
        if executor_implementation is not None and executor_invalidator is not None:
            try:
                executor_invalidator(executor_implementation)
            except base_exception_type as error:
                cleanup_errors.append(error)
            if executor_is_current is None:
                cleanup_errors.append(
                    stage1_error_type(
                        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                        "Executor cleanup has no independent stale-state verifier.",
                        layer="live_executor_implementation_issuance",
                    )
                )
            else:
                try:
                    if executor_is_current(executor_implementation):
                        cleanup_errors.append(
                            stage1_error_type(
                                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                                "Executor cleanup did not make the capability stale.",
                                layer="live_executor_implementation_issuance",
                            )
                        )
                except base_exception_type as error:
                    cleanup_errors.append(error)
        junit_cleanup_complete = junit_handle is None
        if junit_handle is not None:
            if junit_cleanup is None:
                cleanup_errors.append(
                    stage1_error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "JUnit cleanup has no exact cleanup authority.",
                        layer="plan_identities",
                    )
                )
            else:
                try:
                    junit_cleanup(
                        junit_handle,
                        remove_control_directory=False,
                    )
                except base_exception_type as error:
                    cleanup_errors.append(error)
            if junit_is_cleaned is None:
                cleanup_errors.append(
                    stage1_error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "JUnit cleanup has no independent postcondition verifier.",
                        layer="plan_identities",
                    )
                )
            else:
                try:
                    junit_cleanup_complete = junit_is_cleaned(junit_handle)
                    if not junit_cleanup_complete:
                        cleanup_errors.append(
                            stage1_error_type(
                                "PYTEST_PLAN_ID_MISMATCH",
                                "JUnit cleanup postconditions were not satisfied.",
                                layer="plan_identities",
                            )
                        )
                except base_exception_type as error:
                    cleanup_errors.append(error)
        if (
            junit_cleanup_complete
            and control_directory is not None
            and remove_control_directory is not None
        ):
            try:
                remove_control_directory(control_directory)
            except base_exception_type as error:
                cleanup_errors.append(error)
            if not owned_control_directory_is_removed(control_directory):
                cleanup_errors.append(
                    stage1_error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Stage-1 control-directory cleanup postconditions were not satisfied.",
                        layer="plan_identities",
                    )
                )
        with lock:
            current_pending = pending_resources.get(session_token)
            if pending is not None and current_pending is not pending:
                cleanup_errors.append(
                    stage1_error_type(
                        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                        "The ownership ledger changed while cleanup was being verified.",
                        layer="live_executor_implementation_issuance",
                    )
                )
            if cleanup_record is not None:
                cleanup_run_id = cleanup_record.validation_run_id
                current_run = runs_by_id.get(cleanup_run_id)
                if (
                    current_run is not None
                    and current_run.state == "terminal"
                    and not cleanup_errors
                ):
                    runs_by_id[cleanup_run_id] = replace_record(
                        current_run,
                        resources_cleaned=True,
                    )
            if not cleanup_errors and pending is not None:
                completed_pending = replace_record(
                    pending,
                    control_directory_state=(
                        "none" if pending.control_directory_state == "none" else "cleanup_complete"
                    ),
                    junit_ownership_state=(
                        "none" if pending.junit_ownership_state == "none" else "cleanup_complete"
                    ),
                    generation=pending.generation + 1,
                )
                pending_resources[session_token] = completed_pending
                pending_resources.pop(session_token, None)
        if cleanup_errors:
            raise cleanup_errors[0]

    def abort_preparation(
        preparation: _ProductionPreparationCapability,
        session_token: _ProductionSessionToken,
        *,
        local_control_directory: _OwnedControlDirectory
        | _ProvisionalControlDirectory
        | None = None,
        local_junit_handle: object | None = None,
        local_executor_implementation: object | None = None,
        executor_invalidator: Callable[..., None] | None = None,
        executor_is_current: Callable[[object], bool] | None = None,
        junit_cleanup: Callable[..., None] | None = None,
        junit_is_open: Callable[[object], bool] | None = None,
        junit_is_cleaned: Callable[[object], bool] | None = None,
        remove_control_directory: Callable[[object], None] | None = None,
    ) -> None:
        with lock:
            preparation_record = preparations.get(preparation)
            if (
                preparation_record is not None
                and preparation_record.registry_guard is registry_guard
            ):
                preparations[preparation] = replace_record(preparation_record, state="tombstoned")
            run_record = next_value(
                (
                    record
                    for record in runs_by_id.values()
                    if exact_type(record) is run_record_type
                    and record.registry_guard is registry_guard
                    and record.preparation is preparation
                ),
                None,
            )
            has_local_resources = any_value(
                resource is not None
                for resource in (
                    local_control_directory,
                    local_junit_handle,
                    local_executor_implementation,
                )
            )
            if has_local_resources:
                if (
                    executor_invalidator is None
                    or executor_is_current is None
                    or junit_cleanup is None
                    or junit_is_open is None
                    or junit_is_cleaned is None
                    or remove_control_directory is None
                ):
                    fail_closed(
                        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                        "First-abort resource reconciliation lacks an exact cleanup authority.",
                        layer="live_executor_implementation_issuance",
                    )
                merge_pending_resources(
                    session_token,
                    control_directory=local_control_directory,
                    junit_handle=local_junit_handle,
                    executor_implementation=local_executor_implementation,
                    executor_invalidator=executor_invalidator,
                    executor_is_current=executor_is_current,
                    junit_cleanup=junit_cleanup,
                    junit_is_open=junit_is_open,
                    junit_is_cleaned=junit_is_cleaned,
                    remove_control_directory=remove_control_directory,
                )
                if run_record is not None and run_record.resources_cleaned:
                    run_record = replace_record(run_record, resources_cleaned=False)
                    runs_by_id[run_record.validation_run_id] = run_record
            pending = pending_resources.get(session_token)
            if pending is not None and pending.token is session_token:
                normalized_control_state = (
                    "none"
                    if pending.control_directory_state == "acquiring"
                    and pending.control_directory is None
                    else pending.control_directory_state
                )
                normalized_junit_state = (
                    "none"
                    if pending.junit_ownership_state == "acquiring" and pending.junit_handle is None
                    else pending.junit_ownership_state
                )
                if (
                    normalized_control_state != pending.control_directory_state
                    or normalized_junit_state != pending.junit_ownership_state
                ):
                    # Neither component may perform its physical acquisition
                    # before replacing `acquiring` with a centrally registered
                    # provisional owner.  On abort, ownerless acquisition intent
                    # is therefore safely equivalent to no acquired resource.
                    pending_resources[session_token] = replace_record(
                        pending,
                        control_directory_state=normalized_control_state,
                        junit_ownership_state=normalized_junit_state,
                        generation=pending.generation + 1,
                    )
            if run_record is not None and run_record.resources is None:
                runs_by_id[run_record.validation_run_id] = replace_record(
                    run_record, state="terminal"
                )
        cleanup_session(session_token)

    def summary() -> _ProductionRegistrySummary:
        with lock:
            records = materialize_tuple(
                record
                for record in runs_by_id.values()
                if exact_type(record) is run_record_type and record.registry_guard is registry_guard
            )
            pending_records = materialize_tuple(pending_resources.values())
        retained_candidates: list[tuple[object, Callable[[object], bool]]] = []
        for record in records:
            if record.resources is not None:
                retained_candidates.append(
                    (record.resources.junit_handle, record.resources.junit_is_open)
                )
        for pending in pending_records:
            if pending.junit_handle is not None:
                retained_candidates.append((pending.junit_handle, pending.junit_is_open))
        retained = 0
        observed_handles: list[object] = []
        for handle, is_open in retained_candidates:
            if any(observed is handle for observed in observed_handles):
                continue
            observed_handles.append(handle)
            if is_open(handle):
                retained += 1
        return _ProductionRegistrySummary(
            reserved_runs=sum_values(record.state == "reserved" for record in records),
            current_bound_runs=sum_values(record.state == "authority_bound" for record in records),
            terminal_runs=sum_values(record.state == "terminal" for record in records),
            complete_bindings=sum_values(record.binding is not None for record in records),
            terminal_complete_bindings=sum_values(
                record.state == "terminal" and record.binding is not None for record in records
            ),
            complete_binding_plan_slots=sum_values(
                6 for record in records if record.binding is not None and record.plans is not None
            ),
            partial_binding_records=sum_values(
                (record.binding is None) != (record.plans is None) for record in records
            ),
            current_plan_count=sum_values(
                6
                for record in records
                if record.state == "authority_bound" and record.plans is not None
            ),
            current_authority_count=sum_values(
                record.state == "authority_bound" and record.binding is not None
                for record in records
            ),
            retained_junit_handle_count=retained,
            resources_cleaned_count=sum_values(record.resources_cleaned for record in records),
        )

    @context_manager
    def failure_scope(failure_point: BindingFailurePoint) -> Iterator[None]:
        if exact_type(failure_point) is not str or failure_point not in failure_points:
            fail_closed(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Production failure injection requires one exact fail-closed point.",
                layer="issued_plan_binding",
            )
        if failure_selector.get() is not None:
            fail_closed(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Production failure injection cannot be nested or replayed.",
                layer="issued_plan_binding",
            )
        token = failure_selector.set(failure_point)
        try:
            yield
        finally:
            failure_selector.reset(token)

    def install_entrypoint(
        entry_point: Callable[..., object],
    ) -> tuple[Callable[[], object], Callable[..., object]]:
        nonlocal installed_entrypoint, installed_code, installed_gate
        nonlocal installed_public_entrypoint
        nonlocal sealed_component_validator
        if get_attribute(inspect_module, "currentframe", None) is not current_frame:
            fail_closed(
                "CALLABLE_IDENTITY_MISMATCH",
                "Production entry installation inspection authority was replaced.",
                layer="live_executor_implementation_issuance",
            )
        frame = current_frame()
        caller = None if frame is None else frame.f_back
        expected_module = runtime_modules.get("research_decision_engine.benchmarks.broader_smoke")
        expected_source = trusted_smoke_source
        code = get_attribute(entry_point, "__code__", None)
        code_source = None if code is None else path_type(code.co_filename).resolve()
        if (
            caller is None
            or expected_module is None
            or caller.f_globals is not module_vars(expected_module)
            or entry_point.__module__ != expected_module.__name__
            or entry_point.__qualname__ != "execute_bounded_validation_evidence"
            or code is None
            or code != trusted_entry_code
            or code_source != expected_source
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "The production entry route can be installed only by its trusted module.",
                layer="live_executor_implementation_issuance",
            )
        with lock:
            if installed_entrypoint is not None:
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "The sole production entry route is already sealed.",
                    layer="live_executor_implementation_issuance",
                )
            installed_entrypoint = entry_point
            installed_code = code
        with lock:
            preparer = sealed_preparer
            preparer_code = sealed_preparer_code
            collaborators = sealed_collaborators
            collaborator_validator = sealed_collaborator_validator
        if (
            preparer is None
            or preparer_code is None
            or collaborators is None
            or collaborator_validator is None
            or globals().get("_prepare_production_stage1") is not preparer
            or get_attribute(preparer, "__code__", None) is not preparer_code
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "The exact production preparation implementation is not sealed.",
                layer="live_executor_implementation_issuance",
            )
        trusted_preparer: Any = _runtime_cast(preparer)
        from research_decision_engine.benchmarks import (
            broader_conformance,
            broader_execution,
            broader_oracle,
            broader_protocol,
            broader_smoke,
            broader_validation,
        )

        component_rows: tuple[tuple[ModuleType, str, Callable[..., object]], ...] = (
            (
                broader_execution,
                "_issue_production_executor_implementation",
                broader_execution._issue_production_executor_implementation,
            ),
            (
                broader_validation,
                "_issue_production_pytest_plan_draft",
                broader_validation._issue_production_pytest_plan_draft,
            ),
            (
                broader_validation,
                "_validate_production_pytest_runtime",
                broader_validation._validate_production_pytest_runtime,
            ),
            (
                broader_oracle,
                "_issue_production_oracle_plan_draft",
                broader_oracle._issue_production_oracle_plan_draft,
            ),
            (
                broader_execution,
                "_issue_production_execution_plan_drafts",
                broader_execution._issue_production_execution_plan_drafts,
            ),
            (
                broader_execution,
                "_invalidate_production_executor_implementation",
                broader_execution._invalidate_production_executor_implementation,
            ),
            (
                broader_execution,
                "_production_executor_implementation_is_current",
                broader_execution._production_executor_implementation_is_current,
            ),
            (
                broader_validation,
                "_cleanup_retained_junit_handle",
                broader_validation._cleanup_retained_junit_handle,
            ),
            (
                broader_validation,
                "_retained_junit_handle_is_open",
                broader_validation._retained_junit_handle_is_open,
            ),
            (
                broader_validation,
                "_retained_junit_handle_is_cleaned",
                broader_validation._retained_junit_handle_is_cleaned,
            ),
            (
                broader_validation,
                "pytest_plan_id_from_projection",
                broader_validation.pytest_plan_id_from_projection,
            ),
            (
                broader_oracle,
                "oracle_plan_id_from_projection",
                broader_oracle.oracle_plan_id_from_projection,
            ),
            (
                broader_execution,
                "execution_specification_id_from_projection",
                broader_execution.execution_specification_id_from_projection,
            ),
            (
                broader_execution,
                "_require_trusted_executor_callable",
                broader_execution._require_trusted_executor_callable,
            ),
            (
                broader_execution,
                "_validate_execution_specification_context",
                broader_execution._validate_execution_specification_context,
            ),
            (
                broader_execution,
                "_verified_job_callable_projection",
                broader_execution._verified_job_callable_projection,
            ),
            (
                broader_execution,
                "_canonical_production_submitted_jobs",
                broader_execution._canonical_production_submitted_jobs,
            ),
            (
                broader_execution,
                "_assemble_execution_specification_projection",
                broader_execution._assemble_execution_specification_projection,
            ),
            (
                broader_execution,
                "_execution_specification_id_from_projection",
                broader_execution._execution_specification_id_from_projection,
            ),
            (
                broader_oracle,
                "_require_trusted_oracle_callable",
                broader_oracle._require_trusted_oracle_callable,
            ),
            (
                broader_oracle,
                "_build_oracle_plan_projection",
                broader_oracle._build_oracle_plan_projection,
            ),
            (
                broader_oracle,
                "_oracle_plan_id_from_projection",
                broader_oracle._oracle_plan_id_from_projection,
            ),
            (
                broader_oracle,
                "oracle_enumeration_domain_projection",
                broader_oracle.oracle_enumeration_domain_projection,
            ),
            (
                broader_oracle,
                "oracle_enumeration_domain_id",
                broader_oracle.oracle_enumeration_domain_id,
            ),
            (
                broader_validation,
                "_path_is_link_like",
                broader_validation._path_is_link_like,
            ),
            (
                broader_validation,
                "_create_guarded_junit_file",
                broader_validation._create_guarded_junit_file,
            ),
            (
                broader_validation,
                "_build_production_pytest_plan_projection",
                broader_validation._build_production_pytest_plan_projection,
            ),
            (
                broader_validation,
                "_validate_retained_junit_handle_identity",
                broader_validation._validate_retained_junit_handle_identity,
            ),
            (
                broader_validation,
                "_validate_retained_junit_handle",
                broader_validation._validate_retained_junit_handle,
            ),
            (
                broader_validation,
                "_read_file_descriptor",
                broader_validation._read_file_descriptor,
            ),
            (
                broader_smoke,
                "_execute_job",
                broader_smoke._execute_job,
            ),
            (
                broader_conformance,
                "_execute_run_job",
                broader_conformance._execute_run_job,
            ),
            (
                broader_execution,
                "protocol_hash",
                _runtime_cast(_TRUSTED_GETATTR(broader_execution, "protocol_hash")),
            ),
            (
                broader_execution,
                "repository_root",
                _runtime_cast(_TRUSTED_GETATTR(broader_execution, "repository_root")),
            ),
            (
                broader_execution,
                "callable_projection",
                _runtime_cast(_TRUSTED_GETATTR(broader_execution, "callable_projection")),
            ),
            (
                broader_oracle,
                "protocol_hash",
                _runtime_cast(_TRUSTED_GETATTR(broader_oracle, "protocol_hash")),
            ),
            (
                broader_oracle,
                "repository_root",
                _runtime_cast(_TRUSTED_GETATTR(broader_oracle, "repository_root")),
            ),
            (
                broader_oracle,
                "callable_projection",
                _runtime_cast(_TRUSTED_GETATTR(broader_oracle, "callable_projection")),
            ),
            (
                broader_validation,
                "protocol_hash",
                _runtime_cast(_TRUSTED_GETATTR(broader_validation, "protocol_hash")),
            ),
            (
                broader_validation,
                "repository_root",
                _runtime_cast(_TRUSTED_GETATTR(broader_validation, "repository_root")),
            ),
            (
                broader_protocol,
                "canonical_json_bytes",
                broader_protocol.canonical_json_bytes,
            ),
            (
                broader_protocol,
                "protocol_hash",
                broader_protocol.protocol_hash,
            ),
            (
                broader_protocol,
                "repository_root",
                broader_protocol.repository_root,
            ),
        )
        component_value_rows: tuple[tuple[ModuleType, str, object], ...] = (
            (broader_execution, "EVIDENCE_CONTRACT_CHECKPOINT", EVIDENCE_CONTRACT_CHECKPOINT),
            (broader_execution, "PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
            (broader_execution, "STUDY_ID", STUDY_ID),
            (
                broader_execution,
                "_P2_EXECUTION_ROLE_ORDER",
                broader_execution._P2_EXECUTION_ROLE_ORDER,
            ),
            (
                broader_execution,
                "_P2_EXECUTION_CONFIGURATIONS",
                broader_execution._P2_EXECUTION_CONFIGURATIONS,
            ),
            (broader_execution, "_P2_SMOKE_WORLD_IDS", broader_execution._P2_SMOKE_WORLD_IDS),
            (broader_execution, "_P2_SMOKE_SEEDS", broader_execution._P2_SMOKE_SEEDS),
            (broader_execution, "_P2_BUDGETS", broader_execution._P2_BUDGETS),
            (broader_execution, "_P2_ARMS", broader_execution._P2_ARMS),
            (
                broader_execution,
                "_P2_FIXTURE_WORLD_SEEDS",
                broader_execution._P2_FIXTURE_WORLD_SEEDS,
            ),
            (broader_oracle, "EVIDENCE_CONTRACT_CHECKPOINT", EVIDENCE_CONTRACT_CHECKPOINT),
            (broader_oracle, "PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
            (broader_oracle, "STUDY_ID", STUDY_ID),
            (broader_validation, "EVIDENCE_CONTRACT_CHECKPOINT", EVIDENCE_CONTRACT_CHECKPOINT),
            (broader_validation, "PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
            (broader_validation, "STUDY_ID", STUDY_ID),
            (broader_protocol, "PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
        )
        anchors: list[tuple[ModuleType, str, Callable[..., object], object]] = []
        compiled_anchor_cache: dict[tuple[Path, str], CodeType] = {}
        component_source_bytes: dict[Path, bytes] = {}
        for module, name, function in component_rows:
            function_code = get_attribute(function, "__code__", None)
            function_module = runtime_modules.get(get_attribute(function, "__module__", ""))
            function_source_name = (
                None
                if not instance_of(function_module, module_type)
                else get_attribute(function_module, "__file__", None)
            )
            compiled_code = function_code
            if isinstance(function_source_name, str):
                function_source = path_type(function_source_name)
                if function_source.suffix == ".pyc":
                    function_source = function_source.with_suffix(".py")
                function_source = function_source.resolve(strict=True)
                try:
                    function_source.relative_to(trusted_repository)
                except value_error_type:
                    pass
                else:
                    cache_key = (function_source, function.__qualname__)
                    source_bytes = function_source.read_bytes()
                    component_source_bytes.setdefault(function_source, source_bytes)
                    compiled_code = compiled_anchor_cache.get(cache_key)
                    if compiled_code is None:
                        compiled_code = compile_qualified(
                            source_bytes,
                            source_path=function_source,
                            qualname=function.__qualname__,
                        )
                        compiled_anchor_cache[cache_key] = compiled_code
            if (
                not is_callable(function)
                or get_attribute(module, name, None) is not function
                or (
                    function_code is not None
                    and (
                        get_attribute(compile_qualified, "__code__", None)
                        is not compile_qualified_code
                        or function_code != compiled_code
                    )
                )
            ):
                fail_closed(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Stage-1 component issuer is not an exact module callable: {name}.",
                    layer="validation_authority",
                )
            anchors.append((module, name, function, function_code))
        transitive_validate = _make_transitive_integrity_validator(
            (
                broader_execution,
                broader_validation,
                broader_oracle,
                broader_protocol,
                broader_smoke,
                broader_conformance,
            ),
            excluded_names={
                broader_smoke: frozenset(
                    {
                        "_build_bounded_validation_evidence_entrypoint",
                        "execute_bounded_validation_evidence",
                    }
                )
            },
        )
        component_issuers = _ProductionComponentIssuers(
            executor_implementation=broader_execution._issue_production_executor_implementation,
            pytest_plan=broader_validation._issue_production_pytest_plan_draft,
            pytest_runtime_validate=broader_validation._validate_production_pytest_runtime,
            oracle_plan=broader_oracle._issue_production_oracle_plan_draft,
            execution_plans=broader_execution._issue_production_execution_plan_drafts,
            executor_invalidator=(broader_execution._invalidate_production_executor_implementation),
            executor_is_current=(broader_execution._production_executor_implementation_is_current),
            junit_cleanup=broader_validation._cleanup_retained_junit_handle,
            junit_is_open=broader_validation._retained_junit_handle_is_open,
            junit_is_cleaned=broader_validation._retained_junit_handle_is_cleaned,
            anchors=materialize_tuple(anchors),
            value_anchors=component_value_rows,
            source_anchors=materialize_tuple(component_source_bytes.items()),
            transitive_validate=transitive_validate,
        )
        component_validator = exact_instance_validator(
            component_issuers,
            expected_type=component_issuers_type,
            field_names=component_field_names,
            semantic_validate=component_issuers.validate,
        )
        component_validator()
        collaborator_validator()
        with lock:
            sealed_component_validator = component_validator

        def gate() -> object:
            current = current_frame()
            entry_frame = None if current is None else current.f_back
            with lock:
                trusted_entrypoint = installed_entrypoint
                trusted_code = installed_code
                trusted_gate = installed_gate
                trusted_public_entrypoint = installed_public_entrypoint
            if (
                trusted_entrypoint is None
                or trusted_gate is None
                or trusted_public_entrypoint is None
                or entry_frame is None
                or entry_frame.f_locals.get("trusted_gate") is not trusted_gate
                or entry_frame.f_code is not trusted_code
                or entry_frame.f_globals is not module_vars(expected_module)
                or entry_frame.f_globals.get("execute_bounded_validation_evidence")
                is not trusted_public_entrypoint
                or trusted_entrypoint.__code__ is not trusted_code
                or callable_projection is not callable_projector
                or callable_projector.__code__ is not callable_projector_code
                or globals().get("_prepare_production_stage1") is not trusted_preparer
                or get_attribute(trusted_preparer, "__code__", None) is not preparer_code
            ):
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Only the exact installed production entry can open preparation.",
                    layer="live_executor_implementation_issuance",
                )
            component_validator()
            collaborator_validator()
            failure_point = failure_selector.get()

            @context_manager
            def lease() -> Iterator[None]:
                preparation = allocate(preparation_type)
                session_token = allocate(session_token_type)

                def terminate_and_cleanup() -> BaseException | None:
                    cleanup_error: BaseException | None = None
                    for _ in range(3):
                        try:
                            abort_preparation(preparation, session_token)
                        except base_exception_type as error:
                            cleanup_error = error
                        else:
                            return None
                    return cleanup_error

                try:
                    with lock:
                        preparations[preparation] = preparation_record_type(
                            capability=preparation,
                            session_token=session_token,
                            state="issued",
                            registry_guard=registry_guard,
                        )
                    invoke_preparer: Any = trusted_preparer
                    try:
                        invoke_preparer(
                            preparation=preparation,
                            session_token=session_token,
                            trusted_entrypoint=trusted_entrypoint,
                            trusted_public_entrypoint=trusted_public_entrypoint,
                            component_issuers=component_issuers,
                            trusted_callable_projector=callable_projector,
                            collaborators=collaborators,
                            validate_components=component_validator,
                            validate_collaborators=collaborator_validator,
                            failure_point=failure_point,
                        )
                    finally:
                        if failure_point is not None:
                            failure_selector.set(None)
                except base_exception_type as preparation_error:
                    cleanup_error = terminate_and_cleanup()
                    if cleanup_error is not None:
                        preparation_error.add_note(
                            "Stage-1 preparation cleanup also failed: "
                            f"{type(cleanup_error).__name__}: {cleanup_error}"
                        )
                    raise
                try:
                    yield
                finally:
                    terminal_errors: list[BaseException] = []
                    cleanup_error = terminate_and_cleanup()
                    if cleanup_error is not None:
                        terminal_errors.append(cleanup_error)
                    for validator in (collaborator_validator, component_validator):
                        try:
                            validator()
                        except base_exception_type as error:
                            terminal_errors.append(error)
                    if terminal_errors:
                        primary_error = terminal_errors[0]
                        for secondary_error in terminal_errors[1:]:
                            primary_error.add_note(
                                "Stage-1 terminal validation/cleanup also failed: "
                                f"{type(secondary_error).__name__}: {secondary_error}"
                            )
                        raise primary_error

            return lease()

        public_entrypoint = opaque_runtime_callable(entry_point)
        with lock:
            installed_gate = gate
            installed_public_entrypoint = public_entrypoint
        return gate, public_entrypoint

    def seal_preparer(
        preparer: Callable[..., object],
        collaborators: _ProductionPreparationCollaborators,
    ) -> None:
        nonlocal sealed_preparer, sealed_preparer_code, sealed_collaborators
        nonlocal sealed_collaborator_validator
        frame = current_frame()
        caller = None if frame is None else frame.f_back
        code = get_attribute(preparer, "__code__", None)
        if (
            caller is None
            or caller.f_globals is not globals()
            or preparer.__module__ != __name__
            or preparer.__qualname__ != "_prepare_production_stage1"
            or code is None
            or exact_type(collaborators) is not collaborators_type
        ):
            fail_closed(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Production preparer sealing is available only during module initialization.",
                layer="live_executor_implementation_issuance",
            )
        collaborator_validator = exact_instance_validator(
            collaborators,
            expected_type=collaborators_type,
            field_names=collaborator_field_names,
            semantic_validate=collaborators.validate,
        )
        try:
            collaborator_validator()
        except base_exception_type as error:
            if instance_of(error, stage1_error_type):
                raise
            fail_closed(
                "CALLABLE_IDENTITY_MISMATCH",
                "Production preparation collaborators could not be sealed exactly.",
                layer="validation_authority",
            )
        with lock:
            if sealed_preparer is not None:
                fail_closed(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production preparer is already sealed.",
                    layer="live_executor_implementation_issuance",
                )
            sealed_preparer = preparer
            sealed_preparer_code = code
            sealed_collaborators = collaborators
            sealed_collaborator_validator = collaborator_validator

    return (
        _runtime_cast(opaque_runtime_callable(require_preparation)),
        _runtime_cast(opaque_runtime_callable(consume_preparation)),
        _runtime_cast(opaque_runtime_callable(reserve_run)),
        _runtime_cast(opaque_runtime_callable(require_run)),
        _runtime_cast(opaque_runtime_callable(publish_binding)),
        _runtime_cast(opaque_runtime_callable(record_resources)),
        _runtime_cast(opaque_runtime_callable(production_plan)),
        _runtime_cast(opaque_runtime_callable(production_authority)),
        _runtime_cast(opaque_runtime_callable(abort_preparation)),
        _runtime_cast(opaque_runtime_callable(install_entrypoint)),
        opaque_runtime_callable(failure_scope),
        _runtime_cast(opaque_runtime_callable(summary)),
        _runtime_cast(opaque_runtime_callable(seal_preparer)),
        _runtime_cast(opaque_runtime_callable(begin_physical_resource)),
        _runtime_cast(opaque_runtime_callable(transition_physical_resource)),
        _runtime_cast(opaque_runtime_callable(allocate_executor_implementation)),
        _runtime_cast(opaque_runtime_callable(confirm_executor_implementation)),
        _runtime_cast(opaque_runtime_callable(allocate_plan_capability)),
        _runtime_cast(opaque_runtime_callable(record_plan_draft)),
        _runtime_cast(opaque_runtime_callable(allocate_authority_capability)),
        _runtime_cast(opaque_runtime_callable(record_unpublished_binding)),
    )


(
    _require_production_preparation,
    _consume_production_preparation,
    _reserve_production_validation_run,
    _require_production_run,
    _publish_production_binding,
    _record_production_resources,
    _production_plan_lookup,
    _production_authority_lookup,
    _abort_production_preparation,
    _install_production_entrypoint,
    _production_failure_scope,
    _production_registry_snapshot,
    _seal_production_preparer,
    _begin_production_physical_resource,
    _transition_production_physical_resource,
    _allocate_production_executor_implementation,
    _confirm_production_executor_implementation,
    _allocate_production_plan_capability,
    _record_production_plan_draft,
    _allocate_production_authority_capability,
    _record_production_unpublished_binding,
) = _make_production_registry()
del _make_production_registry


def validation_run_id(run: ValidationRun) -> str:
    """Return only a current production run identity."""

    return _production_validation_run_id(run)


def _production_validation_run_id(run: ValidationRun) -> str:
    return _require_production_run(run, allow_bound=True).validation_run_id


def _fixture_validation_run_id(run: _FixtureValidationRun) -> str:
    with _FIXTURE_REGISTRY_LOCK:
        record = _FIXTURE_RUN_RECORDS.get(run)
    if (
        type(run) is not _FixtureValidationRun
        or record is None
        or record.capability is not run
        or record.state == "terminal"
    ):
        _error(
            "VALIDATION_RUN_STALE",
            "Exact current fixture validation-run capability required.",
            layer="validation_run_issuance",
        )
    return record.validation_run_id


def _register_fixture_plan(draft: _PlanDraft) -> None:
    if type(draft.validation_run) is not _FixtureValidationRun:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Fixture plans require the disjoint fixture run capability.",
            layer="plan_identities",
        )
    fixture_run = _runtime_cast(draft.validation_run)
    run_id = _fixture_validation_run_id(fixture_run)
    if draft.validation_run_id != run_id:
        _error(
            "ISSUED_PLAN_RUN_MISMATCH",
            "Fixture plan and fixture run differ.",
            layer="plan_identities",
        )
    expected_slots = {
        "pytest": ("pytest", "pytest"),
        "oracle": ("oracle", "oracle"),
        "primary_smoke": ("execution_specification", "primary_smoke"),
        "altered_order_replay": ("execution_specification", "altered_order_replay"),
        "fixture_primary": ("execution_specification", "fixture_primary"),
        "fixture_replay": ("execution_specification", "fixture_replay"),
    }
    if expected_slots.get(draft.role) != (draft.kind, draft.role):
        _error(
            "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
            "Fixture plan does not occupy one of the six closed slots.",
            layer="validation_authority",
        )
    with _FIXTURE_REGISTRY_LOCK:
        if draft.capability in _FIXTURE_PLAN_RECORDS:
            _error("ISSUED_PLAN_STALE", "Fixture plan was already issued.", layer="plan_identities")
        if any(
            current.draft.validation_run is draft.validation_run
            and current.draft.role == draft.role
            for current in _FIXTURE_PLAN_RECORDS.values()
        ):
            _error(
                "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
                "A closed fixture plan slot can be issued exactly once.",
                layer="validation_authority",
            )
        if draft.validation_run in {
            current.validation_run for current in _FIXTURE_AUTHORITY_RECORDS.values()
        }:
            _error(
                "ISSUED_PLAN_STALE",
                "No fixture plan can be registered after authority publication.",
                layer="live_issued_plan_binding",
            )
        _FIXTURE_PLAN_RECORDS[draft.capability] = _FixturePlanRecord(draft)


def _require_plan(
    capability: object,
    *,
    expected_kind: PlanKind | None = None,
    expected_domain: TrustDomain | None = None,
) -> tuple[_PlanDraft, BindingState, TrustDomain]:
    production = _production_plan_lookup(capability)
    if production is not None:
        draft, run_record = production
        domain: TrustDomain = "production"
        state: BindingState = (
            "stale"
            if run_record.state == "terminal"
            else "authority_bound"
            if run_record.binding is not None
            else "authority_unbound"
        )
    else:
        with _FIXTURE_REGISTRY_LOCK:
            fixture = _FIXTURE_PLAN_RECORDS.get(capability)
            fixture_binding = next(
                (
                    record
                    for record in _FIXTURE_AUTHORITY_RECORDS.values()
                    if fixture is not None and record.validation_run is fixture.draft.validation_run
                ),
                None,
            )
        if fixture is None or fixture.draft.capability is not capability:
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "Exact issued plan capability required.",
                layer="live_issued_plan_binding",
            )
        draft = fixture.draft
        domain = "fixture"
        state = (
            "stale"
            if not fixture.active
            else "authority_bound"
            if fixture_binding is not None and fixture_binding.active
            else "authority_unbound"
        )
    if state == "stale":
        _error("ISSUED_PLAN_STALE", "Issued plan is stale.", layer="live_issued_plan_binding")
    if expected_kind is not None and draft.kind != expected_kind:
        _error(
            "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
            "Plan kind differs from its authority slot.",
            layer="validation_authority",
        )
    if expected_domain is not None and domain != expected_domain:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Fixture and production plan capability types and registries are disjoint.",
            layer="validation_authority",
        )
    _validate_plan_fingerprint(draft)
    return draft, state, domain


def plan_binding_state(capability: object) -> BindingState:
    return _require_plan(capability)[1]


def plan_persistent_id(capability: object) -> str:
    return _require_plan(capability)[0].persistent_id


def plan_projection(capability: object) -> object:
    # Projections are recursively frozen; every as_dict() call reconstructs a
    # defensive mutable rendering rather than exposing registry-owned state.
    return _require_plan(capability)[0].projection


def _validate_layer0_context(context: Layer0Context, trust_domain: TrustDomain) -> None:
    expected_runtime_identity = protocol_hash(
        "validation_evidence_runtime/v1", context.runtime.as_dict()
    )
    if context.runtime_identity != expected_runtime_identity:
        _error(
            "RUNTIME_IDENTITY_MISMATCH",
            "Layer-0 runtime identity does not recompute.",
            layer="validation_authority",
        )
    issuer_rows = (
        (
            context.validation_authority_issuer,
            context.validation_authority_issuer_identity,
            "validation_authority",
        ),
        (context.pytest_plan_issuer, context.pytest_plan_issuer_identity, "pytest_plan"),
        (context.oracle_plan_issuer, context.oracle_plan_issuer_identity, "oracle_plan"),
        (
            context.execution_specification_issuer,
            context.execution_specification_issuer_identity,
            "execution_specification",
        ),
    )
    expected_entries = {
        "production": (
            "research_decision_engine.benchmarks.broader_smoke.execute_bounded_validation_evidence",
            "research_decision_engine.benchmarks.broader_validation.execute_pytest_validation",
            "research_decision_engine.benchmarks.broader_oracle.begin_oracle_evidence_binding",
            "research_decision_engine.benchmarks.broader_execution.execute_deterministic_map",
        ),
        "fixture": (
            "fixture.validation_authority",
            "fixture.pytest_plan",
            "fixture.oracle_plan",
            "fixture.execution_specification",
        ),
    }[trust_domain]
    for index, (issuer, identity, role) in enumerate(issuer_rows):
        if (
            issuer.role != role
            or issuer.trust_domain != trust_domain
            or issuer.entry_point != expected_entries[index]
            or issuer.evidence_contract_checkpoint != EVIDENCE_CONTRACT_CHECKPOINT
            or issuer.protocol_checkpoint != PROTOCOL_CHECKPOINT
            or issuer.implementation != context.implementation
            or issuer.runtime != context.runtime
            or issuer.runtime_identity != context.runtime_identity
            or identity != protocol_hash("validation_evidence_issuer/v1", issuer.as_dict())
        ):
            _error(
                "ISSUER_IDENTITY_MISMATCH",
                "Layer-0 issuer identity or trust domain does not recompute.",
                layer="validation_authority",
            )
    callable_identity = protocol_hash(
        "validation_evidence_callable/v1", context.evidence_generator.as_dict()
    )
    generator_projection = {
        "callable": context.evidence_generator.as_dict(),
        "callable_identity": callable_identity,
        "entry_point": context.evidence_generator_entry_point,
        "evidence_contract_checkpoint": EVIDENCE_CONTRACT_CHECKPOINT,
        "implementation": context.implementation.as_dict(),
        "protocol_checkpoint": PROTOCOL_CHECKPOINT,
        "runtime": context.runtime.as_dict(),
        "runtime_identity": context.runtime_identity,
        "schema_version": "broader-replication-validation-evidence-generator/v1",
    }
    expected_generator_entry = (
        "research_decision_engine.benchmarks.broader_smoke.execute_bounded_validation_evidence"
        if trust_domain == "production"
        else "fixture.validation_generator"
    )
    if (
        context.evidence_generator_entry_point != expected_generator_entry
        or context.evidence_generator_identity
        != protocol_hash("validation_evidence_generator/v1", generator_projection)
    ):
        _error(
            "EVIDENCE_GENERATOR_IDENTITY_MISMATCH",
            "Layer-0 evidence generator identity does not recompute.",
            layer="validation_authority",
        )


def _recompute_plan(
    record: _PlanDraft,
    *,
    trust_domain: TrustDomain,
) -> tuple[dict[str, object], str]:
    from research_decision_engine.benchmarks import (
        broader_execution,
        broader_oracle,
        broader_validation,
    )

    if record.kind == "pytest":
        expected_type: type[object] = _runtime_cast(
            broader_validation.PytestPlan
            if trust_domain == "production"
            else broader_validation._FixturePytestPlan
        )
        if (
            type(record.capability) is not expected_type
            or type(record.projection) is not broader_validation.PytestPlanProjection
        ):
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "Pytest authority slot requires an exact issued PytestPlan.",
                layer="live_issued_plan_binding",
            )
        mapping = record.projection.as_dict()
        persistent_id = broader_validation.pytest_plan_id_from_projection(record.projection)
    elif record.kind == "oracle":
        expected_type = _runtime_cast(
            broader_oracle.OraclePlan
            if trust_domain == "production"
            else broader_oracle._FixtureOraclePlan
        )
        if (
            type(record.capability) is not expected_type
            or type(record.projection) is not broader_oracle.OraclePlanProjection
        ):
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "Oracle authority slot requires an exact issued OraclePlan.",
                layer="live_issued_plan_binding",
            )
        mapping = record.projection.as_dict()
        persistent_id = broader_oracle.oracle_plan_id_from_projection(record.projection)
    else:
        expected_type = _runtime_cast(
            broader_execution.ExecutionSpecification
            if trust_domain == "production"
            else broader_execution._FixtureExecutionSpecification
        )
        if (
            type(record.capability) is not expected_type
            or type(record.projection) is not broader_execution.ExecutionSpecificationProjection
        ):
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "Executor authority slot requires an exact issued ExecutionSpecification.",
                layer="live_issued_plan_binding",
            )
        mapping = record.projection.as_dict()
        persistent_id = (
            broader_execution.execution_specification_id_from_projection(record.projection)
            if trust_domain == "production"
            else broader_execution._fixture_execution_specification_id_from_projection(
                record.projection
            )
        )
    return mapping, persistent_id


def _validate_plan_fingerprint(record: _PlanDraft) -> None:
    trust_domain: TrustDomain = (
        "production" if type(record.validation_run) is ValidationRun else "fixture"
    )
    mapping, recomputed_id = _recompute_plan(record, trust_domain=trust_domain)
    expected_fingerprint = protocol_hash(
        "validation_evidence_live_plan_fingerprint/v1",
        {
            "kind": record.kind,
            "persistent_id": record.persistent_id,
            "projection": mapping,
            "role": record.role,
            "validation_run_id": record.validation_run_id,
        },
    )
    if recomputed_id != record.persistent_id or expected_fingerprint != record.fingerprint:
        _error(
            "ISSUED_PLAN_MUTATED_AFTER_AUTHORITY",
            "A retained immutable plan projection or identity no longer recomputes.",
            layer="live_issued_plan_binding",
        )


def _validate_plan_context(
    *,
    context: Layer0Context,
    validation_run_id: str,
    record: _PlanDraft,
    trust_domain: TrustDomain,
) -> dict[str, object]:
    mapping, recomputed_id = _recompute_plan(record, trust_domain=trust_domain)
    issuer_field, issuer_identity = {
        "pytest": ("plan_issuer_identity", context.pytest_plan_issuer_identity),
        "oracle": ("plan_issuer_identity", context.oracle_plan_issuer_identity),
        "execution_specification": (
            "specification_issuer_identity",
            context.execution_specification_issuer_identity,
        ),
    }[record.kind]
    if (
        recomputed_id != record.persistent_id
        or mapping.get("evidence_contract_checkpoint") != EVIDENCE_CONTRACT_CHECKPOINT
        or mapping.get("protocol_checkpoint") != PROTOCOL_CHECKPOINT
        or mapping.get("validation_run_id") != validation_run_id
        or mapping.get("implementation") != context.implementation.as_dict()
        or mapping.get("runtime") != context.runtime.as_dict()
        or mapping.get("runtime_identity") != context.runtime_identity
        or mapping.get(issuer_field) != issuer_identity
    ):
        _error(
            "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
            "Plan identity, checkpoint, issuer, run, or Layer-0 relation differs.",
            layer="validation_authority",
        )
    return mapping


def _authority_projection(
    *, context: Layer0Context, validation_run_id: str, records: Sequence[_PlanDraft]
) -> ValidationAuthorityProjection:
    if len(records) != 6:
        error_code = (
            "VALIDATION_AUTHORITY_PLAN_MISSING"
            if len(records) < 6
            else "VALIDATION_AUTHORITY_PLAN_EXTRA"
        )
        _error(
            error_code,
            "Validation authority requires exactly six plans.",
            layer="validation_authority",
        )
    expected = (
        ("pytest", "pytest"),
        ("oracle", "oracle"),
        ("execution_specification", "primary_smoke"),
        ("execution_specification", "altered_order_replay"),
        ("execution_specification", "fixture_primary"),
        ("execution_specification", "fixture_replay"),
    )
    observed = tuple((record.kind, record.role) for record in records)
    if observed != expected:
        _error(
            "VALIDATION_AUTHORITY_PLAN_ORDER_MISMATCH",
            "Six-plan order or role differs from the frozen order.",
            layer="validation_authority",
        )
    if (
        len({record.capability for record in records}) != 6
        or len({record.persistent_id for record in records}) != 6
    ):
        _error(
            "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
            "Validation authority plans must be duplicate-free.",
            layer="validation_authority",
        )
    if any(record.validation_run_id != validation_run_id for record in records):
        _error(
            "ISSUED_PLAN_RUN_MISMATCH",
            "All authority plans must belong to one validation run.",
            layer="validation_authority",
        )
    return ValidationAuthorityProjection(
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        evidence_generator_identity=context.evidence_generator_identity,
        implementation=context.implementation,
        oracle_plan_id=records[1].persistent_id,
        permitted_final_evidence_filenames=PERMITTED_FINAL_EVIDENCE_FILENAMES,
        primary_smoke_execution_specification_id=records[2].persistent_id,
        production_fixture_execution_specification_ids=(
            records[4].persistent_id,
            records[5].persistent_id,
        ),
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        pytest_plan_id=records[0].persistent_id,
        replay_execution_specification_id=records[3].persistent_id,
        runtime=context.runtime,
        runtime_identity=context.runtime_identity,
        validation_run_id=validation_run_id,
    )


def validation_authority_id_from_projection(
    projection: ValidationAuthorityProjection,
) -> str:
    return protocol_hash("validation_evidence_authority/v1", projection.as_dict())


def _six_plan_set(records: Sequence[_PlanDraft]) -> _SixPlanSet:
    materialized = tuple(records)
    if len(materialized) != 6:
        error_code = (
            "VALIDATION_AUTHORITY_PLAN_MISSING"
            if len(materialized) < 6
            else "VALIDATION_AUTHORITY_PLAN_EXTRA"
        )
        _error(
            error_code,
            "Validation authority requires six closed slots.",
            layer="validation_authority",
        )
    return _SixPlanSet(
        pytest=materialized[0],
        oracle=materialized[1],
        primary_smoke=materialized[2],
        altered_order_replay=materialized[3],
        fixture_primary=materialized[4],
        fixture_replay=materialized[5],
    )


def _prepare_binding_record(
    *,
    context: Layer0Context,
    validation_run_id: str,
    plans: _SixPlanSet,
    trust_domain: TrustDomain,
    failure_point: BindingFailurePoint | None,
    allocate_authority: Callable[..., object],
    record_unpublished_binding: Callable[[_BindingRecord], None] | None = None,
) -> _BindingRecord:
    """Phase A: perform every fallible operation without authoritative mutation."""

    _validate_layer0_context(context, trust_domain)
    records = plans.ordered()
    for index, record in enumerate(records):
        if failure_point == f"validate_plan_{index}":
            _error(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                f"Injected failure occurred during plan validation {index}.",
                layer="issued_plan_binding",
            )
        _validate_plan_context(
            context=context,
            validation_run_id=validation_run_id,
            record=record,
            trust_domain=trust_domain,
        )
        _validate_plan_fingerprint(record)
    projection = _authority_projection(
        context=context,
        validation_run_id=validation_run_id,
        records=records,
    )
    authority_id = validation_authority_id_from_projection(projection)
    if failure_point == "before_authority_construction":
        _error(
            "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
            "Injected failure occurred before local authority construction.",
            layer="issued_plan_binding",
        )
    authority: ValidationAuthority | _FixtureValidationAuthority = (
        _runtime_cast(
            allocate_authority(
                _runtime_cast(ValidationAuthority),
                authority_id,
            )
        )
        if trust_domain == "production"
        else _runtime_cast(allocate_authority(_runtime_cast(_FixtureValidationAuthority)))
    )
    binding = _BindingRecord(
        capability=authority,
        projection=projection,
        validation_authority_id=authority_id,
        validation_run_id=validation_run_id,
        plans=plans,
        trust_domain=trust_domain,
    )
    if trust_domain == "production":
        if record_unpublished_binding is None:
            _error(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Production authority construction has no central binding owner.",
                layer="issued_plan_binding",
            )
        record_unpublished_binding(binding)
    elif record_unpublished_binding is not None:
        _error(
            "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
            "Fixture authority construction cannot use the production ownership ledger.",
            layer="issued_plan_binding",
        )
    if failure_point == "after_authority_construction":
        _error(
            "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
            "Injected failure occurred after local authority construction.",
            layer="issued_plan_binding",
        )
    return binding


def _issue_fixture_authority_locked(
    *,
    context: Layer0Context,
    validation_run: _FixtureValidationRun,
    plans: Sequence[object],
    failure_point: BindingFailurePoint | None = None,
) -> _FixtureValidationAuthority:
    capabilities = tuple(plans)
    with _FIXTURE_REGISTRY_LOCK:
        run_record = _FIXTURE_RUN_RECORDS.get(validation_run)
        already_bound = any(
            record.validation_run is validation_run and record.active
            for record in _FIXTURE_AUTHORITY_RECORDS.values()
        )
    if (
        type(validation_run) is not _FixtureValidationRun
        or run_record is None
        or run_record.capability is not validation_run
        or run_record.state == "terminal"
    ):
        _error(
            "VALIDATION_RUN_STALE",
            "Exact current fixture run required.",
            layer="validation_run_issuance",
        )
    if already_bound:
        _error(
            "ISSUED_PLAN_AUTHORITY_MISMATCH",
            "Fixture six-slot registry is already closed and bound.",
            layer="issued_plan_binding",
        )
    records = tuple(
        _require_plan(capability, expected_domain="fixture")[0] for capability in capabilities
    )
    if any(record.validation_run is not validation_run for record in records):
        _error(
            "ISSUED_PLAN_RUN_MISMATCH",
            "Every fixture plan must belong to the exact fixture run.",
            layer="validation_authority",
        )
    plan_set = _six_plan_set(records)
    binding = _prepare_binding_record(
        context=context,
        validation_run_id=run_record.validation_run_id,
        plans=plan_set,
        trust_domain="fixture",
        failure_point=failure_point,
        allocate_authority=object.__new__,
    )
    authority = binding.capability
    if type(authority) is not _FixtureValidationAuthority:
        raise AssertionError("Fixture authority construction crossed capability domains.")
    fixture_authority: _FixtureValidationAuthority = _runtime_cast(authority)
    authority_record = _FixtureAuthorityRecord(binding=binding, validation_run=validation_run)
    # Phase B: a single authoritative publication. No plan record is mutated.
    with _FIXTURE_REGISTRY_LOCK:
        if any(
            record.validation_run is validation_run and record.active
            for record in _FIXTURE_AUTHORITY_RECORDS.values()
        ) or any(
            (current := _FIXTURE_PLAN_RECORDS.get(draft.capability)) is None
            or current.draft is not draft
            or not current.active
            for draft in plan_set.ordered()
        ):
            _error(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Fixture registry changed before its single authority publication.",
                layer="issued_plan_binding",
            )
        if failure_point == "before_publication":
            _error(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Injected failure occurred immediately before publication.",
                layer="issued_plan_binding",
            )
        _single_assignment_publish(
            _FIXTURE_AUTHORITY_RECORDS,
            fixture_authority,
            authority_record,
            failure_point=failure_point,
        )
    return fixture_authority


def _issue_fixture_authority(
    *,
    context: Layer0Context,
    validation_run: _FixtureValidationRun,
    plans: Sequence[object],
    failure_point: BindingFailurePoint | None = None,
) -> _FixtureValidationAuthority:
    # Materialize an untrusted/stateful sequence exactly once, then hold the
    # authoritative lock continuously through Phase A and the one publication.
    capabilities = tuple(plans)
    with _FIXTURE_REGISTRY_LOCK:
        return _issue_fixture_authority_locked(
            context=context,
            validation_run=validation_run,
            plans=capabilities,
            failure_point=failure_point,
        )


def validation_authority_projection(
    authority: ValidationAuthority,
) -> ValidationAuthorityProjection:
    if type(authority) is not ValidationAuthority:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Fixture validation authority cannot be projected as production.",
            layer="validation_authority",
        )
    return _require_authority(authority).projection


def validation_authority_id(
    authority: ValidationAuthority,
) -> str:
    if type(authority) is not ValidationAuthority:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Fixture validation authority has no production authority identity.",
            layer="validation_authority",
        )
    return _require_authority(authority).validation_authority_id


def _fixture_validation_authority_projection(
    authority: _FixtureValidationAuthority,
) -> ValidationAuthorityProjection:
    if type(authority) is not _FixtureValidationAuthority:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Exact fixture validation authority required.",
            layer="validation_authority",
        )
    return _require_authority(authority).projection


def _fixture_validation_authority_id(authority: _FixtureValidationAuthority) -> str:
    if type(authority) is not _FixtureValidationAuthority:
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Exact fixture validation authority required.",
            layer="validation_authority",
        )
    return _require_authority(authority).validation_authority_id


def _require_authority(
    authority: ValidationAuthority | _FixtureValidationAuthority,
) -> _BindingRecord:
    production = _production_authority_lookup(authority)
    if production is not None:
        binding, run_record = production
        if (
            type(authority) is not ValidationAuthority
            or binding.capability is not authority
            or run_record.state != "authority_bound"
        ):
            _error(
                "VALIDATION_AUTHORITY_NOT_CURRENT",
                "Production validation authority is stale.",
                layer="validation_authority",
            )
    else:
        with _FIXTURE_REGISTRY_LOCK:
            fixture = _FIXTURE_AUTHORITY_RECORDS.get(_runtime_cast(authority))
            fixture_plans_current = fixture is not None and all(
                (current := _FIXTURE_PLAN_RECORDS.get(draft.capability)) is not None
                and current.draft is draft
                and current.active
                for draft in fixture.binding.plans.ordered()
            )
        if (
            type(authority) is not _FixtureValidationAuthority
            or fixture is None
            or fixture.binding.capability is not authority
            or not fixture.active
            or not fixture_plans_current
        ):
            _error(
                "VALIDATION_AUTHORITY_NOT_CURRENT",
                "Exact current validation authority capability required.",
                layer="validation_authority",
            )
        binding = fixture.binding
    if (
        validation_authority_id_from_projection(binding.projection)
        != binding.validation_authority_id
        or binding.projection.validation_run_id != binding.validation_run_id
        or binding.projection.pytest_plan_id != binding.plans.pytest.persistent_id
        or binding.projection.oracle_plan_id != binding.plans.oracle.persistent_id
        or binding.projection.primary_smoke_execution_specification_id
        != binding.plans.primary_smoke.persistent_id
        or binding.projection.replay_execution_specification_id
        != binding.plans.altered_order_replay.persistent_id
        or binding.projection.production_fixture_execution_specification_ids
        != (
            binding.plans.fixture_primary.persistent_id,
            binding.plans.fixture_replay.persistent_id,
        )
    ):
        _error(
            "VALIDATION_AUTHORITY_ID_MISMATCH",
            "Validation authority projection no longer recomputes.",
            layer="validation_authority",
        )
    for draft in binding.plans.ordered():
        _validate_plan_fingerprint(draft)
    return binding


def assert_stage1_plan_not_executable(capability: object) -> NoReturn:
    _, binding_state, _ = _require_plan(capability)
    if binding_state == "authority_unbound":
        _error(
            "ISSUED_PLAN_AUTHORITY_MISMATCH",
            "An authority-unbound P2 plan cannot execute.",
            layer="live_issued_plan_binding",
        )
    _error(
        "P2_STAGE3_EXECUTION_NOT_IMPLEMENTED",
        "Stage 1 binds plans but does not execute them.",
        layer="stage_boundary",
    )


def _prepare_production_stage1(
    *,
    preparation: _ProductionPreparationCapability,
    session_token: _ProductionSessionToken,
    trusted_entrypoint: Callable[..., object],
    trusted_public_entrypoint: Callable[..., object],
    component_issuers: _ProductionComponentIssuers,
    trusted_callable_projector: Callable[[Callable[..., object]], tuple[CallableProjection, str]],
    collaborators: _ProductionPreparationCollaborators,
    validate_components: Callable[[], None],
    validate_collaborators: Callable[[], None],
    failure_point: BindingFailurePoint | None,
) -> None:
    """Issue and atomically bind the six production plans without executing them."""

    provisional_control_directory: _ProvisionalControlDirectory | None = None
    owned_control_directory: _OwnedControlDirectory | None = None
    control_directory: Path | None = None
    executor_implementation: object | None = None
    provisional_junit_handle: object | None = None
    junit_handle: object | None = None
    validate_collaborators()
    validate_components()
    consume_preparation = collaborators.consume
    derive_context = collaborators.derive_context
    reserve_run = collaborators.reserve_run
    create_control_directory = collaborators.create_control_directory
    begin_physical_resource = collaborators.begin_physical_resource
    transition_physical_resource = collaborators.transition_physical_resource
    allocate_executor_implementation = collaborators.allocate_executor_implementation
    confirm_executor_implementation = collaborators.confirm_executor_implementation
    six_plan_set = collaborators.six_plan_set
    prepare_binding = collaborators.prepare_binding
    allocate_authority = collaborators.allocate_authority
    record_unpublished_binding = collaborators.record_unpublished_binding
    run_id = collaborators.run_id
    publish_binding = collaborators.publish_binding
    record_resources = collaborators.record_resources
    abort = collaborators.abort
    remove_control_directory = collaborators.remove_control_directory
    replace_record = collaborators.replace_record
    resources_type = collaborators.resources_type
    authority_type = collaborators.authority_type
    error_type = collaborators.error_type
    issue_executor_implementation = component_issuers.executor_implementation
    issue_pytest_plan = component_issuers.pytest_plan
    issue_oracle_plan = component_issuers.oracle_plan
    issue_execution_plans = component_issuers.execution_plans
    invalidate_executor = component_issuers.executor_invalidator
    executor_is_current = component_issuers.executor_is_current
    cleanup_junit = component_issuers.junit_cleanup
    junit_is_open = component_issuers.junit_is_open
    junit_is_cleaned = component_issuers.junit_is_cleaned
    validate_components()
    validate_collaborators()
    try:
        validate_collaborators()
        consume_preparation(preparation, session_token)
        validate_components()
        context = derive_context(
            trusted_entrypoint=trusted_entrypoint,
            trusted_public_entrypoint=trusted_public_entrypoint,
            trusted_callable_projector=trusted_callable_projector,
        )
        validate_collaborators()
        validation_run = reserve_run(preparation)
        record_resources(
            preparation,
            session_token,
            validation_run,
            control_directory=None,
            junit_handle=None,
            executor_implementation=None,
            executor_invalidator=invalidate_executor,
            executor_is_current=executor_is_current,
            junit_cleanup=cleanup_junit,
            junit_is_open=junit_is_open,
            junit_is_cleaned=junit_is_cleaned,
            remove_control_directory=remove_control_directory,
        )
        if failure_point == "after_run_reservation_before_ledger":
            raise error_type(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Injected failure occurred immediately after central run registration.",
                layer="issued_plan_binding",
            )

        def begin_control_directory_acquisition() -> None:
            begin_physical_resource(
                preparation,
                session_token,
                validation_run,
                "control_directory",
            )

        def retain_provisional_control_directory(resource: object) -> None:
            nonlocal provisional_control_directory
            if type(resource) is not _ProvisionalControlDirectory:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Control-directory acquisition returned an invalid provisional owner.",
                    layer="plan_identities",
                )
            provisional = _runtime_cast(resource)
            if provisional_control_directory is not None:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "A production session can retain one provisional control directory.",
                    layer="plan_identities",
                )
            provisional_control_directory = provisional
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "control_directory",
                provisional,
                previous_resource=None,
                state="centrally_registered",
            )

        def checkpoint_provisional_control_directory() -> None:
            if failure_point == "after_control_directory_creation_before_ledger":
                raise error_type(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Injected failure occurred after central provisional-directory registration.",
                    layer="issued_plan_binding",
                )

        def cancel_control_directory_acquisition() -> None:
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "control_directory",
                None,
                previous_resource=None,
                state="none",
            )

        def checkpoint_control_directory_acquisition() -> None:
            if failure_point == "control_directory_acquisition_failure":
                raise OSError("Injected clean control-directory acquisition failure.")

        def retain_owned_control_directory(
            provisional: object,
            owned: object,
        ) -> None:
            nonlocal owned_control_directory, control_directory
            if (
                provisional is not provisional_control_directory
                or type(owned) is not _OwnedControlDirectory
            ):
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Control-directory ownership promotion changed the acquired resource.",
                    layer="plan_identities",
                )
            exact_owned = _runtime_cast(owned)
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "control_directory",
                exact_owned,
                previous_resource=provisional,
                state="retained",
            )
            owned_control_directory = exact_owned
            control_directory = exact_owned.path

        returned_control_directory = create_control_directory(
            preparation,
            directory_name_token=run_id(validation_run),
            begin_acquisition=begin_control_directory_acquisition,
            acquisition_checkpoint=checkpoint_control_directory_acquisition,
            cancel_acquisition=cancel_control_directory_acquisition,
            retain_provisional=retain_provisional_control_directory,
            retain_owned=retain_owned_control_directory,
            retained_checkpoint=checkpoint_provisional_control_directory,
        )
        if returned_control_directory is not owned_control_directory:
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Control-directory creator returned a different owned resource.",
                layer="plan_identities",
            )
        record_resources(
            preparation,
            session_token,
            validation_run,
            control_directory=owned_control_directory,
            junit_handle=None,
            executor_implementation=None,
            executor_invalidator=invalidate_executor,
            executor_is_current=executor_is_current,
            junit_cleanup=cleanup_junit,
            junit_is_open=junit_is_open,
            junit_is_cleaned=junit_is_cleaned,
            remove_control_directory=remove_control_directory,
        )
        validate_components()

        def allocate_executor_capability(capability_type: type[object]) -> object:
            capability = allocate_executor_implementation(
                preparation,
                validation_run,
                capability_type=capability_type,
            )
            if executor_is_current(capability):
                raise error_type(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Centrally allocated executor capability became current before registration.",
                    layer="live_executor_implementation_issuance",
                )
            return capability

        def confirm_executor_capability(capability: object) -> None:
            confirm_executor_implementation(
                preparation,
                validation_run,
                capability,
            )

        executor_implementation = issue_executor_implementation(
            preparation,
            context,
            validation_run,
            allocate_executor_capability,
            confirm_executor_capability,
        )
        if failure_point == "after_executor_issuance_before_ledger":
            raise error_type(
                "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                "Injected failure occurred after central executor registration.",
                layer="issued_plan_binding",
            )

        def begin_junit_acquisition() -> None:
            begin_physical_resource(preparation, session_token, validation_run, "junit")

        def cancel_junit_acquisition() -> None:
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "junit",
                None,
                previous_resource=None,
                state="none",
            )

        def checkpoint_junit_acquisition() -> None:
            if failure_point == "junit_acquisition_failure":
                raise OSError("Injected clean JUnit acquisition failure.")

        def checkpoint_provisional_junit_retention() -> None:
            if failure_point == "after_junit_acquisition_before_identity":
                raise error_type(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Injected failure occurred after central provisional-JUnit registration.",
                    layer="issued_plan_binding",
                )

        def retain_provisional_junit_handle(handle: object) -> None:
            nonlocal provisional_junit_handle
            if provisional_junit_handle is not None:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "A production session can retain one provisional JUnit owner.",
                    layer="plan_identities",
                )
            provisional_junit_handle = handle
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "junit",
                handle,
                previous_resource=None,
                state="centrally_registered",
            )

        def retain_junit_handle(provisional: object, handle: object) -> None:
            nonlocal junit_handle
            if provisional is not provisional_junit_handle or junit_handle is not None:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "A production session can promote one exact retained JUnit handle.",
                    layer="plan_identities",
                )
            transition_physical_resource(
                preparation,
                session_token,
                validation_run,
                "junit",
                handle,
                previous_resource=provisional,
                state="retained",
            )
            junit_handle = handle
            if failure_point == "after_junit_ownership_before_ledger":
                raise error_type(
                    "PARTIAL_AUTHORITY_BINDING_FORBIDDEN",
                    "Injected failure occurred after central retained-JUnit registration.",
                    layer="issued_plan_binding",
                )

        pytest_draft, returned_junit_handle = issue_pytest_plan(
            preparation=preparation,
            context=context,
            validation_run=validation_run,
            control_directory=control_directory,
            control_directory_identity=(
                owned_control_directory.device_id,
                owned_control_directory.file_id,
            ),
            retain_provisional_handle=retain_provisional_junit_handle,
            retain_handle=retain_junit_handle,
            begin_acquisition=begin_junit_acquisition,
            cancel_acquisition=cancel_junit_acquisition,
            acquisition_checkpoint=checkpoint_junit_acquisition,
            retained_checkpoint=checkpoint_provisional_junit_retention,
        )
        if (
            returned_junit_handle is not junit_handle
            or getattr(returned_junit_handle, "control_directory", None) != control_directory
            or getattr(returned_junit_handle, "control_directory_identity", None)
            != (owned_control_directory.device_id, owned_control_directory.file_id)
        ):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest issuance returned a different retained JUnit handle.",
                layer="plan_identities",
            )
        record_resources(
            preparation,
            session_token,
            validation_run,
            control_directory=owned_control_directory,
            junit_handle=junit_handle,
            executor_implementation=executor_implementation,
            executor_invalidator=invalidate_executor,
            executor_is_current=executor_is_current,
            junit_cleanup=cleanup_junit,
            junit_is_open=junit_is_open,
            junit_is_cleaned=junit_is_cleaned,
            remove_control_directory=remove_control_directory,
        )
        oracle_draft = issue_oracle_plan(
            preparation=preparation,
            context=context,
            validation_run=validation_run,
        )
        execution_drafts = issue_execution_plans(
            preparation=preparation,
            context=context,
            validation_run=validation_run,
            executor_implementation=executor_implementation,
        )
        if junit_handle is None or not junit_is_open(junit_handle):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production JUnit ownership changed before authority preparation.",
                layer="plan_identities",
            )
        plan_set = six_plan_set((pytest_draft, oracle_draft, *execution_drafts))
        validate_components()
        validate_collaborators()

        def prepare_complete_record(
            reserved: _ProductionRunRecord,
        ) -> _ProductionRunRecord:
            validate_collaborators()
            if not junit_is_open(junit_handle):
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Production JUnit ownership changed before atomic publication.",
                    layer="plan_identities",
                )

            def allocate_session_authority(
                capability_type: type[object],
                validation_authority_id: str,
            ) -> object:
                return allocate_authority(
                    preparation,
                    validation_run,
                    capability_type=capability_type,
                    validation_authority_id=validation_authority_id,
                )

            def retain_unpublished_binding(binding: _BindingRecord) -> None:
                record_unpublished_binding(preparation, validation_run, binding)

            binding = prepare_binding(
                context=context,
                validation_run_id=run_id(validation_run),
                plans=plan_set,
                trust_domain="production",
                failure_point=failure_point,
                allocate_authority=allocate_session_authority,
                record_unpublished_binding=retain_unpublished_binding,
            )
            if binding.capability.__class__ is not authority_type:
                raise AssertionError("Production preparation crossed authority trust domains.")
            resources = resources_type(
                token=session_token,
                control_directory=owned_control_directory,
                control_directory_state="transferred_for_later_execution",
                junit_handle=junit_handle,
                junit_ownership_state="transferred_for_later_execution",
                executor_implementation=executor_implementation,
                plan_capabilities=tuple(draft.capability for draft in plan_set.ordered()),
                published_authority=binding.capability,
                executor_invalidator=invalidate_executor,
                executor_is_current=executor_is_current,
                junit_cleanup=cleanup_junit,
                junit_is_open=junit_is_open,
                junit_is_cleaned=junit_is_cleaned,
                remove_control_directory=remove_control_directory,
            )
            complete = replace_record(
                reserved,
                state="authority_bound",
                plans=plan_set,
                binding=binding,
                resources=resources,
            )
            validate_components()
            validate_collaborators()
            return complete

        validate_collaborators()

        def validate_final_provenance() -> None:
            current_context = derive_context(
                trusted_entrypoint=trusted_entrypoint,
                trusted_public_entrypoint=trusted_public_entrypoint,
                trusted_callable_projector=trusted_callable_projector,
            )
            if current_context != context:
                raise error_type(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Production Layer-0 provenance changed before atomic publication.",
                    layer="validation_authority",
                )

        publish_binding(
            preparation,
            validation_run,
            prepare_complete_record,
            validate_final_provenance,
            failure_point=failure_point,
        )
        return
    except BaseException as preparation_error:
        cleanup_errors: list[BaseException] = []
        # The first call atomically merges the exact local acquisition snapshot
        # before cleanup can be certified.  Every retry remains under that same
        # central owner; no local-only path may certify or release resources.
        for _ in range(3):
            try:
                abort(
                    preparation,
                    session_token,
                    local_control_directory=(
                        owned_control_directory
                        if owned_control_directory is not None
                        else provisional_control_directory
                    ),
                    local_junit_handle=(
                        junit_handle if junit_handle is not None else provisional_junit_handle
                    ),
                    local_executor_implementation=executor_implementation,
                    executor_invalidator=invalidate_executor,
                    executor_is_current=executor_is_current,
                    junit_cleanup=cleanup_junit,
                    junit_is_open=junit_is_open,
                    junit_is_cleaned=junit_is_cleaned,
                    remove_control_directory=remove_control_directory,
                )
            except BaseException as error:
                cleanup_errors.append(error)
            else:
                break
        normalized_error = (
            preparation_error
            if isinstance(preparation_error, error_type)
            else error_type(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Production Stage-1 preparation failed before execution.",
                layer="live_executor_implementation_issuance",
            )
        )
        for cleanup_error in cleanup_errors:
            normalized_error.add_note(
                f"Stage-1 cleanup also failed: {type(cleanup_error).__name__}: {cleanup_error}"
            )
        if normalized_error is preparation_error:
            raise
        raise normalized_error from preparation_error


def _install_owned_control_directory_operations() -> tuple[
    Callable[..., _OwnedControlDirectory],
    Callable[[object], None],
    Callable[[int], object],
]:
    """Seal one temp root and exact-issued ownership for Stage-1 control directories."""

    directory_type = _OwnedControlDirectory
    provisional_type = _ProvisionalControlDirectory
    error_type = P2Stage1Error
    path_type = Path
    temp_root = path_type(tempfile.gettempdir()).resolve(strict=True)
    repository = path_type(__file__).resolve(strict=True).parents[2]
    if temp_root == repository or repository in temp_root.parents:
        raise RuntimeError("The Stage-1 control root cannot be inside the trusted repository.")
    os_fspath = os.fspath
    os_mkdir = os.mkdir
    os_rmdir = os.rmdir
    os_scandir = os.scandir
    os_stat = os.stat
    is_directory = stat.S_ISDIR
    file_not_found_type = FileNotFoundError
    os_error_type = OSError
    lock = _TRUSTED_RLOCK_TYPE()
    require_preparation = _require_production_preparation
    records: dict[
        _OwnedControlDirectory,
        tuple[tuple[Path, int, int], Literal["owned", "rmdir_in_progress", "removed"]],
    ] = {}

    class ProvisionalState:
        __slots__ = (
            "creation_state",
            "identity",
            "owned",
            "ownership_state",
            "path",
            "removal_state",
        )

        def __init__(self, path: Path) -> None:
            self.path = path
            self.creation_state: Literal[
                "planned",
                "mkdir_in_progress",
                "created",
                "creation_failed",
            ] = "planned"
            self.identity: tuple[int, int] | None = None
            self.owned: _OwnedControlDirectory | None = None
            self.ownership_state: _PhysicalOwnershipState = "acquired"
            self.removal_state: Literal["present", "rmdir_in_progress", "removed"] = "present"

    provisional_records: dict[_ProvisionalControlDirectory, ProvisionalState] = {}
    post_rmdir_failure_remaining: ContextVar[int] = ContextVar(
        "rde_owned_control_directory_post_rmdir_failure_remaining",
        default=0,
    )

    def fail(message: str) -> NoReturn:
        raise error_type(
            "PYTEST_PLAN_ID_MISMATCH",
            message,
            layer="plan_identities",
        )

    def fingerprint(
        control_directory: _OwnedControlDirectory,
    ) -> tuple[Path, int, int]:
        return (
            control_directory.path,
            control_directory.device_id,
            control_directory.file_id,
        )

    def validate_status(
        path: Path,
        status: os.stat_result,
        *,
        expected_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        identity = (status.st_dev, status.st_ino)
        if (
            path.resolve(strict=True) != path
            or path.parent != temp_root
            or not path.name.startswith("rde-p2-stage1-")
            or path.is_symlink()
            or bool(getattr(path, "is_junction", lambda: False)())
            or not is_directory(status.st_mode)
            or status.st_dev < 0
            or status.st_ino <= 0
            or (expected_identity is not None and identity != expected_identity)
        ):
            fail("Stage-1 control directory is not the exact owned temporary directory.")
        return identity

    def remove_provisional(state: ProvisionalState) -> None:
        last_error: BaseException | None = None
        path = state.path

        def certify_absence() -> None:
            remaining_failures = post_rmdir_failure_remaining.get()
            if remaining_failures:
                post_rmdir_failure_remaining.set(remaining_failures - 1)
                raise os_error_type("Injected post-rmdir verification failure.")
            state.removal_state = "removed"

        with lock:
            if state.removal_state == "removed":
                return
            for _ in range(3):
                try:
                    status = os_stat(os_fspath(path), follow_symlinks=False)
                except file_not_found_type as error:
                    if state.removal_state == "rmdir_in_progress":
                        try:
                            certify_absence()
                        except os_error_type as verification_error:
                            last_error = verification_error
                            continue
                        return
                    if state.creation_state in {"planned", "mkdir_in_progress"}:
                        state.removal_state = "removed"
                        return
                    if state.creation_state == "creation_failed":
                        state.removal_state = "removed"
                        return
                    if state.creation_state == "created":
                        last_error = error
                        break
                except BaseException as error:
                    last_error = error
                    continue
                if state.creation_state in {"planned", "creation_failed"}:
                    last_error = error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Refusing to remove a control-directory path not created by this session.",
                        layer="plan_identities",
                    )
                    break
                try:
                    state.identity = validate_status(
                        path,
                        status,
                        expected_identity=state.identity,
                    )
                    with os_scandir(os_fspath(path)) as entries:
                        if next(entries, None) is not None:
                            fail("Refusing to roll back a non-empty Stage-1 control directory.")
                    # Persist intent before the destructive syscall so a retry
                    # can distinguish a committed removal from disappearance.
                    state.removal_state = "rmdir_in_progress"
                    os_rmdir(os_fspath(path))
                except file_not_found_type as error:
                    last_error = error
                    continue
                except BaseException as error:
                    last_error = error
                    continue
                try:
                    os_stat(os_fspath(path), follow_symlinks=False)
                except file_not_found_type:
                    try:
                        certify_absence()
                    except os_error_type as verification_error:
                        last_error = verification_error
                        continue
                    return
                except os_error_type as error:
                    last_error = error
                else:
                    last_error = error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Stage-1 control-directory rollback left the directory present.",
                        layer="plan_identities",
                    )
            if last_error is None:
                fail("Could not identify the provisional Stage-1 control directory.")
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Could not roll back the exact provisional Stage-1 control directory.",
                layer="plan_identities",
            ) from last_error

    def create(
        preparation: _ProductionPreparationCapability,
        *,
        directory_name_token: str | None = None,
        begin_acquisition: Callable[[], None] | None = None,
        acquisition_checkpoint: Callable[[], None] | None = None,
        cancel_acquisition: Callable[[], None] | None = None,
        retain_provisional: Callable[[_ProvisionalControlDirectory], None] | None = None,
        retain_owned: (
            Callable[[_ProvisionalControlDirectory, _OwnedControlDirectory], None] | None
        ) = None,
        retained_checkpoint: Callable[[], None] | None = None,
    ) -> _OwnedControlDirectory:
        require_preparation(preparation)
        if (
            type(directory_name_token) is not str
            or len(directory_name_token) != 64
            or any(character not in "0123456789abcdef" for character in directory_name_token)
        ):
            fail("Stage-1 control-directory name token is malformed.")
        path = temp_root / f"rde-p2-stage1-{directory_name_token}"
        provisional: _ProvisionalControlDirectory | None = None
        provisional_identity: tuple[int, int] | None = None
        owned: _OwnedControlDirectory | None = None
        central_ownership_attempted = False
        acquisition_attempted = False
        if (
            begin_acquisition is None
            or acquisition_checkpoint is None
            or cancel_acquisition is None
            or retain_provisional is None
            or retain_owned is None
            or retained_checkpoint is None
        ):
            fail("Stage-1 control-directory creation requires exact central ownership sinks.")
        try:
            provisional = provisional_type(path=path)
            provisional_state = ProvisionalState(path)
            with lock:
                provisional_records[provisional] = provisional_state
            acquisition_attempted = True
            begin_acquisition()
            acquisition_checkpoint()
            retain_provisional(provisional)
            central_ownership_attempted = True
            with lock:
                if (
                    provisional_records.get(provisional) is not provisional_state
                    or provisional_state.ownership_state != "acquired"
                    or provisional_state.creation_state != "planned"
                    or provisional_state.removal_state != "present"
                ):
                    fail("Control-directory ownership changed during central registration.")
                provisional_state.ownership_state = "centrally_registered"
                try:
                    os_stat(os_fspath(path), follow_symlinks=False)
                except file_not_found_type:
                    pass
                except os_error_type as status_error:
                    provisional_state.creation_state = "creation_failed"
                    raise status_error
                else:
                    provisional_state.creation_state = "creation_failed"
                    fail("Stage-1 control-directory destination already exists.")
                provisional_state.creation_state = "mkdir_in_progress"
                try:
                    os_mkdir(os_fspath(path), 0o700)
                except os_error_type:
                    provisional_state.creation_state = "creation_failed"
                    raise
            retained_checkpoint()
            with lock:
                if (
                    provisional_records.get(provisional) is not provisional_state
                    or provisional_state.ownership_state != "centrally_registered"
                    or provisional_state.creation_state != "mkdir_in_progress"
                    or provisional_state.removal_state != "present"
                ):
                    fail("Control-directory ownership changed before identity promotion.")
                provisional_state.creation_state = "created"
                status = os_stat(os_fspath(path), follow_symlinks=False)
                provisional_identity = validate_status(path, status)
                provisional_state.identity = provisional_identity
                owned = directory_type(
                    path=path,
                    device_id=provisional_identity[0],
                    file_id=provisional_identity[1],
                )
                row: tuple[
                    tuple[Path, int, int],
                    Literal["owned", "rmdir_in_progress", "removed"],
                ] = (fingerprint(owned), "owned")
                provisional_state.owned = owned
                records[owned] = row
                provisional_state.ownership_state = "retained"
            retain_owned(provisional, owned)
            with lock:
                if (
                    provisional_records.get(provisional) is not provisional_state
                    or provisional_state.owned is not owned
                    or provisional_state.ownership_state != "retained"
                    or provisional_state.removal_state != "present"
                    or records.get(owned) != row
                ):
                    fail("Control-directory ownership changed during central promotion.")
                provisional_state.ownership_state = "transferred_for_later_execution"
            return owned
        except BaseException as error:
            rollback_complete = path is None
            if provisional is not None:
                try:
                    remove(provisional)
                except BaseException as cleanup_error:
                    error.add_note(
                        "Stage-1 provisional-directory rollback also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                else:
                    rollback_complete = True
            elif path is not None:
                try:
                    unregistered_state = ProvisionalState(path)
                    unregistered_state.identity = provisional_identity
                    remove_provisional(unregistered_state)
                except BaseException as cleanup_error:
                    error.add_note(
                        "Stage-1 unregistered-directory rollback also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                else:
                    rollback_complete = True
            if acquisition_attempted and not central_ownership_attempted and rollback_complete:
                try:
                    cancel_acquisition()
                except BaseException as cancellation_error:
                    error.add_note(
                        "Stage-1 zero-directory acquisition transition also failed: "
                        f"{type(cancellation_error).__name__}: {cancellation_error}"
                    )
            raise

    def remove_owned(control_directory: _OwnedControlDirectory) -> None:
        if type(control_directory) is not directory_type:
            fail("Exact Stage-1 control-directory ownership record required.")
        with lock:
            row = records.get(control_directory)
            if row is None or row[0] != fingerprint(control_directory):
                fail("Unissued or changed Stage-1 control-directory record rejected.")
            if row[1] == "removed":
                return
            path = control_directory.path
            expected_identity = (control_directory.device_id, control_directory.file_id)

            def certify_absence() -> None:
                remaining_failures = post_rmdir_failure_remaining.get()
                if remaining_failures:
                    post_rmdir_failure_remaining.set(remaining_failures - 1)
                    raise os_error_type("Injected post-rmdir verification failure.")
                records[control_directory] = (fingerprint(control_directory), "removed")

            try:
                status = os_stat(os_fspath(path), follow_symlinks=False)
            except file_not_found_type as error:
                if row[1] != "rmdir_in_progress":
                    raise error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Owned Stage-1 control directory disappeared before cleanup.",
                        layer="plan_identities",
                    ) from error
                try:
                    certify_absence()
                except os_error_type as verification_error:
                    raise error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Could not verify the removed Stage-1 control directory.",
                        layer="plan_identities",
                    ) from verification_error
                return
            except os_error_type as error:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Could not verify the exact Stage-1 control directory for cleanup.",
                    layer="plan_identities",
                ) from error
            validate_status(path, status, expected_identity=expected_identity)
            with os_scandir(os_fspath(path)) as entries:
                if next(entries, None) is not None:
                    fail("Refusing to remove a Stage-1 directory containing other resources.")
            # Record the destructive intent before rmdir.  A later retry may
            # accept absence only from this exact identity-bound state.
            row = (row[0], "rmdir_in_progress")
            records[control_directory] = row
            try:
                os_rmdir(os_fspath(path))
            except file_not_found_type:
                pass
            except os_error_type as error:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Could not remove the exact empty Stage-1 control directory.",
                    layer="plan_identities",
                ) from error
            try:
                os_stat(os_fspath(path), follow_symlinks=False)
            except file_not_found_type:
                try:
                    certify_absence()
                except os_error_type as verification_error:
                    raise error_type(
                        "PYTEST_PLAN_ID_MISMATCH",
                        "Could not verify the removed Stage-1 control directory.",
                        layer="plan_identities",
                    ) from verification_error
                return
            except os_error_type as error:
                raise error_type(
                    "PYTEST_PLAN_ID_MISMATCH",
                    "Could not verify the removed Stage-1 control directory.",
                    layer="plan_identities",
                ) from error
            fail("Stage-1 control directory remained after exact cleanup.")

    def remove(control_directory: object) -> None:
        if type(control_directory) is directory_type:
            remove_owned(control_directory)
            return
        if type(control_directory) is not provisional_type:
            fail("Exact Stage-1 control-directory ownership record required.")
        provisional = control_directory
        with lock:
            state = provisional_records.get(provisional)
            if state is None or state.path != provisional.path:
                fail("Unissued or changed provisional control-directory record rejected.")
            if state.ownership_state == "cleanup_complete":
                return
            state.ownership_state = "cleanup_pending"
            promoted = state.owned
        if promoted is not None:
            with lock:
                promoted_is_registered = records.get(promoted) is not None
            if promoted_is_registered:
                remove_owned(promoted)
            else:
                remove_provisional(state)
        else:
            remove_provisional(state)
        with lock:
            state.ownership_state = "released"
            state.ownership_state = "cleanup_complete"

    @contextmanager
    def post_rmdir_failure_scope(attempts: int) -> Iterator[None]:
        if isinstance(attempts, bool) or type(attempts) is not int or not 1 <= attempts <= 6:
            fail("Post-rmdir verification injection requires one through six failures.")
        if post_rmdir_failure_remaining.get() != 0:
            fail("Post-rmdir verification injection cannot be nested.")
        token = post_rmdir_failure_remaining.set(attempts)
        try:
            yield
        finally:
            post_rmdir_failure_remaining.reset(token)

    return (
        _runtime_cast(_opaque_runtime_callable(create)),
        _runtime_cast(_opaque_runtime_callable(remove)),
        _runtime_cast(_opaque_runtime_callable(post_rmdir_failure_scope)),
    )


(
    _create_owned_control_directory,
    _remove_empty_owned_control_directory,
    _owned_control_directory_post_rmdir_failure_scope,
) = _install_owned_control_directory_operations()
del _install_owned_control_directory_operations


def _git_identity_error(message: str) -> NoReturn:
    _error(
        "IMPLEMENTATION_IDENTITY_MISMATCH",
        message,
        layer="validation_authority",
    )


def _git_sha1(raw: bytes) -> str:
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()  # noqa: S324


def _git_object_id(kind: str, payload: bytes) -> str:
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return _git_sha1(header + payload)


def _resolve_git_directory(root: Path) -> Path:
    marker = root / ".git"
    marker_is_link_like = marker.is_symlink() or marker.is_junction()
    if marker_is_link_like:
        _git_identity_error("The trusted Git metadata marker is link-like.")
    if marker.is_dir():
        return marker.resolve(strict=True)
    if not marker.is_file():
        _git_identity_error("The trusted repository has no exact Git metadata directory.")
    try:
        marker_text = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git directory marker is unreadable.",
            layer="validation_authority",
        ) from error
    prefix = "gitdir: "
    if not marker_text.startswith(prefix):
        _git_identity_error("The trusted Git directory marker is malformed.")
    candidate = Path(marker_text[len(prefix) :])
    if not candidate.is_absolute():
        candidate = marker.parent / candidate
    if any(part == ".." for part in candidate.parts):
        _git_identity_error("The trusted Git directory marker contains parent traversal.")
    anchor = Path(candidate.anchor)
    if not candidate.is_absolute() or not anchor.is_absolute():
        _git_identity_error("The trusted Git directory marker has no exact absolute anchor.")
    component = anchor
    component_identities: list[tuple[Path, int, int]] = []
    for part in candidate.parts[1:]:
        if part in {"", "."}:
            continue
        component = component / part
        try:
            status = component.stat(follow_symlinks=False)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "A trusted Git metadata path component is unavailable.",
                layer="validation_authority",
            ) from error
        if component.is_symlink() or component.is_junction():
            _git_identity_error(
                "The trusted Git directory marker resolves through a link-like path."
            )
        component_identities.append((component, status.st_dev, status.st_ino))
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        _git_identity_error("The resolved trusted Git metadata path is not a directory.")
    for component, expected_device, expected_file in component_identities:
        try:
            status = component.stat(follow_symlinks=False)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "A trusted Git metadata path component changed during resolution.",
                layer="validation_authority",
            ) from error
        if (
            component.is_symlink()
            or component.is_junction()
            or status.st_dev != expected_device
            or status.st_ino != expected_file
        ):
            _git_identity_error("A trusted Git metadata path component changed during resolution.")
    return resolved


def _resolve_git_common_directory(git_directory: Path) -> Path:
    """Resolve the trusted common metadata directory for a normal repo or worktree."""

    marker = git_directory / "commondir"
    try:
        marker_status = marker.stat(follow_symlinks=False)
    except FileNotFoundError:
        return git_directory
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git common-directory marker is unreadable.",
            layer="validation_authority",
        ) from error
    if marker.is_symlink() or marker.is_junction() or not stat.S_ISREG(marker_status.st_mode):
        _git_identity_error("The trusted Git common-directory marker is link-like or irregular.")
    try:
        marker_text = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git common-directory marker cannot be decoded.",
            layer="validation_authority",
        ) from error
    if not marker_text or "\0" in marker_text or "\n" in marker_text or "\r" in marker_text:
        _git_identity_error("The trusted Git common-directory marker is malformed.")
    candidate = Path(marker_text)
    if not candidate.is_absolute():
        candidate = git_directory / candidate
    try:
        common = candidate.resolve(strict=True)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git common directory cannot be resolved.",
            layer="validation_authority",
        ) from error
    if common.is_symlink() or common.is_junction() or not common.is_dir():
        _git_identity_error("The trusted Git common directory is link-like or irregular.")
    return common


def _trusted_bootstrap_manifest_path(git_directory: Path, commit: str) -> Path:
    if re.fullmatch(_GIT40_PATTERN, commit) is None:
        _git_identity_error("The trusted bootstrap commit key is not GIT40.")
    common = _resolve_git_common_directory(git_directory)
    return common / "rde" / "trusted-local-process-v1.json"


def _trusted_bootstrap_manifest_bytes(
    *,
    snapshot: _GitSnapshot,
    dependency_lock_sha256: str,
    runtime: RuntimeProjection,
    runtime_identity: str,
    dependency_environment: _DependencyEnvironmentIdentity,
) -> bytes:
    if (
        type(snapshot) is not _GitSnapshot
        or re.fullmatch(_GIT40_PATTERN, snapshot.commit) is None
        or re.fullmatch(_GIT40_PATTERN, snapshot.root_tree) is None
        or re.fullmatch(_H64_PATTERN, dependency_lock_sha256) is None
        or type(runtime) is not RuntimeProjection
        or re.fullmatch(_H64_PATTERN, runtime_identity) is None
        or type(dependency_environment) is not tuple
        or tuple(row[0] for row in dependency_environment if type(row) is tuple and len(row) == 4)
        != ("pluggy", "pytest")
        or len(dependency_environment) != 2
        or any(
            type(row) is not tuple
            or len(row) != 4
            or any(type(value) is not str or not value for value in row)
            or re.fullmatch(_H64_PATTERN, row[3]) is None
            for row in dependency_environment
        )
    ):
        _git_identity_error("The trusted bootstrap facts are incomplete or malformed.")
    manifest = {
        "base_interpreter": runtime.base_interpreter.as_dict(),
        "dependency_environment": [
            {
                "distribution": distribution,
                "installation_identity": installation_identity,
                "installation_root": installation_root,
                "version": version,
            }
            for (
                distribution,
                version,
                installation_root,
                installation_identity,
            ) in dependency_environment
        ],
        "dependency_lock_sha256": dependency_lock_sha256,
        "implementation_commit": snapshot.commit,
        "implementation_root_tree": snapshot.root_tree,
        "interpreter": runtime.interpreter.as_dict(),
        "runtime_identity": runtime_identity,
        "schema_version": "rde-trusted-local-process-bootstrap/v1",
    }
    return (
        json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _validate_trusted_bootstrap_manifest(
    *,
    git_directory: Path,
    snapshot: _GitSnapshot,
    dependency_lock_sha256: str,
    runtime: RuntimeProjection,
    runtime_identity: str,
    dependency_environment: _DependencyEnvironmentIdentity,
) -> None:
    """Reconcile current facts with the externally provisioned bootstrap anchor."""

    manifest_path = _trusted_bootstrap_manifest_path(git_directory, snapshot.commit)
    for directory in (manifest_path.parent.parent, manifest_path.parent):
        try:
            status = directory.stat(follow_symlinks=False)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "The exact trusted bootstrap manifest has not been provisioned.",
                layer="validation_authority",
            ) from error
        if directory.is_symlink() or directory.is_junction() or not stat.S_ISDIR(status.st_mode):
            _git_identity_error("A trusted bootstrap manifest directory is link-like or irregular.")
    try:
        before = manifest_path.stat(follow_symlinks=False)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The exact trusted bootstrap manifest has not been provisioned.",
            layer="validation_authority",
        ) from error
    if (
        manifest_path.is_symlink()
        or manifest_path.is_junction()
        or not stat.S_ISREG(before.st_mode)
        or not 0 < before.st_size <= 16_384
        or before.st_nlink != 1
    ):
        _git_identity_error("The trusted bootstrap manifest is link-like or irregular.")
    try:
        raw = manifest_path.read_bytes()
        after = manifest_path.stat(follow_symlinks=False)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted bootstrap manifest changed during reconciliation.",
            layer="validation_authority",
        ) from error
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ) or raw != _trusted_bootstrap_manifest_bytes(
        snapshot=snapshot,
        dependency_lock_sha256=dependency_lock_sha256,
        runtime=runtime,
        runtime_identity=runtime_identity,
        dependency_environment=dependency_environment,
    ):
        _git_identity_error("Current production facts differ from the trusted bootstrap manifest.")


def _valid_git_ref_name(ref_name: str) -> bool:
    forbidden = frozenset(" ~^:?*[\\")
    parts = ref_name.split("/")
    return (
        len(parts) >= 3
        and parts[0] == "refs"
        and all(
            part
            and part not in {".", ".."}
            and not part.endswith(".")
            and not part.endswith(".lock")
            and ".." not in part
            and "@{" not in part
            and not any(character in forbidden or ord(character) < 32 for character in part)
            for part in parts
        )
    )


def _read_git_head(git_directory: Path, common_directory: Path | None = None) -> str:
    reference_directory = git_directory if common_directory is None else common_directory
    try:
        head_text = (git_directory / "HEAD").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git HEAD is unreadable.",
            layer="validation_authority",
        ) from error
    if re.fullmatch(_GIT40_PATTERN, head_text) is not None:
        return head_text
    prefix = "ref: "
    if not head_text.startswith(prefix):
        _git_identity_error("The trusted Git HEAD is malformed.")
    ref_name = head_text[len(prefix) :]
    if not _valid_git_ref_name(ref_name):
        _git_identity_error("The trusted Git HEAD reference is malformed.")
    loose_ref = reference_directory.joinpath(*ref_name.split("/"))
    try:
        commit = loose_ref.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        commit = ""
        packed_refs = reference_directory / "packed-refs"
        try:
            packed_lines = packed_refs.read_text(encoding="ascii").splitlines()
        except FileNotFoundError:
            packed_lines = []
        except (OSError, UnicodeDecodeError) as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "The trusted packed Git references are unreadable.",
                layer="validation_authority",
            ) from error
        matches = [
            line.split(" ", 1)[0]
            for line in packed_lines
            if not line.startswith(("#", "^")) and " " in line and line.split(" ", 1)[1] == ref_name
        ]
        if len(matches) == 1:
            commit = matches[0]
    except (OSError, UnicodeDecodeError) as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git HEAD reference is unreadable.",
            layer="validation_authority",
        ) from error
    if re.fullmatch(_GIT40_PATTERN, commit) is None:
        _git_identity_error("The trusted Git HEAD does not resolve to GIT40.")
    return commit


def _read_loose_git_object(git_directory: Path, object_id: str, kind: str) -> bytes:
    if re.fullmatch(_GIT40_PATTERN, object_id) is None:
        _git_identity_error("A trusted Git object identity is not GIT40.")
    object_path = git_directory / "objects" / object_id[:2] / object_id[2:]
    try:
        compressed = object_path.read_bytes()
    except FileNotFoundError:
        _git_identity_error(
            "A required trusted Git object is not loose; subprocess fallback is forbidden."
        )
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "A required trusted Git object is unreadable.",
            layer="validation_authority",
        ) from error
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "A required trusted Git object is corrupt.",
            layer="validation_authority",
        ) from error
    if _git_sha1(raw) != object_id:
        _git_identity_error("A required trusted Git object hash does not reconcile.")
    header, separator, payload = raw.partition(b"\0")
    if not separator:
        _git_identity_error("A required trusted Git object has no header boundary.")
    try:
        object_kind, raw_size = header.decode("ascii").split(" ", 1)
        declared_size = int(raw_size)
    except (UnicodeDecodeError, ValueError) as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "A required trusted Git object header is malformed.",
            layer="validation_authority",
        ) from error
    if object_kind != kind or declared_size != len(payload):
        _git_identity_error("A required trusted Git object type or size differs.")
    return payload


def _commit_root_tree(payload: bytes) -> str:
    header, separator, _message = payload.partition(b"\n\n")
    if not separator:
        _git_identity_error("The trusted Git commit has no header boundary.")
    lines = header.split(b"\n")
    if not lines or not lines[0].startswith(b"tree "):
        _git_identity_error("The trusted Git commit does not begin with one root tree header.")
    tree_headers = [line for line in lines if line.startswith(b"tree ")]
    if len(tree_headers) != 1 or len(lines[0]) != 45 or tree_headers[0] != lines[0]:
        _git_identity_error("The trusted Git commit has no exact unique root tree header.")
    try:
        root_tree = lines[0][5:].decode("ascii")
    except UnicodeDecodeError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git commit tree identity is not ASCII.",
            layer="validation_authority",
        ) from error
    if re.fullmatch(_GIT40_PATTERN, root_tree) is None:
        _git_identity_error("The trusted Git commit root tree is not GIT40.")
    return root_tree


def _parse_git_index(git_directory: Path) -> tuple[bytes, tuple[_GitIndexEntry, ...]]:
    try:
        raw = (git_directory / "index").read_bytes()
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted Git index is unreadable.",
            layer="validation_authority",
        ) from error
    if len(raw) < 32 or raw[:4] != b"DIRC" or int.from_bytes(raw[4:8], "big") != 2:
        _git_identity_error("Only one exact Git index v2 is supported.")
    payload_end = len(raw) - 20
    if bytes.fromhex(_git_sha1(raw[:payload_end])) != raw[payload_end:]:
        _git_identity_error("The trusted Git index checksum does not reconcile.")
    entry_count = int.from_bytes(raw[8:12], "big")
    offset = 12
    entries: list[_GitIndexEntry] = []
    seen_paths: set[str] = set()
    for _ in range(entry_count):
        entry_start = offset
        fixed_end = offset + 62
        if fixed_end > payload_end:
            _git_identity_error("The trusted Git index entry table is truncated.")
        mode_value = int.from_bytes(raw[offset + 24 : offset + 28], "big")
        flags = int.from_bytes(raw[offset + 60 : fixed_end], "big")
        if flags & 0x4000 or flags & 0x3000:
            _git_identity_error("Extended, sparse, or unmerged Git index entries are forbidden.")
        path_end = raw.find(b"\0", fixed_end, payload_end)
        if path_end < 0:
            _git_identity_error("A trusted Git index path has no terminator.")
        path_raw = raw[fixed_end:path_end]
        expected_name_length = flags & 0x0FFF
        if expected_name_length != min(len(path_raw), 0x0FFF):
            _git_identity_error("A trusted Git index path length does not reconcile.")
        try:
            path = path_raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "A trusted Git index path is not UTF-8.",
                layer="validation_authority",
            ) from error
        path_parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path_parts)
            or unicodedata.normalize("NFC", path) != path
            or path in seen_paths
        ):
            _git_identity_error("A trusted Git index path is unsafe or duplicated.")
        seen_paths.add(path)
        file_type = mode_value & 0o170000
        if file_type == 0o100000:
            mode = "100755" if mode_value & 0o111 else "100644"
        elif file_type == 0o120000:
            mode = "120000"
        else:
            _git_identity_error("A trusted Git index entry has an unsupported mode.")
        object_id = raw[offset + 40 : offset + 60].hex()
        if re.fullmatch(_GIT40_PATTERN, object_id) is None:
            _git_identity_error("A trusted Git index object identity is malformed.")
        entries.append(_GitIndexEntry(path=path, mode=mode, object_id=object_id))
        offset = path_end + 1
        while (offset - entry_start) % 8:
            if offset >= payload_end or raw[offset] != 0:
                _git_identity_error("A trusted Git index entry has malformed padding.")
            offset += 1
    while offset < payload_end:
        if offset + 8 > payload_end:
            _git_identity_error("A trusted Git index extension is truncated.")
        extension_size = int.from_bytes(raw[offset + 4 : offset + 8], "big")
        offset += 8 + extension_size
        if offset > payload_end:
            _git_identity_error("A trusted Git index extension exceeds its boundary.")
    if offset != payload_end:
        _git_identity_error("The trusted Git index has trailing malformed bytes.")
    return raw, tuple(entries)


def _git_tree_from_index(entries: Sequence[_GitIndexEntry]) -> str:
    root: dict[bytes, object] = {}
    for entry in entries:
        node = root
        parts = tuple(part.encode("utf-8") for part in entry.path.split("/"))
        for part in parts[:-1]:
            current = node.get(part)
            if current is None:
                current = {}
                node[part] = current
            if type(current) is not dict:
                _git_identity_error("The trusted Git index has a file/directory conflict.")
            node = _runtime_cast(current)
        if parts[-1] in node:
            _git_identity_error("The trusted Git index has a duplicate tree entry.")
        node[parts[-1]] = entry

    def tree_id(node: dict[bytes, object]) -> str:
        rows: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            if type(value) is dict:
                child_id = tree_id(_runtime_cast(value))
                mode = b"40000"
                sort_name = name + b"/"
                raw_id = bytes.fromhex(child_id)
            elif type(value) is _GitIndexEntry:
                file_entry = value
                mode = file_entry.mode.encode("ascii")
                sort_name = name
                raw_id = bytes.fromhex(file_entry.object_id)
            else:
                _git_identity_error("The trusted Git index tree is malformed.")
            rows.append((sort_name, mode + b" " + name + b"\0" + raw_id))
        payload = b"".join(row for _, row in sorted(rows, key=lambda item: item[0]))
        return _git_object_id("tree", payload)

    return tree_id(root)


def _implementation_path_is_scoped(path: str) -> bool:
    return path in {"pyproject.toml", "uv.lock"} or path.startswith(
        ("research_decision_engine/", "tests/")
    )


def _read_indexed_worktree_blob(root: Path, entry: _GitIndexEntry) -> bytes:
    path = root.joinpath(*entry.path.split("/"))
    try:
        status = path.stat(follow_symlinks=False)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            f"A trusted tracked path is missing or unreadable: {entry.path}.",
            layer="validation_authority",
        ) from error
    expected_parent = root.joinpath(*entry.path.split("/")[:-1])
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            f"A trusted tracked path parent is unreadable: {entry.path}.",
            layer="validation_authority",
        ) from error
    if resolved_parent != expected_parent:
        _git_identity_error("A trusted tracked path traverses a link-like parent.")
    if entry.mode == "120000":
        if not stat.S_ISLNK(status.st_mode):
            _git_identity_error("A trusted tracked symbolic link changed type.")
        raw = os.fsencode(os.readlink(path))
    else:
        if not stat.S_ISREG(status.st_mode) or path.is_symlink():
            _git_identity_error("A trusted tracked regular file changed type.")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"A trusted tracked file is unreadable: {entry.path}.",
                layer="validation_authority",
            ) from error
        if os.name != "nt" and (bool(status.st_mode & 0o111) != (entry.mode == "100755")):
            _git_identity_error("A trusted tracked executable mode changed.")
    if _git_object_id("blob", raw) != entry.object_id:
        _git_identity_error(f"A trusted tracked file differs from Git: {entry.path}.")
    return raw


def _untracked_implementation_paths(root: Path, tracked_paths: frozenset[str]) -> tuple[str, ...]:
    ignored_directories = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})
    ignored_root_directories = frozenset(
        {
            ".agents",
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "benchmark-validation-output",
            "broader-replication-smoke-v1",
            "broader-replication-smoke-v2",
            "closed-loop-evaluation-v1-100-seeds",
            "divergence-audit-v1-189-cases",
            "lookahead-benchmark-validation-output",
            "paired-evaluation-v1-100-seeds",
            "robust-belief-evaluation-v1-100-seeds",
            "robust-belief-evaluation-v1-100-seeds-accepted",
        }
    )
    untracked: list[str] = []
    try:
        with os.scandir(root) as root_children:
            root_entries = tuple(root_children)
    except OSError as error:
        raise P2Stage1Error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "The trusted repository root is unreadable.",
            layer="validation_authority",
        ) from error
    for child in root_entries:
        relative = Path(child.path).relative_to(root).as_posix()
        if relative in tracked_paths or child.name in {
            ".git",
            "research_decision_engine",
            "tests",
        }:
            continue
        if child.is_dir(follow_symlinks=False) and child.name in ignored_root_directories:
            continue
        untracked.append(relative + ("/" if child.is_dir(follow_symlinks=False) else ""))
    pending = [root / "research_decision_engine", root / "tests"]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as children:
                entries = tuple(children)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "The trusted implementation scope is unreadable.",
                layer="validation_authority",
            ) from error
        for child in entries:
            child_path = Path(child.path)
            relative = child_path.relative_to(root).as_posix()
            is_ignored_directory = child.name in ignored_directories
            is_link_like = child.is_symlink() or bool(
                hasattr(child_path, "is_junction") and child_path.is_junction()
            )
            if child.is_dir(follow_symlinks=False) and not is_link_like:
                if not is_ignored_directory:
                    pending.append(child_path)
                continue
            if relative in tracked_paths:
                continue
            untracked.append(relative)
    return tuple(sorted(untracked, key=str.encode))


def _current_git_snapshot(root: Path) -> _GitSnapshot:
    git_directory = _resolve_git_directory(root)
    common_directory = _resolve_git_common_directory(git_directory)
    commit = _read_git_head(git_directory, common_directory)
    commit_payload = _read_loose_git_object(common_directory, commit, "commit")
    root_tree = _commit_root_tree(commit_payload)
    index_raw, entries = _parse_git_index(git_directory)
    if _git_tree_from_index(entries) != root_tree:
        _git_identity_error("The trusted Git index differs from the HEAD tree.")
    tracked_paths = frozenset(entry.path for entry in entries)
    if not {"pyproject.toml", "uv.lock"}.issubset(tracked_paths):
        _git_identity_error("The trusted implementation root files are not tracked.")
    worktree_identities: list[tuple[str, str]] = []
    scoped_blobs: list[tuple[str, bytes]] = []
    for entry in entries:
        raw = _read_indexed_worktree_blob(root, entry)
        worktree_identities.append((entry.path, hashlib.sha256(raw).hexdigest()))
        if _implementation_path_is_scoped(entry.path):
            scoped_blobs.append((entry.path, raw))
    untracked = _untracked_implementation_paths(root, tracked_paths)
    if untracked:
        _git_identity_error(
            "Production Layer-0 issuance requires no untracked implementation files: "
            + ", ".join(untracked[:3])
            + ("." if len(untracked) <= 3 else ", ...")
        )
    return _GitSnapshot(
        commit=commit,
        root_tree=root_tree,
        index_sha256=hashlib.sha256(index_raw).hexdigest(),
        entries=entries,
        worktree_identities=tuple(worktree_identities),
        scoped_blobs=tuple(scoped_blobs),
    )


def _current_layer0_context(
    *,
    trusted_entrypoint: Callable[..., object],
    trusted_public_entrypoint: Callable[..., object],
    trusted_callable_projector: Callable[[Callable[..., object]], tuple[CallableProjection, str]],
) -> Layer0Context:
    """Reconstruct the exact clean production Layer-0 context from Git/runtime."""

    root = _strict_path(repository_root(), require_file=False)
    snapshot = _current_git_snapshot(root)
    commit = snapshot.commit
    current_rows: list[dict[str, object]] = []
    head_rows: list[dict[str, object]] = []
    trusted_blobs = dict(snapshot.scoped_blobs)
    for entry in snapshot.entries:
        if not _implementation_path_is_scoped(entry.path):
            continue
        raw = trusted_blobs[entry.path]
        current_rows.append(
            {
                "byte_count": len(raw),
                "git_mode": entry.mode,
                "path": entry.path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "tracked": True,
            }
        )
        head_rows.append(
            {
                "git_mode": entry.mode,
                "git_object": entry.object_id,
                "path": entry.path,
            }
        )
    current_rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    head_rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    tree_id = protocol_hash("pytest_current_implementation_tree/v1", current_rows)
    diff_id = protocol_hash(
        "pytest_current_implementation_diff/v1",
        {
            "current_rows": current_rows,
            "head_rows": head_rows,
            "implementation_commit": commit,
        },
    )
    source_rows = [
        row
        for row in current_rows
        if re.fullmatch(r"research_decision_engine/benchmarks/broader_.*\.py", str(row["path"]))
    ]
    test_rows = [
        row
        for row in current_rows
        if str(row["path"]).startswith("tests/") and str(row["path"]).endswith(".py")
    ]
    lock_raw = trusted_blobs["uv.lock"]
    dependency_lock_sha256 = hashlib.sha256(lock_raw).hexdigest()
    source_bundle_sha256 = protocol_hash("broader_validation_sources/v1", source_rows)
    test_bundle_sha256 = protocol_hash("complete_pytest_bundle/v1", test_rows)
    implementation = ImplementationProjection(
        dependency_lock_sha256=dependency_lock_sha256,
        implementation_commit=commit,
        implementation_diff_sha256=diff_id,
        implementation_tree_sha256=tree_id,
        source_bundle_sha256=source_bundle_sha256,
        test_bundle_sha256=test_bundle_sha256,
    )
    if (
        implementation.dependency_lock_sha256 != dependency_lock_sha256
        or implementation.implementation_commit != commit
        or implementation.implementation_diff_sha256 != diff_id
        or implementation.implementation_tree_sha256 != tree_id
        or implementation.source_bundle_sha256 != source_bundle_sha256
        or implementation.test_bundle_sha256 != test_bundle_sha256
    ):
        _error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "Layer-0 implementation projection differs from independently derived Git facts.",
            layer="validation_authority",
        )
    runtime, runtime_identity = _current_runtime()
    _validate_loaded_implementation_bytes(root=root, trusted_blobs=trusted_blobs)
    from research_decision_engine.benchmarks import broader_smoke, broader_validation

    dependency_reader = vars(broader_validation).get("_current_production_dependency_environment")
    if (
        type(dependency_reader) is not FunctionType
        or dependency_reader.__module__ != broader_validation.__name__
        or dependency_reader.__qualname__ != "_current_production_dependency_environment"
    ):
        _error(
            "CALLABLE_IDENTITY_MISMATCH",
            "The production dependency-environment resolver is not the trusted implementation.",
            layer="validation_authority",
        )
    dependency_resolver: Callable[[], _DependencyEnvironmentIdentity] = _runtime_cast(
        dependency_reader
    )
    try:
        dependency_environment = dependency_resolver()
    except Exception as error:
        raise P2Stage1Error(
            "RUNTIME_IDENTITY_MISMATCH",
            "The exact production dependency environment cannot be reconstructed.",
            layer="validation_authority",
        ) from error
    git_directory = _resolve_git_directory(root)
    _validate_trusted_bootstrap_manifest(
        git_directory=git_directory,
        snapshot=snapshot,
        dependency_lock_sha256=dependency_lock_sha256,
        runtime=runtime,
        runtime_identity=runtime_identity,
        dependency_environment=dependency_environment,
    )

    if broader_smoke.execute_bounded_validation_evidence is not trusted_public_entrypoint:
        _error(
            "CALLABLE_IDENTITY_MISMATCH",
            "The installed evidence-generator module global was replaced.",
            layer="validation_authority",
        )
    generator, generator_callable_id = trusted_callable_projector(trusted_entrypoint)
    expected_generator_path = "research_decision_engine/benchmarks/broader_smoke.py"
    if (
        generator.module_name != "research_decision_engine.benchmarks.broader_smoke"
        or generator.qualname != "execute_bounded_validation_evidence"
        or generator.source.sha256
        != hashlib.sha256(trusted_blobs[expected_generator_path]).hexdigest()
        or Path(generator.source.path) != (root / expected_generator_path).resolve(strict=True)
    ):
        _error(
            "CALLABLE_IDENTITY_MISMATCH",
            "The evidence-generator callable is not the exact trusted Git implementation.",
            layer="validation_authority",
        )
    generator_projection = {
        "callable": generator.as_dict(),
        "callable_identity": generator_callable_id,
        "entry_point": (
            "research_decision_engine.benchmarks.broader_smoke.execute_bounded_validation_evidence"
        ),
        "evidence_contract_checkpoint": EVIDENCE_CONTRACT_CHECKPOINT,
        "implementation": implementation.as_dict(),
        "protocol_checkpoint": PROTOCOL_CHECKPOINT,
        "runtime": runtime.as_dict(),
        "runtime_identity": runtime_identity,
        "schema_version": "broader-replication-validation-evidence-generator/v1",
    }
    evidence_generator_identity = protocol_hash(
        "validation_evidence_generator/v1", generator_projection
    )
    issuer_specs = (
        (
            "validation_authority",
            "research_decision_engine.benchmarks.broader_smoke.execute_bounded_validation_evidence",
        ),
        (
            "pytest_plan",
            "research_decision_engine.benchmarks.broader_validation.execute_pytest_validation",
        ),
        (
            "oracle_plan",
            "research_decision_engine.benchmarks.broader_oracle.begin_oracle_evidence_binding",
        ),
        (
            "execution_specification",
            "research_decision_engine.benchmarks.broader_execution.execute_deterministic_map",
        ),
    )
    issuers = [
        issuer_projection(
            context_implementation=implementation,
            runtime=runtime,
            runtime_identity=runtime_identity,
            role=role,  # type: ignore[arg-type]
            entry_point=entry_point,
            trust_domain="production",
        )
        for role, entry_point in issuer_specs
    ]
    context = Layer0Context(
        implementation=implementation,
        runtime=runtime,
        runtime_identity=runtime_identity,
        validation_authority_issuer=issuers[0][0],
        validation_authority_issuer_identity=issuers[0][1],
        pytest_plan_issuer=issuers[1][0],
        pytest_plan_issuer_identity=issuers[1][1],
        oracle_plan_issuer=issuers[2][0],
        oracle_plan_issuer_identity=issuers[2][1],
        execution_specification_issuer=issuers[3][0],
        execution_specification_issuer_identity=issuers[3][1],
        evidence_generator=generator,
        evidence_generator_entry_point=(
            "research_decision_engine.benchmarks.broader_smoke.execute_bounded_validation_evidence"
        ),
        evidence_generator_identity=evidence_generator_identity,
    )
    _validate_layer0_context(context, "production")
    if (
        context.implementation is not implementation
        or context.runtime is not runtime
        or context.runtime_identity != runtime_identity
        or context.validation_authority_issuer is not issuers[0][0]
        or context.validation_authority_issuer_identity != issuers[0][1]
        or context.pytest_plan_issuer is not issuers[1][0]
        or context.pytest_plan_issuer_identity != issuers[1][1]
        or context.oracle_plan_issuer is not issuers[2][0]
        or context.oracle_plan_issuer_identity != issuers[2][1]
        or context.execution_specification_issuer is not issuers[3][0]
        or context.execution_specification_issuer_identity != issuers[3][1]
        or context.evidence_generator is not generator
        or context.evidence_generator_identity != evidence_generator_identity
    ):
        _error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "Layer-0 context does not retain the independently derived Git/runtime facts.",
            layer="validation_authority",
        )
    ending_snapshot = _current_git_snapshot(root)
    ending_runtime, ending_runtime_identity = _current_runtime()
    try:
        ending_dependency_environment = dependency_resolver()
    except Exception as error:
        raise P2Stage1Error(
            "RUNTIME_IDENTITY_MISMATCH",
            "The production dependency environment changed during Layer-0 derivation.",
            layer="validation_authority",
        ) from error
    if (
        ending_snapshot != snapshot
        or ending_runtime != runtime
        or ending_runtime_identity != runtime_identity
        or ending_dependency_environment != dependency_environment
    ):
        _error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "Implementation, runtime, or dependencies changed during Layer-0 derivation.",
            layer="validation_authority",
        )
    _validate_trusted_bootstrap_manifest(
        git_directory=git_directory,
        snapshot=ending_snapshot,
        dependency_lock_sha256=dependency_lock_sha256,
        runtime=ending_runtime,
        runtime_identity=ending_runtime_identity,
        dependency_environment=ending_dependency_environment,
    )
    return context


def _validate_loaded_implementation_bytes(
    *,
    root: Path,
    trusted_blobs: dict[str, bytes],
) -> None:
    """Require every loaded Stage-1 authority module to match its HEAD blob."""

    required_module_names = (
        "research_decision_engine.benchmarks.broader_validation_evidence",
        "research_decision_engine.benchmarks.broader_execution",
        "research_decision_engine.benchmarks.broader_validation",
        "research_decision_engine.benchmarks.broader_oracle",
        "research_decision_engine.benchmarks.broader_smoke",
        "research_decision_engine.benchmarks.broader_conformance",
        "research_decision_engine.benchmarks.broader_protocol",
    )
    required_opaque_names: dict[str, tuple[str, ...]] = {
        "research_decision_engine.benchmarks.broader_validation_evidence": (
            "_require_production_preparation",
            "_consume_production_preparation",
            "_reserve_production_validation_run",
            "_require_production_run",
            "_publish_production_binding",
            "_record_production_resources",
            "_production_plan_lookup",
            "_production_authority_lookup",
            "_abort_production_preparation",
            "_install_production_entrypoint",
            "_production_failure_scope",
            "_production_registry_snapshot",
            "_seal_production_preparer",
            "_create_owned_control_directory",
            "_remove_empty_owned_control_directory",
        ),
        "research_decision_engine.benchmarks.broader_execution": (
            "_require_production_preparation",
            "_require_production_executor_implementation_record",
            "_invalidate_production_executor_implementation_record",
            "_production_executor_implementation_current_count",
            "_require_production_executor_implementation",
            "_invalidate_production_executor_implementation",
            "executor_implementation_projection",
            "executor_implementation_identity",
            "_production_executor_implementation_is_current",
            "_issue_production_executor_implementation",
            "_issue_production_execution_plan_drafts",
        ),
        "research_decision_engine.benchmarks.broader_validation": (
            "_require_production_preparation",
            "_create_guarded_junit_file",
            "_retained_junit_handle_is_open",
            "_retained_junit_handle_is_cleaned",
            "_cleanup_retained_junit_handle",
            "_retained_junit_cleanup_failure_scope",
            "_issue_production_pytest_plan_draft",
            "_validate_production_pytest_runtime",
        ),
        "research_decision_engine.benchmarks.broader_oracle": ("_require_production_preparation",),
        "research_decision_engine.benchmarks.broader_smoke": (
            "execute_bounded_validation_evidence",
        ),
    }
    for required_name in required_module_names:
        if not isinstance(sys.modules.get(required_name), ModuleType):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Required loaded Stage-1 module is absent: {required_name}.",
                layer="validation_authority",
            )
    _validate_production_component_sources(root=root, trusted_blobs=trusted_blobs)
    module_names = tuple(
        sorted(
            name
            for name, module in tuple(sys.modules.items())
            if name == "research_decision_engine"
            or (name.startswith("research_decision_engine.") and isinstance(module, ModuleType))
        )
    )
    compiled_manifests: dict[
        str,
        tuple[Path, dict[tuple[str, int], list[CodeType]]],
    ] = {}
    source_declarations: dict[str, dict[str, str]] = {}
    source_class_nodes: dict[str, dict[str, Any]] = {}
    source_imports: dict[str, dict[str, tuple[str, str | None]]] = {}
    source_assignments: dict[str, dict[str, Any]] = {}

    def compiled_manifest(
        module_name: str,
    ) -> tuple[Path, dict[tuple[str, int], list[CodeType]]]:
        cached = compiled_manifests.get(module_name)
        if cached is not None:
            return cached
        module = sys.modules.get(module_name)
        raw_path = None if not isinstance(module, ModuleType) else getattr(module, "__file__", None)
        if not isinstance(module, ModuleType) or not isinstance(raw_path, str):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded Stage-1 module has no source path: {module_name}.",
                layer="validation_authority",
            )
        source_path = Path(raw_path)
        if source_path.suffix == ".pyc":
            source_path = source_path.with_suffix(".py")
        source_path = _strict_path(source_path, require_file=True)
        try:
            relative = source_path.relative_to(root).as_posix()
        except ValueError:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded Stage-1 module is outside the trusted repository: {module_name}.",
                layer="validation_authority",
            )
        expected = trusted_blobs.get(relative)
        if expected is None or source_path.read_bytes() != expected:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded Stage-1 module bytes differ from trusted Git: {module_name}.",
                layer="validation_authority",
            )
        compiled_module = _runtime_cast(
            _TRUSTED_COMPILE(
                expected,
                str(source_path),
                "exec",
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
        )
        syntax_tree = _runtime_cast(
            _TRUSTED_COMPILE(
                expected,
                str(source_path),
                "exec",
                flags=1024,
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
        )
        declarations: dict[str, str] = {}
        class_nodes: dict[str, Any] = {}
        imports: dict[str, tuple[str, str | None]] = {}
        assignments: dict[str, Any] = {}
        deleted_names: set[str] = set()
        for node in syntax_tree.body:
            node_kind = node.__class__.__name__
            if node_kind in {"FunctionDef", "AsyncFunctionDef", "ClassDef"}:
                declarations[node.name] = node_kind
                imports.pop(node.name, None)
                assignments.pop(node.name, None)
                if node_kind == "ClassDef":
                    class_nodes[node.name] = node
            elif node_kind == "Import":
                for alias in node.names:
                    binding = alias.asname or alias.name.split(".", maxsplit=1)[0]
                    target_module = alias.name if alias.asname else binding
                    imports[binding] = (target_module, None)
                    declarations.pop(binding, None)
                    assignments.pop(binding, None)
            elif node_kind == "ImportFrom" and node.module != "__future__":
                if node.level:
                    package_parts = module_name.split(".")[:-1]
                    retained = len(package_parts) - node.level + 1
                    prefix = ".".join(package_parts[:retained])
                    target_module = prefix if node.module is None else f"{prefix}.{node.module}"
                else:
                    target_module = node.module
                for alias in node.names:
                    if alias.name == "*":
                        _error(
                            "IMPLEMENTATION_IDENTITY_MISMATCH",
                            f"Trusted project source uses an unsupported star import: "
                            f"{module_name}.",
                            layer="validation_authority",
                        )
                    binding = alias.asname or alias.name
                    imports[binding] = (target_module, alias.name)
                    declarations.pop(binding, None)
                    assignments.pop(binding, None)
            elif node_kind == "AnnAssign" and node.target.__class__.__name__ == "Name":
                binding = node.target.id
                if node.value is not None:
                    assignments[binding] = node.value
                imports.pop(binding, None)
                declarations.pop(binding, None)
            elif node_kind == "Assign" and len(node.targets) == 1:
                target = node.targets[0]
                if target.__class__.__name__ == "Name":
                    binding = target.id
                    assignments[binding] = node.value
                    imports.pop(binding, None)
                    declarations.pop(binding, None)
            elif node_kind == "Delete":
                for target in node.targets:
                    if target.__class__.__name__ == "Name":
                        deleted_names.add(target.id)
        for deleted_name in deleted_names:
            declarations.pop(deleted_name, None)
            class_nodes.pop(deleted_name, None)
            imports.pop(deleted_name, None)
            assignments.pop(deleted_name, None)
        source_declarations[module_name] = declarations
        source_class_nodes[module_name] = class_nodes
        source_imports[module_name] = imports
        source_assignments[module_name] = assignments
        compiled_by_location: dict[tuple[str, int], list[CodeType]] = {}
        pending_codes = [compiled_module]
        while pending_codes:
            parent_code = pending_codes.pop()
            for constant in parent_code.co_consts:
                if isinstance(constant, CodeType):
                    pending_codes.append(constant)
                    compiled_by_location.setdefault(
                        (constant.co_qualname, constant.co_firstlineno), []
                    ).append(constant)
        result = source_path, compiled_by_location
        compiled_manifests[module_name] = result
        return result

    source_value_missing = object()
    object_getattribute = _runtime_cast(_TRUSTED_BUILTINS["object"]).__getattribute__
    exact_tuple: Any = _runtime_cast(_TRUSTED_BUILTINS["tuple"])
    exact_list: Any = _runtime_cast(_TRUSTED_BUILTINS["list"])
    exact_dict: Any = _runtime_cast(_TRUSTED_BUILTINS["dict"])
    exact_set: Any = _runtime_cast(_TRUSTED_BUILTINS["set"])
    exact_frozenset: Any = _runtime_cast(_TRUSTED_BUILTINS["frozenset"])
    exact_range: Any = _runtime_cast(_TRUSTED_BUILTINS["range"])
    tuple_constructor: Any = exact_tuple
    frozenset_constructor: Any = exact_frozenset
    range_constructor: Any = exact_range

    def expected_import_binding(module_name: str, binding: str) -> object:
        target_module_name, imported_name = source_imports[module_name][binding]
        target_module = sys.modules.get(target_module_name)
        if type(target_module) is not ModuleType:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted imported module is unavailable: {module_name}.{binding}.",
                layer="validation_authority",
            )
        if imported_name is None:
            return target_module
        target_namespace = vars(target_module)
        if imported_name not in target_namespace:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted imported symbol is unavailable: {module_name}.{binding}.",
                layer="validation_authority",
            )
        return target_namespace[imported_name]

    def source_runtime_value(
        node: Any,
        *,
        module_name: str,
        resolving: frozenset[str] = frozenset(),
    ) -> object:
        node_kind = node.__class__.__name__
        if node_kind == "Constant":
            return node.value
        if node_kind in {"Tuple", "List", "Set"}:
            values = [
                source_runtime_value(child, module_name=module_name, resolving=resolving)
                for child in node.elts
            ]
            if any(value is source_value_missing for value in values):
                return source_value_missing
            if node_kind == "Tuple":
                return exact_tuple(values)
            if node_kind == "List":
                return exact_list(values)
            return exact_set(values)
        if node_kind == "Dict":
            keys = [
                source_runtime_value(child, module_name=module_name, resolving=resolving)
                for child in node.keys
            ]
            values = [
                source_runtime_value(child, module_name=module_name, resolving=resolving)
                for child in node.values
            ]
            if any(value is source_value_missing for value in (*keys, *values)):
                return source_value_missing
            return exact_dict(zip(keys, values, strict=True))
        if node_kind == "UnaryOp" and node.operand.__class__.__name__ == "Constant":
            value = node.operand.value
            operator = node.op.__class__.__name__
            if type(value) in {int, float} and operator in {"USub", "UAdd"}:
                return -value if operator == "USub" else +value
            return source_value_missing
        if node_kind == "Name":
            name = node.id
            assignments = source_assignments[module_name]
            if name in assignments:
                if name in resolving:
                    return source_value_missing
                return source_runtime_value(
                    assignments[name],
                    module_name=module_name,
                    resolving=resolving | {name},
                )
            if name in source_imports[module_name]:
                return expected_import_binding(module_name, name)
            if name in _TRUSTED_BUILTINS:
                return _TRUSTED_BUILTINS[name]
            module = sys.modules.get(module_name)
            if type(module) is ModuleType:
                return vars(module).get(name, source_value_missing)
            return source_value_missing
        if node_kind == "Attribute":
            owner = source_runtime_value(
                node.value,
                module_name=module_name,
                resolving=resolving,
            )
            if owner is source_value_missing:
                return source_value_missing
            return getattr(owner, node.attr, source_value_missing)
        if node_kind != "Call" or node.keywords:
            return source_value_missing
        callable_value = source_runtime_value(
            node.func,
            module_name=module_name,
            resolving=resolving,
        )
        if callable_value is exact_tuple and len(node.args) == 1:
            argument = node.args[0]
            if argument.__class__.__name__ == "Call" and not argument.keywords:
                range_callable = source_runtime_value(
                    argument.func,
                    module_name=module_name,
                    resolving=resolving,
                )
                range_arguments = [
                    source_runtime_value(
                        child,
                        module_name=module_name,
                        resolving=resolving,
                    )
                    for child in argument.args
                ]
                if (
                    range_callable is exact_range
                    and 1 <= len(range_arguments) <= 3
                    and all(type(value) is int for value in range_arguments)
                ):
                    return tuple_constructor(range_constructor(*_runtime_cast(range_arguments)))
            value = source_runtime_value(
                argument,
                module_name=module_name,
                resolving=resolving,
            )
            if value is not source_value_missing:
                try:
                    return tuple_constructor(_runtime_cast(value))
                except TypeError:
                    return source_value_missing
        if callable_value is exact_frozenset and len(node.args) <= 1:
            value = (
                ()
                if not node.args
                else source_runtime_value(
                    node.args[0],
                    module_name=module_name,
                    resolving=resolving,
                )
            )
            if value is not source_value_missing:
                return frozenset_constructor(_runtime_cast(value))
        if (
            type(callable_value) is type
            and dataclasses.is_dataclass(callable_value)
            and callable_value.__module__ == module_name
        ):
            arguments = [
                source_runtime_value(child, module_name=module_name, resolving=resolving)
                for child in node.args
            ]
            if not any(value is source_value_missing for value in arguments):
                try:
                    return callable_value(*arguments)
                except (TypeError, ValueError):
                    return source_value_missing
        return source_value_missing

    def exact_source_value_matches(current: object, expected: object) -> bool:
        if current is source_value_missing or expected is source_value_missing:
            return False
        if type(current) is not type(expected):
            return False
        if type(expected) in {type(None), bool, int, float, complex, str, bytes}:
            return current == expected
        if type(expected) in {tuple, list}:
            current_values = _runtime_cast(current)
            expected_values = _runtime_cast(expected)
            return len(current_values) == len(expected_values) and all(
                exact_source_value_matches(left, right)
                for left, right in zip(current_values, expected_values, strict=True)
            )
        if type(expected) is dict:
            current_mapping = _runtime_cast(current)
            expected_mapping = _runtime_cast(expected)
            if tuple(current_mapping) != tuple(expected_mapping):
                return False
            return all(
                exact_source_value_matches(current_mapping[key], value)
                for key, value in expected_mapping.items()
            )
        if type(expected) in {set, frozenset}:
            return current == expected
        if dataclasses.is_dataclass(expected):
            return all(
                exact_source_value_matches(
                    object_getattribute(current, descriptor.name),
                    object_getattribute(expected, descriptor.name),
                )
                for descriptor in dataclasses.fields(expected)
            )
        return current is expected

    stdlib_root = Path(os.__file__).resolve(strict=True).parent
    external_manifests: dict[Path, dict[tuple[str, int], list[CodeType]]] = {}

    def validate_external_wrapper_code(code: CodeType) -> None:
        source_path = Path(code.co_filename).resolve(strict=True)
        if source_path != stdlib_root and stdlib_root not in source_path.parents:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "A project decorator wrapper is outside the trusted standard library.",
                layer="validation_authority",
            )
        compiled_by_location = external_manifests.get(source_path)
        if compiled_by_location is None:
            module_code = _runtime_cast(
                _TRUSTED_COMPILE(
                    source_path.read_bytes(),
                    str(source_path),
                    "exec",
                    dont_inherit=True,
                    optimize=sys.flags.optimize,
                )
            )
            compiled_by_location = {}
            pending_codes = [module_code]
            while pending_codes:
                parent_code = pending_codes.pop()
                for constant in parent_code.co_consts:
                    if isinstance(constant, CodeType):
                        pending_codes.append(constant)
                        compiled_by_location.setdefault(
                            (constant.co_qualname, constant.co_firstlineno), []
                        ).append(constant)
            external_manifests[source_path] = compiled_by_location
        matches = compiled_by_location.get((code.co_qualname, code.co_firstlineno), [])
        if len(matches) != 1 or matches[0] != code:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                "A project decorator wrapper differs from trusted runtime source.",
                layer="validation_authority",
            )

    def validate_opaque_source(value: object, *, binding: str) -> None:
        attestation = getattr(value, "_rde_opaque_source", None)
        if (
            value.__class__ is not _TRUSTED_LRU_WRAPPER_TYPE
            or type(attestation) is not tuple
            or len(attestation) != 4
            or type(attestation[0]) is not str
            or type(attestation[1]) is not str
            or type(attestation[2]) is not int
            or type(attestation[3]) is not CodeType
        ):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Opaque production boundary has no exact source attestation: {binding}.",
                layer="validation_authority",
            )
        attested_module = attestation[0]
        attested_qualname = attestation[1]
        attested_line = attestation[2]
        attested_code = attestation[3]
        source_path, compiled_by_location = compiled_manifest(attested_module)
        matches = compiled_by_location.get((attested_qualname, attested_line), [])
        try:
            live_source = Path(attested_code.co_filename).resolve(strict=True)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Opaque production code has no exact source: {binding}.",
                layer="validation_authority",
            ) from error
        if live_source != source_path or len(matches) != 1 or matches[0] != attested_code:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Opaque production code differs from trusted Git: {binding}.",
                layer="validation_authority",
            )

    def closure_contains(function: FunctionType, expected: object) -> bool:
        for cell in function.__closure__ or ():
            try:
                if cell.cell_contents is expected:
                    return True
            except ValueError:
                continue
        return False

    def validate_project_function(
        function: FunctionType,
        *,
        module: ModuleType,
        module_name: str,
        source_path: Path,
        compiled_by_location: dict[tuple[str, int], list[CodeType]],
        allow_generated: bool = False,
    ) -> FunctionType:
        module_namespace = vars(module)
        candidate = function
        if candidate.__globals__ is not module_namespace:
            wrapped = getattr(candidate, "__wrapped__", None)
            if (
                type(wrapped) is not FunctionType
                or wrapped.__globals__ is not module_namespace
                or candidate.__module__ != module_name
                or not closure_contains(candidate, wrapped)
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Loaded project function has foreign globals: "
                    f"{module_name}.{candidate.__qualname__}.",
                    layer="validation_authority",
                )
            validate_external_wrapper_code(candidate.__code__)
            candidate = wrapped
        if candidate.__module__ != module_name:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded project function metadata changed: "
                f"{module_name}.{candidate.__qualname__}.",
                layer="validation_authority",
            )
        code = candidate.__code__
        if code.co_filename.startswith("<"):
            if allow_generated and code.co_filename == "<string>":
                return candidate
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded project code has an unauthenticated synthetic source: "
                f"{module_name}.{code.co_qualname}.",
                layer="validation_authority",
            )
        try:
            live_source = Path(code.co_filename).resolve(strict=True)
        except OSError as error:
            raise P2Stage1Error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded project code has no exact source: {module_name}.{code.co_qualname}.",
                layer="validation_authority",
            ) from error
        matches = compiled_by_location.get((code.co_qualname, code.co_firstlineno), [])
        if live_source != source_path or len(matches) != 1 or matches[0] != code:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Loaded project code differs from trusted Git: {module_name}.{code.co_qualname}.",
                layer="validation_authority",
            )
        return candidate

    def dataclass_decorator_parameters(class_node: Any) -> dict[str, bool] | None:
        parameters = {
            "init": True,
            "repr": True,
            "eq": True,
            "order": False,
            "unsafe_hash": False,
            "frozen": False,
            "match_args": True,
            "kw_only": False,
            "slots": False,
            "weakref_slot": False,
        }
        for decorator in class_node.decorator_list:
            decorator_kind = decorator.__class__.__name__
            target = decorator.func if decorator_kind == "Call" else decorator
            target_name = getattr(target, "id", getattr(target, "attr", None))
            if target_name != "dataclass":
                continue
            if decorator_kind == "Call":
                for keyword in decorator.keywords:
                    if (
                        keyword.arg not in parameters
                        or keyword.value.__class__.__name__ != "Constant"
                    ):
                        _error(
                            "IMPLEMENTATION_IDENTITY_MISMATCH",
                            "A trusted dataclass uses a non-constant generation option.",
                            layer="validation_authority",
                        )
                    value = keyword.value.value
                    if type(value) is not bool:
                        _error(
                            "IMPLEMENTATION_IDENTITY_MISMATCH",
                            "A trusted dataclass generation option is not boolean.",
                            layer="validation_authority",
                        )
                    parameters[keyword.arg] = value
            return parameters
        return None

    def generated_dataclass_function(value: object) -> FunctionType | None:
        if type(value) is not FunctionType:
            return None
        function = value
        dataclass_getstate: object = vars(dataclasses).get("_dataclass_getstate")
        dataclass_setstate: object = vars(dataclasses).get("_dataclass_setstate")
        if function is dataclass_getstate or function is dataclass_setstate:
            validate_external_wrapper_code(function.__code__)
            return function
        if function.__code__.co_filename == "<string>":
            return function
        wrapped = getattr(function, "__wrapped__", None)
        if type(wrapped) is FunctionType and wrapped.__code__.co_filename == "<string>":
            if not closure_contains(function, wrapped):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    "A generated dataclass wrapper does not close over its exact method.",
                    layer="validation_authority",
                )
            validate_external_wrapper_code(function.__code__)
            return wrapped
        return None

    def class_source_member_names(class_node: Any) -> frozenset[str]:
        names: set[str] = set()
        for node in class_node.body:
            node_kind = node.__class__.__name__
            if node_kind in {"FunctionDef", "AsyncFunctionDef", "ClassDef"}:
                names.add(node.name)
            elif node_kind == "AnnAssign" and node.target.__class__.__name__ == "Name":
                names.add(node.target.id)
            elif node_kind == "Assign":
                for target in node.targets:
                    if target.__class__.__name__ == "Name":
                        names.add(target.id)
        return frozenset(names)

    def resolve_class_base(node: Any, *, module_name: str) -> type[object] | None:
        value = source_runtime_value(node, module_name=module_name)
        return _runtime_cast(value) if _runtime_cast(_TRUSTED_ISINSTANCE)(value, type) else None

    def validate_source_class_shape(
        candidate: type[object],
        *,
        class_node: Any,
        module_name: str,
        is_dataclass_type: bool,
    ) -> None:
        expected_bases: tuple[type[object], ...]
        if class_node.bases:
            resolved_bases = tuple(
                resolve_class_base(node, module_name=module_name) for node in class_node.bases
            )
            if any(base is None for base in resolved_bases):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted class base cannot be resolved from Git: "
                    f"{module_name}.{candidate.__name__}.",
                    layer="validation_authority",
                )
            expected_bases = _runtime_cast(resolved_bases)
        else:
            expected_bases = (_runtime_cast(_TRUSTED_BUILTINS["object"]),)
        if (
            len(class_node.keywords) != 0
            or len(expected_bases) != 1
            or len(candidate.__bases__) != 1
            or candidate.__bases__[0] is not expected_bases[0]
            or candidate.__mro__[1:] != expected_bases[0].__mro__
            or type(candidate) is not type(expected_bases[0])
        ):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted class inheritance differs from Git: {module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )
        if is_dataclass_type:
            return
        allowed_names = set(class_source_member_names(class_node))
        allowed_names.update(
            {
                "__abstractmethods__",
                "__annotations__",
                "__dict__",
                "__doc__",
                "__firstlineno__",
                "__init__",
                "__module__",
                "__orig_bases__",
                "__parameters__",
                "__protocol_attrs__",
                "__static_attributes__",
                "__subclasshook__",
                "__weakref__",
                "_abc_impl",
                "_is_protocol",
                "_is_runtime_protocol",
            }
        )
        for node in class_node.body:
            if node.__class__.__name__ != "Assign" or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if target.__class__.__name__ != "Name" or target.id != "__slots__":
                continue
            expected_slots = source_runtime_value(node.value, module_name=module_name)
            if expected_slots is source_value_missing or not exact_source_value_matches(
                getattr(candidate, "__slots__", source_value_missing), expected_slots
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted class slots differ from Git: {module_name}.{candidate.__name__}.",
                    layer="validation_authority",
                )
            if type(expected_slots) is str:
                allowed_names.add(expected_slots)
            else:
                allowed_names.update(_runtime_cast(expected_slots))
        unexpected_names = set(vars(candidate)) - allowed_names
        if unexpected_names:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted class namespace has non-source behavior: "
                f"{module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )

    def generated_value_matches(
        current: object,
        expected: object,
        *,
        seen: set[tuple[int, int]] | None = None,
        equivalent_types: tuple[type[object], type[object]] | None = None,
    ) -> bool:
        if current is expected:
            return True
        if (
            equivalent_types is not None
            and current is equivalent_types[0]
            and expected is equivalent_types[1]
        ):
            return True
        if equivalent_types is not None and type(current) is type and type(expected) is type:
            current_type = _runtime_cast(current)
            expected_type = _runtime_cast(expected)
            current_final, expected_final = equivalent_types

            def is_linked_pre_slots_type(original: type[object], final: type[object]) -> bool:
                original_namespace = vars(original)
                final_namespace = vars(final)
                linked_names = (
                    "__annotations__",
                    "__dataclass_fields__",
                    "__dataclass_params__",
                    "__delattr__",
                    "__eq__",
                    "__hash__",
                    "__init__",
                    "__repr__",
                    "__setattr__",
                )
                return (
                    original is not final
                    and original.__name__ == final.__name__
                    and original.__module__ == final.__module__
                    and original.__bases__ == final.__bases__
                    and all(
                        original_namespace.get(name) is final_namespace.get(name)
                        for name in linked_names
                    )
                )

            if is_linked_pre_slots_type(current_type, current_final) and is_linked_pre_slots_type(
                expected_type, expected_final
            ):
                return True
        if type(current) is not type(expected):
            return False
        if seen is None:
            seen = set()
        pair = (id(current), id(expected))
        if pair in seen:
            return True
        seen.add(pair)
        if type(expected) in {type(None), bool, int, float, complex, str, bytes, CodeType}:
            return current == expected
        if type(expected) in {tuple, list}:
            current_values = _runtime_cast(current)
            expected_values = _runtime_cast(expected)
            return len(current_values) == len(expected_values) and all(
                generated_value_matches(
                    left,
                    right,
                    seen=seen,
                    equivalent_types=equivalent_types,
                )
                for left, right in zip(current_values, expected_values, strict=True)
            )
        if type(expected) is dict:
            current_mapping = _runtime_cast(current)
            expected_mapping = _runtime_cast(expected)
            return tuple(current_mapping) == tuple(expected_mapping) and all(
                generated_value_matches(
                    current_mapping[key],
                    value,
                    seen=seen,
                    equivalent_types=equivalent_types,
                )
                for key, value in expected_mapping.items()
            )
        if type(expected) in {set, frozenset}:
            return current == expected
        if type(expected) is FunctionType:
            current_function = _runtime_cast(current)
            expected_function = expected
            if current_function.__code__ != expected_function.__code__:
                return False
            if not generated_value_matches(
                current_function.__defaults__,
                expected_function.__defaults__,
                seen=seen,
                equivalent_types=equivalent_types,
            ) or not generated_value_matches(
                current_function.__kwdefaults__,
                expected_function.__kwdefaults__,
                seen=seen,
                equivalent_types=equivalent_types,
            ):
                return False
            current_closure = tuple(
                cell.cell_contents for cell in current_function.__closure__ or ()
            )
            expected_closure = tuple(
                cell.cell_contents for cell in expected_function.__closure__ or ()
            )
            return generated_value_matches(
                current_closure,
                expected_closure,
                seen=seen,
                equivalent_types=equivalent_types,
            )
        return False

    def validate_dataclass_type(
        candidate: type[object],
        *,
        class_node: Any,
        module_name: str,
        regenerate: bool,
    ) -> None:
        parameters = dataclass_decorator_parameters(class_node)
        if parameters is None:
            return
        if not dataclasses.is_dataclass(candidate):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted dataclass declaration changed type: {module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )
        source_field_nodes = tuple(
            node
            for node in class_node.body
            if node.__class__.__name__ == "AnnAssign" and node.target.__class__.__name__ == "Name"
        )
        source_field_names = tuple(node.target.id for node in source_field_nodes)
        annotations = getattr(candidate, "__annotations__", None)
        dataclass_fields = getattr(candidate, "__dataclass_fields__", None)
        params = getattr(candidate, "__dataclass_params__", None)
        if (
            type(annotations) is not dict
            or type(dataclass_fields) is not dict
            or tuple(annotations) != source_field_names
            or tuple(dataclass_fields) != source_field_names
            or params is None
            or any(getattr(params, name, None) is not value for name, value in parameters.items())
        ):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted dataclass schema differs from Git: {module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )
        if not regenerate:
            return
        field_specs: list[Any] = []
        dataclass_field = _runtime_cast(dataclasses.field)
        normal_field_kind = vars(dataclasses).get("_FIELD")
        classvar_field_kind = vars(dataclasses).get("_FIELD_CLASSVAR")
        initvar_field_kind = vars(dataclasses).get("_FIELD_INITVAR")
        for field_node in source_field_nodes:
            name = field_node.target.id
            descriptor = dataclass_fields[name]
            annotation_names: set[str] = set()
            pending_annotations = [field_node.annotation]
            while pending_annotations:
                annotation_node = pending_annotations.pop()
                annotation_kind = annotation_node.__class__.__name__
                if annotation_kind == "Name":
                    annotation_names.add(annotation_node.id)
                elif annotation_kind == "Attribute":
                    annotation_names.add(annotation_node.attr)
                    pending_annotations.append(annotation_node.value)
                else:
                    for attribute in ("value", "slice", "elts"):
                        child = getattr(annotation_node, attribute, None)
                        if child is None:
                            continue
                        if type(child) is list:
                            pending_annotations.extend(child)
                        else:
                            pending_annotations.append(child)
            expected_field_kind = (
                classvar_field_kind
                if "ClassVar" in annotation_names
                else initvar_field_kind
                if "InitVar" in annotation_names
                else normal_field_kind
            )
            if getattr(descriptor, "_field_type", None) is not expected_field_kind:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass field kind differs from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            if expected_field_kind is classvar_field_kind:
                continue
            field_options: dict[str, object] = {
                "init": True,
                "repr": True,
                "hash": None,
                "compare": True,
                "kw_only": parameters["kw_only"],
            }
            default_node = field_node.value
            default_factory_node: Any | None = None
            if default_node is not None and default_node.__class__.__name__ == "Call":
                field_call = default_node
                field_target = field_call.func
                field_target_name = getattr(
                    field_target,
                    "id",
                    getattr(field_target, "attr", None),
                )
                if field_target_name == "field":
                    if field_call.args:
                        _error(
                            "IMPLEMENTATION_IDENTITY_MISMATCH",
                            "A trusted dataclass field call uses positional arguments.",
                            layer="validation_authority",
                        )
                    default_node = None
                    for keyword in field_call.keywords:
                        if keyword.arg in field_options:
                            if keyword.value.__class__.__name__ != "Constant":
                                _error(
                                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                                    "A trusted dataclass field option is not constant.",
                                    layer="validation_authority",
                                )
                            option_value = keyword.value.value
                            if keyword.arg == "hash":
                                if option_value is not None and type(option_value) is not bool:
                                    _error(
                                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                                        "A trusted dataclass hash option is invalid.",
                                        layer="validation_authority",
                                    )
                            elif type(option_value) is not bool:
                                _error(
                                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                                    "A trusted dataclass field option is not boolean.",
                                    layer="validation_authority",
                                )
                            field_options[keyword.arg] = option_value
                        elif keyword.arg == "default":
                            default_node = keyword.value
                        elif keyword.arg == "default_factory":
                            default_factory_node = keyword.value
                        else:
                            _error(
                                "IMPLEMENTATION_IDENTITY_MISMATCH",
                                "A trusted dataclass field uses an unsupported option.",
                                layer="validation_authority",
                            )
            if any(
                getattr(descriptor, option_name) is not option_value
                for option_name, option_value in field_options.items()
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass field flags differ from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            expected_default = (
                source_value_missing
                if default_node is None
                else source_runtime_value(default_node, module_name=module_name)
            )
            expected_factory = (
                source_value_missing
                if default_factory_node is None
                else source_runtime_value(default_factory_node, module_name=module_name)
            )
            if default_node is not None and expected_default is source_value_missing:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass default cannot be derived from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            if default_factory_node is not None and expected_factory is source_value_missing:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass factory cannot be derived from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            if expected_default is source_value_missing:
                if descriptor.default is not dataclasses.MISSING:
                    _error(
                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                        f"Trusted dataclass default differs from Git: "
                        f"{module_name}.{candidate.__name__}.{name}.",
                        layer="validation_authority",
                    )
            elif not exact_source_value_matches(descriptor.default, expected_default):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass default differs from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            if expected_factory is source_value_missing:
                if descriptor.default_factory is not dataclasses.MISSING:
                    _error(
                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                        f"Trusted dataclass factory differs from Git: "
                        f"{module_name}.{candidate.__name__}.{name}.",
                        layer="validation_authority",
                    )
            elif descriptor.default_factory is not expected_factory:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Trusted dataclass factory differs from Git: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
            annotation: object = (
                dataclasses.InitVar[object] if expected_field_kind is initvar_field_kind else object
            )
            field_arguments: dict[str, object] = {
                **field_options,
            }
            if expected_default is not source_value_missing:
                field_arguments["default"] = expected_default
            elif expected_factory is not source_value_missing:
                field_arguments["default_factory"] = expected_factory
            field_specs.append((name, annotation, dataclass_field(**field_arguments)))
        generated_namespace: dict[str, object] = {}
        if any(
            node.__class__.__name__ in {"FunctionDef", "AsyncFunctionDef"}
            and node.name == "__post_init__"
            for node in class_node.body
        ):

            def generated_post_init(self: object, *values: object) -> None:
                del self, values

            generated_namespace["__post_init__"] = generated_post_init
        regenerated = _runtime_cast(dataclasses.make_dataclass)(
            "_TrustedGitDataclass",
            field_specs,
            namespace=generated_namespace,
            init=parameters["init"],
            repr=parameters["repr"],
            eq=parameters["eq"],
            order=parameters["order"],
            unsafe_hash=parameters["unsafe_hash"],
            frozen=parameters["frozen"],
            match_args=parameters["match_args"],
            kw_only=parameters["kw_only"],
            slots=parameters["slots"],
            weakref_slot=parameters["weakref_slot"],
        )
        if getattr(candidate, "__match_args__", ()) != getattr(
            regenerated, "__match_args__", ()
        ) or getattr(candidate, "__slots__", None) != getattr(regenerated, "__slots__", None):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted dataclass layout differs from Git: {module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )
        explicit_method_names = {
            node.name
            for node in class_node.body
            if node.__class__.__name__ in {"FunctionDef", "AsyncFunctionDef"}
        }
        allowed_namespace_names = set(vars(regenerated)) | set(
            class_source_member_names(class_node)
        )
        allowed_namespace_names.update(
            {
                "__annotations__",
                "__dict__",
                "__doc__",
                "__firstlineno__",
                "__module__",
                "__static_attributes__",
                "__weakref__",
            }
        )
        if set(vars(candidate)) - allowed_namespace_names:
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Trusted dataclass namespace has non-source behavior: "
                f"{module_name}.{candidate.__name__}.",
                layer="validation_authority",
            )
        for name, expected_member in tuple(vars(regenerated).items()):
            if name in explicit_method_names:
                continue
            expected = generated_dataclass_function(expected_member)
            if expected is None:
                continue
            generated = generated_dataclass_function(vars(candidate).get(name))
            if generated is None or not generated_value_matches(
                generated,
                expected,
                equivalent_types=(candidate, regenerated),
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Generated dataclass behavior differs from trusted schema: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )
        for name, member in tuple(vars(candidate).items()):
            generated = generated_dataclass_function(member)
            if generated is None:
                if type(member) is FunctionType and member.__code__.co_filename.startswith("<"):
                    _error(
                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                        f"Trusted class contains unauthenticated generated code: "
                        f"{module_name}.{candidate.__name__}.{name}.",
                        layer="validation_authority",
                    )
                continue
            expected = generated_dataclass_function(vars(regenerated).get(name))
            if expected is None or not generated_value_matches(
                generated,
                expected,
                equivalent_types=(candidate, regenerated),
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Generated dataclass behavior differs from trusted schema: "
                    f"{module_name}.{candidate.__name__}.{name}.",
                    layer="validation_authority",
                )

    for module_name in module_names:
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            _error(
                "IMPLEMENTATION_IDENTITY_MISMATCH",
                f"Required loaded Stage-1 module is absent: {module_name}.",
                layer="validation_authority",
            )
        source_path, compiled_by_location = compiled_manifest(module_name)
        for opaque_name in required_opaque_names.get(module_name, ()):
            validate_opaque_source(
                vars(module).get(opaque_name),
                binding=f"{module_name}.{opaque_name}",
            )
        module_namespace = vars(module)
        validated: set[FunctionType] = set()
        declarations = (
            source_declarations[module_name] if module_name in required_module_names else {}
        )
        class_nodes = source_class_nodes[module_name]
        for binding in source_imports[module_name]:
            expected_binding = expected_import_binding(module_name, binding)
            if module_namespace.get(binding, source_value_missing) is not expected_binding:
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Loaded project import differs from trusted source: {module_name}.{binding}.",
                    layer="validation_authority",
                )
        for declaration_name, declaration_kind in declarations.items():
            value = module_namespace.get(declaration_name)
            if declaration_kind in {"FunctionDef", "AsyncFunctionDef"}:
                if type(value) is FunctionType:
                    validated.add(
                        validate_project_function(
                            value,
                            module=module,
                            module_name=module_name,
                            source_path=source_path,
                            compiled_by_location=compiled_by_location,
                        )
                    )
                elif getattr(value, "_rde_opaque_source", None) is not None:
                    validate_opaque_source(
                        value,
                        binding=f"{module_name}.{declaration_name}",
                    )
                else:
                    _error(
                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                        f"Source-declared project function changed binding: "
                        f"{module_name}.{declaration_name}.",
                        layer="validation_authority",
                    )
                continue
            if (
                declaration_kind != "ClassDef"
                or not isinstance(value, type)
                or value.__module__ != module_name
                or value.__qualname__ != declaration_name
            ):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Source-declared project class changed binding: "
                    f"{module_name}.{declaration_name}.",
                    layer="validation_authority",
                )
            project_type = _runtime_cast(value)
            validate_source_class_shape(
                project_type,
                class_node=class_nodes[declaration_name],
                module_name=module_name,
                is_dataclass_type=(
                    dataclass_decorator_parameters(class_nodes[declaration_name]) is not None
                ),
            )
            validate_dataclass_type(
                project_type,
                class_node=class_nodes[declaration_name],
                module_name=module_name,
                regenerate=module_name in required_module_names,
            )
            explicit_member_names = {
                node.name
                for node in class_nodes[declaration_name].body
                if node.__class__.__name__ in {"FunctionDef", "AsyncFunctionDef"}
            }
            for member_name, member in tuple(vars(project_type).items()):
                if member_name not in explicit_member_names:
                    continue
                candidates: tuple[object, ...]
                if type(member) is FunctionType:
                    candidates = (member,)
                elif type(member) in {staticmethod, classmethod}:
                    candidates = (member.__func__,)
                elif type(member) is property:
                    candidates = (member.fget, member.fset, member.fdel)
                else:
                    candidates = ()
                for candidate in candidates:
                    if type(candidate) is not FunctionType:
                        continue
                    if generated_dataclass_function(candidate) is not None:
                        continue
                    validated.add(
                        validate_project_function(
                            candidate,
                            module=module,
                            module_name=module_name,
                            source_path=source_path,
                            compiled_by_location=compiled_by_location,
                        )
                    )
        for value in tuple(module_namespace.values()):
            if (
                type(value) is FunctionType
                and value.__globals__ is module_namespace
                and value not in validated
            ):
                validate_project_function(
                    value,
                    module=module,
                    module_name=module_name,
                    source_path=source_path,
                    compiled_by_location=compiled_by_location,
                )
        for assignment_name, assignment_node in source_assignments[module_name].items():
            if assignment_name.startswith("_") or not assignment_name.isupper():
                continue
            expected_value = source_runtime_value(
                assignment_node,
                module_name=module_name,
                resolving=frozenset({assignment_name}),
            )
            if expected_value is source_value_missing:
                continue
            current_value = module_namespace.get(assignment_name, source_value_missing)
            if not exact_source_value_matches(current_value, expected_value):
                _error(
                    "IMPLEMENTATION_IDENTITY_MISMATCH",
                    f"Loaded project constant differs from trusted Git: "
                    f"{module_name}.{assignment_name}.",
                    layer="validation_authority",
                )


def _direct_platform_values() -> tuple[str, str, str, str, str]:
    """Derive system identity without platform helpers that may spawn commands."""

    uname = getattr(os, "uname", None)
    if callable(uname):
        value = uname()
        machine = str(value.machine)
        release = str(value.release)
        system = str(value.sysname)
        version = str(value.version)
        return machine, f"{system}-{release}-{machine}", release, system, version
    getwindowsversion = getattr(sys, "getwindowsversion", None)
    if callable(getwindowsversion):
        windows = getwindowsversion()
        major = int(windows.major)
        minor = int(windows.minor)
        build = int(windows.build)
        release = "11" if major == 10 and build >= 22000 else str(major)
        version = f"{major}.{minor}.{build}"
        executable = Path(sys.executable).resolve(strict=True)
        raw = executable.read_bytes()
        machine_codes = {
            0x014C: "x86",
            0x01C4: "ARM",
            0x8664: "AMD64",
            0xAA64: "ARM64",
        }
        machine = "unknown"
        if len(raw) >= 0x40 and raw[:2] == b"MZ":
            pe_offset = int.from_bytes(raw[0x3C:0x40], "little")
            if pe_offset + 6 <= len(raw) and raw[pe_offset : pe_offset + 4] == b"PE\0\0":
                machine = machine_codes.get(
                    int.from_bytes(raw[pe_offset + 4 : pe_offset + 6], "little"),
                    "unknown",
                )
        system = "Windows"
        return machine, f"Windows-{release}-{version}-{machine}", release, system, version
    machine = f"{8 * (sys.maxsize.bit_length() + 1) // 8}-bit"
    return machine, f"{sys.platform}-{machine}", sys.platform, sys.platform, sys.version


def _current_runtime() -> tuple[RuntimeProjection, str]:
    executable = _strict_path(Path(sys.executable), require_file=True)
    base = _strict_path(Path(getattr(sys, "_base_executable", sys.executable)), require_file=True)
    interpreter_raw = executable.read_bytes()
    base_raw = base.read_bytes()
    interpreter = FileProjection(
        len(interpreter_raw), str(executable), hashlib.sha256(interpreter_raw).hexdigest()
    )
    base_interpreter = FileProjection(
        len(base_raw), str(base), hashlib.sha256(base_raw).hexdigest()
    )
    interpreter_identity = InterpreterIdentityProjection(
        cache_tag=sys.implementation.cache_tag,
        compiler=platform.python_compiler(),
        executable_path=str(executable),
        executable_sha256=interpreter.sha256,
        implementation=platform.python_implementation(),
        python_version=platform.python_version(),
    )
    interpreter_identity_sha256 = protocol_hash(
        "pytest_interpreter_identity/v1", interpreter_identity.as_dict()
    )
    machine, platform_text, release, system, version = _direct_platform_values()
    platform_identity = PlatformIdentityProjection(
        machine=machine,
        platform=platform_text,
        release=release,
        system=system,
        version=version,
    )
    platform_identity_sha256 = protocol_hash(
        "pytest_platform_identity/v1", platform_identity.as_dict()
    )
    build_number, build_date = platform.python_build()
    runtime = RuntimeProjection(
        base_interpreter=base_interpreter,
        interpreter=interpreter,
        interpreter_identity=interpreter_identity,
        interpreter_identity_sha256=interpreter_identity_sha256,
        platform_identity=platform_identity,
        platform_identity_sha256=platform_identity_sha256,
        python_build_date=build_date,
        python_build_number=build_number,
    )
    return runtime, protocol_hash("validation_evidence_runtime/v1", runtime.as_dict())


def _strict_path(path: Path, *, require_file: bool) -> Path:
    resolved = path.resolve(strict=True)
    if require_file and (not resolved.is_file() or resolved.is_symlink()):
        _error(
            "IMPLEMENTATION_IDENTITY_MISMATCH",
            "Expected a regular file.",
            layer="validation_authority",
        )
    text = str(resolved)
    if unicodedata.normalize("NFC", text) != text:
        _error("IMPLEMENTATION_IDENTITY_MISMATCH", "Path is not NFC.", layer="validation_authority")
    return resolved


def _install_current_production_preparer(
    allocate_production_authority: Callable[..., object] = (
        _allocate_production_authority_capability
    ),
) -> None:
    """Seal exact transitive collaborators before the module exposes fixture support."""

    from research_decision_engine.benchmarks import broader_protocol

    _validate_external_runtime_provenance()
    trusted_module = sys.modules[__name__]
    error_type = P2Stage1Error
    read_attribute = getattr
    instance_of = isinstance
    compile_source = compile
    code_type = CodeType
    trusted_repository = Path(__file__).resolve(strict=True).parents[2]
    trusted_implementation = (
        type(sys.implementation),
        sys.implementation.name,
        sys.implementation.cache_tag,
        tuple(sys.implementation.version),
        sys.implementation.hexversion,
        getattr(sys.implementation, "_multiarch", None),
    )
    trusted_sys_values = (
        sys.executable,
        getattr(sys, "_base_executable", sys.executable),
        sys.flags,
        sys.version,
        sys.version_info,
        trusted_implementation,
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
        sys.base_exec_prefix,
        os.name,
        sys.platform,
        sys.maxsize,
        tuple(sys.path),
    )
    trusted_platform_values = (
        *_direct_platform_values(),
        platform.python_build(),
        platform.python_compiler(),
        platform.python_implementation(),
        platform.python_version(),
    )
    protocol_hashlib: ModuleType = broader_protocol.hashlib  # type: ignore[attr-defined]
    protocol_json: ModuleType = broader_protocol.json  # type: ignore[attr-defined]
    anchor_rows: tuple[tuple[ModuleType, str, object, object | None], ...] = tuple(
        (
            trusted_module,
            name,
            value,
            getattr(value, "__code__", None),
        )
        for name, value in (
            ("_consume_production_preparation", _consume_production_preparation),
            ("_prepare_production_stage1", _prepare_production_stage1),
            ("_compiled_qualified_function", _compiled_qualified_function),
            ("_validate_external_runtime_provenance", _validate_external_runtime_provenance),
            ("_TRUSTED_COMPILE", _TRUSTED_COMPILE),
            ("_TRUSTED_GETATTR", _TRUSTED_GETATTR),
            ("_TRUSTED_ISINSTANCE", _TRUSTED_ISINSTANCE),
            ("_TRUSTED_VARS", _TRUSTED_VARS),
            ("_TRUSTED_LEN", _TRUSTED_LEN),
            ("_TRUSTED_OPEN", _TRUSTED_OPEN),
            ("_TRUSTED_BUILTINS", _TRUSTED_BUILTINS),
            ("_TRUSTED_LRU_WRAPPER_TYPE", _TRUSTED_LRU_WRAPPER_TYPE),
            ("_validate_runtime_bootstrap", _validate_runtime_bootstrap),
            ("_opaque_runtime_callable", _opaque_runtime_callable),
            (
                "_seal_production_component_callable",
                _seal_production_component_callable,
            ),
            (
                "_register_production_component_callable",
                _register_production_component_callable,
            ),
            (
                "_production_component_callable_is_registered",
                _production_component_callable_is_registered,
            ),
            (
                "_validate_production_component_sources",
                _validate_production_component_sources,
            ),
            ("_make_transitive_integrity_validator", _make_transitive_integrity_validator),
            ("_validate_run_id", _validate_run_id),
            ("_single_assignment_publish", _single_assignment_publish),
            ("_current_layer0_context", _current_layer0_context),
            ("_reserve_production_validation_run", _reserve_production_validation_run),
            ("_create_owned_control_directory", _create_owned_control_directory),
            ("_six_plan_set", _six_plan_set),
            ("_prepare_binding_record", _prepare_binding_record),
            ("_production_validation_run_id", _production_validation_run_id),
            ("_require_production_run", _require_production_run),
            ("_publish_production_binding", _publish_production_binding),
            ("_record_production_resources", _record_production_resources),
            ("_begin_production_physical_resource", _begin_production_physical_resource),
            (
                "_transition_production_physical_resource",
                _transition_production_physical_resource,
            ),
            (
                "_allocate_production_executor_implementation",
                _allocate_production_executor_implementation,
            ),
            (
                "_confirm_production_executor_implementation",
                _confirm_production_executor_implementation,
            ),
            ("_allocate_production_plan_capability", _allocate_production_plan_capability),
            ("_record_production_plan_draft", _record_production_plan_draft),
            (
                "_allocate_production_authority_capability",
                _allocate_production_authority_capability,
            ),
            (
                "_record_production_unpublished_binding",
                _record_production_unpublished_binding,
            ),
            ("_abort_production_preparation", _abort_production_preparation),
            ("_remove_empty_owned_control_directory", _remove_empty_owned_control_directory),
            ("_git_identity_error", _git_identity_error),
            ("_git_sha1", _git_sha1),
            ("_git_object_id", _git_object_id),
            ("_resolve_git_directory", _resolve_git_directory),
            ("_resolve_git_common_directory", _resolve_git_common_directory),
            ("_trusted_bootstrap_manifest_path", _trusted_bootstrap_manifest_path),
            ("_trusted_bootstrap_manifest_bytes", _trusted_bootstrap_manifest_bytes),
            ("_validate_trusted_bootstrap_manifest", _validate_trusted_bootstrap_manifest),
            ("_valid_git_ref_name", _valid_git_ref_name),
            ("_read_git_head", _read_git_head),
            ("_read_loose_git_object", _read_loose_git_object),
            ("_commit_root_tree", _commit_root_tree),
            ("_parse_git_index", _parse_git_index),
            ("_git_tree_from_index", _git_tree_from_index),
            ("_implementation_path_is_scoped", _implementation_path_is_scoped),
            ("_read_indexed_worktree_blob", _read_indexed_worktree_blob),
            ("_untracked_implementation_paths", _untracked_implementation_paths),
            ("_current_git_snapshot", _current_git_snapshot),
            ("_validate_loaded_implementation_bytes", _validate_loaded_implementation_bytes),
            ("_direct_platform_values", _direct_platform_values),
            ("_current_runtime", _current_runtime),
            ("_strict_path", _strict_path),
            ("_validate_layer0_context", _validate_layer0_context),
            ("_validate_plan_context", _validate_plan_context),
            ("_validate_plan_fingerprint", _validate_plan_fingerprint),
            ("_recompute_plan", _recompute_plan),
            ("_authority_projection", _authority_projection),
            ("validation_authority_id_from_projection", validation_authority_id_from_projection),
            ("callable_projection", callable_projection),
            ("issuer_projection", issuer_projection),
            ("protocol_hash", protocol_hash),
            ("repository_root", repository_root),
            ("replace", replace),
            ("_OwnedControlDirectory", _OwnedControlDirectory),
            ("_GitIndexEntry", _GitIndexEntry),
            ("_GitSnapshot", _GitSnapshot),
            ("_SessionResources", _SessionResources),
            ("_PendingSessionResources", _PendingSessionResources),
            ("_PreparationRecord", _PreparationRecord),
            ("_ProductionRunRecord", _ProductionRunRecord),
            ("_ProductionRegistrySummary", _ProductionRegistrySummary),
            ("_ProductionComponentIssuers", _ProductionComponentIssuers),
            ("_ProductionPreparationCollaborators", _ProductionPreparationCollaborators),
            ("_PlanDraft", _PlanDraft),
            ("_SixPlanSet", _SixPlanSet),
            ("_BindingRecord", _BindingRecord),
            ("_ProductionPreparationCapability", _ProductionPreparationCapability),
            ("_ProductionSessionToken", _ProductionSessionToken),
            ("ValidationRun", ValidationRun),
            ("ValidationAuthority", ValidationAuthority),
            ("ValidationAuthorityProjection", ValidationAuthorityProjection),
            ("ImplementationProjection", ImplementationProjection),
            ("RuntimeProjection", RuntimeProjection),
            ("Layer0Context", Layer0Context),
            ("CallableProjection", CallableProjection),
            ("IssuerProjection", IssuerProjection),
            ("FileProjection", FileProjection),
            ("InterpreterIdentityProjection", InterpreterIdentityProjection),
            ("PlatformIdentityProjection", PlatformIdentityProjection),
            ("P2Stage1Error", P2Stage1Error),
            ("_error", _error),
            ("Path", Path),
            ("hashlib", hashlib),
            ("os", os),
            ("platform", platform),
            ("re", re),
            ("sys", sys),
            ("tempfile", tempfile),
            ("unicodedata", unicodedata),
            ("zlib", zlib),
            ("EVIDENCE_CONTRACT_CHECKPOINT", EVIDENCE_CONTRACT_CHECKPOINT),
            ("PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
            ("STUDY_ID", STUDY_ID),
            ("PERMITTED_FINAL_EVIDENCE_FILENAMES", PERMITTED_FINAL_EVIDENCE_FILENAMES),
        )
    ) + _runtime_cast(
        (
            (hashlib, "sha1", hashlib.sha1, getattr(hashlib.sha1, "__code__", None)),
            (hashlib, "sha256", hashlib.sha256, getattr(hashlib.sha256, "__code__", None)),
            (platform, "python_build", platform.python_build, platform.python_build.__code__),
            (
                platform,
                "python_compiler",
                platform.python_compiler,
                platform.python_compiler.__code__,
            ),
            (
                platform,
                "python_implementation",
                platform.python_implementation,
                platform.python_implementation.__code__,
            ),
            (platform, "python_version", platform.python_version, platform.python_version.__code__),
            (re, "fullmatch", re.fullmatch, re.fullmatch.__code__),
            (tempfile, "gettempdir", tempfile.gettempdir, tempfile.gettempdir.__code__),
            (tempfile, "mkdtemp", tempfile.mkdtemp, tempfile.mkdtemp.__code__),
            (unicodedata, "normalize", unicodedata.normalize, None),
            (zlib, "decompress", zlib.decompress, None),
            (
                broader_protocol,
                "canonical_json_bytes",
                broader_protocol.canonical_json_bytes,
                broader_protocol.canonical_json_bytes.__code__,
            ),
            (
                broader_protocol,
                "protocol_hash",
                broader_protocol.protocol_hash,
                broader_protocol.protocol_hash.__code__,
            ),
            (
                broader_protocol,
                "repository_root",
                broader_protocol.repository_root,
                broader_protocol.repository_root.__code__,
            ),
            (protocol_hashlib, "sha256", protocol_hashlib.sha256, None),
            (protocol_json, "dumps", protocol_json.dumps, None),
        )
    )
    central_class_rows = tuple(
        (
            candidate,
            frozenset(vars(candidate)),
            tuple(sorted(vars(candidate).items())),
        )
        for candidate in (
            _ProductionComponentIssuers,
            _ProductionPreparationCollaborators,
            _OwnedControlDirectory,
            _GitIndexEntry,
            _GitSnapshot,
            _SessionResources,
            _PendingSessionResources,
            _PreparationRecord,
            _ProductionRunRecord,
            _ProductionRegistrySummary,
            _PlanDraft,
            _SixPlanSet,
            _BindingRecord,
            ValidationAuthorityProjection,
            ImplementationProjection,
            RuntimeProjection,
            Layer0Context,
            CallableProjection,
            IssuerProjection,
            FileProjection,
            InterpreterIdentityProjection,
            PlatformIdentityProjection,
        )
    )

    def validate() -> None:
        for candidate, expected_names, expected_bindings in central_class_rows:
            current_class_namespace = vars(candidate)
            if frozenset(current_class_namespace) != expected_names or any(
                current_class_namespace.get(name) is not expected
                for name, expected in expected_bindings
            ):
                raise error_type(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted production class behavior changed: "
                    f"{candidate.__module__}.{candidate.__qualname__}.",
                    layer="validation_authority",
                )
        compiled_modules: dict[Path, dict[str, list[CodeType]]] = {}
        for module, name, expected, code in anchor_rows:
            current_anchor = getattr(module, name, None)
            if current_anchor is not expected or (
                code is not None and getattr(current_anchor, "__code__", None) is not code
            ):
                raise error_type(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted production preparation dependency was replaced: "
                    f"{module.__name__}.{name}.",
                    layer="validation_authority",
                )
            if code is None or read_attribute(expected, "__module__", None) != module.__name__:
                continue
            source_name = read_attribute(module, "__file__", None)
            if not instance_of(source_name, str):
                continue
            source_path = Path(_runtime_cast(source_name))
            if source_path.suffix == ".pyc":
                source_path = source_path.with_suffix(".py")
            source_path = source_path.resolve(strict=True)
            try:
                source_path.relative_to(trusted_repository)
            except ValueError:
                continue
            compiled_by_qualname = compiled_modules.get(source_path)
            if compiled_by_qualname is None:
                module_code = compile_source(
                    source_path.read_bytes(),
                    str(source_path),
                    "exec",
                    dont_inherit=True,
                    optimize=sys.flags.optimize,
                )
                compiled_by_qualname = {}
                pending: list[CodeType] = [module_code]
                while pending:
                    parent = pending.pop()
                    for value in parent.co_consts:
                        if instance_of(value, code_type):
                            nested_code = _runtime_cast(value)
                            pending.append(nested_code)
                            compiled_by_qualname.setdefault(nested_code.co_qualname, []).append(
                                nested_code
                            )
                compiled_modules[source_path] = compiled_by_qualname
            expected_qualname = _runtime_cast(read_attribute(expected, "__qualname__"))
            matches = compiled_by_qualname.get(expected_qualname, [])
            if len(matches) != 1 or matches[0] != code:
                raise error_type(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Live production code differs from source bytes: {module.__name__}.{name}.",
                    layer="validation_authority",
                )
        current_sys_values = (
            sys.executable,
            read_attribute(sys, "_base_executable", sys.executable),
            sys.flags,
            sys.version,
            sys.version_info,
            (
                type(sys.implementation),
                sys.implementation.name,
                sys.implementation.cache_tag,
                tuple(sys.implementation.version),
                sys.implementation.hexversion,
                read_attribute(sys.implementation, "_multiarch", None),
            ),
            sys.prefix,
            sys.base_prefix,
            sys.exec_prefix,
            sys.base_exec_prefix,
            os.name,
            sys.platform,
            sys.maxsize,
            tuple(sys.path),
        )
        current_platform_values = (
            *_direct_platform_values(),
            platform.python_build(),
            platform.python_compiler(),
            platform.python_implementation(),
            platform.python_version(),
        )
        if (
            current_sys_values != trusted_sys_values
            or current_platform_values != trusted_platform_values
        ):
            raise error_type(
                "RUNTIME_IDENTITY_MISMATCH",
                "Trusted runtime changed after production sealing.",
                layer="validation_authority",
            )

    collaborators = _ProductionPreparationCollaborators(
        consume=_consume_production_preparation,
        derive_context=_current_layer0_context,
        reserve_run=_reserve_production_validation_run,
        create_control_directory=_create_owned_control_directory,
        begin_physical_resource=_begin_production_physical_resource,
        transition_physical_resource=_transition_production_physical_resource,
        allocate_executor_implementation=_allocate_production_executor_implementation,
        confirm_executor_implementation=_confirm_production_executor_implementation,
        six_plan_set=_six_plan_set,
        prepare_binding=_prepare_binding_record,
        allocate_authority=allocate_production_authority,
        record_unpublished_binding=_record_production_unpublished_binding,
        run_id=_production_validation_run_id,
        require_run=_require_production_run,
        publish_binding=_publish_production_binding,
        record_resources=_record_production_resources,
        abort=_abort_production_preparation,
        remove_control_directory=_remove_empty_owned_control_directory,
        replace_record=replace,
        resources_type=_SessionResources,
        authority_type=_runtime_cast(ValidationAuthority),
        error_type=P2Stage1Error,
        validate=validate,
    )
    _seal_production_preparer(_prepare_production_stage1, collaborators)


_install_current_production_preparer()
del _install_current_production_preparer


def _fixture_layer0_context(*, implementation_seed: str = "stage1-fixture") -> Layer0Context:
    """Build deterministic non-production Layer 0 for focused Stage-1 tests."""

    def digest(label: str) -> str:
        return hashlib.sha256(f"{implementation_seed}:{label}".encode()).hexdigest()

    implementation = ImplementationProjection(
        dependency_lock_sha256=digest("lock"),
        implementation_commit="1" * 40,
        implementation_diff_sha256=digest("diff"),
        implementation_tree_sha256=digest("tree"),
        source_bundle_sha256=digest("source"),
        test_bundle_sha256=digest("tests"),
    )
    file = FileProjection(1, str(repository_root().resolve()), digest("file"))
    interpreter_identity = InterpreterIdentityProjection(
        cache_tag="cpython-312",
        compiler="fixture",
        executable_path=file.path,
        executable_sha256=file.sha256,
        implementation="CPython",
        python_version="3.12.0",
    )
    platform_identity = PlatformIdentityProjection(
        machine="fixture",
        platform="fixture",
        release="fixture",
        system="fixture",
        version="fixture",
    )
    runtime = RuntimeProjection(
        base_interpreter=file,
        interpreter=file,
        interpreter_identity=interpreter_identity,
        interpreter_identity_sha256=protocol_hash(
            "pytest_interpreter_identity/v1", interpreter_identity.as_dict()
        ),
        platform_identity=platform_identity,
        platform_identity_sha256=protocol_hash(
            "pytest_platform_identity/v1", platform_identity.as_dict()
        ),
        python_build_date="fixture",
        python_build_number="fixture",
    )
    runtime_identity = protocol_hash("validation_evidence_runtime/v1", runtime.as_dict())
    dummy_callable = CallableProjection(
        bytecode_sha256=digest("bytecode"),
        callable_type="builtins.function",
        module_name="fixture",
        qualname="fixture",
        source=file,
    )
    issuer_specs = (
        ("validation_authority", "fixture.validation_authority"),
        ("pytest_plan", "fixture.pytest_plan"),
        ("oracle_plan", "fixture.oracle_plan"),
        ("execution_specification", "fixture.execution_specification"),
    )
    issuers = [
        issuer_projection(
            context_implementation=implementation,
            runtime=runtime,
            runtime_identity=runtime_identity,
            role=role,  # type: ignore[arg-type]
            entry_point=entry_point,
            trust_domain="fixture",
        )
        for role, entry_point in issuer_specs
    ]
    generator_projection = {
        "callable": dummy_callable.as_dict(),
        "callable_identity": protocol_hash(
            "validation_evidence_callable/v1", dummy_callable.as_dict()
        ),
        "entry_point": "fixture.validation_generator",
        "evidence_contract_checkpoint": EVIDENCE_CONTRACT_CHECKPOINT,
        "implementation": implementation.as_dict(),
        "protocol_checkpoint": PROTOCOL_CHECKPOINT,
        "runtime": runtime.as_dict(),
        "runtime_identity": runtime_identity,
        "schema_version": "broader-replication-validation-evidence-generator/v1",
    }
    return Layer0Context(
        implementation=implementation,
        runtime=runtime,
        runtime_identity=runtime_identity,
        validation_authority_issuer=issuers[0][0],
        validation_authority_issuer_identity=issuers[0][1],
        pytest_plan_issuer=issuers[1][0],
        pytest_plan_issuer_identity=issuers[1][1],
        oracle_plan_issuer=issuers[2][0],
        oracle_plan_issuer_identity=issuers[2][1],
        execution_specification_issuer=issuers[3][0],
        execution_specification_issuer_identity=issuers[3][1],
        evidence_generator=dummy_callable,
        evidence_generator_entry_point="fixture.validation_generator",
        evidence_generator_identity=protocol_hash(
            "validation_evidence_generator/v1", generator_projection
        ),
    )


def _issue_fixture_validation_run() -> _FixtureValidationRun:
    for _ in range(128):
        validation_run_identity = secrets.token_bytes(32).hex()
        _validate_run_id(validation_run_identity)
        with _FIXTURE_REGISTRY_LOCK:
            if validation_run_identity in _FIXTURE_RUN_IDS:
                continue
            capability: _FixtureValidationRun = _runtime_cast(
                object.__new__(_runtime_cast(_FixtureValidationRun))
            )
            _FIXTURE_RUN_IDS.add(validation_run_identity)
            _FIXTURE_RUN_RECORDS[capability] = _FixtureRunRecord(
                capability=capability,
                validation_run_id=validation_run_identity,
                state="reserved",
            )
            return capability
    _error(
        "VALIDATION_RUN_COLLISION",
        "Fixture validation-run issuance exhausted collision retries.",
        layer="validation_run_issuance",
    )


def _invalidate_plan(capability: object) -> None:
    _, _, domain = _require_plan(capability)
    if domain != "fixture":
        _error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "Production plans cannot be invalidated through fixture support.",
            layer="live_issued_plan_binding",
        )
    with _FIXTURE_REGISTRY_LOCK:
        record = _FIXTURE_PLAN_RECORDS.get(capability)
        if record is None:
            _error(
                "ISSUED_PLAN_CAPABILITY_INVALID",
                "Exact fixture plan capability required.",
                layer="live_issued_plan_binding",
            )
        if any(
            authority.validation_run is record.draft.validation_run and authority.active
            for authority in _FIXTURE_AUTHORITY_RECORDS.values()
        ):
            _error(
                "ISSUED_PLAN_AUTHORITY_MISMATCH",
                "An individually bound plan cannot be invalidated outside its authority.",
                layer="live_issued_plan_binding",
            )
        _FIXTURE_PLAN_RECORDS[capability] = replace(record, active=False)


def _reset_fixture_registries() -> None:
    """Remove only fixture records between focused tests; production is untouched."""

    with _FIXTURE_REGISTRY_LOCK:
        _FIXTURE_RUN_RECORDS.clear()
        _FIXTURE_PLAN_RECORDS.clear()
        _FIXTURE_AUTHORITY_RECORDS.clear()
        _FIXTURE_RUN_IDS.clear()
    from research_decision_engine.benchmarks import broader_execution

    broader_execution._reset_fixture_executor_implementations()


def _fixture_registry_counts() -> tuple[int, int, int]:
    with _FIXTURE_REGISTRY_LOCK:
        return (
            len(_FIXTURE_RUN_RECORDS),
            len(_FIXTURE_PLAN_RECORDS),
            len(_FIXTURE_AUTHORITY_RECORDS),
        )


__all__ = [
    "CallableProjection",
    "EVIDENCE_CONTRACT_CHECKPOINT",
    "FileProjection",
    "ImplementationProjection",
    "InterpreterIdentityProjection",
    "IssuerProjection",
    "Layer0Context",
    "P2Stage1Error",
    "PERMITTED_FINAL_EVIDENCE_FILENAMES",
    "PlatformIdentityProjection",
    "RuntimeProjection",
    "STUDY_ID",
    "ValidationAuthority",
    "ValidationAuthorityProjection",
    "ValidationRun",
    "assert_stage1_plan_not_executable",
    "callable_projection",
    "plan_binding_state",
    "plan_persistent_id",
    "plan_projection",
    "validation_authority_id",
    "validation_authority_id_from_projection",
    "validation_authority_projection",
    "validation_run_id",
]
