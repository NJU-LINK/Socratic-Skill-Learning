from .numeric import coerce_values


class Vector:
    def __init__(self, values):
        self.values = coerce_values(values)

    def magnitude_squared(self):
        return sum(abs(value) for value in self.values)

    def dot(self, other):
        other_values = coerce_values(other.values if isinstance(other, Vector) else other)
        return sum(left * right for left, right in zip(self.values, other_values))
