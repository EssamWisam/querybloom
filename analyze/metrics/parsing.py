"""Shared SPARQL parsing utilities: feature extraction, rdflib AST walk, query anonymisation."""

import re
import os
import sys

import rdflib
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.term import URIRef, Variable, Literal

try:
    from querybloom.executor.sparql_executor import execute_sparql_query
except Exception:
    execute_sparql_query = None

_ENTITY_TYPE_CACHE = {}

FEATURE_KEYS = [
    "SELECT",
    "ASK",
    "DISTINCT",
    "COUNT",
    "OPTIONAL",
    "UNION",
    "FILTER",
    "EXISTS",
    "GROUP BY",
    "HAVING",
    "ORDER BY",
    "LIMIT",
    "Property Paths",
]

# Features to hide from bar chart (redundant with others or broken into subtypes)
BAR_CHART_EXCLUDE = {"COUNT", "FILTER", "EXISTS"}


# ---------------------------------------------------------------------------
# SPARQL 1.1 built-in functions (spec-defined, used for automated FILTER
# subtype discovery).  Order defines label priority when a clause contains
# multiple nested functions (outermost / most-specific wins).
# ---------------------------------------------------------------------------
_SPARQL_BUILTIN_FUNCS = {
    "REGEX",
    "CONTAINS",
    "STRSTARTS",
    "STRENDS",
    "STRLEN",
    "SUBSTR",
    "UCASE",
    "LCASE",
    "ENCODE_FOR_URI",
    "CONCAT",
    "REPLACE",
    "YEAR",
    "MONTH",
    "DAY",
    "HOURS",
    "MINUTES",
    "SECONDS",
    "TIMEZONE",
    "TZ",
    "NOW",
    "LANG",
    "LANGMATCHES",
    "DATATYPE",
    "BOUND",
    "SAMETERM",
    "ISIRI",
    "ISURI",
    "ISBLANK",
    "ISLITERAL",
    "ISNUMERIC",
    "ABS",
    "ROUND",
    "CEIL",
    "FLOOR",
    "RAND",
    "IF",
    "COALESCE",
    "IN",
    "BNODE",
    "STRDT",
    "STRLANG",
    "STR",
    "IRI",
    "URI",
}

# Functions that are almost always nested helpers (e.g. NOW inside YEAR);
# suppress them when a more informative function is also present.
_NESTED_HELPERS = {"NOW", "STR", "URI", "IRI", "BNODE"}


def extract_filter_subtypes(sparql):
    """Derive canonical subtype labels for every FILTER clause in *sparql*.

    Returns a **set** of ``"FILTER:<label>"`` strings (one per distinct
    subtype found).  The label is automatically determined from the
    SPARQL 1.1 built-in functions and comparison operators present in
    the clause — no manual category mapping.
    """
    body = strip_lang_en_filters(get_query_body(sparql))
    upper = body.upper()
    if "FILTER" not in upper:
        return set()

    subtypes = set()

    # 1. EXISTS / NOT EXISTS (keyword-level, not parenthesised)
    if re.search(r"\bFILTER\s+NOT\s+EXISTS\b", upper):
        subtypes.add("FILTER:NOT EXISTS")
    if re.search(r"\bFILTER\s+(?!NOT)EXISTS\b", upper):
        subtypes.add("FILTER:EXISTS")

    # 2. Parenthesised FILTER(...) — balanced-paren extraction
    for m in re.finditer(r"\bFILTER\s*\(", upper):
        start = m.end()
        depth, pos = 1, start
        while pos < len(upper) and depth > 0:
            if upper[pos] == "(":
                depth += 1
            elif upper[pos] == ")":
                depth -= 1
            pos += 1
        clause = upper[start : pos - 1]

        # Find recognised SPARQL built-in function calls (NAME followed by '(')
        fns = [
            tok
            for tok in re.findall(r"\b([A-Z_]+)\s*\(", clause)
            if tok in _SPARQL_BUILTIN_FUNCS
        ]
        # Remove nested helpers when a more informative function is present
        informative = [f for f in fns if f not in _NESTED_HELPERS]
        label_fns = informative if informative else fns

        if label_fns:
            # Use the first (outermost) recognised function as the label
            subtypes.add(f"FILTER:{label_fns[0]}")
        else:
            # No function call — classify by comparison operator
            if "!=" in clause:
                subtypes.add("FILTER:!=")
            elif re.search(r">=|<=|(?<!=)>|(?<!=)<(?!=)", clause):
                subtypes.add("FILTER:comparison")
            elif "=" in clause:
                subtypes.add("FILTER:=")
            elif re.search(r"\bIN\b", clause):
                subtypes.add("FILTER:IN")
            else:
                subtypes.add("FILTER:other")

    return subtypes


