from .models import Vector
from .numeric import coerce_values


def dotproduct(left, right):
    left_values = coerce_values(left)
    right_values = coerce_values(right)
    return Vector(left_values).dot(right_values)
