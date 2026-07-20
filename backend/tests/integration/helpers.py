import math


def normalized_vector() -> list[float]:
    base = [1.0] * 512
    norm = math.sqrt(sum(v * v for v in base))
    return [v / norm for v in base]


def another_normalized_vector() -> list[float]:
    base = [1.0] * 256 + [2.0] * 256
    norm = math.sqrt(sum(v * v for v in base))
    return [v / norm for v in base]
