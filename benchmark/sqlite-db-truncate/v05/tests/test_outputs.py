"""
Tests for the SQLite database fragment recovery solution.

Verifies that /app/recover.json contains correctly recovered records
from all three tables, with proper handling of:
- Big-endian integer encoding in the employees table
- NULL values in departments and salaries
- Overflow page text values in salaries bonus field
- Multi-table disambiguation
"""
import json
import os
import pytest


@pytest.fixture
def recover():
    """Load the recovered data from /app/recover.json."""
    path = "/app/recover.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


class TestStructure:
    """Verify the output file has the correct top-level structure."""

    def test_top_level_keys(self, recover):
        assert "employees" in recover, "Missing 'employees' key"
        assert "departments" in recover, "Missing 'departments' key"
        assert "salaries" in recover, "Missing 'salaries' key"

    def test_record_counts(self, recover):
        assert len(recover["employees"]) == 20, f"Expected 20 employees, got {len(recover['employees'])}"
        assert len(recover["departments"]) == 10, f"Expected 10 departments, got {len(recover['departments'])}"
        assert len(recover["salaries"]) == 20, f"Expected 20 salaries, got {len(recover['salaries'])}"


class TestEmployees:
    """Verify the employees table records."""

    @pytest.fixture
    def employees(self, recover):
        return recover["employees"]

    def test_fields_present(self, employees):
        for emp in employees:
            assert "id" in emp, f"Missing 'id' in employee record"
            assert "name" in emp, f"Missing 'name' in employee record"
            assert "dept_id" in emp, f"Missing 'dept_id' in employee record"

    def test_id_types_are_int(self, employees):
        for emp in employees:
            assert isinstance(emp["id"], int), (
                f"Employee id should be an integer, got {type(emp['id'])}: {emp['id']}"
            )
            assert isinstance(emp["dept_id"], int), (
                f"Employee dept_id should be an integer, got {type(emp['dept_id'])}: {emp['dept_id']}"
            )

    def test_name_types_are_str(self, employees):
        for emp in employees:
            assert isinstance(emp["name"], str), (
                f"Employee name should be a string, got {type(emp['name'])}"
            )

    def test_ids_are_in_expected_range(self, employees):
        """All employee ids should be between 101-120 (big-endian decoded)."""
        ids = [emp["id"] for emp in employees]
        for i in ids:
            assert 101 <= i <= 120, f"Employee id {i} out of expected range 101-120"

    def test_dept_ids_in_expected_set(self, employees):
        """Department IDs should be from {201, 202, 203}."""
        valid_depts = {201, 202, 203}
        for emp in employees:
            assert emp["dept_id"] in valid_depts, (
                f"Employee dept_id {emp['dept_id']} not in expected set {valid_depts}"
            )

    def test_known_employees(self, employees):
        """Verify specific known employees exist with correct data."""
        by_id = {emp["id"]: emp for emp in employees}
        assert by_id[101]["name"] == "Alice Smith"
        assert by_id[101]["dept_id"] == 201
        assert by_id[106]["name"] == "Fiona Green"
        assert by_id[110]["name"] == "Julia Roberts"
        assert by_id[115]["name"] == "Oliver Stone"
        assert by_id[120]["name"] == "Tina Fey"

    def test_all_names_non_empty(self, employees):
        for emp in employees:
            assert len(emp["name"]) > 0, f"Employee name should not be empty"


class TestDepartments:
    """Verify the departments table records."""

    @pytest.fixture
    def departments(self, recover):
        return recover["departments"]

    def test_fields_present(self, departments):
        for dept in departments:
            assert "id" in dept
            assert "name" in dept
            assert "budget" in dept

    def test_known_departments(self, departments):
        by_id = {d["id"]: d for d in departments}
        assert by_id[201]["name"] == "Engineering"
        assert by_id[201]["budget"] == pytest.approx(1500000.0)
        assert by_id[202]["name"] == "Marketing"
        assert by_id[203]["name"] == "Sales"
        assert by_id[203]["budget"] is None
        assert by_id[205]["name"] == "Finance"
        assert by_id[205]["budget"] is None
        assert by_id[208]["name"] == "Legal"
        assert by_id[208]["budget"] is None
        assert by_id[210]["name"] == "Quality Assurance"

    def test_null_budget_departments(self, departments):
        """Departments 203 (Sales), 205 (Finance), 208 (Legal) have NULL budgets."""
        null_ids = {203, 205, 208}
        for dept in departments:
            if dept["id"] in null_ids:
                assert dept["budget"] is None, (
                    f"Department {dept['id']} ({dept['name']}) should have null budget"
                )

    def test_non_null_budgets_are_numbers(self, departments):
        for dept in departments:
            if dept["budget"] is not None:
                assert isinstance(dept["budget"], (int, float)), (
                    f"Department {dept['id']} budget should be a number, got {type(dept['budget'])}"
                )


class TestSalaries:
    """Verify the salaries table records."""

    @pytest.fixture
    def salaries(self, recover):
        return recover["salaries"]

    def test_fields_present(self, salaries):
        for sal in salaries:
            assert "emp_id" in sal
            assert "amount" in sal
            assert "bonus" in sal

    def test_emp_ids_match_employee_ids(self, salaries):
        """emp_id values should be 101-120 (matching employee ids)."""
        emp_ids = [s["emp_id"] for s in salaries]
        for eid in emp_ids:
            assert 101 <= eid <= 120, f"salary emp_id {eid} out of range"

    def test_amounts_are_expected_values(self, salaries):
        """Amounts should be 50000 + (emp_id - 101) * 5000."""
        for sal in salaries:
            expected = 50000 + (sal["emp_id"] - 101) * 5000
            assert sal["amount"] == pytest.approx(expected), (
                f"Salary for emp_id {sal['emp_id']} should be {expected}, got {sal['amount']}"
            )

    def test_null_bonus_rows(self, salaries):
        """Rows for emp_ids 102, 106, 110, 114, 118 have NULL bonuses."""
        null_emp_ids = {102, 106, 110, 114, 118}
        for sal in salaries:
            if sal["emp_id"] in null_emp_ids:
                assert sal["bonus"] is None, (
                    f"emp_id {sal['emp_id']} should have null bonus"
                )

    def test_numeric_bonus_rows(self, salaries):
        """Rows for emp_ids 103, 104, 107, 108, 111, 112, 115, 116, 119, 120
        have numeric bonuses."""
        numeric_ids = {103, 104, 107, 108, 111, 112, 115, 116, 119, 120}
        for sal in salaries:
            if sal["emp_id"] in numeric_ids:
                assert isinstance(sal["bonus"], (int, float)), (
                    f"emp_id {sal['emp_id']} bonus should be numeric, got {type(sal['bonus'])}"
                )

    def test_text_bonus_rows(self, salaries):
        """Rows for emp_ids 101, 105, 109, 113, 117 have text bonuses
        (overflow page values)."""
        text_ids = {101, 105, 109, 113, 117}
        for sal in salaries:
            if sal["emp_id"] in text_ids:
                assert isinstance(sal["bonus"], str), (
                    f"emp_id {sal['emp_id']} bonus should be a text string, got {type(sal['bonus'])}"
                )
                assert len(sal["bonus"]) > 100, (
                    f"emp_id {sal['emp_id']} text bonus is too short ({len(sal['bonus'])} chars), "
                    f"expected long overflow text"
                )
                assert "Performance bonus" in sal["bonus"], (
                    f"emp_id {sal['emp_id']} text bonus does not contain expected phrase"
                )
