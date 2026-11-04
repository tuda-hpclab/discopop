# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The logic behind the editor of ``llm_config.json``, without a toolkit.

The dialog reads its widgets into text (a ``ConnectionForm`` resp. the values of a backend section) and this module
turns that text into the dict stored in the configuration, and back for display. Empty values are dropped: an empty
field means "inherit", and writing it would freeze today's default into the file. Credentials are not handled here,
as nowhere else in the configuration.
"""

from dataclasses import dataclass, field
import shlex
from typing import Any, Dict, Iterable, List, Optional, Sequence

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.llm_backends import RESERVED_KEYS, FieldSpec

BOOL_TRUE = "yes"
BOOL_FALSE = "no"


@dataclass
class ConnectionForm:
    """The values of the Connections editor, all as the text of their widgets."""

    backend: str = ""
    model: str = ""
    description: str = ""
    prompts: str = ""
    retries: str = ""
    timeout: str = ""
    extra_args: str = ""
    env: str = ""
    options: Dict[str, str] = field(default_factory=dict)


# ---- text <-> value -------------------------------------------------------------


def parse_extra_args(text: str) -> List[str]:
    """The arguments in ``text``, split like a shell does (quotes group); ValueError for an unbalanced quote."""
    try:
        return shlex.split(text)
    except ValueError as error:
        raise ValueError("The extra arguments are not valid: " + str(error))


def format_extra_args(args: Optional[Iterable[Any]]) -> str:
    return " ".join(shlex.quote(str(a)) for a in (args or []))


def parse_env(text: str) -> Dict[str, str]:
    """``KEY=VALUE`` lines as a dict; blank lines and ``#`` comments are skipped, ValueError for anything else."""
    env: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("An environment line is not KEY=VALUE: " + line)
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("An environment line has no name: " + line)
        env[key] = value.strip()
    return env


def format_env(env: Optional[Dict[str, Any]]) -> str:
    return "".join(str(key) + "=" + str(value) + "\n" for key, value in sorted((env or {}).items()))


def _parse_number(text: str, label: str, kind: type, minimum: float) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        number = kind(text)
    except ValueError:
        raise ValueError(label + " must be a number (got '" + text + "').")
    if number < minimum:
        raise ValueError(label + " must be at least " + str(minimum if kind is float else int(minimum)) + ".")
    return number


# ---- backend specific options ---------------------------------------------------


