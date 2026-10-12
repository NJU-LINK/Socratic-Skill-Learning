#!/usr/bin/env python3
"""
Organization JSON Generator
Transforms departments.csv, employees.csv, projects.csv into organization.json
conforming to schema.json.

Usage:
    python3 generate.py [data_dir] [schema_path] [output_path]

Defaults:
    data_dir:    /app/data
    schema_path: /app/schema.json
    output_path: /app/organization.json
"""

import csv
import json
import datetime
import os
import sys


def read_csv(filepath):
    """Read a CSV file and return a list of dicts with stripped keys and values.
    Handles quoted text, extra whitespace, and various CSV formatting."""
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                val = v.strip() if v else ""
                cleaned[key] = val
            rows.append(cleaned)
    return rows


def parse_semicolon_list(value):
    """Split a semicolon-delimited string into a list of stripped, non-empty strings.
    Handles: extra whitespace, repeated delimiters (;;), empty fields, trailing delimiters."""
    if not value:
        return []
    return [s.strip() for s in value.split(';') if s.strip()]


def parse_int(value):
    """Parse a string to int, stripping whitespace."""
    return int(value.strip())


def parse_number(value):
    """Parse a string to a number (int if whole, float otherwise).
    Handles: whitespace, comma separators."""
    cleaned = value.strip().replace(',', '')
    num = float(cleaned)
    if num == int(num):
        return int(num)
    return num


def main():
    # Parse arguments with defaults
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
    schema_path = sys.argv[2] if len(sys.argv) > 2 else "/app/schema.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "/app/organization.json"

    # Read all CSV data
    departments_raw = read_csv(os.path.join(data_dir, "departments.csv"))
    employees_raw = read_csv(os.path.join(data_dir, "employees.csv"))
    projects_raw = read_csv(os.path.join(data_dir, "projects.csv"))

    # Parse departments
    departments = []
    for d in departments_raw:
        dept = {
            "id": d["id"],
            "name": d["name"],
            "budget": parse_number(d["budget"]),
        }
        departments.append(dept)

    # Group employees by department_id
    emp_by_dept = {}
    for e in employees_raw:
        did = e["department_id"]
        if did not in emp_by_dept:
            emp_by_dept[did] = []
        emp_by_dept[did].append({
            "id": e["id"],
            "name": e["name"],
            "position": e["position"],
            "skills": parse_semicolon_list(e["skills"]),
            "years_of_service": parse_int(e["years_of_service"]),
        })

    # Group projects by department_id
    proj_by_dept = {}
    for p in projects_raw:
        did = p["department_id"]
        if did not in proj_by_dept:
            proj_by_dept[did] = []
        proj_by_dept[did].append({
            "name": p["name"],
            "status": p["status"],
            "members": parse_semicolon_list(p["member_ids"]),
            "deadline": p["deadline"],
        })

    # Assemble department objects with nested employees and projects
    dept_objects = []
    for dept in departments:
        did = dept["id"]
        dept_obj = {
            "id": dept["id"],
            "name": dept["name"],
            "budget": dept["budget"],
            "employees": emp_by_dept.get(did, []),
            "projects": proj_by_dept.get(did, []),
        }
        dept_objects.append(dept_obj)

    # Compute statistics
    total_departments = len(departments)
    total_budget = sum(d["budget"] for d in departments)
    avg_budget = total_budget / total_departments if total_departments > 0 else 0.0

    all_employees = []
    for dept_obj in dept_objects:
        all_employees.extend(dept_obj["employees"])
    total_employees = len(all_employees)

    # Skill distribution: global counter across all employees
    skill_dist = {}
    for emp in all_employees:
        for skill in emp["skills"]:
            skill_dist[skill] = skill_dist.get(skill, 0) + 1

    # Department sizes: keyed by department name
    dept_sizes = {}
    for dept_obj in dept_objects:
        dept_sizes[dept_obj["name"]] = len(dept_obj["employees"])

    # Project status distribution
    all_projects = []
    for dept_obj in dept_objects:
        all_projects.extend(dept_obj["projects"])
    status_dist = {}
    for proj in all_projects:
        s = proj["status"]
        status_dist[s] = status_dist.get(s, 0) + 1

    # Average years of service
    total_years = sum(emp["years_of_service"] for emp in all_employees)
    avg_years = total_years / total_employees if total_employees > 0 else 0.0

    # Build the final JSON
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "organization-json-generator"
        },
        "organization": {
            "name": "Organization",
            "founded": "2000-01-01",
            "departments": dept_objects
        },
        "statistics": {
            "averageDepartmentBudget": avg_budget,
            "totalEmployees": total_employees,
            "skillDistribution": skill_dist,
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": status_dist,
            "averageYearsOfService": avg_years
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_path} successfully.")
    print(f"  Departments: {total_departments}")
    print(f"  Employees: {total_employees}")
    print(f"  Projects: {len(all_projects)}")


if __name__ == "__main__":
    main()
