# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The argument shapes a real model sent, and what has to happen to them.

Every case in :class:`TestObservedCalls` is taken verbatim from a benchmark run
whose ``events.jsonl`` recorded the call and the rejection it got; they are the
reason this module exists, so they are the tests that guard it.
"""

import unittest

from mcp_server.argument_coercion import coerce_arguments, coerce_value, validation_error

_SCHEMA = {
    "type": "object",
    "properties": {
        "project_path": {"type": "string"},
        "config_name": {"type": "string"},
        "apply": {"type": "boolean"},
        "timeout_seconds": {"type": "number"},
        "algorithm": {"type": "integer"},
        "hotspot_config_names": {"type": "array", "items": {"type": "string"}},
        "suggestion_ids": {"type": "array", "items": {"type": "string"}},
        "options": {"type": "object"},
        "limit": {"type": ["integer", "null"]},
    },
    "required": ["project_path"],
}


class TestObservedCalls(unittest.TestCase):
    """The calls that failed in the field now reach the handler."""

    def _coerced(self, arguments):
        return coerce_arguments(arguments, _SCHEMA)[0]

    def test_apply_as_python_bool_literal(self):
        self.assertEqual(self._coerced({"apply": "True"})["apply"], True)

    def test_apply_as_json_bool_literal(self):
        self.assertEqual(self._coerced({"apply": "true"})["apply"], True)

    def test_hotspot_config_names_as_json_string(self):
        self.assertEqual(
            self._coerced({"hotspot_config_names": '["1024", "8192"]'})["hotspot_config_names"],
            ["1024", "8192"],
        )

    def test_suggestion_ids_as_json_string(self):
        self.assertEqual(self._coerced({"suggestion_ids": '["63"]'})["suggestion_ids"], ["63"])

    def test_line_numbers_as_strings(self):
        schema = {"type": "object", "properties": {"start_line": {"type": "integer"}}}
        self.assertEqual(coerce_arguments({"start_line": "130"}, schema)[0]["start_line"], 130)

    def test_every_observed_call_validates(self):
        for arguments in (
            {"project_path": "/p", "config_name": "1024", "apply": "True"},
            {"project_path": "/p", "config_name": "1024", "apply": "true"},
            {"project_path": "/p", "hotspot_config_names": '["1024", "8192"]'},
            {"project_path": "/p", "suggestion_ids": '["63"]'},
        ):
            with self.subTest(arguments=arguments):
                coerced, _ = coerce_arguments(arguments, _SCHEMA)
                self.assertIsNone(validation_error("t", coerced, _SCHEMA))


class TestCoercion(unittest.TestCase):
    def test_well_typed_arguments_are_untouched(self):
        arguments = {"project_path": "/p", "apply": True, "hotspot_config_names": ["a"]}
        coerced, changes = coerce_arguments(dict(arguments), _SCHEMA)
        self.assertEqual(coerced, arguments)
        self.assertEqual(changes, {})

    def test_changes_are_reported_for_logging(self):
        _, changes = coerce_arguments({"apply": "yes"}, _SCHEMA)
        self.assertIn("apply", changes)

    def test_unknown_argument_is_left_alone(self):
        coerced, changes = coerce_arguments({"nope": "true"}, _SCHEMA)
        self.assertEqual(coerced["nope"], "true")
        self.assertEqual(changes, {})

    def test_comma_separated_list(self):
        self.assertEqual(
            coerce_arguments({"hotspot_config_names": "1024, 8192"}, _SCHEMA)[0]["hotspot_config_names"],
            ["1024", "8192"],
        )

    def test_single_value_becomes_a_one_element_list(self):
        self.assertEqual(
            coerce_arguments({"hotspot_config_names": "1024"}, _SCHEMA)[0]["hotspot_config_names"],
            ["1024"],
        )

    def test_object_from_json_string(self):
        self.assertEqual(coerce_arguments({"options": '{"a": 1}'}, _SCHEMA)[0]["options"], {"a": 1})

    def test_number_from_string(self):
        self.assertEqual(coerce_arguments({"timeout_seconds": "900"}, _SCHEMA)[0]["timeout_seconds"], 900.0)

    def test_integer_from_float_string_only_when_integral(self):
        self.assertEqual(coerce_arguments({"algorithm": "6.0"}, _SCHEMA)[0]["algorithm"], 6)
        self.assertEqual(coerce_arguments({"algorithm": "6.5"}, _SCHEMA)[0]["algorithm"], "6.5")

    def test_union_type_picks_the_one_that_works(self):
        self.assertEqual(coerce_arguments({"limit": "5"}, _SCHEMA)[0]["limit"], 5)

    def test_a_string_field_keeps_its_string(self):
        # "1024" must not become 1024 just because it looks like a number.
        self.assertEqual(coerce_arguments({"config_name": "1024"}, _SCHEMA)[0]["config_name"], "1024")

    def test_boolean_in_a_number_field_is_not_coerced(self):
        self.assertEqual(coerce_value(True, {"type": "number"}), (False, True))


class TestStillRejected(unittest.TestCase):
    """Coercion must not turn a wrong call into a plausible one."""

    def test_unrecognizable_boolean(self):
        coerced, _ = coerce_arguments({"project_path": "/p", "apply": "perhaps"}, _SCHEMA)
        error = validation_error("run_auto_tuning", coerced, _SCHEMA)
        self.assertIsNotNone(error)
        self.assertIn("apply", error)
        self.assertIn("boolean", error)

    def test_missing_required_property_is_reported_as_such(self):
        error = validation_error("run_auto_tuning", {"apply": True}, _SCHEMA)
        self.assertIsNotNone(error)
        self.assertIn("required", error)
        # Not "expected object": the type belongs to the enclosing schema, and
        # naming it here would describe the wrong problem.
        self.assertNotIn("expected object", error)

    def test_non_numeric_string_in_a_number_field(self):
        coerced, _ = coerce_arguments({"project_path": "/p", "timeout_seconds": "soon"}, _SCHEMA)
        self.assertIsNotNone(validation_error("t", coerced, _SCHEMA))

    def test_malformed_json_array(self):
        coerced, _ = coerce_arguments({"project_path": "/p", "suggestion_ids": "[63"}, _SCHEMA)
        self.assertIsNotNone(validation_error("t", coerced, _SCHEMA))


if __name__ == "__main__":
    unittest.main()
