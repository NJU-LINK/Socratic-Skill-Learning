from ._engine import _DotProductEngine


def dotproduct(left, right):
    return _DotProductEngine().calculate(left, right)
