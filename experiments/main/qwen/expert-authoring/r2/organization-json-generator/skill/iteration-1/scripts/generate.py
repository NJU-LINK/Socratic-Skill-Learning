#!/usr/bin/env python3
"""
Transform CSV data (departments, employees, projects) into a nested
organization JSON file that validates against the provided schema.
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


def parse_semicolon_list(value):
    """Split a semicolon-delimited string into a list of stripped, non-empty tokens."""
    if not value:
        return []
    tokens = [t.strip() for t in value.split(";")]
    return [t for t in tokens if t]


def parse_number(value):
    """Parse a numeric string to int or float."""
    value = value.strip()
    if not value:
        return 0
    # Try int first
    try:
        return int(value)
    except ValueError:
        pass
    # Try float
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0


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
            "skills": parse_semicolon_list(e.get("skills", "")),
            "years_of_service": parse_number(e.get("years_of_service", "0")),
            "department_id": e["department_id"],
        })

    projects = []
    for p in projects_raw:
        projects.append({
            "name": p["name"],
            "status": p.get("status", ""),
            "members": parse_semicolon_list(p.get("member_ids", "")),
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

    # ---- 4. Build nested department records ----
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

    # ---- 5. Compute statistics ----
    total_budget = sum(d["budget"] for d in dept_records)
    num_departments = len(dept_records)
    average_dept_budget = total_budget / num_departments if num_departments > 0 else 0

    total_employees = sum(len(d["employees"]) for d in dept_records)

    # Skill distribution: count each skill across all employees
    skill_distribution = defaultdict(int)
    for dept in dept_records:
        for emp in dept["employees"]:
            for skill in emp["skills"]:
                skill_distribution[skill] += 1

    # Department sizes: department name -> employee count
    department_sizes = {}
    for dept in dept_records:
        department_sizes[dept["name"]] = len(dept["employees"])

    # Project status distribution
    project_status_dist = defaultdict(int)
    for dept in dept_records:
        for proj in dept["projects"]:
            project_status_dist[proj["status"]] += 1

    # Average years of service
    total_years = sum(
        emp["years_of_service"]
        for dept in dept_records
        for emp in dept["employees"]
    )
    avg_years = total_years / total_employees if total_employees > 0 else 0

    statistics = {
        "averageDepartmentBudget": average_dept_budget,
        "totalEmployees": total_employees,
        "skillDistribution": dict(skill_distribution),
        "departmentSizes": department_sizes,
        "projectStatusDistribution": dict(project_status_dist),
        "averageYearsOfService": avg_years,
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

    # ---- 8. Write output ----
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Written {OUTPUT_PATH} successfully.")


if __name__ == "__main__":
    main()
