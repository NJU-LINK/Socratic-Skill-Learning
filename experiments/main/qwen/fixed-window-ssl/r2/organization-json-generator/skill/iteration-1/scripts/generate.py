#!/usr/bin/env python3
"""
Organization JSON Generator
Transforms CSV data into nested organization JSON structure.
"""

import csv
import json
from datetime import datetime, timezone
from collections import defaultdict

def read_csv(path):
    """Read a CSV file and return list of dicts."""
    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [row for row in reader]

def parse_semicolon_list(value):
    """Parse a semicolon-delimited string into a list, handling empty/whitespace."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(';') if item.strip()]

def main():
    # Read CSV data
    departments = read_csv('/app/data/departments.csv')
    employees = read_csv('/app/data/employees.csv')
    projects = read_csv('/app/data/projects.csv')

    # Build employee lookup by ID
    emp_by_id = {}
    for emp in employees:
        emp_by_id[emp['id'].strip()] = emp

    # Group employees by department_id
    emps_by_dept = defaultdict(list)
    for emp in employees:
        dept_id = emp['department_id'].strip()
        emps_by_dept[dept_id].append(emp)

    # Group projects by department_id
    projs_by_dept = defaultdict(list)
    for proj in projects:
        dept_id = proj['department_id'].strip()
        projs_by_dept[dept_id].append(proj)

    # Build department records
    dept_records = []
    for dept in departments:
        dept_id = dept['id'].strip()
        dept_name = dept['name'].strip()
        budget = float(dept['budget'].strip())

        # Build employee records for this department
        emp_records = []
        for emp in emps_by_dept.get(dept_id, []):
            skills = parse_semicolon_list(emp['skills'])
            emp_record = {
                "id": emp['id'].strip(),
                "name": emp['name'].strip(),
                "position": emp['position'].strip(),
                "skills": skills,
                "years_of_service": int(emp['years_of_service'].strip())
            }
            emp_records.append(emp_record)

        # Build project records for this department
        proj_records = []
        for proj in projs_by_dept.get(dept_id, []):
            member_ids = parse_semicolon_list(proj['member_ids'])
            # Convert member IDs to employee names
            member_names = []
            for mid in member_ids:
                mid_stripped = mid.strip()
                if mid_stripped in emp_by_id:
                    member_names.append(emp_by_id[mid_stripped]['name'].strip())
                else:
                    member_names.append(mid_stripped)

            proj_record = {
                "name": proj['name'].strip(),
                "status": proj['status'].strip(),
                "members": member_names,
                "deadline": proj['deadline'].strip()
            }
            proj_records.append(proj_record)

        dept_record = {
            "id": dept_id,
            "name": dept_name,
            "budget": budget,
            "employees": emp_records,
            "projects": proj_records
        }
        dept_records.append(dept_record)

    # Compute statistics
    total_budget = sum(d['budget'] for d in dept_records)
    num_depts = len(dept_records)
    avg_dept_budget = total_budget / num_depts if num_depts > 0 else 0

    all_employees = []
    for dept in dept_records:
        all_employees.extend(dept['employees'])
    total_employees = len(all_employees)

    # Skill distribution
    skill_dist = defaultdict(int)
    for emp in all_employees:
        for skill in emp['skills']:
            skill_dist[skill] += 1

    # Department sizes (by department name)
    dept_sizes = {}
    for dept in dept_records:
        dept_sizes[dept['name']] = len(dept['employees'])

    # Project status distribution
    status_dist = defaultdict(int)
    for dept in dept_records:
        for proj in dept['projects']:
            status_dist[proj['status']] += 1

    # Average years of service
    if total_employees > 0:
        avg_years = sum(e['years_of_service'] for e in all_employees) / total_employees
    else:
        avg_years = 0

    # Build final JSON
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "generator": "organization-json-generator"
        },
        "organization": {
            "name": "Organization",
            "founded": "2024-01-01",
            "departments": dept_records
        },
        "statistics": {
            "averageDepartmentBudget": avg_dept_budget,
            "totalEmployees": total_employees,
            "skillDistribution": dict(skill_dist),
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": dict(status_dist),
            "averageYearsOfService": avg_years
        }
    }

    with open('/app/organization.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("Generated /app/organization.json")

if __name__ == '__main__':
    main()
