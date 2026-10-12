#!/usr/bin/env python3
"""
CSV to Organization JSON Generator - Reference Implementation
Transforms department, employee, and project CSV data into a nested JSON structure.

Usage:
    python3 generate_json.py

Reads from /app/data/{departments,employees,projects}.csv
Writes to /app/organization.json
Validates against /app/schema.json
Runs self-test to verify logic correctness
"""

import csv
import json
from datetime import datetime
from collections import defaultdict


def read_csv(filepath):
    """Read a CSV file and return a list of dictionaries."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def clean_value(val):
    """Clean a string value: strip whitespace and surrounding quotes."""
    if not val:
        return ''
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1].strip()
    return val


def parse_delimited_field(field_str, delimiter=';'):
    """Parse a delimited field into a list of cleaned values.
    
    Handles: empty fields, repeated delimiters, leading/trailing delimiters,
    extra whitespace, quoted values.
    """
    if not field_str or not field_str.strip():
        return []
    return [clean_value(v) for v in field_str.split(delimiter) if clean_value(v)]


def parse_int_robust(val):
    """Parse an integer robustly: handles '7.0', ' 7 ', '1,000'."""
    cleaned = clean_value(val).replace(',', '')
    return int(float(cleaned))


def parse_float_robust(val):
    """Parse a float robustly: handles various formats including commas."""
    cleaned = clean_value(val).replace(',', '')
    return float(cleaned)


def self_test(data):
    """Run self-test to verify logic correctness beyond schema validation.
    
    Catches:
    - Member IDs translated to names
    - Empty arrays not properly handled
    - Statistics not matching actual data
    - Integer division instead of float division
    """
    depts = data['organization']['departments']
    stats = data['statistics']

    # 1. Verify project members are employee IDs belonging to owning department
    emp_ids_by_dept = {}
    for d in depts:
        emp_ids_by_dept[d['name']] = set(e['id'] for e in d['employees'])

    for d in depts:
        for p in d['projects']:
            for m in p['members']:
                assert m in emp_ids_by_dept[d['name']], \
                    f'Member {m} not in dept {d["name"]}'

    # 2. Verify empty arrays for departments/projects with no data
    for d in depts:
        assert isinstance(d['employees'], list)
        assert isinstance(d['projects'], list)
        for p in d['projects']:
            assert isinstance(p['members'], list)

    # 3. Verify statistics consistency
    total_emps = sum(len(d['employees']) for d in depts)
    assert stats['totalEmployees'] == total_emps, \
        f'totalEmployees mismatch: {stats["totalEmployees"]} != {total_emps}'

    total_projs = sum(len(d['projects']) for d in depts)
    status_sum = sum(stats['projectStatusDistribution'].values())
    assert status_sum == total_projs, \
        f'projectStatusDistribution sum {status_sum} != total projects {total_projs}'

    # 4. Verify departmentSizes consistency
    for d in depts:
        expected_size = len(d['employees'])
        actual_size = stats['departmentSizes'].get(d['name'], -1)
        assert actual_size == expected_size, \
            f'departmentSizes[{d["name"]}] = {actual_size}, expected {expected_size}'

    # 5. Verify skill distribution consistency
    skill_check = defaultdict(int)
    for d in depts:
        for e in d['employees']:
            for s in e['skills']:
                skill_check[s] += 1
    assert dict(skill_check) == stats['skillDistribution'], \
        'skillDistribution mismatch'

    # 6. Verify averages are floats
    assert isinstance(stats['averageDepartmentBudget'], (float, int))
    assert isinstance(stats['averageYearsOfService'], (float, int))


def main():
    # Step 1: Read CSV files
    departments_data = read_csv('/app/data/departments.csv')
    employees_data = read_csv('/app/data/employees.csv')
    projects_data = read_csv('/app/data/projects.csv')

    # Step 2: Build lookup structures
    employees_by_id = {}
    for emp in employees_data:
        emp_id = clean_value(emp['id'])
        employees_by_id[emp_id] = emp

    # Step 3: Group employees by department
    employees_by_dept = defaultdict(list)
    for emp in employees_data:
        dept_id = clean_value(emp['department_id'])
        employees_by_dept[dept_id].append({
            'id': clean_value(emp['id']),
            'name': clean_value(emp['name']),
            'position': clean_value(emp['position']),
            'skills': parse_delimited_field(clean_value(emp['skills'])),
            'years_of_service': parse_int_robust(emp['years_of_service'])
        })

    # Step 4: Group projects by department
    # Keep member_ids as employee ID strings (not names) to preserve referential integrity
    projects_by_dept = defaultdict(list)
    for proj in projects_data:
        dept_id = clean_value(proj['department_id'])
        member_ids = parse_delimited_field(clean_value(proj['member_ids']))
        projects_by_dept[dept_id].append({
            'name': clean_value(proj['name']),
            'status': clean_value(proj['status']),
            'members': member_ids,
            'deadline': clean_value(proj['deadline'])
        })

    # Step 5: Assemble department objects
    departments = []
    for dept in departments_data:
        dept_id = clean_value(dept['id'])
        departments.append({
            'id': dept_id,
            'name': clean_value(dept['name']),
            'budget': parse_float_robust(dept['budget']),
            'employees': employees_by_dept.get(dept_id, []),
            'projects': projects_by_dept.get(dept_id, [])
        })

    # Step 6: Compute statistics
    total_employees = len(employees_data)
    num_depts = len(departments_data)

    # Average department budget (float division)
    total_budget = sum(parse_float_robust(d['budget']) for d in departments_data)
    avg_budget = total_budget / num_depts if num_depts > 0 else 0

    # Skill distribution: count each skill across ALL employees
    skill_counts = defaultdict(int)
    for emp in employees_data:
        for skill in parse_delimited_field(clean_value(emp['skills'])):
            skill_counts[skill] += 1

    # Department sizes: keyed by department NAME, includes ALL departments
    dept_sizes = {}
    for dept in departments_data:
        dept_id = clean_value(dept['id'])
        dept_sizes[clean_value(dept['name'])] = len(employees_by_dept.get(dept_id, []))

    # Project status distribution: only statuses that appear
    status_counts = defaultdict(int)
    for proj in projects_data:
        status_counts[clean_value(proj['status'])] += 1

    # Average years of service (float division)
    total_years = sum(parse_int_robust(emp['years_of_service']) for emp in employees_data)
    avg_years = total_years / total_employees if total_employees > 0 else 0

    # Step 7: Build final JSON structure
    organization_json = {
        'metadata': {
            'version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'generator': 'csv-to-json-processor'
        },
        'organization': {
            'name': 'Organization',
            'founded': '2020-01-01',
            'departments': departments
        },
        'statistics': {
            'averageDepartmentBudget': avg_budget,
            'totalEmployees': total_employees,
            'skillDistribution': dict(skill_counts),
            'departmentSizes': dept_sizes,
            'projectStatusDistribution': dict(status_counts),
            'averageYearsOfService': avg_years
        }
    }

    # Step 8: Write output
    with open('/app/organization.json', 'w', encoding='utf-8') as f:
        json.dump(organization_json, f, indent=2)

    # Step 9: Validate against schema
    from jsonschema import validate, ValidationError
    with open('/app/schema.json', 'r') as f:
        schema = json.load(f)
    try:
        validate(instance=organization_json, schema=schema)
        print("Schema validation passed")
    except ValidationError as e:
        print(f"Schema validation FAILED: {e.message}")
        print(f"Path: {list(e.absolute_path)}")
        raise

    # Step 10: Run self-test
    self_test(organization_json)
    print("Self-test passed")
    print("Generated /app/organization.json successfully")


if __name__ == '__main__':
    main()
