class _DotProductEngine:
    def calculate(self, left, right):
        return sum(left_value + right_value for left_value, right_value in zip(left, right))
