import warnings
from typing import Any, Dict, List, Optional, Tuple


def check_clauses_for_FP(
    test_cls: Any,
    expected_clauses: Dict[str, List[str]],
    pattern: Any,
    allowed_clauses: Optional[Dict[str, List[str]]] = None,
) -> Tuple[bool, str]:
    """check that only expected clauses are found"""
    msg = ""
    res = True
    unexpected_clauses = ""
    for clause_type in ["private", "shared", "first_private", "last_private"]:
        for clause_var in pattern.__dict__[clause_type]:
            unexpected = False
            if clause_type not in expected_clauses:
                if allowed_clauses is None:
                    unexpected = True
                else:
                    if clause_type in allowed_clauses:
                        warnings.warn(
                            "Found allowed but unnecessary clause: " + clause_type + "(" + clause_var.name + ")"
                        )
                    else:
                        unexpected = True
            elif clause_var.name not in expected_clauses[clause_type]:
                if allowed_clauses is None:
                    unexpected = True
                else:
                    if clause_var.name in allowed_clauses[clause_type]:
                        warnings.warn(
                            "Found allowed but unnecessary clause: " + clause_type + "(" + clause_var.name + ")"
                        )
                    else:
                        unexpected = True
            if unexpected:
                unexpected_clauses += clause_type + "(" + clause_var.name + ") "
    if len(unexpected_clauses) > 0:
        msg = "Found unexpected clauses: " + unexpected_clauses
        res = False

    return res, msg


def check_clauses_for_FN(test_cls: Any, expected_clauses: Dict[str, List[str]], pattern: Any) -> Tuple[bool, str]:
    """check that all expected clauses are found"""
    msg = ""
    res = True
    missed_clauses = ""
    for clause_type in expected_clauses:
        for clause_var_name in expected_clauses[clause_type]:
            found = False
            for found_var in pattern.__dict__[clause_type]:
                if clause_type == "reduction":
                    if ":" not in clause_var_name:
                        continue
                    if (
                        found_var.operation == clause_var_name.split(":")[0]
                        and found_var.name == clause_var_name.split(":")[1]
                    ):
                        found = True
                        break
                else:
                    if found_var.name == clause_var_name:
                        found = True
                        break
            if not found:
                missed_clauses += clause_type + "(" + clause_var_name + ") "
    if len(missed_clauses) > 0:
        msg = "Missed expected clauses: " + missed_clauses
        res = False
    return res, msg
