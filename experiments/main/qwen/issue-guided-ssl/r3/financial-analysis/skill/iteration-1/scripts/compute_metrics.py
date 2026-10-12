#!/usr/bin/env python3
"""
Financial metric computation registry.

Provides exact formulas for the five standard metrics in the family:
  - gross_margin
  - operating_margin
  - net_margin
  - return_on_equity
  - year_over_year_growth

All metrics are expressed as percentage numbers (e.g., 72.72 means 72.72%).
"""

from typing import Dict, List, Optional, Tuple, Callable


# ─── Metric Registry ──────────────────────────────────────────────────────────

class MetricFormula:
    """A financial metric with its formula, required fields, and computation."""

    def __init__(self, name: str, numerator_field: str, denominator_field: str,
                 description: str, requires_consecutive_years: bool = False):
        self.name = name
        self.numerator_field = numerator_field
        self.denominator_field = denominator_field
        self.description = description
        self.requires_consecutive_years = requires_consecutive_years

    def compute(self, data: Dict[int, Dict[str, float]], year: int) -> Optional[float]:
        """Compute the metric for a given year. Returns None if data is missing."""
        if year not in data:
            return None

        year_data = data[year]
        numerator = year_data.get(self.numerator_field)
        denominator = year_data.get(self.denominator_field)

        if numerator is None or denominator is None or denominator == 0:
            return None

        return (numerator / denominator) * 100

    def compute_all_years(self, data: Dict[int, Dict[str, float]]) -> List[Tuple[int, float]]:
        """Compute the metric for all available years."""
        results = []
        years = sorted(data.keys())

        for year in years:
            if self.requires_consecutive_years:
                # Need previous year data
                prev_year = year - 1
                if prev_year not in data:
                    continue
                prev_revenue = data[prev_year].get(self.denominator_field)
                curr_revenue = data[year].get(self.numerator_field)
                if prev_revenue is None or curr_revenue is None or prev_revenue == 0:
                    continue
                value = ((curr_revenue - prev_revenue) / prev_revenue) * 100
            else:
                value = self.compute(data, year)

            if value is not None:
                results.append((year, round(value, 2)))

        return results


# ─── Standard Metrics ─────────────────────────────────────────────────────────

METRICS = {
    'gross_margin': MetricFormula(
        name='gross_margin',
        numerator_field='gross_profit',
        denominator_field='revenue',
        description='Gross Profit / Revenue × 100',
    ),
    'operating_margin': MetricFormula(
        name='operating_margin',
        numerator_field='operating_income',
        denominator_field='revenue',
        description='Operating Income / Revenue × 100',
    ),
    'net_margin': MetricFormula(
        name='net_margin',
        numerator_field='net_income',
        denominator_field='revenue',
        description='Net Income / Revenue × 100',
    ),
    'return_on_equity': MetricFormula(
        name='return_on_equity',
        numerator_field='net_income',
        denominator_field='shareholders_equity',
        description='Net Income / Shareholders\' Equity × 100',
    ),
    'year_over_year_growth': MetricFormula(
        name='year_over_year_growth',
        numerator_field='revenue',  # current year revenue
        denominator_field='revenue',  # previous year revenue
        description='(Revenue_t - Revenue_{t-1}) / Revenue_{t-1} × 100',
        requires_consecutive_years=True,
    ),
}


def get_metric(name: str) -> Optional[MetricFormula]:
    """Get a metric formula by name."""
    return METRICS.get(name)


def compute_metric_for_year(metric_name: str, data: Dict[int, Dict[str, float]],
                            year: int) -> Optional[float]:
    """Compute a metric for a specific year, rounded to 2 decimal places."""
    formula = get_metric(metric_name)
    if formula is None:
        raise ValueError(f"Unknown metric: {metric_name}")
    value = formula.compute(data, year)
    return round(value, 2) if value is not None else None


def compute_metric_all_years(metric_name: str, data: Dict[int, Dict[str, float]]) -> List[Tuple[int, float]]:
    """Compute a metric for all available years."""
    formula = get_metric(metric_name)
    if formula is None:
        raise ValueError(f"Unknown metric: {metric_name}")
    return formula.compute_all_years(data)


def evaluate_condition(metric_name: str, data: Dict[int, Dict[str, float]],
                       condition_type: str, threshold: float,
                       year_selector: str = 'most_recent') -> bool:
    """
    Evaluate a conditional expression on a metric.

    Args:
        metric_name: The metric to evaluate
        data: Financial data by year
        condition_type: 'exceeds', 'below', 'positive', 'negative'
        threshold: The threshold value for exceeds/below
        year_selector: 'most_recent', 'earliest', 'all', or specific year int

    Returns:
        True if the condition is met
    """
    formula = get_metric(metric_name)
    if formula is None:
        return False

    years = sorted(data.keys())
    if not years:
        return False

    if year_selector == 'most_recent':
        target_years = [years[-1]]
    elif year_selector == 'earliest':
        target_years = [years[0]]
    elif year_selector == 'all':
        target_years = years
    else:
        target_years = [int(year_selector)]

    for year in target_years:
        value = formula.compute(data, year)
        if value is None:
            return False

        if condition_type == 'exceeds':
            if value <= threshold:
                return False
        elif condition_type == 'below':
            if value >= threshold:
                return False
        elif condition_type == 'positive':
            if value <= 0:
                return False
        elif condition_type == 'negative':
            if value >= 0:
                return False

    return True


if __name__ == '__main__':
    # Example usage with v01 data
    sample_data = {
        2022: {'revenue': 26914, 'gross_profit': 17475, 'net_income': 9752, 'operating_income': 10041},
        2023: {'revenue': 26974, 'gross_profit': 15356, 'net_income': 4368, 'operating_income': 4224},
        2024: {'revenue': 60922, 'gross_profit': 44301, 'net_income': 29760, 'operating_income': 32972},
        2025: {'revenue': 130497, 'gross_profit': 97858, 'net_income': 72880, 'operating_income': 81453},
        2026: {'revenue': 215938, 'gross_profit': 153463, 'net_income': 120067, 'operating_income': 130387},
    }

    print("Gross Margin by year:")
    for year, value in compute_metric_all_years('gross_margin', sample_data):
        print(f"  FY{year}: {value}%")

    print("\nNet Margin by year:")
    for year, value in compute_metric_all_years('net_margin', sample_data):
        print(f"  FY{year}: {value}%")

    print("\nCondition: most recent gross margin > 70%?")
    result = evaluate_condition('gross_margin', sample_data, 'exceeds', 70.0)
    print(f"  {result}")
