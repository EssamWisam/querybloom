"""Verify correctness of all SPARQL removal functions.

Self-contained: copies the five helpers inline to avoid heavy transitive imports.
"""

import re


# --- Copied from metrics/redundancy.py ---


def _remove_distinct(sparql: str) -> str:
    return re.sub(r"\bSELECT\s+DISTINCT\b", "SELECT", sparql, flags=re.IGNORECASE)


def _multiply_limit(sparql: str, factor: int = 5) -> str:
    def _repl(m):
        return f"LIMIT {int(m.group(1)) * factor}"

    return re.sub(r"\bLIMIT\s+(\d+)", _repl, sparql, flags=re.IGNORECASE)


def _remove_order_by(sparql: str) -> str:
    return re.sub(
        r"\bORDER\s+BY\s+.+?(?=\bLIMIT\b|\bOFFSET\b|\bHAVING\b|}|\Z)",
        "",
        sparql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _find_balanced_block(sparql: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    i = start
    while i < len(sparql):
        if sparql[i] == open_ch:
            depth += 1
        elif sparql[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(sparql)


def _remove_all_filter(sparql: str) -> str:
    result = sparql
    while True:
        match = re.search(r"\bFILTER\s*\(", result, re.IGNORECASE)
        if not match:
            break
        paren_start = match.end() - 1
        paren_end = _find_balanced_block(result, paren_start, "(", ")")
        result = result[: match.start()] + result[paren_end:]
    return result


def _remove_all_optional(sparql: str) -> str:
    result = sparql
    while True:
        match = re.search(r"\bOPTIONAL\s*\{", result, re.IGNORECASE)
        if not match:
            break
        brace_start = match.end() - 1
        brace_end = _find_balanced_block(result, brace_start, "{", "}")
        result = result[: match.start()] + result[brace_end:]
    return result


passed = 0

# --- DISTINCT ---
q1 = "SELECT DISTINCT ?x WHERE { ?x a <http://ex.org/C> }"
out = _remove_distinct(q1)
assert "DISTINCT" not in out
assert out.startswith("SELECT")
passed += 1
print(f"[PASS] DISTINCT removal: {out}")

# --- LIMIT ---
q2 = "SELECT ?x WHERE { ?x a <http://ex.org/C> } LIMIT 10"
out = _multiply_limit(q2)
assert "LIMIT 50" in out
passed += 1
print(f"[PASS] LIMIT x5: {out}")

# --- ORDER BY (before LIMIT) ---
q3 = "SELECT ?x WHERE { ?x a <http://ex.org/C> } ORDER BY DESC(?x) LIMIT 5"
out = _remove_order_by(q3)
assert "ORDER" not in out.upper()
assert "LIMIT 5" in out
passed += 1
print(f"[PASS] ORDER BY (before LIMIT): {out}")

# --- ORDER BY (end of query) ---
q3b = "SELECT ?x WHERE { ?x a <http://ex.org/C> } ORDER BY ?x"
out = _remove_order_by(q3b)
assert "ORDER" not in out.upper()
passed += 1
print(f"[PASS] ORDER BY (end): {out}")

# --- FILTER (simple) ---
q4 = "SELECT ?x WHERE { ?x <http://ex.org/p> ?y . FILTER(?y > 10) ?x <http://ex.org/q> ?z . }"
out = _remove_all_filter(q4)
assert "FILTER" not in out.upper()
assert "?x <http://ex.org/q> ?z" in out
passed += 1
print(f"[PASS] FILTER simple: {out}")

# --- FILTER (nested parens) ---
q5 = 'SELECT ?x WHERE { ?x <http://ex.org/p> ?y . FILTER(LANG(?y) = "en" && CONTAINS(STR(?y), "test")) }'
out = _remove_all_filter(q5)
assert "FILTER" not in out.upper()
passed += 1
print(f"[PASS] FILTER nested parens: {out}")

# --- FILTER with EXISTS (now removed too) ---
q6 = "SELECT ?x WHERE { ?x a <http://ex.org/C> . FILTER(EXISTS { ?x <http://ex.org/p> ?z }) FILTER(?x != <http://ex.org/bad>) }"
out = _remove_all_filter(q6)
assert "FILTER" not in out.upper(), "all FILTERs including EXISTS should be removed"
assert "!=" not in out
passed += 1
print(f"[PASS] FILTER w/ EXISTS removed: {out}")

# --- OPTIONAL (simple) ---
q7 = "SELECT ?x ?y WHERE { ?x a <http://ex.org/C> . OPTIONAL { ?x <http://ex.org/p> ?y } }"
out = _remove_all_optional(q7)
assert "OPTIONAL" not in out.upper()
assert "?x a <http://ex.org/C>" in out
passed += 1
print(f"[PASS] OPTIONAL simple: {out}")

# --- OPTIONAL (nested braces) ---
q8 = "SELECT ?x ?y ?z WHERE { ?x a <http://ex.org/C> . OPTIONAL { ?x <http://ex.org/p> ?y . OPTIONAL { ?y <http://ex.org/q> ?z } } }"
out = _remove_all_optional(q8)
assert "OPTIONAL" not in out.upper()
passed += 1
print(f"[PASS] OPTIONAL nested: {out}")

# --- Multiple FILTERs ---
q9 = "SELECT ?x WHERE { ?x <http://ex.org/p> ?y . FILTER(?y > 5) FILTER(?y < 100) }"
out = _remove_all_filter(q9)
assert "FILTER" not in out.upper()
passed += 1
print(f"[PASS] Multiple FILTERs: {out}")

# --- DISTINCT absent (no-op) ---
q10 = "SELECT ?x WHERE { ?x a <http://ex.org/C> }"
out = _remove_distinct(q10)
assert out == q10
passed += 1
print(f"[PASS] DISTINCT absent (no-op)")

# --- LIMIT absent (no-op) ---
out = _multiply_limit(q10)
assert out == q10
passed += 1
print(f"[PASS] LIMIT absent (no-op)")

# --- ORDER BY absent (no-op) ---
out = _remove_order_by(q10)
assert out == q10
passed += 1
print(f"[PASS] ORDER BY absent (no-op)")

# --- FILTER NOT EXISTS (also removed now) ---
q11 = "SELECT ?x WHERE { ?x a <http://ex.org/C> . FILTER(NOT EXISTS { ?x <http://ex.org/p> ?z }) }"
out = _remove_all_filter(q11)
assert "FILTER" not in out.upper(), "FILTER NOT EXISTS should be removed"
passed += 1
print(f"[PASS] FILTER NOT EXISTS removed: {out}")

print(f"\n=== ALL {passed} TESTS PASSED ===")
