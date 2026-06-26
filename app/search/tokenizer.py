"""Tokenizer for repository text and queries.

Design choices (worth defending in an interview):
- Lowercase, split on non-alphanumeric, BUT preserve common tech tokens that
  would otherwise be destroyed: c++, c#, .net, node.js, etc.
- Small curated stopword list. We deliberately keep short tech terms (go, c, r,
  ml, ai) that a generic English stopword list would drop.
- No stemming in v1. Stemming mangles tech terms ("redis" -> "redi"); we expose
  it later behind a flag as a measurable ranking experiment.

Tokenization must be IDENTICAL for indexing and querying, so both paths call
`tokenize()`. BM25 is a bag-of-words model, so token order does not matter.
"""
import re

# Multi-character tech tokens that survive intact (extracted before generic split).
_SPECIAL_TOKENS = [
    "objective-c", "node.js", "asp.net", "scikit-learn",
    "c++", "c#", "f#", ".net", "ci/cd", "k8s",
]

# Keep this list tight. Removing too much hurts recall on technical text.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "be", "this", "that", "it", "as", "by", "from", "at",
    "your", "you", "we", "our", "can", "will", "use", "using", "used",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    text = text.lower()

    # Extract special tokens first, then strip them from the text so the generic
    # splitter can't break them apart (e.g. "c++" -> "c").
    preserved: list[str] = []
    for tok in _SPECIAL_TOKENS:
        while tok in text:
            preserved.append(tok)
            text = text.replace(tok, " ", 1)

    raw = _TOKEN_RE.findall(text)

    tokens: list[str] = []
    for t in raw:
        if t in _STOPWORDS:
            continue
        if len(t) == 1 and t.isdigit():
            continue
        tokens.append(t)

    return preserved + tokens
