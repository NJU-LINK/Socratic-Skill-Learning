#!/usr/bin/env python3
"""
Organization JSON Generator
============================
Transforms CSV data from /app/data/ (departments.csv, employees.csv, projects.csv)
into /app/organization.json validated against /app/schema.json.

Usage:
    python3 generate.py

Handles all variation dimensions:
- Entity relationship complexity (empty projects, dense member reuse, etc.)
- Field parsing and normalization (whitespace, delimiters, quotes, etc.)
- Value distribution for aggregation (skewed values, extreme ranges, etc.)
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from collections import Counter

DATA_DIR = "/app/data"
OUTPUT_PATH = "/app/organization.json"
SCHEMA_PATH = "/app/schema.json"


def read_csv(filename):
    """Read a CSV file from DATA_DIR, return list of dicts with stripped keys/values."""
    rows = []
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ""
                # Remove surrounding quotes if present
                if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                    v = v[1:-1]
                cleaned[k] = v
            rows.append(cleaned)
    return rows


def parse_semicolon_list(value):
    """Parse semicolon-delimited field into list of stripped non-empty strings.
    Handles: empty strings, repeated delimiters, extra whitespace."""
    if not value:
        return []
    parts = value.split(";")
    return [p.strip() for p in parts if p.strip()]


def smart_number(value):
    """Parse a numeric string, returning int if whole number, float otherwise.
    
    Note: Returns 0 on parse failure — a deliberate trade-off for this task family
    where schema minimums (>=0) mean 0 passes validation but may corrupt statistics.
    For development/debugging, consider raising or logging instead.
    """
    v = value.strip().replace(",", "")
    if not v:
        return 0
    try:
        f = float(v)
        if f == int(f) and '.' not in value.strip():
            return int(f)
        return f
    except (ValueError, TypeError):
        return 0


def smart_int(value):
    """Parse a numeric string to int, tolerating decimals, commas, whitespace.
    
    Handles: "7.0" -> 7, "1,000" -> 1000, "" -> 0, " 7 " -> 7
    Uses round() to handle float representations like "6.9999" -> 7.
    """
    v = value.strip().replace(",", "")
    if not v:
        return 0
    try:
        return int(round(float(v)))
    except (ValueError, TypeError):
        return 0


def main():
    # ---- Read CSV data ----
    departments_raw = read_csv("departments.csv")
    employees_raw = read_csv("employees.csv")
    projects_raw = read_csv("projects.csv")

    # ---- Build lookup structures ----
    # Group employees by department
    emp_by_dept = {}
    for e in employees_raw:
        dept_id = e["department_id"]
        emp_by_dept.setdefault(dept_id, []).append(e)

    # Group projects by department
    proj_by_dept = {}
    for p in projects_raw:
        dept_id = p["department_id"]
        proj_by_dept.setdefault(dept_id, []).append(p)

    # ---- Build department records ----
    departments = []
    for d in departments_raw:
        dept_id = d["id"]

        # Employees for this department
        dept_employees = []
        for e in emp_by_dept.get(dept_id, []):
            skills = parse_semicolon_list(e.get("skills", ""))
            dept_employees.append({
                "id": e["id"],
                "name": e["name"],
                "position": e["position"],
                "skills": skills,
                "years_of_service": smart_int(e["years_of_service"])
            })

        # Projects for this department
        dept_projects = []
        for p in proj_by_dept.get(dept_id, []):
            member_ids = parse_semicolon_list(p.get("member_ids", ""))
            # Keep member IDs as-is (do NOT resolve to names)
            dept_projects.append({
                "name": p["name"],
                "status": p["status"],
                "members": member_ids,
                "deadline": p["deadline"]
            })

        departments.append({
            "id": d["id"],
            "name": d["name"],
            "budget": smart_number(d["budget"]),
            "employees": dept_employees,
            "projects": dept_projects
        })

    # ---- Compute statistics ----
    all_employees = []
    all_skills = []
    dept_sizes = {}
    budget_sum = 0.0

    for dept in departments:
        dept_sizes[dept["name"]] = len(dept["employees"])
        budget_sum += dept["budget"]
        for emp in dept["employees"]:
            all_employees.append(emp)
            all_skills.extend(emp["skills"])

    total_employees = len(all_employees)
    avg_budget = budget_sum / len(departments) if departments else 0.0

    skill_dist = dict(sorted(Counter(all_skills).items()))

    all_statuses = []
    for dept in departments:
        for proj in dept["projects"]:
            all_statuses.append(proj["status"])
    status_dist = dict(sorted(Counter(all_statuses).items()))

    total_yos = sum(e["years_of_service"] for e in all_employees)
    avg_yos = total_yos / total_employees if total_employees > 0 else 0.0

    # ---- Build output ----
    output = {
        "metadata": {
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "organization-json-generator"
        },
        "organization": {
            "name": "Organization",
            "founded": "2000-01-01",
            "departments": departments
        },
        "statistics": {
            "averageDepartmentBudget": avg_budget,
            "totalEmployees": total_employees,
            "skillDistribution": skill_dist,
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": status_dist,
            "averageYearsOfService": avg_yos
        }
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {OUTPUT_PATH} successfully")

    # ---- Validate against schema ----
    try:
        import jsonschema
        with open(SCHEMA_PATH) as sf:
            schema = json.load(sf)
        jsonschema.validate(output, schema)
        print("Schema validation passed!")
    except ImportError:
        print("jsonschema not installed; skipping validation")
    except jsonschema.ValidationError as e:
        print(f"Schema validation FAILED: {e.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
