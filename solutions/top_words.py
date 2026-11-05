import re
from collections import Counter

def top_words(text, k):
    """
    Return the k most frequent words in `text` as a list of (word, count) tuples.
    Words are compared case‑insensitively and punctuation is ignored.
    Ties are resolved by alphabetical order of the words.
    """
    # Extract words: lower‑case alphanumeric sequences
    words = re.findall(r"[a-z0-9]+", text.lower())
    freq = Counter(words)
    # Sort by descending count then alphabetically
    sorted_items = sorted(freq.items(), key=lambda item: (-item[1], item[0]))
    return sorted_items[:k]
