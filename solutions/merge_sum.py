def merge_sum(a, b):
    """
    Merge two dictionaries of numbers, adding values for keys present in both.
    Neither input dictionary is modified.

    Parameters:
        a (dict): First dictionary with numeric values.
        b (dict): Second dictionary with numeric values.

    Returns:
        dict: A new dictionary containing the merged keys and summed values.
    """
    result = {}
    for key, value in a.items():
        result[key] = value
    for key, value in b.items():
        if key in result:
            result[key] = result[key] + value
        else:
            result[key] = value
    return result
