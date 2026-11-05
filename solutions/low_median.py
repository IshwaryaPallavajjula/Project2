def median(nums):
    """
    Return the median of a non-empty list of numbers without modifying the input list.
    For an odd number of elements, returns the middle element.
    For an even number of elements, returns the lower of the two middle elements.
    """
    if not nums:
        raise ValueError("median() arg is an empty sequence")
    sorted_nums = sorted(nums)
    n = len(sorted_nums)
    mid = n // 2
    if n % 2 == 1:
        return sorted_nums[mid]
    else:
        return sorted_nums[mid - 1]
