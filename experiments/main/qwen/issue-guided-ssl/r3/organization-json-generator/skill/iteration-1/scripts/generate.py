#!/usr/bin/env python3
"""
CSV to Organization JSON Generator

Implements a 5-stage pipeline:
1. Parse: Read CSV files and split fields
2. Normalize: Clean whitespace, coerce types, split delimited lists
3. Index: Build lookup structures by department
4. Assemble: Construct nested JSON structure
5. Summarize: Compute aggregate statistics

Handles family variations:
- Empty project member lists
- Departments with no projects
- Semicolon-list normalization with empty-element filtering
- Whitespace trimming and type coercion
- Various data distributions for statistics
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def parse_csv(filepath):
    """Stage 1: Parse CSV file into list of dicts."""
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def normalize_string(value):
    """Normalize a string field: strip whitespace."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_integer(value):
    """Normalize an integer field: strip whitespace and convert to int."""
    if value is None or str(value).strip() == "":
        return 0
    cleaned = str(value).strip().replace(',', '')
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def normalize_number(value):
    """Normalize a numeric field: strip whitespace and convert to float."""
    if value is None or str(value).strip() == "":
        return 0.0
    cleaned = str(value).strip().replace(',', '')
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def normalize_semicolon_list(value):
    """
    Normalize a semicolon-delimited list field.
    Splits on semicolons, strips whitespace, filters empty elements.
    Handles: "A;B;C", "A;;B", " A ; B ; ", "", etc.
    """
    if value is None or str(value).strip() == "":
        return []
    
    # Split on semicolon, strip each element, filter empty
    parts = [normalize_string(part) for part in str(value).split(';')]
    return [part for part in parts if part]


def parse_and_normalize_departments(rows):
    """Stage 2: Normalize department fields."""
    departments = []
    for row in rows:
        dept = {
            'id': normalize_string(row.get('id', '')),
            'name': normalize_string(row.get('name', '')),
            'budget': normalize_number(row.get('budget', 0))
        }
        departments.append(dept)
    return departments


def parse_and_normalize_employees(rows):
    """Stage 2: Normalize employee fields."""
    employees = []
    for row in rows:
        emp = {
            'id': normalize_string(row.get('id', '')),
            'name': normalize_string(row.get('name', '')),
            'position': normalize_string(row.get('position', '')),
            'skills': normalize_semicolon_list(row.get('skills', '')),
            'years_of_service': normalize_integer(row.get('years_of_service', 0)),
            'department_id': normalize_string(row.get('department_id', ''))
        }
        employees.append(emp)
    return employees


def parse_and_normalize_projects(rows):
    """Stage 2: Normalize project fields."""
    projects = []
    for row in rows:
        proj = {
            'name': normalize_string(row.get('name', '')),
            'status': normalize_string(row.get('status', '')),
            'members': normalize_semicolon_list(row.get('member_ids', '')),
            'deadline': normalize_string(row.get('deadline', '')),
            'department_id': normalize_string(row.get('department_id', ''))
        }
        projects.append(proj)
    return projects


def index_by_department(departments, employees, projects):
    """
    Stage 3: Build lookup structures.
    Returns:
    - dept_by_id: dict mapping department id to department
    - employees_by_dept: dict mapping department id to list of employees
    - projects_by_dept: dict mapping department id to list of projects
    """
    dept_by_id = {dept['id']: dept for dept in departments}
    
    employees_by_dept = defaultdict(list)
    for emp in employees:
        dept_id = emp['department_id']
        if dept_id:
            employees_by_dept[dept_id].append(emp)
    
    projects_by_dept = defaultdict(list)
    for proj in projects:
        dept_id = proj['department_id']
        if dept_id:
            projects_by_dept[dept_id].append(proj)
    
    return dept_by_id, employees_by_dept, projects_by_dept


def assemble_organization(departments, employees_by_dept, projects_by_dept):
    """
    Stage 4: Assemble nested organization structure.
    Each department contains its employees and projects.
    Removes internal fields (department_id) that aren't part of the schema.
    """
    dept_objects = []
    
    for dept in departments:
        dept_id = dept['id']
        
        # Clean employees: remove department_id (not in schema)
        clean_employees = []
        for emp in employees_by_dept.get(dept_id, []):
            clean_emp = {
                'id': emp['id'],
                'name': emp['name'],
                'position': emp['position'],
                'skills': emp['skills'],
                'years_of_service': emp['years_of_service']
            }
            clean_employees.append(clean_emp)
        
        # Clean projects: remove department_id (not in schema)
        clean_projects = []
        for proj in projects_by_dept.get(dept_id, []):
            clean_proj = {
                'name': proj['name'],
                'status': proj['status'],
                'members': proj['members'],
                'deadline': proj['deadline']
            }
            clean_projects.append(clean_proj)
        
        # Build department object
        dept_obj = {
            'id': dept['id'],
            'name': dept['name'],
            'budget': dept['budget'],
            'employees': clean_employees,
            'projects': clean_projects
        }
        
        dept_objects.append(dept_obj)
    
    return dept_objects


