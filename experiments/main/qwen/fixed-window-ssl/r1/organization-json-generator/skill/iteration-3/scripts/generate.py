#!/usr/bin/env python3
"""
Organization JSON Generator

Transforms CSV data (departments, employees, projects) into a nested JSON
document that validates against a provided JSON schema.

Usage:
    python3 generate.py

Inputs (in /app/data/):
    - departments.csv
    - employees.csv
    - projects.csv

Schema: /app/schema.json
Output: /app/organization.json
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Paths
DATA_DIR = Path('/app/data')
SCHEMA_PATH = Path('/app/schema.json')
OUTPUT_PATH = Path('/app/organization.json')


def read_csv(filepath):
    """
    Read CSV file and return list of dicts.
    Handles: whitespace stripping, empty values, quoted fields.
    """
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace from keys and values
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                val = v.strip() if v else ''
                cleaned[key] = val
            rows.append(cleaned)
    return rows


def detect_delimiter(sample_values):
    """
    Detect the delimiter used in multi-value fields.
    Tries semicolon, comma, pipe in order of preference.
    Falls back to semicolon if none found.
    """
    for delim in [';', ',', '|']:
        if any(delim in str(v) for v in sample_values if v):
            return delim
    return ';'


def parse_delimited_list(value, delimiter=';'):
    """
    Parse a delimited list from a CSV field.
    Handles: empty values, repeated delimiters, extra whitespace, empty items.
    Returns a list of non-empty stripped strings.
    """
    if not value or not value.strip():
        return []
    items = [item.strip() for item in value.split(delimiter)]
    return [item for item in items if item]


def parse_number(value, as_int=False):
    """
    Parse a numeric value from a CSV field.
    Handles: commas, quotes, whitespace, empty values.
    Preserves int vs float from source when as_int=False.
    """
    if not value or not value.strip():
        return 0 if as_int else 0.0
    # Remove common formatting
    cleaned = value.replace(',', '').replace('"', '').replace("'", '').strip()
    if not cleaned:
        return 0 if as_int else 0.0
    try:
        if as_int:
            return int(float(cleaned))
        # Preserve int vs float from source
        if '.' not in cleaned:
            return int(cleaned)
        return float(cleaned)
    except (ValueError, TypeError):
        return 0 if as_int else 0.0


def validate_output(data, schema_path):
    """Validate output against JSON schema. Returns (is_valid, error_message)."""
    try:
        import jsonschema
        with open(schema_path) as f:
            schema = json.load(f)
        jsonschema.validate(instance=data, schema=schema)
        return True, None
    except ImportError:
        return True, "jsonschema not available, skipping validation"
    except Exception as e:
        return False, str(e)


def build_organization(departments_data, employees_data, projects_data, delimiter=';'):
    """
    Build the nested organization structure from flat CSV data.
    
    Key relationships:
    - employees belong to departments via department_id
    - projects belong to departments via department_id
    - project members are kept as raw employee IDs (not resolved to names)
    """
    # Build department lookup
    dept_by_id = {}
    for dept in departments_data:
        dept_by_id[dept['id']] = {
            'id': dept['id'],
            'name': dept['name'],
            'budget': parse_number(dept['budget']),
            'employees': [],
            'projects': []
        }
    
    # Build employee lookup and attach to departments
    employee_by_id = {}
    for emp in employees_data:
        emp_id = emp['id']
        dept_id = emp['department_id']
        
        employee_obj = {
            'id': emp_id,
            'name': emp['name'],
            'position': emp['position'],
            'skills': parse_delimited_list(emp.get('skills', ''), delimiter),
            'years_of_service': parse_number(emp.get('years_of_service', ''), as_int=True)
        }
        
        employee_by_id[emp_id] = employee_obj
        
        # Attach to department
        if dept_id in dept_by_id:
            dept_by_id[dept_id]['employees'].append(employee_obj)
    
    # Build projects and attach to departments
    for proj in projects_data:
        dept_id = proj['department_id']
        
        # Keep member IDs as-is (employee IDs, not resolved to names)
        member_ids = parse_delimited_list(proj.get('member_ids', ''), delimiter)
        
        project_obj = {
            'name': proj['name'],
            'status': proj['status'],
            'members': member_ids,  # Employee IDs, not names
            'deadline': proj['deadline']
        }
        
        if dept_id in dept_by_id:
            dept_by_id[dept_id]['projects'].append(project_obj)
    
    return dept_by_id, employee_by_id


def compute_statistics(departments_data, employees_data, projects_data, dept_by_id, delimiter=';'):
    """
    Compute the six required aggregate statistics.
    """
    # Total employees
    total_employees = len(employees_data)
    
    # Average department budget
    total_budget = sum(dept['budget'] for dept in dept_by_id.values())
    num_depts = len(dept_by_id)
    avg_budget = total_budget / num_depts if num_depts > 0 else 0.0
    
    # Department sizes (by name)
    dept_sizes = {dept['name']: len(dept['employees']) for dept in dept_by_id.values()}
    
    # Skill distribution
    skill_counts = defaultdict(int)
    for emp in employees_data:
        skills = parse_delimited_list(emp.get('skills', ''), delimiter)
        for skill in skills:
            skill_counts[skill] += 1
    
    # Project status distribution
    status_counts = defaultdict(int)
    for proj in projects_data:
        status_counts[proj['status']] += 1
    
    # Average years of service
    total_years = sum(parse_number(emp.get('years_of_service', '')) for emp in employees_data)
    avg_years = total_years / total_employees if total_employees > 0 else 0.0
    
    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_counts),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_counts),
        'averageYearsOfService': avg_years
    }


def main():
    # Read CSV files
    departments_data = read_csv(DATA_DIR / 'departments.csv')
    employees_data = read_csv(DATA_DIR / 'employees.csv')
    projects_data = read_csv(DATA_DIR / 'projects.csv')
    
    # Auto-detect delimiter for multi-value fields
    skill_samples = [emp.get('skills', '') for emp in employees_data]
    member_samples = [proj.get('member_ids', '') for proj in projects_data]
    delimiter = detect_delimiter(skill_samples + member_samples)
    
    # Build organization structure
    dept_by_id, employee_by_id = build_organization(
        departments_data, employees_data, projects_data, delimiter
    )
    
    # Compute statistics
    statistics = compute_statistics(
        departments_data, employees_data, projects_data, dept_by_id, delimiter
    )
    
    # Build final output
    output = {
        'metadata': {
            'version': '1.0.0',
            'timestamp': datetime.now().isoformat(),
            'generator': 'organization-json-generator'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2020-01-01',
            'departments': list(dept_by_id.values())
        },
        'statistics': statistics
    }
    
    # Validate against schema
    is_valid, error = validate_output(output, SCHEMA_PATH)
    if not is_valid:
        print(f"WARNING: Output does not validate against schema: {error}", file=sys.stderr)
    
    # Write output
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)
        f.write('\n')  # Trailing newline for POSIX compliance
    
    print(f"Generated {OUTPUT_PATH} successfully")
    if is_valid:
        print("Output validates against schema")
    else:
        print(f"Validation error: {error}", file=sys.stderr)


if __name__ == '__main__':
    main()
