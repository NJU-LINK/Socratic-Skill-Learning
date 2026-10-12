from numbers import Real


def ensure_numeric_sequence(values, name):
    checked = []
    for item in values:
        if not isinstance(item, Real):
            raise TypeError(f"{name} must contain only numeric items")
        checked.append(item)
    return checked


def ensure_same_length(left, right):
    if len(left) != len(right):
        raise ValueError("sequences must have the same length")
