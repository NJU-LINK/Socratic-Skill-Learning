def validate_pair(left, right):
    if len(left) != len(right):
        raise ValueError("dotproduct requires lists of the same length")

    return left, right
