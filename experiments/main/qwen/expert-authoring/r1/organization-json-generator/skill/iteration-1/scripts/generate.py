#!/usr/bin/env python3
"""
Organization JSON Generator – reference implementation.

Reads /app/data/{departments,employees,projects}.csv, assembles a nested
organization JSON, computes aggregate statistics, validates against
/app/schema.json, and writes /app/organization.json.
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

DATA_DIR = Path("/app/data")
SCHEMA_PATH = Path("/app/schema.json")
OUTPUT_PATH = Path("/app/organization.json")


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file and return a list of row dicts."""
    with open(path, newline="") as f:
        return [row for row in csv.DictReader(f)]


def split_semicolon(value: str) -> list[str]:
    """Split a semicolon-delimited string, stripping whitespace and
    discarding empty tokens.  Returns [] for blank input."""
    value = value.strip()
    if not value:
        return []
    return [token.strip() for token in value.split(";") if token.strip()]


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Read inputs
    # ------------------------------------------------------------------
    departments_raw = read_csv(DATA_DIR / "departments.csv")
    employees_raw = read_csv(DATA_DIR / "employees.csv")
    projects_raw = read_csv(DATA_DIR / "projects.csv")

    # ------------------------------------------------------------------
    # 2. Build department skeleton (keyed by department id)
    # ------------------------------------------------------------------
    departments: dict[str, dict] = {}
    for row in departments_raw:
        did = row["id"].strip()
        departments[did] = {
            "id": did,
            "name": row["name"].strip(),
            "budget": float(row["budget"].strip()),
            "employees": [],
            "projects": [],
        }

    # ------------------------------------------------------------------
    # 3. Parse employees, attach to departments, build ID->name lookup
    # ------------------------------------------------------------------
    emp_id_to_name: dict[str, str] = {}
    for row in employees_raw:
        did = row["department_id"].strip()
        emp = {
            "id": row["id"].strip(),
            "name": row["name"].strip(),
            "position": row["position"].strip(),
            "skills": split_semicolon(row.get("skills", "")),
            "years_of_service": int(row["years_of_service"].strip()),
        }
        emp_id_to_name[emp["id"]] = emp["name"]
        if did in departments:
            departments[did]["employees"].append(emp)

    # ------------------------------------------------------------------
    # 4. Parse projects, resolve member IDs -> names, attach to depts
    # ------------------------------------------------------------------
    for row in projects_raw:
        did = row["department_id"].strip()
        member_ids = split_semicolon(row.get("member_ids", ""))
        members = [emp_id_to_name[mid] for mid in member_ids if mid in emp_id_to_name]
        project = {
            "name": row["name"].strip(),
            "status": row["status"].strip(),
            "members": members,
            "deadline": row["deadline"].strip(),
        }
        if did in departments:
            departments[did]["projects"].append(project)

    # ------------------------------------------------------------------
    # 5. Assemble department list (preserve CSV order)
    # ------------------------------------------------------------------
    dept_list = list(departments.values())

    # ------------------------------------------------------------------
    # 6. Compute statistics
    # ------------------------------------------------------------------
    all_employees = []
    all_projects = []
    for d in dept_list:
        all_employees.extend(d["employees"])
        all_projects.extend(d["projects"])

    budgets = [d["budget"] for d in dept_list]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0

    total_employees = len(all_employees)

    skill_dist: dict[str, int] = defaultdict(int)
    for emp in all_employees:
        for skill in emp["skills"]:
            skill_dist[skill] += 1

    dept_sizes: dict[str, int] = {}
    for d in dept_list:
        dept_sizes[d["name"]] = len(d["employees"])

    status_dist: dict[str, int] = defaultdict(int)
    for p in all_projects:
        status_dist[p["status"]] += 1

    all_yos = [e["years_of_service"] for e in all_employees]
    avg_yos = round(sum(all_yos) / len(all_yos), 2) if all_yos else 0

    # ------------------------------------------------------------------
    # 7. Build output JSON
    # ------------------------------------------------------------------
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "organization-json-generator",
        },
        "organization": {
            "name": "Organization",
            "founded": "2020-01-01",
            "departments": dept_list,
        },
        "statistics": {
            "averageDepartmentBudget": avg_budget,
            "totalEmployees": total_employees,
            "skillDistribution": dict(skill_dist),
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": dict(status_dist),
            "averageYearsOfService": avg_yos,
        },
    }

    # ------------------------------------------------------------------
    # 8. Validate against schema and write
    # ------------------------------------------------------------------
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    try:
        jsonschema.validate(output, schema)
    except jsonschema.ValidationError as exc:
        print(f"Schema validation FAILED: {exc.message}", file=sys.stderr)
        sys.exit(1)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"Written and validated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
