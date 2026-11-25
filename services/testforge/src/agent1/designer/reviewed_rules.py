"""Expand all reviewed field rules without inventing their business oracles."""
import copy
import re


def expand_suite(suite):
    expanded = copy.deepcopy(suite)
    expanded["cases"] = []
    coverage = []
    for case in suite.get("cases", []):
        base = copy.deepcopy(case)
        rules = base.pop("rules", [])
        expanded["cases"].append(base)
        for rule in rules:
            rid = rule.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", rid) or not rule.get("source_ref"):
                raise ValueError("Rule ID and source_ref are required")
            target = rule.get("target")
            positions = [i for i, step in enumerate(base.get("steps", []))
                         if step.get("action") == "FILL" and step.get("target") == target]
            if not positions:
                raise ValueError(f"Rule {rid} has no matching FILL target")
            kind = rule["kind"]
            if kind == "REQUIRED":
                values = [("empty", "", False)]
            elif kind == "FORMAT":
                if "invalid_value" not in rule:
                    raise ValueError(f"Rule {rid} needs reviewed invalid_value")
                values = [("invalid", rule["invalid_value"], False)]
            elif kind == "UNIQUE":
                if "duplicate_value" not in rule or not base.get("fixtures"):
                    raise ValueError(f"Rule {rid} needs a seeded duplicate value")
                values = [("duplicate", rule["duplicate_value"], False)]
            elif kind == "LENGTH":
                lower, upper = rule.get("min", 0), rule.get("max")
                if type(lower) is not int or lower < 0 or (upper is not None and (type(upper) is not int or upper < lower)):
                    raise ValueError(f"Rule {rid} has invalid length bounds")
                if "min" not in rule and upper is None:
                    raise ValueError(f"Rule {rid} needs a length bound")
                sizes = set()
                for bound in ([lower] if "min" in rule else []) + ([upper] if upper is not None else []):
                    sizes.update(n for n in (bound-1, bound, bound+1) if n >= 0)
                if max(sizes) > 100000:
                    raise ValueError("Boundary fixture too large for browser pilot")
                values = [(f"length-{n}", "A" * n, n >= lower and (upper is None or n <= upper)) for n in sorted(sizes)]
            else:
                raise ValueError(f"Unsupported rule kind {kind}; supply an explicit reviewed case")
            ids = []
            for label, value, valid in values:
                derived = copy.deepcopy(base)
                expectations = rule.get("valid_expectations" if valid else "invalid_expectations")
                if not expectations or not any(expectations.get(k) for k in ("ui_oracles", "api_checks", "db")):
                    raise ValueError(f"Rule {rid}/{label} lacks reviewed expectations")
                for key in ("ui_oracles", "api_checks", "db"):
                    derived.pop(key, None)
                    if key in expectations:
                        derived[key] = copy.deepcopy(expectations[key])
                derived["steps"][positions[-1]]["value"] = value
                derived["test_case_id"] = f"{base['test_case_id']}--{rid}--{label}"
                derived["requirement_refs"] = sorted(set(base.get("requirement_refs", []) + [rule["source_ref"]]))
                derived["source_rule"] = {"id": rid, "kind": kind, "source_ref": rule["source_ref"]}
                expanded["cases"].append(derived)
                ids.append(derived["test_case_id"])
            coverage.append({"rule_id": rid, "source_ref": rule["source_ref"], "cases": ids})
    return expanded, coverage
