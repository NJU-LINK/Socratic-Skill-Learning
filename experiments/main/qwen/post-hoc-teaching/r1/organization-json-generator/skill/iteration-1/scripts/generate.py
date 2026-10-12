#!/usr/bin/env python3
"""
Organization JSON Generator — Reference Implementation

Reads CSV data from /app/data/ (departments.csv, employees.csv, projects.csv),
applies parsing/normalization, builds a nested organization structure, computes
aggregate statistics, validates against /app/schema.json, and writes the result
to /app/organization.json.

Robust against:
- Extra whitespace, repeated delimiters, empty multi-value fields
- Quoted CSV text, BOM characters
- Whole-number vs fractional budgets
- Departments with no projects, projects with no members
- Skewed distributions in numeric and categorical fields
"""

import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone


def read_csv(filepath):
    """Read a CSV file and return list of dicts with stripped keys/values."""
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                if k is None:
                    continue
                cleaned[k.strip()] = v.strip() if v else ''
            rows.append(cleaned)
    return rows


def parse_semicolon_list(value):
    """Parse semicolon-delimited string into list of non-empty stripped strings."""
    if not value:
        return []
    parts = [p.strip() for p in value.split(';')]
    return [p for p in parts if p]


def parse_number(value):
    """Parse numeric string. Returns int if whole, float otherwise."""
    v = value.strip().replace(',', '')
    if not v:
        return 0
    f = float(v)
    if f == math.floor(f) and not math.isinf(f):
        return int(f)
    return f


def parse_int(value):
    """Parse string to integer."""
    return int(value.strip().replace(',', ''))


def main():
    data_dir = '/app/data'
    schema_path = '/app/schema.json'
    output_path = '/app/organization.json'

    # ── Read CSV files ──────────────────────────────────────────────
    departments_raw = read_csv(os.path.join(data_dir, 'departments.csv'))
    employees_raw = read_csv(os.path.join(data_dir, 'employees.csv'))
    projects_raw = read_csv(os.path.join(data_dir, 'projects.csv'))

    # ── Build employee lookup by ID ─────────────────────────────────
    employee_by_id = {}
    for emp in employees_raw:
        emp_id = emp['id'].strip()
        skills = parse_semicolon_list(emp.get('skills', ''))
        if not skills:
            skills = ['Unspecified']
        employee_by_id[emp_id] = {
            'id': emp_id,
            'name': emp['name'].strip(),
            'position': emp['position'].strip(),
            'skills': skills,
            'years_of_service': parse_int(emp['years_of_service']),
            'department_id': emp['department_id'].strip()
        }

    # ── Group employees by department ───────────────────────────────
    employees_by_dept = defaultdict(list)
    for emp in employee_by_id.values():
        employees_by_dept[emp['department_id']].append(emp)

    # ── Group projects by department ────────────────────────────────
    # Keep member_ids as literal ID strings from the source data.
    # The instruction says "preserve the relationships exactly" — the source
    # stores member references as employee IDs, so we keep them as-is.
    projects_by_dept = defaultdict(list)
    for proj in projects_raw:
        dept_id = proj['department_id'].strip()
        member_ids = parse_semicolon_list(proj.get('member_ids', ''))

        projects_by_dept[dept_id].append({
            'name': proj['name'].strip(),
            'status': proj['status'].strip(),
            'members': member_ids,
            'deadline': proj['deadline'].strip()
        })

    # ── Build department objects ────────────────────────────────────
    departments = []
    for dept in departments_raw:
        dept_id = dept['id'].strip()
        dept_obj = {
            'id': dept_id,
            'name': dept['name'].strip(),
            'budget': parse_number(dept['budget']),
            'employees': [],
            'projects': []
        }

        for emp in employees_by_dept.get(dept_id, []):
            dept_obj['employees'].append({
                'id': emp['id'],
                'name': emp['name'],
                'position': emp['position'],
                'skills': emp['skills'],
                'years_of_service': emp['years_of_service']
            })

        dept_obj['projects'] = projects_by_dept.get(dept_id, [])
        departments.append(dept_obj)

    # ── Compute statistics ──────────────────────────────────────────
    num_departments = len(departments)
    total_employees = sum(len(d['employees']) for d in departments)
    total_budget = sum(d['budget'] for d in departments)

    avg_budget = total_budget / num_departments if num_departments > 0 else 0
    if isinstance(avg_budget, float) and avg_budget == math.floor(avg_budget):
        avg_budget = int(avg_budget)

    skill_dist = defaultdict(int)
    total_years = 0
    for d in departments:
        for emp in d['employees']:
            for skill in emp['skills']:
                skill_dist[skill] += 1
            total_years += emp['years_of_service']

    avg_years = total_years / total_employees if total_employees > 0 else 0

    dept_sizes = {d['name']: len(d['employees']) for d in departments}

    status_dist = defaultdict(int)
    for d in departments:
        for proj in d['projects']:
            status_dist[proj['status']] += 1

    # ── Assemble output ─────────────────────────────────────────────
    output = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'generator': 'organization-json-generator'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2000-01-01',
            'departments': departments
        },
        'statistics': {
            'averageDepartmentBudget': avg_budget,
            'totalEmployees': total_employees,
            'skillDistribution': dict(skill_dist),
            'departmentSizes': dept_sizes,
            'projectStatusDistribution': dict(status_dist),
            'averageYearsOfService': avg_years
        }
    }

    # ── Write output ────────────────────────────────────────────────
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_path}")

    # ── Validate against schema ─────────────────────────────────────
    try:
        import jsonschema
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        jsonschema.validate(output, schema)
        print("Schema validation passed!")
    except ImportError:
        print("Warning: jsonschema not available for validation")
    except Exception as e:
        print(f"Schema validation FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
