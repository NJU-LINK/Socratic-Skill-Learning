#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/generate_organization.py
#!/usr/bin/env python3
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

import jsonschema


def clean_text(value):
    return value.strip().strip('"').strip()


def parse_money(value):
    cleaned = clean_text(value).replace(",", "")
    return float(Decimal(cleaned))


def parse_int(value):
    return int(clean_text(value))


def parse_multi_value(value):
    parts = [clean_text(part) for part in value.split(";")]
    return [part for part in parts if part]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_schema(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    schema = load_schema("/app/schema.json")
    department_rows = read_rows("/app/data/departments.csv")
    employee_rows = read_rows("/app/data/employees.csv")
    project_rows = read_rows("/app/data/projects.csv")

    departments = []
    all_skills = []
    all_years = []
    status_counts = Counter()

    for department_row in department_rows:
        department_id = clean_text(department_row["id"])
        employees = []

        for employee_row in employee_rows:
            if clean_text(employee_row["department_id"]) != department_id:
                continue

            skills = parse_multi_value(employee_row["skills"])
            years = parse_int(employee_row["years_of_service"])
            employees.append(
                {
                    "id": clean_text(employee_row["id"]),
                    "name": clean_text(employee_row["name"]),
                    "position": clean_text(employee_row["position"]),
                    "skills": skills,
                    "years_of_service": years,
                }
            )
            all_skills.extend(skills)
            all_years.append(years)

        projects = []
        for project_row in project_rows:
            if clean_text(project_row["department_id"]) != department_id:
                continue

            status = clean_text(project_row["status"])
            projects.append(
                {
                    "name": clean_text(project_row["name"]),
                    "status": status,
                    "members": parse_multi_value(project_row["member_ids"]),
                    "deadline": clean_text(project_row["deadline"]),
                }
            )
            status_counts[status] += 1

        departments.append(
            {
                "id": department_id,
                "name": clean_text(department_row["name"]),
                "budget": parse_money(department_row["budget"]),
                "employees": employees,
                "projects": projects,
            }
        )

    statistics = {
        "averageDepartmentBudget": sum(department["budget"] for department in departments) / len(departments),
        "totalEmployees": sum(len(department["employees"]) for department in departments),
        "skillDistribution": dict(Counter(all_skills)),
        "departmentSizes": {department["name"]: len(department["employees"]) for department in departments},
        "projectStatusDistribution": dict(status_counts),
        "averageYearsOfService": sum(all_years) / len(all_years),
    }

    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "generator": "organization-json-processor",
        },
        "organization": {
            "name": "Organization from cleaned CSV exports",
            "founded": "1970-01-01",
            "departments": departments,
        },
        "statistics": statistics,
    }

    jsonschema.validate(output, schema)

    with open("/app/organization.json", "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
PY

python3 /app/generate_organization.py
