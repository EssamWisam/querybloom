"""Shared SPARQL parsing utilities: feature extraction, rdflib AST walk, query anonymisation."""

import re
import os
import sys
import logging
import json

import rdflib
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.term import URIRef, Variable, Literal

from ._cache import _CACHE_ROOT, _make_key

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
)
try:
    from querybloom.executor.sparql_executor import execute_sparql_query
except Exception:
    execute_sparql_query = None

logger = logging.getLogger(__name__)

_META_TYPES = {
    "http://www.w3.org/2002/07/owl#Class",
    "http://www.w3.org/2000/01/rdf-schema#Class",
    "http://www.w3.org/2000/01/rdf-schema#Datatype",
}
_ENTITY_TYPE_CACHE_DIR = os.path.join(_CACHE_ROOT, "entity_types")
_CLASS_INSTANCE_CACHE_DIR = os.path.join(_CACHE_ROOT, "class_instances")

_QALD9_PREFIXES = {
    "dbc": "http://dbpedia.org/resource/Category:",
    "dct": "http://purl.org/dc/terms/",
    "yago": "http://dbpedia.org/class/yago/",
}

_LITERAL_PATTERN = re.compile(
    r"""
    (?:
        "(?:\\.|[^"\\])*"          # Double-quoted string
        | '(?:\\.|[^'\\])*'         # Single-quoted string
    )
    (?:
        @[a-zA-Z]+(?:-[a-zA-Z0-9]+)*  # Optional language tag
        | \^\^<URI>                   # Optional datatype, after URI replacement
    )?
    |
    (?<![a-zA-Z0-9_.])                # Do not match digits inside names or decimals
    [+-]?
    (?:\d+\.\d*|\.\d+|\d+)         # Integer or decimal
    (?:[eE][+-]?\d+)?                 # Optional exponent
    (?![a-zA-Z0-9_.])
    """,
    re.VERBOSE,
)

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

# Features to hide from feature distribution bar chart
BAR_CHART_EXCLUDE = {"COUNT", "DISTINCT", "EXISTS"}


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


def _lookup_cache_path(cache_dir, endpoint, entity_uri):
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{_make_key(endpoint, entity_uri)}.json")


def _load_successful_lookup(cache_dir, endpoint, entity_uri, field):
    if os.environ.get("METRICS_NO_CACHE") == "1":
        return None
    try:
        with open(_lookup_cache_path(cache_dir, endpoint, entity_uri)) as cache_file:
            cached = json.load(cache_file)
        if cached.get("success") is True:
            return cached[field]
    except Exception:
        pass
    return None


def _store_successful_lookup(cache_dir, endpoint, entity_uri, **result):
    if os.environ.get("METRICS_NO_CACHE") == "1":
        return
    try:
        with open(_lookup_cache_path(cache_dir, endpoint, entity_uri), "w") as cache_file:
            json.dump({"success": True, **result}, cache_file)
    except Exception:
        pass


def _log_lookup_failure(kind, entity_uri, endpoint, query_source, query_index, reason):
    logger.warning(
        "[metrics.parsing] --- %s lookup failed ---\n"
        "source=%s query_index=%s endpoint=%s\n"
        "fallback=continue classification without this lookup\n"
        "entity=%s reason=%s",
        kind,
        query_source or "<unspecified>",
        query_index if query_index is not None else "<unspecified>",
        endpoint,
        entity_uri,
        reason,
    )


def get_entity_classes(entity_uri, endpoint="dblp", query_source=None, query_index=None):
    """Return endpoint types, or ``None`` when the lookup fails."""
    if not execute_sparql_query:
        _log_lookup_failure(
            "entity type", entity_uri, endpoint, query_source, query_index, "executor unavailable"
        )
        return None
    entity_uri = _normalize_uri_escapes(f"<{entity_uri}>")[1:-1]
    cached = _load_successful_lookup(
        _ENTITY_TYPE_CACHE_DIR, endpoint, entity_uri, "types"
    )
    if cached is not None:
        return set(cached)
    query = (
        f"SELECT DISTINCT ?t WHERE {{ <{entity_uri}> a ?t }}"
    )
    try:
        res = execute_sparql_query(query, endpoint=endpoint)
        results = res.get("results")
        if res.get("success") and isinstance(results, list):
            classes = set(
                r["t"]["value"] for r in results if "t" in r
            )
            _store_successful_lookup(
                _ENTITY_TYPE_CACHE_DIR, endpoint, entity_uri, types=sorted(classes)
            )
            return classes
        reason = (
            "successful response did not contain a result list"
            if res.get("success")
            else res.get("error_message")
            or res.get("error")
            or res.get("status", "unknown error")
        )
        _log_lookup_failure(
            "entity type", entity_uri, endpoint, query_source, query_index,
            reason,
        )
    except Exception as exc:
        _log_lookup_failure(
            "entity type", entity_uri, endpoint, query_source, query_index, exc
        )
    return None


def _get_ask_result(response):
    for key in ("boolean", "result", "ask"):
        value = response.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
    results = response.get("results")
    return results if isinstance(results, bool) else None


