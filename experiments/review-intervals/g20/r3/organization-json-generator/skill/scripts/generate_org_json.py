#!/usr/bin/env python3
"""
Generate organization.json from CSV data files.
Transforms departments, employees, and projects CSVs into a nested JSON structure
with metadata, organization data, and statistics.
"""

import csv
import json
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path


def parse_number(value, as_int=False):
    """
    Parse a numeric string, handling whitespace, commas, and currency symbols.
    For integer fields, handles float strings like "10.0" → 10.
    """
    try:
        cleaned = str(value).strip().replace(',', '').replace('$', '').replace('€', '').replace('£', '')
        if as_int:
            return int(float(cleaned))  # handles "10.0" → 10
        return float(cleaned)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Cannot parse numeric value '{value}': {e}")


def parse_csv(filepath):
    """Parse a CSV file and return list of dictionaries."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                raise ValueError(f"CSV file is empty: {filepath}")
            return rows
    except Exception as e:
        raise RuntimeError(f"Error reading CSV file {filepath}: {e}")


def parse_semicolon_list(value):
    """Parse a semicolon-delimited string into a list, handling empty values and repeated delimiters."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(';') if item.strip()]


def build_organization(departments_data, employees_data, projects_data):
    """Build the nested organization structure."""
    
    # Group employees by department
    employees_by_dept = defaultdict(list)
    for emp in employees_data:
        try:
            dept_id = emp['department_id'].strip()
            employees_by_dept[dept_id].append({
                'id': emp['id'].strip(),
                'name': emp['name'].strip(),
                'position': emp['position'].strip(),
                'skills': parse_semicolon_list(emp['skills']),
                'years_of_service': parse_number(emp['years_of_service'], as_int=True)
            })
        except KeyError as e:
            raise KeyError(f"Missing required column in employees.csv: {e}")
    
    # Group projects by department
    projects_by_dept = defaultdict(list)
    for proj in projects_data:
        try:
            dept_id = proj['department_id'].strip()
            projects_by_dept[dept_id].append({
                'name': proj['name'].strip(),
                'status': proj['status'].strip(),
                'members': parse_semicolon_list(proj['member_ids']),
                'deadline': proj['deadline'].strip()
            })
        except KeyError as e:
            raise KeyError(f"Missing required column in projects.csv: {e}")
    
    # Build departments array
    departments = []
    for dept in departments_data:
        try:
            dept_id = dept['id'].strip()
            departments.append({
                'id': dept_id,
                'name': dept['name'].strip(),
                'budget': parse_number(dept['budget']),
                'employees': employees_by_dept.get(dept_id, []),
                'projects': projects_by_dept.get(dept_id, [])
            })
        except KeyError as e:
            raise KeyError(f"Missing required column in departments.csv: {e}")
    
    return departments


def compute_statistics(departments):
    """Compute all required statistics from the organization data."""
    
    # Average department budget
    total_budget = sum(dept['budget'] for dept in departments)
    avg_budget = total_budget / len(departments) if departments else 0
    
    # Total employees
    total_employees = sum(len(dept['employees']) for dept in departments)
    
    # Skill distribution
    skill_counts = defaultdict(int)
    for dept in departments:
        for emp in dept['employees']:
            for skill in emp['skills']:
                skill_counts[skill] += 1
    
    # Department sizes (keyed by department name)
    dept_sizes = {dept['name']: len(dept['employees']) for dept in departments}
    
    # Project status distribution
    status_counts = defaultdict(int)
    for dept in departments:
        for proj in dept['projects']:
            status_counts[proj['status']] += 1
    
    # Average years of service
    total_years = 0
    for dept in departments:
        for emp in dept['employees']:
            total_years += emp['years_of_service']
    avg_years = total_years / total_employees if total_employees > 0 else 0
    
    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_counts),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_counts),
        'averageYearsOfService': avg_years
    }


def validate_output(data, schema_path):
    """Validate the generated JSON against the schema."""
    try:
        import jsonschema
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        jsonschema.validate(instance=data, schema=schema)
        return True, None
    except ImportError:
        # jsonschema not available, skip validation
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    # Allow command-line override of paths for reusability
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/app/data')
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/app/organization.json')
    schema_file = Path('/app/schema.json')
    
    # Parse input CSV files
    try:
        departments_data = parse_csv(data_dir / 'departments.csv')
        employees_data = parse_csv(data_dir / 'employees.csv')
        projects_data = parse_csv(data_dir / 'projects.csv')
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Build organization structure
    try:
        departments = build_organization(departments_data, employees_data, projects_data)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Compute statistics
    statistics = compute_statistics(departments)
    
    # Build final JSON structure
    organization_json = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'generator': 'organization-json-generator'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2000-01-01',
            'departments': departments
        },
        'statistics': statistics
    }
    
    # Validate against schema if available
    if schema_file.exists():
        valid, error = validate_output(organization_json, schema_file)
        if not valid:
            print(f"Warning: Output does not validate against schema: {error}", file=sys.stderr)
    
    # Write output
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(organization_json, f, indent=2)
        print(f"Generated {output_file} successfully")
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
