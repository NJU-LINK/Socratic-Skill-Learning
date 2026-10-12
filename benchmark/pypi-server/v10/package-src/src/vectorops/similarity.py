import math

from .mathops import dotproduct


def cosine_similarity(a, b):
    left = math.sqrt(dotproduct(a, a))
    right = math.sqrt(dotproduct(b, b))
    return dotproduct(a, b) / (left * right)
