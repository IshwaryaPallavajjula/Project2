def is_palindrome(s: str) -> bool:
    filtered = [ch.lower() for ch in s if ch.isalnum()]
    return filtered == filtered[::-1]