def get_entity_classes(entity_uri, endpoint="dblp"):
    if not execute_sparql_query:
        return set()
    entity_uri = _normalize_uri_escapes(f"<{entity_uri}>")[1:-1]
    if entity_uri in _ENTITY_TYPE_CACHE:
        return _ENTITY_TYPE_CACHE[entity_uri]
    # Fetch only the most specific (leaf) types: exclude any class that
    # has a more specific subclass also asserted for this entity.
    query = (
        f"SELECT DISTINCT ?t WHERE {{ "
        f"<{entity_uri}> a ?t . "
        f"FILTER NOT EXISTS {{ "
        f"  <{entity_uri}> a ?sub . "
        f"  ?sub <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?t . "
        f"  FILTER(?sub != ?t) "
        f"}} }} LIMIT 1"
    )
    try:
        res = execute_sparql_query(query, endpoint=endpoint)
        if res.get("success") and res.get("results"):
            classes = set(r["t"]["value"] for r in res["results"] if "t" in r)
            _ENTITY_TYPE_CACHE[entity_uri] = classes
            return classes
    except Exception:
        pass
    _ENTITY_TYPE_CACHE[entity_uri] = set()
    return set()


def get_query_body(sparql):
    """Isolate the query body without PREFIX definitions."""
    return re.sub(r"PREFIX.*?\n", "", sparql, flags=re.IGNORECASE).strip()


