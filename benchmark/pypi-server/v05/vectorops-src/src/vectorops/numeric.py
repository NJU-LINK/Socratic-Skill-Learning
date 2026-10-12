def coerce_values(values):
    if isinstance(values, (str, bytes)):
        raise TypeError("values must be an iterable of numbers")

    coerced = []
    for value in values:
        if not isinstance(value, (int, float)):
            raise TypeError("values must contain only ints or floats")
        coerced.append(value)

    return coerced
