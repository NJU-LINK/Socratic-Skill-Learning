#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import re
from html.parser import HTMLParser
from pathlib import Path


REPORT_PATH = Path('/app/earnings-report.html')
OUTPUT_PATH = Path('/app/value.txt')


def parse_number(text: str) -> int:
    cleaned = text.strip().replace(',', '')
    if not re.fullmatch(r'-?\d+', cleaned):
        raise ValueError(f'Unsupported numeric value: {text!r}')
    return int(cleaned)


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tr = False
        self.current_td_class = None
        self.cell_text = []
        self.cells = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.in_tr = True
            self.cells = []
        elif self.in_tr and tag == 'td':
            self.current_td_class = attrs.get('class', '')
            self.cell_text = []

    def handle_data(self, data):
        if self.current_td_class is not None:
            self.cell_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.current_td_class is not None:
            text = ''.join(self.cell_text).strip()
            self.cells.append((self.current_td_class, text))
            self.current_td_class = None
            self.cell_text = []
        elif tag == 'tr' and self.in_tr:
            if len(self.cells) == 3:
                line = self.cells[0][1]
                metric = self.cells[1][1]
                value = self.cells[2][1]
                if line.isdigit():
                    self.rows.append({
                        'line': line,
                        'metric': metric,
                        'value': value,
                        'numeric': parse_number(value),
                    })
            self.in_tr = False
            self.cells = []


def build_equations():
    return [
        (
            'Gross profit',
            lambda values: values['Total revenue'] - values['Cost of revenue'],
        ),
        (
            'Total operating expenses',
            lambda values: values['Research and development']
            + values['Sales and marketing']
            + values['General and administrative'],
        ),
        (
            'Operating income',
            lambda values: values['Gross profit'] - values['Total operating expenses'],
        ),
        (
            'Total segment revenue',
            lambda values: values['Cloud platform revenue']
            + values['Enterprise software revenue']
            + values['Services and support revenue'],
        ),
        (
            'Non-GAAP operating income',
            lambda values: values['GAAP operating income']
            + values['Stock-based compensation']
            + values['Acquisition-related costs'],
        ),
    ]


def equation_is_applicable(metric, values):
    dependencies = {
        'Gross profit': ['Total revenue', 'Cost of revenue'],
        'Total operating expenses': [
            'Research and development',
            'Sales and marketing',
            'General and administrative',
        ],
        'Operating income': ['Gross profit', 'Total operating expenses'],
        'Total segment revenue': [
            'Cloud platform revenue',
            'Enterprise software revenue',
            'Services and support revenue',
        ],
        'Non-GAAP operating income': [
            'GAAP operating income',
            'Stock-based compensation',
            'Acquisition-related costs',
        ],
    }
    required = [metric, *dependencies[metric]]
    return all(name in values for name in required)


def find_incorrect_metric(rows):
    by_metric = {row['metric']: row for row in rows}
    values = {metric: row['numeric'] for metric, row in by_metric.items()}
    equations = build_equations()

    candidates = []
    for metric, derive in equations:
        if not equation_is_applicable(metric, values):
            continue
        expected = derive(values)
        if values[metric] == expected:
            continue

        adjusted = dict(values)
        adjusted[metric] = expected
        if all(
            adjusted[target] == expr(adjusted)
            for target, expr in equations
            if equation_is_applicable(target, adjusted)
        ):
            candidates.append(metric)

    if len(candidates) != 1:
        raise RuntimeError(f'Expected exactly one fixable inconsistent metric, found {candidates}')
    return by_metric[candidates[0]]


parser = ReportParser()
parser.feed(REPORT_PATH.read_text())
incorrect = find_incorrect_metric(parser.rows)
OUTPUT_PATH.write_text(f"{incorrect['line']},{incorrect['value']}\n")
PY
