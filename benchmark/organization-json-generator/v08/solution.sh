#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import jsonschema


def clean_text(value: str | None) -> str:
    return (value or "").strip()


def parse_number(value: str) -> float:
    return float(clean_text(value).replace(",", ""))


def parse_int(value: str) -> int:
    return int(parse_number(value))


def split_multi(value: str | None) -> list[str]:
    return [part.strip() for part in clean_text(value).split(";") if part.strip()]


def read_csv_rows(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


departments_csv = read_csv_rows("/app/data/departments.csv")
employees_csv = read_csv_rows("/app/data/employees.csv")
projects_csv = read_csv_rows("/app/data/projects.csv")

departments = []
department_by_id = {}
all_skills = []
all_years = []
project_statuses = []

for row in departments_csv:
    department = {
        "id": clean_text(row["id"]),
        "name": clean_text(row["name"]),
        "budget": parse_number(row["budget"]),
        "employees": [],
        "projects": [],
    }
    departments.append(department)
    department_by_id[department["id"]] = department

for row in employees_csv:
    department_id = clean_text(row["department_id"])
    employee = {
        "id": clean_text(row["id"]),
        "name": clean_text(row["name"]),
        "position": clean_text(row["position"]),
        "skills": split_multi(row["skills"]),
        "years_of_service": parse_int(row["years_of_service"]),
    }
    department_by_id[department_id]["employees"].append(employee)
    all_skills.extend(employee["skills"])
    all_years.append(employee["years_of_service"])

for row in projects_csv:
    department_id = clean_text(row["department_id"])
    project = {
        "name": clean_text(row["name"]),
        "status": clean_text(row["status"]),
        "members": split_multi(row["member_ids"]),
        "deadline": clean_text(row["deadline"]),
    }
    department_by_id[department_id]["projects"].append(project)
    project_statuses.append(project["status"])

payload = {
    "metadata": {
        "version": "1.0",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "generator": "OrganizationDataGenerator",
    },
    "organization": {
        "name": "Siu Industries",
        "founded": "2005-06-15",
        "departments": departments,
    },
    "statistics": {
        "averageDepartmentBudget": round(
            sum(department["budget"] for department in departments) / len(departments), 2
        ),
        "totalEmployees": sum(len(department["employees"]) for department in departments),
        "skillDistribution": dict(Counter(all_skills)),
        "departmentSizes": {
            department["name"]: len(department["employees"])
            for department in departments
        },
        "projectStatusDistribution": dict(Counter(project_statuses)),
        "averageYearsOfService": round(sum(all_years) / len(all_years), 2),
    },
}

with open("/app/schema.json", encoding="utf-8") as handle:
    schema = json.load(handle)

jsonschema.validate(instance=payload, schema=schema)

Path("/app/organization.json").write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
PY
