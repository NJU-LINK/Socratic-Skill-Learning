from .validation import ensure_numeric_sequence, ensure_same_length


def dotproduct(a, b):
    left = ensure_numeric_sequence(a, "a")
    right = ensure_numeric_sequence(b, "b")
    ensure_same_length(left, right)
    return sum(x * y for x, y in zip(left, right))
