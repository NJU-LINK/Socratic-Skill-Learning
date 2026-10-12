import csv
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker


OUTPUT_PATH = Path("/app/organization.json")
SCHEMA_PATH = Path("/app/schema.json")
DATA_DIR = Path("/app/data")


def load_output() -> dict:
    assert OUTPUT_PATH.exists(), f"{OUTPUT_PATH} does not exist"
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))


def rows(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def text(value: str) -> str:
    return value.strip().strip('"').strip()


def items(value: str) -> list[str]:
    return [text(part) for part in value.split(";") if text(part)]


def money(value: str) -> float:
    return float(value.strip().replace(",", "").replace("$", ""))


def expected_departments() -> list[dict]:
    employees_by_department: dict[str, list[dict]] = {}
    for row in rows("employees.csv"):
        employee = {
            "id": text(row["id"]),
            "name": text(row["name"]),
            "position": text(row["position"]),
            "skills": items(row["skills"]),
            "years_of_service": int(text(row["years_of_service"])),
        }
        employees_by_department.setdefault(text(row["department_id"]), []).append(employee)

    projects_by_department: dict[str, list[dict]] = {}
    for row in rows("projects.csv"):
        project = {
            "name": text(row["name"]),
            "status": text(row["status"]),
            "members": items(row["member_ids"]),
            "deadline": text(row["deadline"]),
        }
        projects_by_department.setdefault(text(row["department_id"]), []).append(project)

    result = []
    for row in rows("departments.csv"):
        department_id = text(row["id"])
        result.append(
            {
                "id": department_id,
                "name": text(row["name"]),
                "budget": money(row["budget"]),
                "employees": employees_by_department.get(department_id, []),
                "projects": projects_by_department.get(department_id, []),
            }
        )
    return result


def expected_statistics(departments: list[dict]) -> dict:
    employees = [
        employee
        for department in departments
        for employee in department["employees"]
    ]
    projects = [
        project
        for department in departments
        for project in department["projects"]
    ]
    return {
        "averageDepartmentBudget": (
            sum(department["budget"] for department in departments) / len(departments)
        ),
        "totalEmployees": len(employees),
        "skillDistribution": dict(
            Counter(skill for employee in employees for skill in employee["skills"])
        ),
        "departmentSizes": {
            department["name"]: len(department["employees"])
            for department in departments
        },
        "projectStatusDistribution": dict(
            Counter(project["status"] for project in projects)
        ),
        "averageYearsOfService": (
            sum(employee["years_of_service"] for employee in employees) / len(employees)
        ),
    }


def test_output_is_valid_json_and_schema_compliant():
    data = load_output()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda error: list(error.path),
    )
    assert not errors, "\n".join(error.message for error in errors)


def test_metadata_is_well_formed_without_hidden_constant_requirements():
    data = load_output()
    metadata = data["metadata"]
    assert all(isinstance(metadata[key], str) and metadata[key].strip() for key in (
        "version",
        "generator",
        "timestamp",
    ))
    datetime.fromisoformat(metadata["timestamp"].replace("Z", "+00:00"))

    organization = data["organization"]
    assert isinstance(organization["name"], str) and organization["name"].strip()
    date.fromisoformat(organization["founded"])


def test_departments_employees_and_projects_match_public_csv_inputs():
    actual = load_output()["organization"]["departments"]
    assert actual == expected_departments()


def test_project_members_remain_within_their_owning_department():
    for department in load_output()["organization"]["departments"]:
        employee_ids = {employee["id"] for employee in department["employees"]}
        for project in department["projects"]:
            assert set(project["members"]).issubset(employee_ids)


def test_count_and_distribution_statistics_match_normalized_inputs():
    departments = expected_departments()
    expected = expected_statistics(departments)
    actual = load_output()["statistics"]

    for key in (
        "totalEmployees",
        "skillDistribution",
        "departmentSizes",
        "projectStatusDistribution",
    ):
        assert actual[key] == expected[key]


def test_average_statistics_are_correct_to_two_decimal_places():
    expected = expected_statistics(expected_departments())
    actual = load_output()["statistics"]
    for key in ("averageDepartmentBudget", "averageYearsOfService"):
        assert math.isclose(actual[key], expected[key], rel_tol=0, abs_tol=0.005)
