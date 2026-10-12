#!/bin/bash
set -euo pipefail

cat <<'PY' > /tmp/generate_organization.py
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


def clean_text(value: str) -> str:
    return value.strip()


def parse_multi_value(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def parse_budget(value: str) -> float:
    return float(clean_text(value).replace(",", ""))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_output() -> dict:
    departments = read_rows(DATA_DIR / "departments.csv")
    employees = read_rows(DATA_DIR / "employees.csv")
    projects = read_rows(DATA_DIR / "projects.csv")

    department_records = []
    departments_by_id = {}
    skill_distribution = Counter()
    project_status_distribution = Counter()
    years_of_service = []

    for row in departments:
        record = {
            "id": clean_text(row["id"]),
            "name": clean_text(row["name"]),
            "budget": parse_budget(row["budget"]),
            "employees": [],
            "projects": [],
        }
        department_records.append(record)
        departments_by_id[record["id"]] = record

    for row in employees:
        employee = {
            "id": clean_text(row["id"]),
            "name": clean_text(row["name"]),
            "position": clean_text(row["position"]),
            "skills": parse_multi_value(row["skills"]),
            "years_of_service": int(clean_text(row["years_of_service"])),
        }
        departments_by_id[clean_text(row["department_id"])] ["employees"].append(employee)
        skill_distribution.update(employee["skills"])
        years_of_service.append(employee["years_of_service"])

    for row in projects:
        project = {
            "name": clean_text(row["name"]),
            "status": clean_text(row["status"]),
            "members": parse_multi_value(row["member_ids"]),
            "deadline": clean_text(row["deadline"]),
        }
        departments_by_id[clean_text(row["department_id"])] ["projects"].append(project)
        project_status_distribution.update([project["status"]])

    statistics = {
        "averageDepartmentBudget": sum(dept["budget"] for dept in department_records) / len(department_records),
        "totalEmployees": sum(len(dept["employees"]) for dept in department_records),
        "skillDistribution": dict(skill_distribution),
        "departmentSizes": {dept["name"]: len(dept["employees"]) for dept in department_records},
        "projectStatusDistribution": dict(project_status_distribution),
        "averageYearsOfService": sum(years_of_service) / len(years_of_service),
    }

    return {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "generator": "organization-json-processor",
        },
        "organization": {
            "name": "Siu Industries",
            "founded": "2005-06-15",
            "departments": department_records,
        },
        "statistics": statistics,
    }


def main() -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)

    output = build_output()
    jsonschema.validate(instance=output, schema=schema)

    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY

python3 /tmp/generate_organization.py
