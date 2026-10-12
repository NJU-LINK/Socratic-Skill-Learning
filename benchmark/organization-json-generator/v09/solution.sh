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
OUTPUT_PATH = Path("/app/organization.json")
SCHEMA_PATH = Path("/app/schema.json")


def cleaned(value: str) -> str:
    return value.strip()


def split_cleaned(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    departments_raw = read_csv(DATA_DIR / "departments.csv")
    employees_raw = read_csv(DATA_DIR / "employees.csv")
    projects_raw = read_csv(DATA_DIR / "projects.csv")

    employees_by_department: dict[str, list[dict[str, object]]] = {}
    projects_by_department: dict[str, list[dict[str, object]]] = {}
    skill_distribution: Counter[str] = Counter()
    total_years = 0

    for row in employees_raw:
        skills = split_cleaned(row["skills"])
        employee = {
            "id": cleaned(row["id"]),
            "name": cleaned(row["name"]),
            "position": cleaned(row["position"]),
            "skills": skills,
            "years_of_service": int(cleaned(row["years_of_service"])),
        }
        employees_by_department.setdefault(cleaned(row["department_id"]), []).append(employee)
        skill_distribution.update(skills)
        total_years += employee["years_of_service"]

    for row in projects_raw:
        project = {
            "name": cleaned(row["name"]),
            "status": cleaned(row["status"]),
            "members": split_cleaned(row["member_ids"]),
            "deadline": cleaned(row["deadline"]),
        }
        projects_by_department.setdefault(cleaned(row["department_id"]), []).append(project)

    departments: list[dict[str, object]] = []
    department_sizes: dict[str, int] = {}
    project_status_distribution: Counter[str] = Counter()
    total_budget = 0.0

    for row in departments_raw:
        department_id = cleaned(row["id"])
        department_name = cleaned(row["name"])
        budget = float(cleaned(row["budget"]))
        projects = projects_by_department.get(department_id, [])
        department = {
            "id": department_id,
            "name": department_name,
            "budget": budget,
            "employees": employees_by_department.get(department_id, []),
            "projects": projects,
        }
        departments.append(department)
        department_sizes[department_name] = len(department["employees"])
        project_status_distribution.update(project["status"] for project in projects)
        total_budget += budget

    total_employees = sum(len(department["employees"]) for department in departments)
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "generator": "organization-json-processor",
        },
        "organization": {
            "name": "Siu Industries",
            "founded": "2005-06-15",
            "departments": departments,
        },
        "statistics": {
            "averageDepartmentBudget": total_budget / len(departments),
            "totalEmployees": total_employees,
            "skillDistribution": dict(skill_distribution),
            "departmentSizes": department_sizes,
            "projectStatusDistribution": dict(project_status_distribution),
            "averageYearsOfService": total_years / total_employees,
        },
    }

    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.validate(output, schema)

    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY

python3 /tmp/generate_organization.py
