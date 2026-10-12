from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader


DATA = Path("/app/data")
SOURCE = DATA / "sales_report.pdf"
REGION_NAMES = ("Australia", "North America", "South America")
MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)


def _source_rows() -> list[tuple[int, int, str]]:
    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(SOURCE).pages
    )
    rows = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        for region in REGION_NAMES:
            pattern = (
                rf"^(?:{MONTHS})\s+([\d,]+)\s+\$?([\d,]+)\s+"
                rf"{re.escape(region)}\s+\S"
            )
            match = re.match(pattern, line)
            if match:
                rows.append(
                    (
                        int(match.group(1).replace(",", "")),
                        int(match.group(2).replace(",", "")),
                        region,
                    )
                )
                break
    assert rows, "Source PDF has no parseable sales rows"
    return rows


def _expected() -> dict[str, object]:
    rows = _source_rows()
    units = [row[0] for row in rows]
    revenues = [row[1] for row in rows]
    mean_units = sum(units) / len(units)
    mean_revenue = sum(revenues) / len(revenues)
    numerator = sum(
        (unit - mean_units) * (revenue - mean_revenue)
        for unit, revenue in zip(units, revenues)
    )
    denominator = math.sqrt(
        sum((unit - mean_units) ** 2 for unit in units)
        * sum((revenue - mean_revenue) ** 2 for revenue in revenues)
    )

    regions = []
    for region in sorted({row[2] for row in rows}):
        selected = [row for row in rows if row[2] == region]
        total_units = sum(row[0] for row in selected)
        total_revenue = sum(row[1] for row in selected)
        regions.append(
            {
                "region": region,
                "record_count": len(selected),
                "total_units": total_units,
                "total_revenue": total_revenue,
                "revenue_per_unit": round(total_revenue / total_units, 6),
            }
        )

    return {
        "record_count": len(rows),
        "overall": {
            "total_units": sum(units),
            "total_revenue": sum(revenues),
            "pearson_units_revenue": round(numerator / denominator, 6),
        },
        "regions": regions,
        "highest_total_revenue_region": min(
            regions,
            key=lambda row: (-row["total_revenue"], row["region"]),
        )["region"],
        "highest_revenue_per_unit_region": min(
            regions,
            key=lambda row: (-row["revenue_per_unit"], row["region"]),
        )["region"],
    }


EXPECTED = _expected()

sys.path.insert(0, "/app")
from solve import run


def _actual() -> dict[str, object]:
    return json.loads((DATA / "analysis.json").read_text(encoding="utf-8"))


def test_json_schema_and_region_order() -> None:
    run()
    actual = _actual()
    assert set(actual) == {
        "record_count",
        "overall",
        "regions",
        "highest_total_revenue_region",
        "highest_revenue_per_unit_region",
    }
    assert list(actual["overall"]) == [
        "total_units",
        "total_revenue",
        "pearson_units_revenue",
    ]
    assert [row["region"] for row in actual["regions"]] == sorted(REGION_NAMES)


def test_overall_metrics() -> None:
    run()
    actual = _actual()
    assert actual["record_count"] == EXPECTED["record_count"]
    assert actual["overall"]["total_units"] == EXPECTED["overall"]["total_units"]
    assert actual["overall"]["total_revenue"] == EXPECTED["overall"]["total_revenue"]
    assert actual["overall"]["pearson_units_revenue"] == pytest.approx(
        EXPECTED["overall"]["pearson_units_revenue"],
        abs=1e-6,
    )


@pytest.mark.parametrize("expected", EXPECTED["regions"])
def test_region_metrics(expected: dict[str, object]) -> None:
    run()
    actual = {
        row["region"]: row
        for row in _actual()["regions"]
    }[expected["region"]]
    assert set(actual) == {
        "region",
        "record_count",
        "total_units",
        "total_revenue",
        "revenue_per_unit",
    }
    assert actual["record_count"] == expected["record_count"]
    assert actual["total_units"] == expected["total_units"]
    assert actual["total_revenue"] == expected["total_revenue"]
    assert actual["revenue_per_unit"] == pytest.approx(
        expected["revenue_per_unit"],
        abs=1e-6,
    )


def test_highest_total_revenue_region() -> None:
    run()
    assert (
        _actual()["highest_total_revenue_region"]
        == EXPECTED["highest_total_revenue_region"]
    )


def test_highest_revenue_per_unit_region() -> None:
    run()
    assert (
        _actual()["highest_revenue_per_unit_region"]
        == EXPECTED["highest_revenue_per_unit_region"]
    )


def test_analysis_image_is_readable_jpeg() -> None:
    run()
    with Image.open(DATA / "analyze.jpg") as image:
        assert image.format == "JPEG"
        assert image.width >= 1200
        assert image.height >= 800


def test_analysis_image_has_structured_content() -> None:
    run()
    with Image.open(DATA / "analyze.jpg") as image:
        rgb = image.convert("RGB")
        colors = rgb.resize((280, 180)).getcolors(maxcolors=280 * 180)
        assert colors is not None
        non_background = sum(
            count
            for count, color in colors
            if max(color) - min(color) > 12 or max(color) < 235
        )
        assert len(colors) > 100
        assert non_background > 1500
