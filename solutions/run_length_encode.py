def rle(s: str) -> str:
    if not s:
        return ""
    result = []
    count = 1
    prev = s[0]
    for ch in s[1:]:
        if ch == prev:
            count += 1
        else:
            result.append(f"{prev}{count}")
            prev = ch
            count = 1
    result.append(f"{prev}{count}")
    return "".join(result)
