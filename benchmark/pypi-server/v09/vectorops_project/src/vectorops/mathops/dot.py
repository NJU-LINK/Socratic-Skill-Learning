from vectorops.mathops.helpers import multiply_pair
from vectorops.validation import validate_pair


def dotproduct(left, right):
    validated_left, validated_right = validate_pair(left, right)
    return sum(multiply_pair(a, b) for a, b in zip(validated_left, validated_right))
