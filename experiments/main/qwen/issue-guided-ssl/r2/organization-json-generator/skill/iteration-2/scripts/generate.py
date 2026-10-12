#!/usr/bin/env python3
"""
Organization JSON Generator
Transforms CSV data (departments, employees, projects) into a nested
organization JSON file conforming to the provided schema.

Three-stage pipeline:
  1. CSV Parsing with dynamic column detection and normalization
  2. Relationship Assembly (department → employees + projects)
  3. Statistics Computation + JSON Output

Usage:
  python3 generate.py [data_dir] [output_path]
  Defaults: data_dir=/app/data, output_path=/app/organization.json
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone


# ─── Column Name Detection ──────────────────────────────────────────────────

# Aliases for each expected field. The first entry is the canonical name.
# When a CSV header matches any alias (case-insensitive, underscore-normalized),
# it maps to the canonical field name.
COLUMN_ALIASES = {
    'departments': {
        'id': ['id', 'department_id', 'dept_id'],
        'name': ['name', 'department_name', 'dept_name'],
        'budget': ['budget', 'dept_budget', 'annual_budget'],
    },
    'employees': {
        'id': ['id', 'employee_id', 'emp_id'],
        'name': ['name', 'employee_name', 'emp_name', 'full_name'],
        'position': ['position', 'role', 'title', 'job_title'],
        'skills': ['skills', 'skill_set', 'competencies'],
        'years_of_service': ['years_of_service', 'years', 'yos', 'tenure',
                             'experience_years', 'years_of_experience'],
        'department_id': ['department_id', 'dept_id', 'department', 'dept'],
    },
    'projects': {
        'name': ['name', 'project_name'],
        'status': ['status', 'project_status', 'state'],
        'member_ids': ['member_ids', 'members', 'employee_ids',
                       'team_members', 'project_members'],
        'deadline': ['deadline', 'due_date', 'end_date', 'target_date'],
        'department_id': ['department_id', 'dept_id', 'department', 'dept'],
    },
}

# Fields that MUST be present in each CSV type (fail loudly if missing)
REQUIRED_COLUMNS = {
    'departments': ['id', 'name', 'budget'],
    'employees': ['id', 'name', 'position', 'skills', 'years_of_service',
                  'department_id'],
    'projects': ['name', 'status', 'member_ids', 'deadline', 'department_id'],
}


def normalize_header(h):
    """Normalize a header name for matching: lowercase, strip, replace spaces with underscores."""
    return h.strip().lower().replace(' ', '_')


def detect_columns(actual_headers, csv_type):
    """
    Map expected field names to actual CSV column names.
    
    Args:
        actual_headers: list of column names from the CSV header row
        csv_type: one of 'departments', 'employees', 'projects'
    
    Returns:
        dict mapping canonical field name -> actual CSV column name
    
    Raises:
        ValueError if a required column cannot be found
    """
    # Build normalized -> original mapping
    norm_to_actual = {}
    for h in actual_headers:
        norm_to_actual[normalize_header(h)] = h.strip()

    aliases = COLUMN_ALIASES[csv_type]
    mapping = {}
    missing = []

    for canonical_name, alias_list in aliases.items():
        found = False
        for alias in alias_list:
            norm_alias = normalize_header(alias)
            if norm_alias in norm_to_actual:
                mapping[canonical_name] = norm_to_actual[norm_alias]
                found = True
                break
        if not found:
            mapping[canonical_name] = None
            if canonical_name in REQUIRED_COLUMNS[csv_type]:
                missing.append(canonical_name)

    if missing:
        raise ValueError(
            f"CSV file '{csv_type}' is missing required column(s): {missing}. "
            f"Available columns: {list(actual_headers)}. "
            f"Expected aliases: {aliases}"
        )

    return mapping


def get_field(row, col_map, field_name, default=''):
    """Safely get a field value from a row using the column mapping."""
    actual_col = col_map.get(field_name)
    if actual_col is None:
        return default
    return row.get(actual_col, default) or default


# ─── Normalization helpers ───────────────────────────────────────────────────

def parse_list_field(value):
    """Parse semicolon-delimited field into a clean list of strings.
    Handles: extra whitespace, repeated delimiters (;;), empty fields.
    """
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(';') if item.strip()]


def parse_number(value):
    """Parse a numeric string, handling commas, whitespace, and different formats.
    Returns int if the value is a whole number, float otherwise.
    """
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(',', '').replace('"', '').replace("'", "")
    if '.' in cleaned:
        return float(cleaned)
    return int(cleaned)


def parse_int(value):
    """Parse an integer field."""
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(',', '').replace('"', '').replace("'", "")
    return int(float(cleaned))  # handle "10.0" style inputs


def parse_string(value):
    """Parse a string field, stripping whitespace and residual quotes."""
    if value is None:
        return ""
    return value.strip().strip('"').strip("'").strip()


def parse_date(value):
    """Parse and normalize a date field to ISO format YYYY-MM-DD."""
    if not value or not value.strip():
        return ""
    cleaned = value.strip()
    # Already in ISO format
    if len(cleaned) == 10 and cleaned[4] == '-' and cleaned[7] == '-':
        return cleaned
    # Try parsing common formats
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(cleaned, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return cleaned


# ─── Stage 1: CSV Parsing ───────────────────────────────────────────────────

def read_csv(filepath):
    """Read a CSV file and return (headers, rows) with stripped keys/values.
    Uses utf-8-sig encoding to handle BOM (Byte Order Mark) if present.
    """
    rows = []
    headers = None
    with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames) if reader.fieldnames else []
        for row in reader:
            # Strip whitespace from keys and values, handle None values
            cleaned = {k.strip(): (v.strip() if v else '') for k, v in row.items() if k is not None}
            rows.append(cleaned)
    return headers, rows


def parse_departments(rows, col_map):
    """Parse department rows into normalized department dicts."""
    departments = []
    for row in rows:
        dept = {
            'id': parse_string(get_field(row, col_map, 'id')),
            'name': parse_string(get_field(row, col_map, 'name')),
            'budget': parse_number(get_field(row, col_map, 'budget', '0')),
        }
        departments.append(dept)
    return departments


def parse_employees(rows, col_map):
    """Parse employee rows into normalized employee dicts."""
    employees = []
    for row in rows:
        emp = {
            'id': parse_string(get_field(row, col_map, 'id')),
            'name': parse_string(get_field(row, col_map, 'name')),
            'position': parse_string(get_field(row, col_map, 'position')),
            'skills': parse_list_field(get_field(row, col_map, 'skills')),
            'years_of_service': parse_int(get_field(row, col_map, 'years_of_service', '0')),
            'department_id': parse_string(get_field(row, col_map, 'department_id')),
        }
        employees.append(emp)
    return employees


def parse_projects(rows, col_map):
    """Parse project rows into normalized project dicts."""
    projects = []
    for row in rows:
        proj = {
            'name': parse_string(get_field(row, col_map, 'name')),
            'status': parse_string(get_field(row, col_map, 'status')),
            'members': parse_list_field(get_field(row, col_map, 'member_ids')),
            'deadline': parse_date(get_field(row, col_map, 'deadline')),
            'department_id': parse_string(get_field(row, col_map, 'department_id')),
        }
        projects.append(proj)
    return projects


# ─── Stage 2: Relationship Assembly ─────────────────────────────────────────

def assemble_organization(departments, employees, projects):
    """
    Build the nested organization structure:
      organization → departments[] → { employees[], projects[] }

    Groups employees and projects by department_id foreign key.
    Departments with no projects get an empty projects array.
    Projects with empty member lists get an empty members array.
    """
    # Build department map preserving original order
    dept_map = {}
    dept_order = []
    for dept in departments:
        dept_map[dept['id']] = {
            'id': dept['id'],
            'name': dept['name'],
            'budget': dept['budget'],
            'employees': [],
            'projects': [],
        }
        dept_order.append(dept['id'])

    # Group employees by department
    for emp in employees:
        dept_id = emp['department_id']
        if dept_id in dept_map:
            dept_map[dept_id]['employees'].append({
                'id': emp['id'],
                'name': emp['name'],
                'position': emp['position'],
                'skills': emp['skills'],
                'years_of_service': emp['years_of_service'],
            })

    # Group projects by department
    for proj in projects:
        dept_id = proj['department_id']
        if dept_id in dept_map:
            dept_map[dept_id]['projects'].append({
                'name': proj['name'],
                'status': proj['status'],
                'members': proj['members'],
                'deadline': proj['deadline'],
            })

    # Build ordered departments list
    return [dept_map[did] for did in dept_order]


# ─── Stage 3: Statistics + JSON Output ──────────────────────────────────────

def compute_statistics(departments_list):
    """
    Compute all required aggregate statistics from the assembled data.

    Returns dict with:
      - averageDepartmentBudget: mean of department budgets
      - totalEmployees: total count of employees across all departments
      - skillDistribution: {skill_name: count} across all employees
      - departmentSizes: {dept_name: employee_count}
      - projectStatusDistribution: {status: count} across all projects
      - averageYearsOfService: mean of all employees' years_of_service
    """
    all_employees = []
    skill_counts = defaultdict(int)
    dept_sizes = {}
    status_counts = defaultdict(int)
    total_budget = 0

    for dept in departments_list:
        total_budget += dept['budget']
        dept_sizes[dept['name']] = len(dept['employees'])

        for emp in dept['employees']:
            all_employees.append(emp)
            for skill in emp['skills']:
                skill_counts[skill] += 1

        for proj in dept['projects']:
            status_counts[proj['status']] += 1

    total_employees = len(all_employees)
    num_departments = len(departments_list)

    avg_budget = total_budget / num_departments if num_departments > 0 else 0.0
    total_yos = sum(emp['years_of_service'] for emp in all_employees)
    avg_yos = total_yos / total_employees if total_employees > 0 else 0.0

    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_counts),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_counts),
        'averageYearsOfService': avg_yos,
    }


def derive_organization_metadata(departments_list):
    """
    Derive organization-level metadata from the data.
    - name: Use a generic organization name
    - founded: Use the earliest date found in project deadlines
    """
    earliest_date = None
    for dept in departments_list:
        for proj in dept['projects']:
            if proj['deadline']:
                try:
                    d = datetime.strptime(proj['deadline'], '%Y-%m-%d')
                    if earliest_date is None or d < earliest_date:
                        earliest_date = d
                except ValueError:
                    pass

    founded = earliest_date.strftime('%Y-%m-%d') if earliest_date else '2020-01-01'
    return {'name': 'Organization', 'founded': founded}


def generate_json(data_dir='/app/data', output_path='/app/organization.json', schema_path=None):
    """Main entry point: read CSVs, assemble, compute stats, write JSON.
    
    Args:
        data_dir: Directory containing CSV files (default: /app/data)
        output_path: Path for output JSON file (default: /app/organization.json)
        schema_path: Optional path to schema.json for validation (default: None)
    """
    # Stage 1: Parse CSVs with column detection
    dept_headers, dept_rows = read_csv(os.path.join(data_dir, 'departments.csv'))
    emp_headers, emp_rows = read_csv(os.path.join(data_dir, 'employees.csv'))
    proj_headers, proj_rows = read_csv(os.path.join(data_dir, 'projects.csv'))

    # Detect column mappings (fails loudly if required columns missing)
    dept_col_map = detect_columns(dept_headers, 'departments')
    emp_col_map = detect_columns(emp_headers, 'employees')
    proj_col_map = detect_columns(proj_headers, 'projects')

    print(f"Column mappings detected:")
    print(f"  departments: {dept_col_map}")
    print(f"  employees:   {emp_col_map}")
    print(f"  projects:    {proj_col_map}")

    departments = parse_departments(dept_rows, dept_col_map)
    employees = parse_employees(emp_rows, emp_col_map)
    projects = parse_projects(proj_rows, proj_col_map)

    # Stage 2: Assemble nested structure
    departments_list = assemble_organization(departments, employees, projects)

    # Stage 3: Compute statistics and build output
    statistics = compute_statistics(departments_list)
    org_meta = derive_organization_metadata(departments_list)

    # Build metadata
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    output = {
        'metadata': {
            'version': '1.0',
            'timestamp': timestamp,
            'generator': 'organization-json-generator',
        },
        'organization': {
            'name': org_meta['name'],
            'founded': org_meta['founded'],
            'departments': departments_list,
        },
        'statistics': statistics,
    }

    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_path} successfully.")
    
    # Optional schema validation
    if schema_path and os.path.exists(schema_path):
        try:
            import jsonschema
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            jsonschema.validate(output, schema)
            print(f"✓ Output validates against schema: {schema_path}")
        except ImportError:
            print("⚠ jsonschema not available, skipping validation")
        except Exception as e:
            print(f"✗ Schema validation failed: {e}")
            raise
    
    return output


if __name__ == '__main__':
    data_dir = sys.argv[1] if len(sys.argv) > 1 else '/app/data'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/organization.json'
    schema_path = sys.argv[3] if len(sys.argv) > 3 else None
    # Auto-detect schema if not specified
    if schema_path is None:
        default_schema = os.path.join(os.path.dirname(data_dir) if data_dir != '/app/data' else '/app', 'schema.json')
        if os.path.exists(default_schema):
            schema_path = default_schema
    generate_json(data_dir, output_path, schema_path)
