#!/usr/bin/env python3
"""
Generate /app/organization.json from CSV data, validated against /app/schema.json.

Handles the full variation space of the organization-json-generator family:
- Variable entity counts and relationship complexity
- Field-level normalization (whitespace, delimiters, quoting, numeric formats,
  currency symbols)
- Arbitrary value distributions for aggregation statistics
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

DATA_DIR = "/app/data"
SCHEMA_PATH = "/app/schema.json"
OUTPUT_PATH = "/app/organization.json"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def read_csv(filepath):
    """Read CSV -> list[dict] with all keys and values stripped of whitespace.

    Skips None keys produced by extra commas in a row.
    """
    rows = []
    with open(filepath, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cleaned = {}
            for key, val in row.items():
                if key is None:
                    continue  # skip extra-comma artifacts
                k = key.strip()
                v = val.strip() if val else ""
                # Strip surrounding quotes that may remain after CSV parsing
                if v and len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                cleaned[k] = v
            rows.append(cleaned)
    return rows


def parse_semicolon_list(value):
    """Split a semicolon-delimited string into non-empty stripped tokens.

    Handles: repeated delimiters (;;), leading/trailing whitespace, empty input.
    """
    if not value or not value.strip():
        return []
    return [tok for tok in (part.strip() for part in value.split(";")) if tok]


def parse_number(value):
    """Parse a numeric string to int or float.

    Handles: leading/trailing whitespace, surrounding quotes, thousands
    separators (commas), currency symbols ($, EUR, GBP, etc.), integer
    and decimal forms.
    """
    v = value.strip()
    # Remove surrounding quotes
    if v and len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    # Strip currency symbols and other non-numeric characters,
    # preserving digits, decimal point, sign, exponent, and commas
    v = re.sub(r"[^\d.\-+eE,]", "", v)
    # Remove thousands separators
    v = v.replace(",", "")
    if not v:
        return 0
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return 0


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    # 1. Read CSV tables
    departments_raw = read_csv(os.path.join(DATA_DIR, "departments.csv"))
    employees_raw = read_csv(os.path.join(DATA_DIR, "employees.csv"))
    projects_raw = read_csv(os.path.join(DATA_DIR, "projects.csv"))

    # 2. Build grouping structures
    employees_by_dept = defaultdict(list)
    for emp in employees_raw:
        employees_by_dept[emp["department_id"]].append(emp)

    projects_by_dept = defaultdict(list)
    for proj in projects_raw:
        projects_by_dept[proj["department_id"]].append(proj)

    # 3. Assemble nested department records
    departments = []
    all_employees = []
    all_projects = []
    budgets = []

    for dept in departments_raw:
        dept_id = dept["id"]
        budget = parse_number(dept.get("budget", "0"))
        budgets.append(budget)

        # Employees for this department
        dept_employees = []
        for emp in employees_by_dept.get(dept_id, []):
            skills = parse_semicolon_list(emp.get("skills", ""))
            years = parse_number(emp.get("years_of_service", "0"))
            record = {
                "id": emp["id"],
                "name": emp["name"],
                "position": emp["position"],
                "skills": skills,
                "years_of_service": int(years),
            }
            dept_employees.append(record)
            all_employees.append(record)

        # Projects for this department
        dept_projects = []
        for proj in projects_by_dept.get(dept_id, []):
            member_ids = parse_semicolon_list(proj.get("member_ids", ""))
            record = {
                "name": proj["name"],
                "status": proj["status"],
                "members": member_ids,  # keep raw employee IDs, do not resolve to names
                "deadline": proj["deadline"],
            }
            dept_projects.append(record)
            all_projects.append(record)

        departments.append({
            "id": dept_id,
            "name": dept["name"],
            "budget": budget,
            "employees": dept_employees,
            "projects": dept_projects,
        })

    # 4. Compute statistics
    num_departments = len(departments)
    total_employees = len(all_employees)

    avg_budget = sum(budgets) / num_departments if num_departments else 0

    skill_dist = defaultdict(int)
    for emp in all_employees:
        for skill in emp["skills"]:
            skill_dist[skill] += 1

    dept_sizes = {d["name"]: len(d["employees"]) for d in departments}

    status_dist = defaultdict(int)
    for proj in all_projects:
        status_dist[proj["status"]] += 1

    total_years = sum(e["years_of_service"] for e in all_employees)
    avg_years = total_years / total_employees if total_employees else 0

    # 5. Build output
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "organization-json-generator",
        },
        "organization": {
            "name": "Organization",
            "founded": "2000-01-01",
            "departments": departments,
        },
        "statistics": {
            "averageDepartmentBudget": avg_budget,
            "totalEmployees": total_employees,
            "skillDistribution": dict(skill_dist),
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": dict(status_dist),
            "averageYearsOfService": avg_years,
        },
    }

    # 6. Write output
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {OUTPUT_PATH}")

    # 7. Self-verification
    errors = []

    # Schema validation
    try:
        import jsonschema
        with open(SCHEMA_PATH, "r") as sf:
            schema = json.load(sf)
        jsonschema.validate(output, schema)
        print("  [PASS] Schema validation")
    except ImportError:
        print("  [SKIP] jsonschema not installed")
    except jsonschema.ValidationError as exc:
        errors.append(f"Schema: {exc.message}")
        print(f"  [FAIL] Schema: {exc.message}")

    # Structural cross-checks
    if total_employees != sum(len(d["employees"]) for d in departments):
        errors.append("totalEmployees mismatch")
    for d in departments:
        if dept_sizes[d["name"]] != len(d["employees"]):
            errors.append(f"departmentSizes mismatch for {d['name']}")
    expected_avg = sum(budgets) / num_departments if num_departments else 0
    if abs(avg_budget - expected_avg) > 0.001:
        errors.append("averageDepartmentBudget mismatch")
    if total_employees and abs(avg_years - total_years / total_employees) > 0.0001:
        errors.append("averageYearsOfService mismatch")

    # Verify project members are valid employee IDs within their department
    for d in departments:
        dept_emp_ids = {e["id"] for e in d["employees"]}
        for p in d["projects"]:
            for m in p["members"]:
                if m not in dept_emp_ids:
                    errors.append(
                        f"Member '{m}' in project '{p['name']}' "
                        f"not found in department '{d['name']}'"
                    )

    if errors:
        print(f"  [FAIL] {len(errors)} cross-check failure(s):")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print("  [PASS] All cross-checks")

    # Summary
    print(f"  Departments: {num_departments}")
    print(f"  Employees:   {total_employees}")
    print(f"  Projects:    {len(all_projects)}")


if __name__ == "__main__":
    main()
