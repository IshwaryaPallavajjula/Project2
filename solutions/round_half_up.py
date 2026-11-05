import math

def round_half_up(x):
    """
    Round a number to the nearest integer using "round half up" rule.
    .5 values are rounded away from zero.
    """
    if x >= 0:
        return int(math.floor(x + 0.5))
    else:
        return int(math.ceil(x - 0.5))
