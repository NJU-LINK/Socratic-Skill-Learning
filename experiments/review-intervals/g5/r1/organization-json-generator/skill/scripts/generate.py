#!/usr/bin/env python3
"""
Organization JSON Generator
Transforms CSV data (departments, employees, projects) into a nested
organization JSON conforming to a provided schema.

Usage:
    python3 generate.py [--data-dir DIR] [--schema SCHEMA] [--output OUTPUT]

Defaults:
    --data-dir  /app/data
    --schema    /app/schema.json
    --output    /app/organization.json
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone


def parse_semicolon_list(value):
    """Split a semicolon-delimited string into a cleaned list.

    Handles:
    - None or empty string -> []
    - Extra whitespace around elements -> trimmed
    - Repeated delimiters (e.g. "a;;b") -> empty strings filtered out
    - Single values with no delimiter -> [value]
    """
    if value is None:
        return []
    value = value.strip()
    if not value:
        return []
    parts = [p.strip() for p in value.split(";")]
    return [p for p in parts if p]


def parse_number(value, as_type=float):
    """Parse a numeric string robustly.

    Strips whitespace and commas (handles "1,500,000" or " 7 ").
    Returns the value cast to as_type (float or int).
    """
    if value is None:
        return as_type(0)
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return as_type(0)
    return as_type(cleaned)


def read_csv(filepath):
    """Read a CSV file and return a list of dicts (one per row).
    Uses utf-8-sig encoding to handle optional BOM.
    """
    rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def validate_output(output_path, schema_path):
    """Validate the generated JSON against the schema. Returns True if valid."""
    try:
        import jsonschema
    except ImportError:
        print("Warning: jsonschema not installed, skipping validation", file=sys.stderr)
        return True

    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"Schema validation FAILED: {e.message}", file=sys.stderr)
        print(f"  Path: {list(e.absolute_path)}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate organization JSON from CSV data")
    parser.add_argument("--data-dir", default="/app/data", help="Directory containing CSV files")
    parser.add_argument("--schema", default="/app/schema.json", help="Path to JSON schema")
    parser.add_argument("--output", default="/app/organization.json", help="Output JSON path")
    args = parser.parse_args()

    data_dir = args.data_dir
    output_path = args.output
    schema_path = args.schema

    # Read CSV files
    departments_raw = read_csv(os.path.join(data_dir, "departments.csv"))
    employees_raw = read_csv(os.path.join(data_dir, "employees.csv"))
    projects_raw = read_csv(os.path.join(data_dir, "projects.csv"))

    # Build department lookup, preserving CSV order
    dept_order = []
    departments = {}
    for row in departments_raw:
        dept_id = row["id"].strip()
        departments[dept_id] = {
            "id": dept_id,
            "name": row["name"].strip(),
            "budget": parse_number(row["budget"], float),
            "employees": [],
            "projects": [],
        }
        dept_order.append(dept_id)

    # Group employees by department_id
    for row in employees_raw:
        dept_id = row["department_id"].strip()
        skills = parse_semicolon_list(row.get("skills", ""))
        years = parse_number(row.get("years_of_service", "0"), int)
        employee = {
            "id": row["id"].strip(),
            "name": row["name"].strip(),
            "position": row["position"].strip(),
            "skills": skills,
            "years_of_service": years,
        }
        if dept_id in departments:
            departments[dept_id]["employees"].append(employee)

    # Group projects by department_id
    for row in projects_raw:
        dept_id = row["department_id"].strip()
        member_ids = parse_semicolon_list(row.get("member_ids", ""))
        project = {
            "name": row["name"].strip(),
            "status": row["status"].strip(),
            "members": member_ids,
            "deadline": row["deadline"].strip(),
        }
        if dept_id in departments:
            departments[dept_id]["projects"].append(project)

    # Build ordered department list (preserve CSV order)
    dept_list = [departments[did] for did in dept_order]

    # Compute statistics
    num_depts = len(dept_list)
    total_budget = sum(d["budget"] for d in dept_list)
    avg_budget = total_budget / num_depts if num_depts > 0 else 0.0

    all_employees = []
    for d in dept_list:
        all_employees.extend(d["employees"])
    total_employees = len(all_employees)

    # Skill distribution: count how many employees have each skill
    skill_dist = {}
    for emp in all_employees:
        for skill in emp["skills"]:
            skill_dist[skill] = skill_dist.get(skill, 0) + 1

    # Department sizes: department name -> employee count
    dept_sizes = {}
    for d in dept_list:
        dept_sizes[d["name"]] = len(d["employees"])

    # Project status distribution
    status_dist = {}
    for d in dept_list:
        for p in d["projects"]:
            status = p["status"]
            status_dist[status] = status_dist.get(status, 0) + 1

    # Average years of service
    total_years = sum(e["years_of_service"] for e in all_employees)
    avg_years = total_years / total_employees if total_employees > 0 else 0.0

    # Build final JSON
    result = {
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
            "skillDistribution": skill_dist,
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": status_dist,
            "averageYearsOfService": avg_years,
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Self-validate
    if os.path.exists(schema_path):
        if validate_output(output_path, schema_path):
            print(f"Generated {output_path} — schema validation PASSED")
        else:
            print(f"Generated {output_path} — schema validation FAILED", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Generated {output_path} (no schema found, skipped validation)")


if __name__ == "__main__":
    main()