def strip_lang_en_filters(sparql):
    """Remove FILTER clauses that only check ``lang(...) = 'en'`` or
    ``langMatches(lang(...), 'en')``.

    These are boilerplate language-gate filters that add no structural
    variety.  The removal is applied *before* feature counting so they
    don't inflate the FILTER percentage or affect redundancy checks.
    """
    result = sparql

    # Pattern 1: FILTER( lang(...) = "en" )
    p1 = re.compile(
        r"""\bFILTER\s*\(\s*          # FILTER (
            lang\s*\(                  # lang(
            [^)]*                      # variable inside lang()
            \)\s*                      # )
            =\s*                       # =
            ['"]en['"]\s*             # 'en' or "en"
            \)                         # closing paren of FILTER
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    result = p1.sub("", result)

    # Pattern 2: FILTER( langMatches(lang(...), "en") )
    p2 = re.compile(
        r"""\bFILTER\s*\(\s*          # FILTER (
            langMatches\s*\(\s*        # langMatches(
            lang\s*\(                  # lang(
            [^)]*                      # variable inside lang()
            \)\s*,\s*                  # ),
            ['"]en['"]\s*             # 'en' or "en"
            \)\s*                      # closing paren of langMatches
            \)                         # closing paren of FILTER
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    result = p2.sub("", result)

    return result


def analyze_sparql_features(sparql):
    """Check for the presence of SPARQL 1.1 structural features. Returns dict of binary flags."""
    upper_sparql = sparql.upper()
    body = strip_lang_en_filters(get_query_body(sparql))
    upper_body = body.upper()

    has_select = 1 if re.search(r"\bSELECT\b", upper_sparql) else 0
    has_ask = 1 if re.search(r"\bASK\b", upper_sparql) else 0
    has_distinct = 1 if re.search(r"\bDISTINCT\b", upper_sparql) else 0
    has_count = 1 if re.search(r"\bCOUNT\b", upper_sparql) else 0
    has_optional = 1 if "OPTIONAL" in upper_body else 0
    has_union = 1 if "UNION" in upper_body else 0
    has_filter = 1 if "FILTER" in upper_body else 0
    has_groupby = 1 if "GROUP BY" in upper_body else 0
    has_having = 1 if "HAVING" in upper_body else 0
    has_orderby = 1 if "ORDER BY" in upper_body else 0
    has_limit = 1 if "LIMIT" in upper_body else 0
    has_exists = 1 if re.search(r"\bEXISTS\b", upper_body) else 0

    sanitized = re.sub(r"<[^>]+>", "URI", body)
    sanitized = re.sub(r'".*?"(\^\^<.*?>)?', "LITERAL", sanitized)
    has_property_path = (
        1 if re.search(r"(:[a-zA-Z0-9_]+|URI)[\s]*[\*\+\|\/]", sanitized) else 0
    )

    return {
        "SELECT": has_select,
        "ASK": has_ask,
        "DISTINCT": has_distinct,
        "COUNT": has_count,
        "OPTIONAL": has_optional,
        "UNION": has_union,
        "FILTER": has_filter,
        "EXISTS": has_exists,
        "GROUP BY": has_groupby,
        "HAVING": has_having,
        "ORDER BY": has_orderby,
        "LIMIT": has_limit,
        "Property Paths": has_property_path,
    }


def _normalize_uri_escapes(sparql):
    """Remove SPARQL-style backslash escapes inside angle-bracket URIs.

    Some benchmark queries contain IRIs like ``Barons\'_Crusade`` or
    ``Armageddon_\(2008\)``.  The punctuation itself is valid in an IRIREF;
    the literal backslash is not, and rdflib warns when building URIRef terms.
    """
    return re.sub(
        r"<([^>]*)>",
        lambda m: "<" + re.sub(r"\\([!'()*+,;=:/?#@$_\-.~])", r"\1", m.group(1)) + ">",
        sparql,
    )


def parse_and_extract_rdflib_metrics(sparql, endpoint="dblp"):
    """Uses rdflib to parse entities, properties, variables, and triple count."""
    import warnings

    sparql = _normalize_uri_escapes(sparql)

    metrics = {
        "num_triples": 0,
        "variables": set(),
        "entities": [],
        "classes": set(),
        "properties": set(),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = parseQuery(sparql)
            algebra = translateQuery(parsed).algebra
    except Exception:
        return metrics

    def walk_algebra(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "triples" and v is not None:
                    metrics["num_triples"] += len(v)
                    for triple in v:
                        s, p, o = triple[:3]
                        is_type_triple = str(
                            p
                        ) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" and isinstance(
                            o, URIRef
                        )
                        if is_type_triple:
                            metrics["classes"].add(str(o))
                        for term, is_class_obj in [(s, False), (o, is_type_triple)]:
                            if is_class_obj:
                                pass  # class URI — not an instance entity
                            elif isinstance(term, (URIRef, Literal)):
                                metrics["entities"].append(str(term))
                            elif isinstance(term, Variable):
                                metrics["variables"].add(str(term))
                        if isinstance(p, URIRef):
                            metrics["properties"].add(str(p))
                        elif isinstance(p, Variable):
                            metrics["variables"].add(str(p))
                else:
                    walk_algebra(v)
        elif isinstance(node, list):
            for item in node:
                walk_algebra(item)

    walk_algebra(algebra)

    # Use the SELECT projection list (PV) when available — it gives the true
    # number of output columns.  ASK queries have no PV, so fall back to the
    # variables collected from the graph pattern.
    pv = getattr(algebra, "PV", None)
    if pv is not None:
        metrics["variables"] = {str(v) for v in pv}

    for entity in set(metrics["entities"]):
        if entity.startswith("http"):
            entity_classes = get_entity_classes(entity, endpoint)
            metrics["classes"].update(entity_classes)

    return metrics


def anonymise_query(sparql):
    """Anonymise a SPARQL query to a structural template.

    Both full URIs (``<http://…>``) and prefixed names (``dbo:Thing``)
    are replaced with the same ``<URI>`` token so that queries differing
    only in prefix style produce identical templates.
    """
    body = get_query_body(sparql)
    body = re.sub(r"\?[a-zA-Z0-9_]+", "?VAR", body)
    body = re.sub(r"<[^>]+>", "<URI>", body)
    body = re.sub(r'".*?"(\^\^<.*?>)?|[\'0-9]+', "<LITERAL>", body)
    # Replace prefixed names (e.g. dbo:Thing) with <URI> — same token used
    # for full URIs above — so prefix style doesn't affect the template.
    body = re.sub(r"\b[a-zA-Z0-9_]+:[a-zA-Z0-9_]+\b", "<URI>", body)
    return body.strip()


def _anonymise_text(text):
    """Anonymise a fragment of SPARQL (same rules as anonymise_query)."""
    text = re.sub(r"\?[a-zA-Z0-9_]+", "?VAR", text)
    text = re.sub(r"<[^>]+>", "<URI>", text)
    text = re.sub(r'".*?"(\^\^<.*?>)?|[\'0-9]+', "<LITERAL>", text)
    text = re.sub(r"\b[a-zA-Z0-9_]+:[a-zA-Z0-9_]+\b", "<URI>", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_filter_templates(sparql):
    """Return a list of anonymised FILTER clause templates from *sparql*.

    Each FILTER clause body is anonymised (URIs, variables, literals replaced)
    so that structurally identical filters map to the same template string.
    ``FILTER EXISTS`` / ``FILTER NOT EXISTS`` are returned as literal tokens.
    """
    body = strip_lang_en_filters(get_query_body(sparql))
    upper = body.upper()
    if "FILTER" not in upper:
        return []

    templates = []

    # EXISTS / NOT EXISTS (keyword-level — not parenthesised expressions)
    for _ in re.finditer(r"\bFILTER\s+NOT\s+EXISTS\b", upper):
        templates.append("FILTER NOT EXISTS { ... }")
    for _ in re.finditer(r"\bFILTER\s+(?!NOT)EXISTS\b", upper):
        templates.append("FILTER EXISTS { ... }")

    # Parenthesised FILTER(...) — balanced-paren extraction on original body
    for m in re.finditer(r"\bFILTER\s*\(", body, re.IGNORECASE):
        start = m.end()
        depth, pos = 1, start
        while pos < len(body) and depth > 0:
            if body[pos] == "(":
                depth += 1
            elif body[pos] == ")":
                depth -= 1
            pos += 1
        clause = body[start : pos - 1]
        templates.append("FILTER ( " + _anonymise_text(clause) + " )")

    return templates