def option_to_text(spec: FieldSpec, value: Any) -> str:
    """How a stored option shows in its widget; an unset option is the empty text (inherit)."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return BOOL_TRUE if value else BOOL_FALSE
    return str(value)


def options_to_form(specs: Sequence[FieldSpec], stored: Dict[str, Any]) -> Dict[str, str]:
    return {spec.key: option_to_text(spec, stored.get(spec.key)) for spec in specs}


def options_from_form(
    specs: Sequence[FieldSpec], values: Dict[str, str], preserved: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """The options to store: empty ones dropped, booleans as booleans, other text stripped.

    ``preserved`` are stored keys the backend no longer declares; they stay, as they do in
    ``llm_backends.resolve_options``, so a setting is not lost silently on the next save.
    """
    out: Dict[str, Any] = {}
    declared = {spec.key for spec in specs}
    for key, value in (preserved or {}).items():
        if key not in declared:
            out[key] = value
    for spec in specs:
        text = str(values.get(spec.key, "")).strip()
        if not text:
            continue
        out[spec.key] = (text.lower() == BOOL_TRUE) if spec.kind == "bool" else text
    return out


def undeclared_options(specs: Sequence[FieldSpec], stored: Dict[str, Any]) -> Dict[str, Any]:
    declared = {spec.key for spec in specs}
    return {key: value for key, value in stored.items() if key not in declared}


# ---- connections ----------------------------------------------------------------


def connection_to_form(
    connection: Dict[str, Any], specs: Sequence[FieldSpec], stored_options: Dict[str, Any]
) -> ConnectionForm:
    """The form of a stored connection; ``stored_options`` come from ``llm_backends.stored_options``."""

    def text(key: str) -> str:
        value = connection.get(key)
        return "" if value is None else str(value)

    return ConnectionForm(
        backend=text("backend"),
        model=text("model"),
        description=text("description"),
        prompts=text("prompts"),
        retries=text("retries"),
        timeout=text("timeout"),
        extra_args=format_extra_args(connection.get("extra_args")),
        env=format_env(connection.get("env")),
        options=options_to_form(specs, stored_options),
    )


def connection_from_form(
    form: ConnectionForm,
    specs: Sequence[FieldSpec],
    base: Optional[Dict[str, Any]] = None,
    preserved_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The dict stored for a connection; ValueError (message for the user) when a value is invalid.

    ``base`` is the connection as stored before: keys the form does not edit are kept. Every key the form edits is
    rewritten (or removed when empty), and the settings of every backend's declared fields are removed from the top
    level, since they live under ``backend_options`` now.
    """
    result: Dict[str, Any] = dict(base or {})
    for spec_key in list(result):
        if spec_key not in RESERVED_KEYS and _is_declared_somewhere(spec_key):
            del result[spec_key]

    strings = {
        "backend": form.backend.strip(),
        "model": form.model.strip(),
        "description": form.description.strip(),
    }
    numbers = {
        "prompts": _parse_number(form.prompts, "Prompts", int, 1),
        "retries": _parse_number(form.retries, "Retries", int, 0),
        "timeout": _parse_number(form.timeout, "Timeout", float, 0.001),
    }
    if numbers["timeout"] is not None and numbers["timeout"] == int(numbers["timeout"]):
        numbers["timeout"] = int(numbers["timeout"])
    extra_args = parse_extra_args(form.extra_args)
    env = parse_env(form.env)
    options = options_from_form(specs, form.options, preserved_options)

    for key, value in {**strings, **numbers, "extra_args": extra_args, "env": env, "backend_options": options}.items():
        if value is None or value == "" or value == [] or value == {}:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def _is_declared_somewhere(key: str) -> bool:
    return any(spec.key == key for name in llm_backends.available_backends() for spec in llm_backends.fields_of(name))


# ---- backend sections -----------------------------------------------------------


@dataclass
class BackendForm:
    """The values of one section of the Backends editor."""

    binary: str = ""
    extra_args: str = ""
    env: str = ""
    options: Dict[str, str] = field(default_factory=dict)


def backend_to_form(section: Dict[str, Any], specs: Sequence[FieldSpec]) -> BackendForm:
    return BackendForm(
        binary=str(section.get("binary") or ""),
        extra_args=format_extra_args(section.get("extra_args")),
        env=format_env(section.get("env")),
        options=options_to_form(specs, section.get("options") or {}),
    )


def backend_from_form(
    form: BackendForm, specs: Sequence[FieldSpec], base: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """The section stored for a backend (empty when nothing is configured); ValueError for an invalid value."""
    result: Dict[str, Any] = dict(base or {})
    preserved = undeclared_options(specs, dict(result.get("options") or {}))
    values: Dict[str, Any] = {
        "binary": form.binary.strip(),
        "extra_args": parse_extra_args(form.extra_args),
        "env": parse_env(form.env),
        "options": options_from_form(specs, form.options, preserved),
    }
    for key, value in values.items():
        if value in ("", [], {}):
            result.pop(key, None)
        else:
            result[key] = value
    return result


# ---- names ----------------------------------------------------------------------


def validate_connection_name(name: str, taken: Iterable[str]) -> Optional[str]:
    """None for a usable name, otherwise what is wrong with it."""
    name = name.strip()
    if not name:
        return "The name must not be empty."
    if name in set(taken):
        return "There is already a connection named '" + name + "'."
    if name in RESERVED_KEYS:
        return "'" + name + "' is a reserved word and cannot be a connection name."
    return None