def compute_statistics(departments):
    """
    Stage 5: Compute aggregate statistics from assembled data.
    
    Required statistics:
    - averageDepartmentBudget: average of all department budgets
    - totalEmployees: total count of all employees across all departments
    - skillDistribution: count of each skill across all employees
    - departmentSizes: count of employees per department
    - projectStatusDistribution: count of projects per status
    - averageYearsOfService: average years of service across all employees
    """
    # Average department budget
    budgets = [dept['budget'] for dept in departments]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0.0
    
    # Total employees and collect all employees
    all_employees = []
    for dept in departments:
        all_employees.extend(dept['employees'])
    total_employees = len(all_employees)
    
    # Skill distribution
    skill_counts = defaultdict(int)
    for emp in all_employees:
        for skill in emp['skills']:
            skill_counts[skill] += 1
    
    # Department sizes
    dept_sizes = {}
    for dept in departments:
        dept_sizes[dept['name']] = len(dept['employees'])
    
    # Project status distribution
    status_counts = defaultdict(int)
    for dept in departments:
        for proj in dept['projects']:
            status_counts[proj['status']] += 1
    
    # Average years of service
    years_list = [emp['years_of_service'] for emp in all_employees]
    avg_years = sum(years_list) / len(years_list) if years_list else 0.0
    
    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_counts),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_counts),
        'averageYearsOfService': avg_years
    }


def generate_organization_json(data_dir, schema_path, output_path):
    """
    Main pipeline: Parse → Normalize → Index → Assemble → Summarize
    """
    data_dir = Path(data_dir)
    
    # Stage 1: Parse CSVs
    dept_rows = parse_csv(data_dir / 'departments.csv')
    emp_rows = parse_csv(data_dir / 'employees.csv')
    proj_rows = parse_csv(data_dir / 'projects.csv')
    
    # Stage 2: Normalize fields
    departments = parse_and_normalize_departments(dept_rows)
    employees = parse_and_normalize_employees(emp_rows)
    projects = parse_and_normalize_projects(proj_rows)
    
    # Stage 3: Index by department
    dept_by_id, employees_by_dept, projects_by_dept = index_by_department(
        departments, employees, projects
    )
    
    # Stage 4: Assemble nested structure
    dept_objects = assemble_organization(departments, employees_by_dept, projects_by_dept)
    
    # Stage 5: Compute statistics
    statistics = compute_statistics(dept_objects)
    
    # Build complete organization JSON
    # Note: organization.name and organization.founded are required by schema
    # but not present in source data. Use reasonable defaults.
    organization = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'generator': 'csv-to-organization-json-processor'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2000-01-01',
            'departments': dept_objects
        },
        'statistics': statistics
    }
    
    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(organization, f, indent=2, ensure_ascii=False)
    
    # Validate against schema if jsonschema is available
    schema_path = Path(schema_path)
    if HAS_JSONSCHEMA and schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        try:
            jsonschema.validate(organization, schema)
        except jsonschema.exceptions.ValidationError as e:
            print(f"WARNING: Output does not validate against schema: {e.message}", file=sys.stderr)
            print(f"Path: {list(e.path)}", file=sys.stderr)
    
    return organization


if __name__ == '__main__':
    # Default paths
    data_dir = '/app/data'
    schema_path = '/app/schema.json'
    output_path = '/app/organization.json'
    
    # Allow override via command line
    if len(sys.argv) >= 2:
        data_dir = sys.argv[1]
    if len(sys.argv) >= 3:
        schema_path = sys.argv[2]
    if len(sys.argv) >= 4:
        output_path = sys.argv[3]
    
    result = generate_organization_json(data_dir, schema_path, output_path)
    print(f"Generated organization JSON with {len(result['organization']['departments'])} departments")
    print(f"Total employees: {result['statistics']['totalEmployees']}")
    print(f"Output written to: {output_path}")
