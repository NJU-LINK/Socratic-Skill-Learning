import math


def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))


def vector_length(values):
    return math.sqrt(sum(value * value for value in values))
