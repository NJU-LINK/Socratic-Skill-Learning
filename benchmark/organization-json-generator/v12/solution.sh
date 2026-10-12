#!/bin/bash
set -euo pipefail

python3 <<'PY'
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path("/app/data")
SCHEMA_PATH = Path("/app/schema.json")
OUTPUT_PATH = Path("/app/organization.json")


def clean_text(value: str) -> str:
    return value.strip()


def clean_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def parse_number(value: str) -> float:
    return float(clean_text(value).replace(",", ""))


def parse_int(value: str) -> int:
    return int(clean_text(value).replace(",", ""))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


departments_rows = read_csv(DATA_DIR / "departments.csv")
employees_rows = read_csv(DATA_DIR / "employees.csv")
projects_rows = read_csv(DATA_DIR / "projects.csv")

employees_by_department: dict[str, list[dict[str, object]]] = {}
employee_ids_by_department: dict[str, set[str]] = {}
all_skills: list[str] = []
all_years: list[int] = []

for row in employees_rows:
    department_id = clean_text(row["department_id"])
    employee = {
        "id": clean_text(row["id"]),
        "name": clean_text(row["name"]),
        "position": clean_text(row["position"]),
        "skills": clean_list(row["skills"]),
        "years_of_service": parse_int(row["years_of_service"]),
    }
    employees_by_department.setdefault(department_id, []).append(employee)
    employee_ids_by_department.setdefault(department_id, set()).add(employee["id"])
    all_skills.extend(employee["skills"])
    all_years.append(employee["years_of_service"])

projects_by_department: dict[str, list[dict[str, object]]] = {}
status_counter: Counter[str] = Counter()

for row in projects_rows:
    department_id = clean_text(row["department_id"])
    members = clean_list(row["member_ids"])
    project = {
        "name": clean_text(row["name"]),
        "status": clean_text(row["status"]),
        "members": members,
        "deadline": clean_text(row["deadline"]),
    }
    projects_by_department.setdefault(department_id, []).append(project)
    status_counter[project["status"]] += 1

departments: list[dict[str, object]] = []
for row in departments_rows:
    department_id = clean_text(row["id"])
    departments.append(
        {
            "id": department_id,
            "name": clean_text(row["name"]),
            "budget": parse_number(row["budget"]),
            "employees": employees_by_department.get(department_id, []),
            "projects": projects_by_department.get(department_id, []),
        }
    )

organization = {
    "name": "Siu Industries",
    "founded": "2005-06-15",
    "departments": departments,
}

statistics = {
    "averageDepartmentBudget": round(
        sum(department["budget"] for department in departments) / len(departments), 2
    ),
    "totalEmployees": sum(len(department["employees"]) for department in departments),
    "skillDistribution": dict(Counter(all_skills)),
    "departmentSizes": {
        department["name"]: len(department["employees"]) for department in departments
    },
    "projectStatusDistribution": dict(status_counter),
    "averageYearsOfService": round(sum(all_years) / len(all_years), 2),
}

document = {
    "metadata": {
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generator": "OrganizationDataGenerator",
    },
    "organization": organization,
    "statistics": statistics,
}

schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

try:
    import jsonschema
except ImportError as exc:
    raise SystemExit(f"jsonschema is required but unavailable: {exc}")

jsonschema.validate(instance=document, schema=schema)
OUTPUT_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
PY
