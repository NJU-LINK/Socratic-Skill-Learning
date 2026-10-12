from .validators import validate_vectors


def dotproduct(a, b):
    validate_vectors(a, b)
    return sum(left * right for left, right in zip(a, b))
