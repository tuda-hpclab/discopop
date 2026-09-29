# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Accept the arguments a model actually sends, not only the ones it should.

Every tool here declares a JSON Schema, and the MCP SDK validates against it
before the handler is reached. That validation is strict about types, and a good
number of models -- especially smaller ones, and anything whose tool calling is
templated rather than natively typed -- emit *every* argument as a string::

    run_auto_tuning(apply="true")            -> 'true' is not of type 'boolean'
    gather_data(hotspot_config_names='["a"]') -> '["a"]' is not of type 'array'
    get_data_dependencies(start_line="130")   -> '130' is not of type 'integer'

The call then fails before any DiscoPoP code runs, and the model has no way to
tell a type error from the tool being unavailable: in one measured benchmark run
every single ``run_auto_tuning(apply=true)`` was rejected this way, so the tuner
never applied anything, the model fell back to hand-picking patches, and the
report showed that as the model's own decision.

Rejecting the call is the wrong trade. The string ``"true"`` in a field declared
boolean has exactly one meaning; refusing it buys no safety and costs the whole
interaction. So arguments are coerced *towards the declared schema* before they
are validated:

* only where the schema declares a type, and only when the value does not
  already have it -- a well-typed call passes through untouched;
* never inventing a value: a string that is not a recognisable boolean, number,
  array or object is left exactly as it is and fails validation as before, with
  the message it would have had;
* per declared type, never guessed from the value, so a string stays a string
  even when it looks like a number.

What remains rejected is what is genuinely ambiguous or wrong, and the error for
it now says what was received and what was expected, which the SDK's message
does not.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Strings a boolean field accepts, beyond real booleans. Deliberately short: a
# model writes what it would write in JSON or in Python, and anything more
# creative is better rejected than guessed at.
_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0"})


def _declared_types(schema: Dict[str, Any]) -> List[str]:
    """The JSON Schema types a value may have, as a list.

    ``{"type": "integer"}`` and ``{"type": ["integer", "null"]}`` are both
    common, and a field described only by ``anyOf`` has to be looked into.
    """
    declared = schema.get("type")
    types: List[str] = []
    if isinstance(declared, str):
        types.append(declared)
    elif isinstance(declared, list):
        types.extend(t for t in declared if isinstance(t, str))
    for alternative in schema.get("anyOf") or schema.get("oneOf") or []:
        if isinstance(alternative, dict):
            types.extend(_declared_types(alternative))
    return types


def _matches(value: Any, declared: str) -> bool:
    """Whether `value` already has the declared type."""
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "string":
        return isinstance(value, str)
    if declared == "array":
        return isinstance(value, list)
    if declared == "object":
        return isinstance(value, dict)
    if declared == "null":
        return value is None
    return False


