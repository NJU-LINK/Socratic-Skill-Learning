def validate_vectors(a, b):
    if not isinstance(a, list) or not isinstance(b, list):
        raise TypeError("dotproduct expects two lists")

    if len(a) != len(b):
        raise ValueError("vectors must have the same length")

    for value in a + b:
        if not isinstance(value, (int, float)):
            raise TypeError("vector elements must be ints or floats")
