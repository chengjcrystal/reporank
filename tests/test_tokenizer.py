from app.search.tokenizer import tokenize


def test_lowercases_and_splits():
    assert tokenize("Distributed Systems Project") == ["distributed", "systems", "project"]


def test_removes_stopwords():
    toks = tokenize("a project for the database")
    assert "the" not in toks and "for" not in toks
    assert "project" in toks and "database" in toks


def test_preserves_special_tech_tokens():
    assert "c++" in tokenize("a C++ project")
    assert "c#" in tokenize("built with C#")
    assert "node.js" in tokenize("Node.js backend")


def test_query_and_doc_tokenization_match():
    # Identical pipeline for both sides is essential for recall.
    assert tokenize("FastAPI PostgreSQL") == tokenize("fastapi   postgresql")


def test_empty():
    assert tokenize("") == []
    assert tokenize(None) == []