def _to_boolean(value: Any) -> Tuple[bool, Any]:
    if isinstance(value, bool):
        return True, value
    if isinstance(value, int):
        return (True, bool(value)) if value in (0, 1) else (False, value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True, True
        if text in _FALSE:
            return True, False
    return False, value


def _to_number(value: Any, integral: bool) -> Tuple[bool, Any]:
    if isinstance(value, bool):
        return False, value  # True is not 1 here; a boolean in a number field is a mistake
    if isinstance(value, str):
        text = value.strip()
        try:
            number: Any = int(text) if integral else float(text)
        except ValueError:
            if not integral:
                return False, value
            # "4.0" in an integer field is still unambiguous.
            try:
                as_float = float(text)
            except ValueError:
                return False, value
            if as_float.is_integer():
                return True, int(as_float)
            return False, value
        return True, number
    if integral and isinstance(value, float) and value.is_integer():
        return True, int(value)
    if not integral and isinstance(value, int):
        return True, float(value)
    return False, value


def _to_array(value: Any, schema: Dict[str, Any]) -> Tuple[bool, Any]:
    """A list out of what was sent, without inventing elements.

    Three shapes are accepted, in order of how unambiguous they are: a JSON array
    in a string (what a model writes when it serializes its own argument), a
    comma separated list (what it writes when it is thinking in prose), and a
    lone scalar for a one-element list. The scalar case is last and applies only
    to a string that is neither -- wrapping is what the caller meant if anything,
    and an element list that rejects it still rejects it afterwards.
    """
    if isinstance(value, list):
        return True, value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                return False, value
            if isinstance(parsed, list):
                return True, parsed
            return False, value
        if not text:
            return True, []
        items = schema.get("items")
        item_types = _declared_types(items) if isinstance(items, dict) else []
        if "," in text and (not item_types or "string" in item_types):
            return True, [part.strip() for part in text.split(",") if part.strip()]
        return True, [value]
    return False, value


def _to_object(value: Any) -> Tuple[bool, Any]:
    if isinstance(value, dict):
        return True, value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except ValueError:
                return False, value
            if isinstance(parsed, dict):
                return True, parsed
    return False, value


def coerce_value(value: Any, schema: Dict[str, Any]) -> Tuple[bool, Any]:
    """Move `value` towards the type `schema` declares.

    Returns ``(changed, value)``. Unchanged covers both "already right" and
    "cannot be helped": either way the caller passes it on to validation, which
    is the one place that decides whether a call is acceptable.
    """
    if not isinstance(schema, dict):
        return False, value
    declared = _declared_types(schema)
    if not declared or any(_matches(value, t) for t in declared):
        return False, value

    for candidate in declared:
        if candidate == "boolean":
            changed, coerced = _to_boolean(value)
        elif candidate in ("integer", "number"):
            changed, coerced = _to_number(value, integral=(candidate == "integer"))
        elif candidate == "array":
            changed, coerced = _to_array(value, schema)
        elif candidate == "object":
            changed, coerced = _to_object(value)
        elif candidate == "string":
            # A number or boolean where a string was asked for is unambiguous,
            # but JSON's spelling of it is not Python's.
            if isinstance(value, bool):
                changed, coerced = True, "true" if value else "false"
            elif isinstance(value, (int, float)):
                changed, coerced = True, str(value)
            else:
                changed, coerced = False, value
        else:
            changed, coerced = False, value
        if changed:
            return True, coerced
    return False, value


def coerce_arguments(
    arguments: Optional[Dict[str, Any]], input_schema: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Coerce a whole argument dict against a tool's ``inputSchema``.

    Returns the (possibly new) arguments and a description of what was changed,
    keyed by argument name -- which is logged, because a call that only worked
    because of this is worth being able to see in a transcript.
    """
    arguments = dict(arguments or {})
    properties = (input_schema or {}).get("properties") or {}
    changes: Dict[str, str] = {}
    for name, value in list(arguments.items()):
        schema = properties.get(name)
        if not isinstance(schema, dict):
            continue
        changed, coerced = coerce_value(value, schema)
        if changed:
            arguments[name] = coerced
            changes[name] = f"{value!r} -> {coerced!r}"
    return arguments, changes


def validation_error(name: str, arguments: Dict[str, Any], input_schema: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why `arguments` still do not satisfy the schema, in a usable sentence.

    The SDK's own message names the offending value but not the argument it
    belongs to nor the type expected, which is exactly what a caller needs in
    order to fix the call. Returns None when the arguments are acceptable, and
    None as well when jsonschema is unavailable -- a missing optional dependency
    must not turn every call into a failure.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema ships with the SDK
        return None
    if not input_schema:
        return None
    try:
        jsonschema.validate(instance=arguments, schema=input_schema)
    except jsonschema.ValidationError as error:
        path = list(error.absolute_path)
        where = ".".join(str(part) for part in path)
        detail = f"{name}: invalid value for '{where}': {error.message}" if where else f"{name}: {error.message}"
        # Only a type error gets the expected type appended; on a missing
        # required property `error.schema` is the *object's* schema, and naming
        # its type there would read as "expected object" for a wrong boolean.
        if error.validator == "type" and isinstance(error.schema, dict):
            expected = error.schema.get("type")
            if expected:
                detail += f" (expected {expected}; a JSON value of that type, " f"not a string containing one)"
        return detail
    except Exception:  # pragma: no cover - a malformed schema is not the caller's fault
        return None
    return None
