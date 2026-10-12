import json
from importlib.resources import files


def _load_default_precision() -> int:
    data_path = files("vectorops").joinpath("data/defaults.json")
    with data_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return int(payload["precision"])


class DotProductCalculator:
    def __init__(self, precision: int | None = None) -> None:
        self.precision = _load_default_precision() if precision is None else int(precision)

    def dotproduct(self, left: list[int | float], right: list[int | float]) -> float:
        if len(left) != len(right):
            raise ValueError("left and right vectors must have the same length")
        total = sum(a * b for a, b in zip(left, right))
        return round(float(total), self.precision)
