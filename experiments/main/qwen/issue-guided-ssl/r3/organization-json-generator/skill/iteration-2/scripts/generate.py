#!/usr/bin/env python3
"""
CSV to Organization JSON Generator

Implements a 5-stage pipeline:
1. Parse: Read CSV files and split fields
2. Normalize: Clean whitespace, coerce types, split delimited lists
3. Index: Build lookup structures by department
4. Assemble: Construct nested JSON structure (schema-driven field selection)
5. Summarize: Compute aggregate statistics

Handles family variations:
- Empty project member lists
- Departments with no projects or employees
- Semicolon-list normalization with empty-element filtering
- Whitespace trimming and type coercion
- Various data distributions for statistics
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# ── Stage 1: Parse ──────────────────────────────────────────────────────────

def parse_csv(filepath):
    """Read CSV file into list of dicts keyed by column headers."""
    with open(filepath, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


# ── Stage 2: Normalize ─────────────────────────────────────────────────────

def normalize_string(value):
    """Strip whitespace from string fields."""
    return value.strip() if value else ""


def normalize_int(value):
    """Strip whitespace, remove commas, convert to int."""
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(',', '')
    return int(float(cleaned))


def normalize_number(value):
    """
    Strip whitespace, remove commas, convert to number.
    Preserves int when source has no decimal component.
    """
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(',', '')
    f = float(cleaned)
    # Preserve as int if no fractional part
    if f == int(f) and '.' not in cleaned:
        return int(f)
    return f


def normalize_semicolon_list(value):
    """Split on ';', strip each element, filter empty strings."""
    if not value or not value.strip():
        return []
    parts = value.split(';')
    return [p.strip() for p in parts if p.strip()]


def normalize_departments(rows):
    """Normalize department records."""
    result = []
    for row in rows:
        result.append({
            'id': normalize_string(row.get('id', '')),
            'name': normalize_string(row.get('name', '')),
            'budget': normalize_number(row.get('budget', '0')),
        })
    return result


def normalize_employees(rows):
    """Normalize employee records (includes department_id for indexing)."""
    result = []
    for row in rows:
        result.append({
            'id': normalize_string(row.get('id', '')),
            'name': normalize_string(row.get('name', '')),
            'position': normalize_string(row.get('position', '')),
            'skills': normalize_semicolon_list(row.get('skills', '')),
            'years_of_service': normalize_int(row.get('years_of_service', '0')),
            'department_id': normalize_string(row.get('department_id', '')),
        })
    return result


def normalize_projects(rows):
    """Normalize project records (includes department_id for indexing)."""
    result = []
    for row in rows:
        result.append({
            'name': normalize_string(row.get('name', '')),
            'status': normalize_string(row.get('status', '')),
            'members': normalize_semicolon_list(row.get('member_ids', '')),
            'deadline': normalize_string(row.get('deadline', '')),
            'department_id': normalize_string(row.get('department_id', '')),
        })
    return result


# ── Stage 3: Index ──────────────────────────────────────────────────────────

def build_indexes(departments, employees, projects):
    """Build lookup structures for efficient assembly."""
    dept_by_id = {d['id']: d for d in departments}

    employees_by_dept = defaultdict(list)
    for emp in employees:
        if emp['department_id']:
            employees_by_dept[emp['department_id']].append(emp)

    projects_by_dept = defaultdict(list)
    for proj in projects:
        if proj['department_id']:
            projects_by_dept[proj['department_id']].append(proj)

    return dept_by_id, employees_by_dept, projects_by_dept


# ── Stage 4: Assemble ───────────────────────────────────────────────────────

# Exact output fields per entity type (schema-driven).
# department_id is an internal relationship key — NOT included in output.
DEPARTMENT_OUTPUT_FIELDS = ('id', 'name', 'budget', 'employees', 'projects')
EMPLOYEE_OUTPUT_FIELDS = ('id', 'name', 'position', 'skills', 'years_of_service')
PROJECT_OUTPUT_FIELDS = ('name', 'status', 'members', 'deadline')


def assemble(departments, employees_by_dept, projects_by_dept):
    """
    Construct nested JSON structure.
    Only schema-defined fields are included in output objects.
    The department_id column is stripped — it was only used for indexing.
    """
    dept_list = []
    for dept in departments:
        dept_id = dept['id']

        # Build clean employee objects (only schema fields, no department_id)
        clean_employees = []
        for emp in employees_by_dept.get(dept_id, []):
            clean_employees.append({
                k: emp[k] for k in EMPLOYEE_OUTPUT_FIELDS
            })

        # Build clean project objects (only schema fields, no department_id)
        clean_projects = []
        for proj in projects_by_dept.get(dept_id, []):
            clean_projects.append({
                k: proj[k] for k in PROJECT_OUTPUT_FIELDS
            })

        dept_list.append({
            'id': dept['id'],
            'name': dept['name'],
            'budget': dept['budget'],
            'employees': clean_employees,
            'projects': clean_projects,
        })
    return dept_list


# ── Stage 5: Summarize ──────────────────────────────────────────────────────

def compute_statistics(departments):
    """Compute aggregate statistics from assembled department data."""
    budgets = [d['budget'] for d in departments]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0.0

    all_employees = []
    for d in departments:
        all_employees.extend(d['employees'])
    total_employees = len(all_employees)

    skill_dist = defaultdict(int)
    for emp in all_employees:
        for skill in emp['skills']:
            skill_dist[skill] += 1

    dept_sizes = {}
    for d in departments:
        dept_sizes[d['name']] = len(d['employees'])

    status_dist = defaultdict(int)
    for d in departments:
        for proj in d['projects']:
            status_dist[proj['status']] += 1

    years = [emp['years_of_service'] for emp in all_employees]
    avg_years = sum(years) / len(years) if years else 0.0

    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_dist),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_dist),
        'averageYearsOfService': avg_years,
    }


# ── Main Pipeline ───────────────────────────────────────────────────────────

def main():
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else '/app/data')
    schema_path = Path(sys.argv[2] if len(sys.argv) > 2 else '/app/schema.json')
    output_path = Path(sys.argv[3] if len(sys.argv) > 3 else '/app/organization.json')

    # Stage 1: Parse
    dept_rows = parse_csv(data_dir / 'departments.csv')
    emp_rows = parse_csv(data_dir / 'employees.csv')
    proj_rows = parse_csv(data_dir / 'projects.csv')

    # Stage 2: Normalize
    departments = normalize_departments(dept_rows)
    employees = normalize_employees(emp_rows)
    projects = normalize_projects(proj_rows)

    # Stage 3: Index
    dept_by_id, employees_by_dept, projects_by_dept = build_indexes(
        departments, employees, projects
    )

    # Stage 4: Assemble
    dept_list = assemble(departments, employees_by_dept, projects_by_dept)

    # Stage 5: Summarize
    statistics = compute_statistics(dept_list)

    # Build final output
    output = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'generator': 'organization-json-generator',
        },
        'organization': {
            'name': 'Organization',
            'founded': '2000-01-01',
            'departments': dept_list,
        },
        'statistics': statistics,
    }

    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Validate against schema
    if HAS_JSONSCHEMA and schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        try:
            jsonschema.validate(output, schema)
        except jsonschema.exceptions.ValidationError as e:
            print(f"WARNING: Schema validation failed: {e.message}", file=sys.stderr)
            print(f"Path: {list(e.path)}", file=sys.stderr)

    print(f"✓ Output written to {output_path}")
    print(f"  Departments: {len(dept_list)}")
    print(f"  Total employees: {statistics['totalEmployees']}")
    print(f"  Total projects: {sum(len(d['projects']) for d in dept_list)}")


if __name__ == '__main__':
    main()
