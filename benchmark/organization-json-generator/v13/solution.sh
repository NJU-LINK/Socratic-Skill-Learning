#!/bin/bash
set -euo pipefail

cat > /tmp/generate_organization.py <<'PY'
#!/usr/bin/env python3
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import jsonschema


DATA_DIR = Path("/app/data")
SCHEMA_PATH = Path("/app/schema.json")
OUTPUT_PATH = Path("/app/organization.json")


def read_csv_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_semicolon_list(raw_value):
    if not raw_value:
        return []
    return [part.strip() for part in raw_value.split(";") if part.strip()]


def main():
    departments = read_csv_rows(DATA_DIR / "departments.csv")
    employees = read_csv_rows(DATA_DIR / "employees.csv")
    projects = read_csv_rows(DATA_DIR / "projects.csv")

    employees_by_department = {}
    all_skills = []
    all_years = []

    for employee_row in employees:
        department_id = employee_row["department_id"].strip()
        skills = split_semicolon_list(employee_row["skills"])
        employee = {
            "id": employee_row["id"].strip(),
            "name": employee_row["name"].strip(),
            "position": employee_row["position"].strip(),
            "skills": skills,
            "years_of_service": int(employee_row["years_of_service"].strip()),
        }
        employees_by_department.setdefault(department_id, []).append(employee)
        all_skills.extend(skills)
        all_years.append(employee["years_of_service"])

    projects_by_department = {}
    for project_row in projects:
        department_id = project_row["department_id"].strip()
        project = {
            "name": project_row["name"].strip(),
            "status": project_row["status"].strip(),
            "members": split_semicolon_list(project_row["member_ids"]),
            "deadline": project_row["deadline"].strip(),
        }
        projects_by_department.setdefault(department_id, []).append(project)

    organization_departments = []
    for department_row in departments:
        department_id = department_row["id"].strip()
        organization_departments.append(
            {
                "id": department_id,
                "name": department_row["name"].strip(),
                "budget": float(department_row["budget"].strip()),
                "employees": employees_by_department.get(department_id, []),
                "projects": projects_by_department.get(department_id, []),
            }
        )

    average_budget = sum(dept["budget"] for dept in organization_departments) / len(organization_departments)
    project_status_distribution = Counter(
        project["status"]
        for department in organization_departments
        for project in department["projects"]
    )

    document = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "generator": "OrganizationDataGenerator",
        },
        "organization": {
            "name": "Siu Industries",
            "founded": "2005-06-15",
            "departments": organization_departments,
        },
        "statistics": {
            "averageDepartmentBudget": round(average_budget, 2),
            "totalEmployees": len(employees),
            "skillDistribution": dict(Counter(all_skills)),
            "departmentSizes": {
                department["name"]: len(department["employees"])
                for department in organization_departments
            },
            "projectStatusDistribution": dict(project_status_distribution),
            "averageYearsOfService": round(sum(all_years) / len(all_years), 2),
        },
    }

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=document, schema=schema)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY

python3 /tmp/generate_organization.py
