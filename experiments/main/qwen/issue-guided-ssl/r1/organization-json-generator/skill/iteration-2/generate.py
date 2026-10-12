#!/usr/bin/env python3
"""
CSV-to-JSON Organization Generator

Transforms departments.csv, employees.csv, and projects.csv into a nested
organization.json conforming to schema.json.

Handles the full family of variants including:
- Departments with no projects or no employees
- Empty member lists in projects
- Semicolon-delimited fields with whitespace, repeated delimiters, empties
- Skewed numeric distributions
- Cross-department project member references
"""

import csv
import json
import sys
import os
from datetime import datetime, timezone
from collections import defaultdict


def parse_semicolon_field(value):
    """Parse a semicolon-delimited field into a list of stripped, non-empty strings.
    
    Handles:
    - Empty string -> []
    - "a;b;c" -> ["a", "b", "c"]
    - "a;;b" -> ["a", "b"]  (repeated delimiters)
    - " a ; b " -> ["a", "b"]  (whitespace)
    - ";" -> []  (only delimiters)
    """
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def parse_csv(filepath):
    """Read a CSV file and return a list of dicts with stripped keys and values.
    
    Uses utf-8-sig encoding to handle BOM (Byte Order Mark) that some CSV
    exporters (e.g., Excel) may include.
    """
    rows = []
    with open(filepath, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for key, val in row.items():
                k = key.strip() if key else key
                v = val.strip() if val else ""
                cleaned[k] = v
            rows.append(cleaned)
    return rows


def parse_numeric(value, as_type=float):
    """Parse a numeric string, handling whitespace and formatting.
    
    Args:
        value: string to parse
        as_type: int or float
    
    Returns:
        Parsed numeric value, or 0 if empty/unparseable.
    """
    if not value or not value.strip():
        return as_type(0)
    cleaned = value.strip().replace(",", "")  # handle "1,500,000" formatting
    try:
        return as_type(cleaned)
    except (ValueError, TypeError):
        # Try float then convert if int requested
        try:
            f = float(cleaned)
            if as_type == int:
                return int(f)
            return f
        except (ValueError, TypeError):
            return as_type(0)


def parse_budget(value):
    """Parse budget field, returning int when possible, float otherwise.
    
    This produces more natural JSON output: 1500000 instead of 1500000.0
    """
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(",", "")
    try:
        # Try int first
        if "." not in cleaned:
            return int(cleaned)
        # Has decimal point - try float, but return int if it's a whole number
        f = float(cleaned)
        if f == int(f):
            return int(f)
        return f
    except (ValueError, TypeError):
        return 0


def build_organization(data_dir, schema_path=None):
    """Main pipeline: parse CSVs, assemble nested JSON, compute statistics."""
    
    # ── STEP 1: Parse CSVs ──────────────────────────────────────────────
    departments_raw = parse_csv(os.path.join(data_dir, "departments.csv"))
    employees_raw = parse_csv(os.path.join(data_dir, "employees.csv"))
    projects_raw = parse_csv(os.path.join(data_dir, "projects.csv"))
    
    # ── STEP 2: Build lookup structures ─────────────────────────────────
    # Department lookup
    departments_by_id = {}
    for dept in departments_raw:
        dept_id = dept.get("id", "").strip()
        departments_by_id[dept_id] = {
            "id": dept_id,
            "name": dept.get("name", "").strip(),
            "budget": parse_budget(dept.get("budget", "0")),
            "employees": [],
            "projects": [],
        }
    
    # Group employees by department_id
    for emp in employees_raw:
        dept_id = emp.get("department_id", "").strip()
        if dept_id not in departments_by_id:
            # Employee references unknown department - skip or create placeholder
            continue
        
        employee_record = {
            "id": emp.get("id", "").strip(),
            "name": emp.get("name", "").strip(),
            "position": emp.get("position", "").strip(),
            "skills": parse_semicolon_field(emp.get("skills", "")),
            "years_of_service": parse_numeric(emp.get("years_of_service", "0"), int),
        }
        departments_by_id[dept_id]["employees"].append(employee_record)
    
    # Group projects by department_id
    for proj in projects_raw:
        dept_id = proj.get("department_id", "").strip()
        if dept_id not in departments_by_id:
            continue
        
        project_record = {
            "name": proj.get("name", "").strip(),
            "status": proj.get("status", "").strip(),
            "members": parse_semicolon_field(proj.get("member_ids", "")),
            "deadline": proj.get("deadline", "").strip(),
        }
        departments_by_id[dept_id]["projects"].append(project_record)
    
    # ── STEP 3: Assemble nested JSON ────────────────────────────────────
    # Build departments array preserving CSV order
    departments_list = []
    for dept in departments_raw:
        dept_id = dept.get("id", "").strip()
        if dept_id in departments_by_id:
            departments_list.append(departments_by_id[dept_id])
    
    # Organization metadata - not from CSV, use sensible defaults
    organization = {
        "name": "Organization",
        "founded": "2020-01-01",
        "departments": departments_list,
    }
    
    # ── STEP 4: Compute statistics over ASSEMBLED data ──────────────────
    all_employees = []
    all_projects = []
    skill_counts = defaultdict(int)
    status_counts = defaultdict(int)
    dept_sizes = {}
    total_budget = 0.0
    dept_count = 0
    
    for dept in departments_list:
        dept_count += 1
        total_budget += dept["budget"]
        dept_sizes[dept["name"]] = len(dept["employees"])
        
        for emp in dept["employees"]:
            all_employees.append(emp)
            for skill in emp["skills"]:
                skill_counts[skill] += 1
        
        for proj in dept["projects"]:
            all_projects.append(proj)
            status_counts[proj["status"]] += 1
    
    total_employees = len(all_employees)
    total_years = sum(e["years_of_service"] for e in all_employees)
    
    statistics = {
        "averageDepartmentBudget": total_budget / dept_count if dept_count > 0 else 0.0,
        "totalEmployees": total_employees,
        "skillDistribution": dict(skill_counts),
        "departmentSizes": dept_sizes,
        "projectStatusDistribution": dict(status_counts),
        "averageYearsOfService": total_years / total_employees if total_employees > 0 else 0.0,
    }
    
    # ── STEP 5: Build final output ──────────────────────────────────────
    output = {
        "metadata": {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "csv-to-json-processor",
        },
        "organization": organization,
        "statistics": statistics,
    }
    
    return output


def validate_output(output, schema_path):
    """Validate output against JSON schema if jsonschema is available."""
    try:
        import jsonschema
        with open(schema_path, "r") as f:
            schema = json.load(f)
        jsonschema.validate(output, schema)
        return True, None
    except ImportError:
        return True, "jsonschema not available, skipping validation"
    except jsonschema.ValidationError as e:
        return False, str(e.message)


def main():
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    schema_path = os.environ.get("SCHEMA_PATH", "/app/schema.json")
    output_path = os.environ.get("OUTPUT_PATH", "/app/organization.json")
    
    # Build the organization JSON
    output = build_organization(data_dir, schema_path)
    
    # Validate against schema
    valid, error = validate_output(output, schema_path)
    if not valid:
        print(f"Schema validation FAILED: {error}", file=sys.stderr)
        sys.exit(1)
    elif error:
        print(f"Note: {error}", file=sys.stderr)
    else:
        print("Schema validation passed.", file=sys.stderr)
    
    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Output written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
