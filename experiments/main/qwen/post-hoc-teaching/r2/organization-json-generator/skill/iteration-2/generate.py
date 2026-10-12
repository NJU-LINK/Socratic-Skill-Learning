#!/usr/bin/env python3
"""
Organization JSON Generator
Transforms CSV data (departments, employees, projects) into a nested organization JSON
conforming to a given JSON schema.

Usage:
    python3 generate.py

Environment variables (optional overrides):
    DATA_DIR     - Directory containing CSV files (default: /app/data)
    SCHEMA_PATH  - Path to schema.json (default: /app/schema.json)
    OUTPUT_PATH  - Path for output JSON (default: /app/organization.json)
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict


def read_csv(filepath):
    """Read a CSV file and return list of dicts, handling whitespace, quoting, and None values.
    
    When csv.DictReader encounters rows with fewer fields than the header, it assigns
    None to missing fields. This function coerces None to empty string so downstream
    code can safely call .strip() on any value.
    """
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                val = v.strip() if v is not None else ''
                cleaned[key] = val
            rows.append(cleaned)
    return rows


def parse_semicolon_list(value):
    """Parse a semicolon-delimited string into a list of stripped, non-empty strings.
    
    Handles:
    - Empty/None values → []
    - Extra whitespace → stripped
    - Repeated delimiters (e.g. 'a;;b') → ['a', 'b']
    - Single values → [value]
    """
    if not value or not value.strip():
        return []
    parts = value.split(';')
    return [p.strip() for p in parts if p.strip()]


def parse_int(value):
    """Parse a string to integer, handling float-formatted and comma-formatted numbers.
    
    Handles:
    - Plain integers: "10" → 10
    - Float-formatted: "10.0" → 10, "10.7" → 10
    - Comma-separated: "1,000" → 1000
    - Whitespace: " 10 " → 10
    - None/empty: None → 0
    """
    if value is None:
        return 0
    cleaned = value.strip().replace(',', '')
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        # Handle "10.0" → 10, "10.7" → 10
        return int(float(cleaned))


def parse_number(value):
    """Parse a string to a number. Returns int if whole number, float otherwise.
    
    Handles:
    - Plain integers: "1500000" → 1500000
    - Plain floats: "1500000.5" → 1500000.5
    - Comma-separated: "1,500,000" → 1500000
    - Whitespace: " 1500000 " → 1500000
    """
    if value is None:
        return 0
    cleaned = value.strip().replace(',', '')
    try:
        return int(cleaned)
    except ValueError:
        return float(cleaned)


def build_organization(departments_csv, employees_csv, projects_csv):
    """Build the nested organization structure from CSV data.
    
    Returns a list of department records, each containing:
    - id, name, budget (from departments.csv)
    - employees: list of employee objects with parsed skills and years_of_service
    - projects: list of project objects with parsed member_ids
    """
    departments = read_csv(departments_csv)
    employees = read_csv(employees_csv)
    projects = read_csv(projects_csv)
    
    # Group employees by department_id
    emp_by_dept = defaultdict(list)
    for emp in employees:
        dept_id = emp.get('department_id', '').strip()
        emp_by_dept[dept_id].append({
            'id': emp['id'].strip(),
            'name': emp['name'].strip(),
            'position': emp['position'].strip(),
            'skills': parse_semicolon_list(emp.get('skills', '')),
            'years_of_service': parse_int(emp.get('years_of_service', '0'))
        })
    
    # Group projects by department_id
    proj_by_dept = defaultdict(list)
    for proj in projects:
        dept_id = proj.get('department_id', '').strip()
        member_ids = parse_semicolon_list(proj.get('member_ids', ''))
        proj_by_dept[dept_id].append({
            'name': proj['name'].strip(),
            'status': proj['status'].strip(),
            'members': member_ids,
            'deadline': proj['deadline'].strip()
        })
    
    # Build department records (preserve order from departments.csv)
    dept_records = []
    for dept in departments:
        dept_id = dept['id'].strip()
        dept_record = {
            'id': dept_id,
            'name': dept['name'].strip(),
            'budget': parse_number(dept.get('budget', '0')),
            'employees': emp_by_dept.get(dept_id, []),
            'projects': proj_by_dept.get(dept_id, [])
        }
        dept_records.append(dept_record)
    
    return dept_records


def compute_statistics(dept_records):
    """Compute aggregate statistics from the assembled organization data.
    
    Returns dict with:
    - averageDepartmentBudget: float
    - totalEmployees: int
    - skillDistribution: {skill_name: count}
    - departmentSizes: {dept_name: employee_count}
    - projectStatusDistribution: {status: count}
    - averageYearsOfService: float
    """
    # Average department budget
    budgets = [d['budget'] for d in dept_records]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0.0
    
    # Total employees
    total_employees = sum(len(d['employees']) for d in dept_records)
    
    # Skill distribution: count each skill across all employees
    skill_dist = defaultdict(int)
    for d in dept_records:
        for emp in d['employees']:
            for skill in emp['skills']:
                skill_dist[skill] += 1
    
    # Department sizes: employee count per department (keyed by name)
    dept_sizes = {}
    for d in dept_records:
        dept_sizes[d['name']] = len(d['employees'])
    
    # Project status distribution
    status_dist = defaultdict(int)
    for d in dept_records:
        for proj in d['projects']:
            status_dist[proj['status']] += 1
    
    # Average years of service
    all_years = []
    for d in dept_records:
        for emp in d['employees']:
            all_years.append(emp['years_of_service'])
    avg_years = sum(all_years) / len(all_years) if all_years else 0.0
    
    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_dist),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_dist),
        'averageYearsOfService': avg_years
    }


def main():
    # Default paths
    data_dir = '/app/data'
    schema_path = '/app/schema.json'
    output_path = '/app/organization.json'
    
    # Allow overrides via environment variables
    data_dir = os.environ.get('DATA_DIR', data_dir)
    schema_path = os.environ.get('SCHEMA_PATH', schema_path)
    output_path = os.environ.get('OUTPUT_PATH', output_path)
    
    departments_csv = os.path.join(data_dir, 'departments.csv')
    employees_csv = os.path.join(data_dir, 'employees.csv')
    projects_csv = os.path.join(data_dir, 'projects.csv')
    
    # Build organization structure
    dept_records = build_organization(departments_csv, employees_csv, projects_csv)
    
    # Compute statistics
    statistics = compute_statistics(dept_records)
    
    # Build the full output
    output = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'generator': 'organization-json-generator'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2020-01-01',
            'departments': dept_records
        },
        'statistics': statistics
    }
    
    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Generated {output_path} successfully.")
    print(f"  Departments: {len(dept_records)}")
    print(f"  Total employees: {statistics['totalEmployees']}")
    print(f"  Total projects: {sum(len(d['projects']) for d in dept_records)}")
    
    # Validate against schema if jsonschema is available
    try:
        import jsonschema
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        jsonschema.validate(output, schema)
        print(f"  Schema validation: PASSED")
    except ImportError:
        print(f"  Schema validation: SKIPPED (jsonschema not available)")
    except Exception as e:
        print(f"  Schema validation: FAILED - {e}")


if __name__ == '__main__':
    main()
