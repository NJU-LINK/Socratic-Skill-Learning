#!/usr/bin/env python3
"""
Organization JSON Generator
============================
Transforms CSV data (departments, employees, projects) into a nested
organization JSON conforming to a provided JSON schema.

Usage:
    python3 generate.py [--data-dir DIR] [--schema PATH] [--output PATH]

Defaults:
    --data-dir  /app/data
    --schema    /app/schema.json
    --output    /app/organization.json
"""

import csv
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from collections import defaultdict


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def read_csv(filepath):
    """
    Read a CSV file and return a list of dicts.
    Strips whitespace from all keys and values.
    Handles quoted fields (via csv.DictReader).
    """
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                val = v.strip() if v else ''
                cleaned[key] = val
            rows.append(cleaned)
    return rows


# ---------------------------------------------------------------------------
# Value parsing / normalization
# ---------------------------------------------------------------------------

def parse_semicolon_list(value):
    """
    Split a semicolon-delimited string into a list of trimmed, non-empty strings.
    Handles: empty fields -> [], repeated delimiters, extra whitespace.
    """
    if not value or not value.strip():
        return []
    parts = [p.strip() for p in value.split(';')]
    return [p for p in parts if p]


def parse_number(value):
    """
    Parse a numeric string, preserving int vs float.
    If the string contains a decimal point, parse as float; otherwise int.
    Handles leading/trailing whitespace.
    """
    val = value.strip()
    if '.' in val:
        return float(val)
    return int(val)


def parse_int(value):
    """Parse a string to integer, handling whitespace."""
    return int(value.strip())


# ---------------------------------------------------------------------------
# Entity relationship assembly
# ---------------------------------------------------------------------------

def build_organization(departments, employees, projects):
    """
    Assemble the nested organization structure.
    
    Groups employees and projects by department_id, then attaches them
    to each department record. Departments with no employees or projects
    get empty arrays (not missing keys).
    """
    # Group employees by department_id
    emp_by_dept = defaultdict(list)
    for emp in employees:
        dept_id = emp['department_id']
        emp_by_dept[dept_id].append({
            "id": emp['id'],
            "name": emp['name'],
            "position": emp['position'],
            "skills": parse_semicolon_list(emp['skills']),
            "years_of_service": parse_int(emp['years_of_service'])
        })

    # Group projects by department_id
    proj_by_dept = defaultdict(list)
    for proj in projects:
        dept_id = proj['department_id']
        member_ids = parse_semicolon_list(proj.get('member_ids', ''))
        proj_by_dept[dept_id].append({
            "name": proj['name'],
            "status": proj['status'],
            "members": member_ids,
            "deadline": proj['deadline']
        })

    # Build department records
    dept_records = []
    for dept in departments:
        dept_id = dept['id']
        dept_record = {
            "id": dept_id,
            "name": dept['name'],
            "budget": parse_number(dept['budget']),
            "employees": emp_by_dept.get(dept_id, []),
            "projects": proj_by_dept.get(dept_id, [])
        }
        dept_records.append(dept_record)

    return dept_records


# ---------------------------------------------------------------------------
# Statistics computation
# ---------------------------------------------------------------------------

def compute_statistics(dept_records):
    """
    Compute aggregate statistics from the assembled department records.
    
    Returns dict with:
      - averageDepartmentBudget (float)
      - totalEmployees (int)
      - skillDistribution (dict: skill_name -> count)
      - departmentSizes (dict: dept_name -> employee_count)
      - projectStatusDistribution (dict: status -> count)
      - averageYearsOfService (float)
    """
    total_employees = 0
    total_years = 0
    total_budget = 0
    skill_counts = defaultdict(int)
    dept_sizes = {}
    status_counts = defaultdict(int)

    for dept in dept_records:
        total_budget += dept['budget']

        emp_count = len(dept['employees'])
        total_employees += emp_count
        dept_sizes[dept['name']] = emp_count

        for emp in dept['employees']:
            total_years += emp['years_of_service']
            for skill in emp['skills']:
                skill_counts[skill] += 1

        for proj in dept['projects']:
            status_counts[proj['status']] += 1

    num_depts = len(dept_records)
    avg_budget = total_budget / num_depts if num_depts > 0 else 0.0
    avg_years = total_years / total_employees if total_employees > 0 else 0.0

    return {
        "averageDepartmentBudget": avg_budget,
        "totalEmployees": total_employees,
        "skillDistribution": dict(skill_counts),
        "departmentSizes": dept_sizes,
        "projectStatusDistribution": dict(status_counts),
        "averageYearsOfService": avg_years
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Generate organization JSON from CSV data')
    parser.add_argument('--data-dir', default='/app/data', help='Directory containing CSV files')
    parser.add_argument('--schema', default='/app/schema.json', help='Path to JSON schema')
    parser.add_argument('--output', default='/app/organization.json', help='Output JSON path')
    args = parser.parse_args()

    data_dir = args.data_dir

    # Read CSV files
    departments = read_csv(os.path.join(data_dir, 'departments.csv'))
    employees = read_csv(os.path.join(data_dir, 'employees.csv'))
    projects = read_csv(os.path.join(data_dir, 'projects.csv'))

    # Assemble nested structure
    dept_records = build_organization(departments, employees, projects)
    statistics = compute_statistics(dept_records)

    # Generate timestamp in ISO 8601 format
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Build final output
    output = {
        "metadata": {
            "version": "1.0.0",
            "timestamp": timestamp,
            "generator": "organization-json-generator"
        },
        "organization": {
            "name": "Organization",
            "founded": "2020-01-01",
            "departments": dept_records
        },
        "statistics": statistics
    }

    # Write output
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {args.output}")
    print(f"  Departments: {len(dept_records)}")
    print(f"  Total employees: {statistics['totalEmployees']}")
    print(f"  Total projects: {sum(len(d['projects']) for d in dept_records)}")

    # Validate if jsonschema is available
    try:
        import jsonschema
        with open(args.schema) as sf:
            schema = json.load(sf)
        jsonschema.validate(output, schema)
        print("  Schema validation: PASSED")
    except ImportError:
        print("  Schema validation: SKIPPED (jsonschema not installed)")
    except Exception as e:
        print(f"  Schema validation: FAILED - {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
