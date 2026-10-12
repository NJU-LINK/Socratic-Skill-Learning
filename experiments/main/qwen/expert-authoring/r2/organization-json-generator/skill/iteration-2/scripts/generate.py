#!/usr/bin/env python3
"""
Transform CSV data (departments, employees, projects) into a nested
organization JSON file that validates against the provided schema.

Usage:
    python3 <skill-base-dir>/scripts/generate.py

Reads from /app/data/*.csv and /app/schema.json.
Writes to /app/organization.json.
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("/app/data")
SCHEMA_PATH = Path("/app/schema.json")
OUTPUT_PATH = Path("/app/organization.json")


def read_csv(filepath):
    """Read a CSV file and return a list of dicts with stripped keys/values."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Strip header whitespace
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ""
                cleaned[k] = v
            rows.append(cleaned)
    return rows


def parse_number(raw):
    """Parse a numeric string that may contain commas, decimals, or whitespace.

    Returns int when the value is a whole number, float otherwise.
    Handles: '1500000', '1500000.0', '1,500,000', '6.93', '', etc.
    """
    if not raw:
        return 0
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        pass
    try:
        f = float(cleaned)
        return int(f) if f == int(f) else f
    except ValueError:
        return 0


def parse_list(raw, delimiter=";"):
    """Split a delimited string into non-empty stripped tokens.

    Handles: empty string, repeated delimiters (;;), trailing delimiters,
    leading/trailing whitespace on individual tokens.
    """
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(delimiter) if t.strip()]


def main():
    # ---- 1. Read CSV data ----
    departments_raw = read_csv(DATA_DIR / "departments.csv")
    employees_raw = read_csv(DATA_DIR / "employees.csv")
    projects_raw = read_csv(DATA_DIR / "projects.csv")

    # ---- 2. Parse and normalize ----
    departments = []
    for d in departments_raw:
        departments.append({
            "id": d["id"],
            "name": d["name"],
            "budget": parse_number(d.get("budget", "0")),
        })

    employees = []
    for e in employees_raw:
        employees.append({
            "id": e["id"],
            "name": e["name"],
            "position": e.get("position", ""),
            "skills": parse_list(e.get("skills", "")),
            "years_of_service": parse_number(e.get("years_of_service", "0")),
            "department_id": e["department_id"],
        })

    projects = []
    for p in projects_raw:
        projects.append({
            "name": p["name"],
            "status": p.get("status", ""),
            "members": parse_list(p.get("member_ids", "")),
            "deadline": p.get("deadline", ""),
            "department_id": p["department_id"],
        })

    # ---- 3. Group by department_id ----
    employees_by_dept = defaultdict(list)
    for emp in employees:
        employees_by_dept[emp["department_id"]].append(emp)

    projects_by_dept = defaultdict(list)
    for proj in projects:
        projects_by_dept[proj["department_id"]].append(proj)

    # ---- 4. Build nested department records (sorted by id) ----
    dept_records = []
    for dept in sorted(departments, key=lambda d: d["id"]):
        dept_id = dept["id"]
        dept_employees = [
            {
                "id": e["id"],
                "name": e["name"],
                "position": e["position"],
                "skills": e["skills"],
                "years_of_service": e["years_of_service"],
            }
            for e in employees_by_dept.get(dept_id, [])
        ]
        dept_projects = [
            {
                "name": p["name"],
                "status": p["status"],
                "members": p["members"],
                "deadline": p["deadline"],
            }
            for p in projects_by_dept.get(dept_id, [])
        ]
        dept_records.append({
            "id": dept_id,
            "name": dept["name"],
            "budget": dept["budget"],
            "employees": dept_employees,
            "projects": dept_projects,
        })

    # ---- 5. Compute statistics over ALL data ----
    all_employees = [e for d in dept_records for e in d["employees"]]
    all_projects = [p for d in dept_records for p in d["projects"]]

    total_budget = sum(d["budget"] for d in dept_records)
    n_depts = len(dept_records)
    n_emps = len(all_employees)

    skill_distribution = defaultdict(int)
    for emp in all_employees:
        for skill in emp["skills"]:
            skill_distribution[skill] += 1

    department_sizes = {d["name"]: len(d["employees"]) for d in dept_records}

    project_status_dist = defaultdict(int)
    for proj in all_projects:
        project_status_dist[proj["status"]] += 1

    total_years = sum(e["years_of_service"] for e in all_employees)

    statistics = {
        "averageDepartmentBudget": total_budget / n_depts if n_depts else 0,
        "totalEmployees": n_emps,
        "skillDistribution": dict(skill_distribution),
        "departmentSizes": department_sizes,
        "projectStatusDistribution": dict(project_status_dist),
        "averageYearsOfService": total_years / n_emps if n_emps else 0,
    }

    # ---- 6. Assemble full output ----
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "organization-json-generator",
        },
        "organization": {
            "name": "Organization",
            "founded": "2020-01-01",
            "departments": dept_records,
        },
        "statistics": statistics,
    }

    # ---- 7. Validate against schema ----
    try:
        import jsonschema
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(instance=output, schema=schema)
        print("Schema validation passed.", file=sys.stderr)
    except ImportError:
        print("WARNING: jsonschema not installed; skipping validation.", file=sys.stderr)
    except jsonschema.ValidationError as e:
        print(f"Schema validation FAILED: {e.message}", file=sys.stderr)
        print(f"  Path: {list(e.absolute_path)}", file=sys.stderr)
        sys.exit(1)

    # ---- 8. Self-verification ----
    assert len(dept_records) == len(departments), \
        f"Department count mismatch: {len(dept_records)} vs {len(departments)}"
    assert n_emps == len(employees), \
        f"Employee count mismatch: {n_emps} vs {len(employees)}"
    assert len(all_projects) == len(projects), \
        f"Project count mismatch: {len(all_projects)} vs {len(projects)}"
    for d in dept_records:
        for p in d["projects"]:
            assert "" not in p["members"], \
                f"Empty string in members of project '{p['name']}'"
        for e in d["employees"]:
            assert isinstance(e["years_of_service"], int), \
                f"years_of_service is not int for {e['id']}: {type(e['years_of_service'])}"
    print("Self-verification passed.", file=sys.stderr)

    # ---- 9. Write output ----
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Written {OUTPUT_PATH} successfully.")


if __name__ == "__main__":
    main()
