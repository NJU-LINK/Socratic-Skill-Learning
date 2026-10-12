#!/bin/bash
set -euo pipefail

python3 <<'PY'
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker


DATA_DIR = Path("/app/data")
OUTPUT_PATH = Path("/app/organization.json")
SCHEMA_PATH = Path("/app/schema.json")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_list(value):
    if value is None:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


departments = read_csv(DATA_DIR / "departments.csv")
employees = read_csv(DATA_DIR / "employees.csv")
projects = read_csv(DATA_DIR / "projects.csv")
schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

employees_by_department = {}
all_skills = []
all_years = []

for row in employees:
    skills = split_list(row["skills"])
    employee = {
        "id": row["id"].strip(),
        "name": row["name"].strip(),
        "position": row["position"].strip(),
        "skills": skills,
        "years_of_service": int(row["years_of_service"]),
    }
    employees_by_department.setdefault(row["department_id"].strip(), []).append(employee)
    all_skills.extend(skills)
    all_years.append(employee["years_of_service"])

projects_by_department = {}

for row in projects:
    project = {
        "name": row["name"].strip(),
        "status": row["status"].strip(),
        "members": split_list(row["member_ids"]),
        "deadline": row["deadline"].strip(),
    }
    projects_by_department.setdefault(row["department_id"].strip(), []).append(project)

department_records = []
for row in departments:
    department_records.append(
        {
            "id": row["id"].strip(),
            "name": row["name"].strip(),
            "budget": float(row["budget"]),
            "employees": employees_by_department.get(row["id"].strip(), []),
            "projects": projects_by_department.get(row["id"].strip(), []),
        }
    )

project_status_distribution = Counter()
for department in department_records:
    for project in department["projects"]:
        project_status_distribution[project["status"]] += 1

output = {
    "metadata": {
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generator": "OrganizationDataGenerator",
    },
    "organization": {
        "name": "Siu Industries",
        "founded": "2005-06-15",
        "departments": department_records,
    },
    "statistics": {
        "averageDepartmentBudget": round(
            sum(department["budget"] for department in department_records) / len(department_records),
            2,
        ),
        "totalEmployees": sum(len(department["employees"]) for department in department_records),
        "skillDistribution": dict(Counter(all_skills)),
        "departmentSizes": {
            department["name"]: len(department["employees"]) for department in department_records
        },
        "projectStatusDistribution": dict(project_status_distribution),
        "averageYearsOfService": round(sum(all_years) / len(all_years), 2),
    },
}

Draft7Validator(schema, format_checker=FormatChecker()).validate(output)
OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
PY
