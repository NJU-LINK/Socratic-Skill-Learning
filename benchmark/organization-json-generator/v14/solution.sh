#!/bin/bash
set -euo pipefail

cat > /tmp/generate_organization.py <<'PY'
#!/usr/bin/env python3
import csv
import json
import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import jsonschema


DATA_DIR = os.environ.get("ORG_DATA_DIR", "/app/data")
OUTPUT_PATH = os.environ.get("ORG_OUTPUT_PATH", "/app/organization.json")
SCHEMA_PATH = os.environ.get("ORG_SCHEMA_PATH", "/app/schema.json")


def read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_semicolon_list(raw_value):
    if not raw_value:
        return []
    return [part.strip() for part in raw_value.split(";") if part.strip()]


def clean_numeric_string(raw_value):
    value = raw_value.strip()
    value = re.sub(r"^[\$€£]", "", value)
    value = re.sub(r"[,_\s]", "", value)
    if not value:
        raise ValueError("Numeric value is empty after normalization")
    return value


def parse_number(raw_value, *, integer=False):
    cleaned = clean_numeric_string(raw_value)
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value: {raw_value!r}") from exc

    if integer:
        if parsed != parsed.to_integral_value():
            raise ValueError(f"Expected integer numeric value, got {raw_value!r}")
        return int(parsed)

    return float(parsed)


def build_departments():
    departments = read_csv_rows(f"{DATA_DIR}/departments.csv")
    employees = read_csv_rows(f"{DATA_DIR}/employees.csv")
    projects = read_csv_rows(f"{DATA_DIR}/projects.csv")

    employees_by_department = {}
    for row in employees:
        department_id = row["department_id"].strip()
        employees_by_department.setdefault(department_id, []).append(
            {
                "id": row["id"].strip(),
                "name": row["name"].strip(),
                "position": row["position"].strip(),
                "skills": split_semicolon_list(row["skills"]),
                "years_of_service": parse_number(row["years_of_service"], integer=True),
            }
        )

    projects_by_department = {}
    for row in projects:
        department_id = row["department_id"].strip()
        projects_by_department.setdefault(department_id, []).append(
            {
                "name": row["name"].strip(),
                "status": row["status"].strip(),
                "members": split_semicolon_list(row["member_ids"]),
                "deadline": row["deadline"].strip(),
            }
        )

    return [
        {
            "id": row["id"].strip(),
            "name": row["name"].strip(),
            "budget": parse_number(row["budget"]),
            "employees": employees_by_department.get(row["id"].strip(), []),
            "projects": projects_by_department.get(row["id"].strip(), []),
        }
        for row in departments
    ]


def build_statistics(departments):
    all_employees = [
        employee
        for department in departments
        for employee in department["employees"]
    ]
    all_projects = [
        project
        for department in departments
        for project in department["projects"]
    ]

    average_department_budget = round(
        sum(department["budget"] for department in departments) / len(departments),
        2,
    )
    average_years_of_service = round(
        sum(employee["years_of_service"] for employee in all_employees) / len(all_employees),
        2,
    )

    return {
        "averageDepartmentBudget": average_department_budget,
        "totalEmployees": len(all_employees),
        "skillDistribution": dict(
            Counter(
                skill
                for employee in all_employees
                for skill in employee["skills"]
            )
        ),
        "departmentSizes": {
            department["name"]: len(department["employees"])
            for department in departments
        },
        "projectStatusDistribution": dict(
            Counter(project["status"] for project in all_projects)
        ),
        "averageYearsOfService": average_years_of_service,
    }


def main():
    departments = build_departments()
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "generator": "OrganizationDataGenerator",
        },
        "organization": {
            "name": "Siu Industries",
            "founded": "2005-06-15",
            "departments": departments,
        },
        "statistics": build_statistics(departments),
    }

    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.validate(instance=output, schema=schema)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
PY

python3 /tmp/generate_organization.py
