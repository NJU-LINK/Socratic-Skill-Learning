#!/usr/bin/env python3
"""
Transform CSV data (departments, employees, projects) into a nested
organization JSON file that validates against the provided schema.

This is the reference implementation. The solver should implement this
inline by extracting the code block from SKILL.md.
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone


# --- Robust field parsing ---

def read_csv(filepath):
    """Read CSV with robust header and value stripping."""
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ''
                cleaned[k] = v
            rows.append(cleaned)
    return rows


def parse_number(raw):
    """Parse numeric string with commas, decimals, or whitespace.
    Returns int for whole numbers, float otherwise.
    '1500000'→1500000  '1,500,000'→1500000  '10.0'→10  '6.93'→6.93  ''→0
    """
    if not raw:
        return 0
    cleaned = raw.replace(',', '').strip()
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        pass
    try:
        f = float(cleaned)
        return int(f) if f == int(f) else f
    except ValueError:
        return 0


def parse_list(raw, delimiter=';'):
    """Split delimited string into non-empty stripped tokens.
    'A;B;C'→['A','B','C']  'A;;B'→['A','B']  ''→[]
    """
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(delimiter) if t.strip()]


def find_column(headers, *candidates):
    """Return the first header that matches any candidate name (case-insensitive)."""
    h_lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in h_lower:
            return h_lower[c.lower()]
    return candidates[0]


# --- Read data ---

departments = read_csv('/app/data/departments.csv')
employees = read_csv('/app/data/employees.csv')
projects = read_csv('/app/data/projects.csv')

# Adaptive column discovery from actual headers
dept_headers = list(departments[0].keys()) if departments else []
emp_headers = list(employees[0].keys()) if employees else []
proj_headers = list(projects[0].keys()) if projects else []

D_ID = find_column(dept_headers, 'id')
D_NAME = find_column(dept_headers, 'name')
D_BUDGET = find_column(dept_headers, 'budget')

E_ID = find_column(emp_headers, 'id')
E_NAME = find_column(emp_headers, 'name')
E_POSITION = find_column(emp_headers, 'position')
E_SKILLS = find_column(emp_headers, 'skills')
E_YEARS = find_column(emp_headers, 'years_of_service')
E_DEPT = find_column(emp_headers, 'department_id')

P_NAME = find_column(proj_headers, 'name')
P_STATUS = find_column(proj_headers, 'status')
P_MEMBERS = find_column(proj_headers, 'member_ids')
P_DEADLINE = find_column(proj_headers, 'deadline')
P_DEPT = find_column(proj_headers, 'department_id')

# --- Parse into typed records ---

dept_list = []
for d in departments:
    dept_list.append({
        'id': d[D_ID],
        'name': d[D_NAME],
        'budget': parse_number(d.get(D_BUDGET, '0')),
    })

emp_records = []
for e in employees:
    emp_records.append({
        'id': e[E_ID],
        'name': e[E_NAME],
        'position': e.get(E_POSITION, ''),
        'skills': parse_list(e.get(E_SKILLS, '')),
        'years_of_service': parse_number(e.get(E_YEARS, '0')),
        'department_id': e[E_DEPT],
    })

proj_records = []
for p in projects:
    proj_records.append({
        'name': p[P_NAME],
        'status': p.get(P_STATUS, ''),
        'members': parse_list(p.get(P_MEMBERS, '')),
        'deadline': p.get(P_DEADLINE, ''),
        'department_id': p[P_DEPT],
    })

# --- Group by department_id ---

emp_by_dept = defaultdict(list)
for e in emp_records:
    emp_by_dept[e['department_id']].append(e)

proj_by_dept = defaultdict(list)
for p in proj_records:
    proj_by_dept[p['department_id']].append(p)

# --- Build nested structure (sorted by department id) ---

nested_depts = []
for dept in sorted(dept_list, key=lambda d: d['id']):
    did = dept['id']
    nested_depts.append({
        'id': did,
        'name': dept['name'],
        'budget': dept['budget'],
        'employees': [
            {
                'id': e['id'],
                'name': e['name'],
                'position': e['position'],
                'skills': e['skills'],
                'years_of_service': e['years_of_service'],
            }
            for e in emp_by_dept.get(did, [])
        ],
        'projects': [
            {
                'name': p['name'],
                'status': p['status'],
                'members': p['members'],
                'deadline': p['deadline'],
            }
            for p in proj_by_dept.get(did, [])
        ],
    })

# --- Compute statistics over ALL data ---

all_employees = [e for d in nested_depts for e in d['employees']]
all_projects = [p for d in nested_depts for p in d['projects']]
n_depts = len(nested_depts)
n_emps = len(all_employees)

skill_dist = defaultdict(int)
for emp in all_employees:
    for s in emp['skills']:
        skill_dist[s] += 1

dept_sizes = {d['name']: len(d['employees']) for d in nested_depts}

status_dist = defaultdict(int)
for proj in all_projects:
    status_dist[proj['status']] += 1

total_years = sum(e['years_of_service'] for e in all_employees)

statistics = {
    'averageDepartmentBudget': sum(d['budget'] for d in nested_depts) / n_depts if n_depts else 0,
    'totalEmployees': n_emps,
    'skillDistribution': dict(skill_dist),
    'departmentSizes': dept_sizes,
    'projectStatusDistribution': dict(status_dist),
    'averageYearsOfService': total_years / n_emps if n_emps else 0,
}

# --- Assemble output ---

output = {
    'metadata': {
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generator': 'organization-json-generator',
    },
    'organization': {
        'name': 'Organization',
        'founded': '2020-01-01',
        'departments': nested_depts,
    },
    'statistics': statistics,
}

# --- Validate against schema ---

try:
    import jsonschema
    with open('/app/schema.json') as f:
        schema = json.load(f)
    jsonschema.validate(instance=output, schema=schema)
    print('Schema validation: PASSED', file=sys.stderr)
except ImportError:
    print('WARNING: jsonschema not available', file=sys.stderr)
except jsonschema.ValidationError as e:
    print(f'VALIDATION FAILED: {e.message}', file=sys.stderr)
    print(f'  Path: {list(e.absolute_path)}', file=sys.stderr)
    sys.exit(1)

# --- Self-verification ---

assert n_depts == len(departments), f'Dept count: {n_depts} vs {len(departments)}'
assert n_emps == len(employees), f'Employee count: {n_emps} vs {len(employees)}'
assert len(all_projects) == len(projects), f'Project count: {len(all_projects)} vs {len(projects)}'
for d in nested_depts:
    for p in d['projects']:
        assert '' not in p['members'], f'Empty string in {p["name"]} members'
    for e in d['employees']:
        assert isinstance(e['years_of_service'], int), f'{e["id"]} years not int'
        assert '' not in e['skills'], f'Empty string in {e["id"]} skills'

# --- Write output ---

with open('/app/organization.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
    f.write('\n')

print(f'Written /app/organization.json ({n_depts} depts, {n_emps} emps, {len(all_projects)} projects)')