def uri_has_instances(entity_uri, endpoint="dblp", query_source=None, query_index=None):
    """Return whether any resource has ``entity_uri`` as its type, or ``None`` on failure."""
    if not execute_sparql_query:
        _log_lookup_failure(
            "class instance", entity_uri, endpoint, query_source, query_index, "executor unavailable"
        )
        return None
    cached = _load_successful_lookup(
        _CLASS_INSTANCE_CACHE_DIR, endpoint, entity_uri, "has_instances"
    )
    if cached is not None:
        return bool(cached)
    query = f"ASK {{ ?x a <{entity_uri}> }}"
    try:
        res = execute_sparql_query(query, endpoint=endpoint)
        if res.get("success"):
            has_instances = _get_ask_result(res)
            if has_instances is not None:
                _store_successful_lookup(
                    _CLASS_INSTANCE_CACHE_DIR,
                    endpoint,
                    entity_uri,
                    has_instances=has_instances,
                )
                return has_instances
            reason = "successful response did not contain a boolean result"
        else:
            reason = (
                res.get("error_message")
                or res.get("error")
                or res.get("status", "unknown error")
            )
        _log_lookup_failure(
            "class instance", entity_uri, endpoint, query_source, query_index,
            reason,
        )
    except Exception as exc:
        _log_lookup_failure(
            "class instance", entity_uri, endpoint, query_source, query_index, exc
        )
    return None


def resolve_terms(
    parsed_metrics,
    endpoint="dblp",
    kg_name=None,
    kgs_data_dir=None,
    query_source=None,
    query_index=None,
    ontology_classes=None,
):
    """Resolve directly named and entity-implied classes using KG evidence."""
    if ontology_classes is None:
        from ontology_loader import load_ontology_classes

        ontology_classes = (
            load_ontology_classes(kg_name, kgs_data_dir) if kg_name else set()
        )
    classes = set(parsed_metrics["classes"])
    raw_entities = parsed_metrics["entities"]
    for entity_uri in dict.fromkeys(raw_entities):
        if entity_uri in classes:
            continue
        entity_types = get_entity_classes(
            entity_uri, endpoint, query_source, query_index
        )
        if entity_types is not None:
            classes.update(entity_types - _META_TYPES)
        if entity_types is not None and entity_types & _META_TYPES:
            classes.add(entity_uri)
        elif entity_types is not None and not (entity_types - _META_TYPES) and (
            uri_has_instances(entity_uri, endpoint, query_source, query_index) is True
        ):
            classes.add(entity_uri)
        elif not entity_types and entity_uri in ontology_classes:
            classes.add(entity_uri)
    parsed_metrics["classes"] = classes
    parsed_metrics["entities"] = [
        entity_uri for entity_uri in raw_entities if entity_uri not in classes
    ]
    return parsed_metrics


def get_query_body(sparql):
    """Isolate the query body without PREFIX definitions."""
    return re.sub(
        r"^\s*(?:PREFIX\s+(?:[a-zA-Z][a-zA-Z0-9_-]*)?:\s*<[^>]+>\s*)+",
        "",
        sparql,
        flags=re.IGNORECASE,
    ).strip()


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


def normalize_sparql(sparql, query_source=None):
    """Repair known benchmark formatting defects before rdflib parses a query."""
    sparql = _normalize_uri_escapes(sparql)

    # RDF literal suffixes are single lexical tokens in SPARQL, so whitespace
    # between the quoted value and @lang/^^datatype is invalid.
    sparql = re.sub(
        r'''(?<!\\)(["'])\s+(@[A-Za-z]+(?:-[A-Za-z0-9]+)*\b)''',
        r"\1\2",
        sparql,
    )
    sparql = re.sub(r'''(?<!\\)(["'])\s*\^\^\s*''', r"\1^^", sparql)

    if query_source and re.search(r"qald[-_]?9", os.path.basename(str(query_source)), re.I):
        declared = set(
            re.findall(r"(?i)\bPREFIX\s+([A-Za-z][\w-]*):", sparql)
        )
        used = set(
            re.findall(r"(?<![<\w])([A-Za-z][\w-]*):[A-Za-z_]", sparql)
        )
        additions = [
            f"PREFIX {prefix}: <{namespace}>"
            for prefix, namespace in _QALD9_PREFIXES.items()
            if prefix in used - declared
        ]
        if additions:
            sparql = " ".join(additions + [sparql])
    return sparql


def parse_and_extract_rdflib_metrics(
    sparql, endpoint="dblp", query_source=None, query_index=None
):
    """Uses rdflib to parse entities, properties, variables, and triple count."""
    import warnings

    sparql = normalize_sparql(sparql, query_source)

    metrics = {
        "num_triples": 0,
        "variables": set(),
        "entities": [],
        # literal values are kept apart so entity metrics stay URI-only
        "literals": [],
        "classes": set(),
        "properties": set(),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = parseQuery(sparql)
            algebra = translateQuery(parsed).algebra
    except Exception as exc:
        logger.warning(
            "[metrics.parsing] --- SPARQL parse failed ---\n"
            "source=%s query_index=%s\n"
            "fallback=empty parsed metrics\n"
            "reason=%s query=%s",
            query_source or "<unspecified>",
            query_index if query_index is not None else "<unspecified>",
            exc,
            sparql[:500],
        )
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
                            elif isinstance(term, URIRef):
                                metrics["entities"].append(str(term))
                            elif isinstance(term, Literal):
                                metrics["literals"].append(str(term))
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

    return metrics


def anonymise_query(sparql):
    """Anonymise a SPARQL query to a structural template.

    Both full URIs (``<http://…>``) and prefixed names (``dbo:Thing``)
    are replaced with the same ``<URI>`` token so that queries differing
    only in prefix style produce identical templates.
    """
    return _anonymise_fragment(get_query_body(sparql))


def _anonymise_fragment(text, collapse_whitespace=False):
    text = re.sub(r"\?[a-zA-Z0-9_]+", "?VAR", text)
    text = re.sub(r"<[^>]+>", "<URI>", text)
    text = _LITERAL_PATTERN.sub("<LITERAL>", text)
    text = re.sub(r"\b[a-zA-Z0-9_]+:[a-zA-Z0-9_]+\b", "<URI>", text)
    if collapse_whitespace:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _anonymise_text(text):
    """Anonymise a fragment of SPARQL (same rules as anonymise_query)."""
    return _anonymise_fragment(text, collapse_whitespace=True)


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
