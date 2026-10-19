"""Fast, data-driven product and warehouse resolution for natural queries."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz

from vendor_ai_assistant.database_pipeline.sqlite_connection import DEFAULT_DB_PATH
from vendor_ai_assistant.tools.database import fetch_all, read_only_connection


_WORDS = re.compile(r"[a-z0-9]+")
_PRODUCT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "available",
        "buy",
        "cost",
        "for",
        "in",
        "near",
        "of",
        "price",
        "the",
        "unit",
        "units",
        "want",
        "what",
    }
)
ResolutionStatus = Literal["resolved", "ambiguous", "not_found"]


def normalize_search_text(value: str) -> str:
    """Normalize casing, punctuation, and common unit spellings."""

    normalized = " ".join(_WORDS.findall(value.casefold()))
    replacements = {
        "litres": "l",
        "litre": "l",
        "liters": "l",
        "liter": "l",
        "kilograms": "kg",
        "kilogram": "kg",
        "kilos": "kg",
        "kilo": "kg",
        "grams": "g",
        "gram": "g",
        "millilitres": "ml",
        "millilitre": "ml",
        "milliliters": "ml",
        "milliliter": "ml",
    }
    return " ".join(replacements.get(word, word) for word in normalized.split())


def _meaningful_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            word
            for word in normalize_search_text(value).split()
            if word not in _PRODUCT_STOP_WORDS and len(word) > 1
        )
    )


@dataclass(frozen=True)
class ProductCandidate:
    sku: str
    product_name: str
    brand: str
    category: str
    pack_size: int
    unit_type: str
    score: float

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


@dataclass(frozen=True)
class ProductResolution:
    status: ResolutionStatus
    query: str
    candidates: tuple[ProductCandidate, ...] = ()

    @property
    def match(self) -> ProductCandidate | None:
        return self.candidates[0] if self.status == "resolved" else None


@dataclass(frozen=True)
class LocationCandidate:
    warehouse_id: str
    warehouse_city: str
    region: str
    score: float

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(frozen=True)
class LocationResolution:
    status: ResolutionStatus
    query: str
    candidates: tuple[LocationCandidate, ...] = ()

    @property
    def match(self) -> LocationCandidate | None:
        return self.candidates[0] if self.status == "resolved" else None


def _product_rows(connection: object, query: str) -> list[dict]:
    normalized = normalize_search_text(query)
    exact = fetch_all(
        connection,  # type: ignore[arg-type]
        "SELECT product_id, product_name, brand, category, pack_size, unit_type "
        "FROM dim_products WHERE product_id = ? COLLATE NOCASE "
        "OR product_name = ? COLLATE NOCASE LIMIT 2",
        (query.strip(), query.strip()),
    )
    if exact:
        return exact

    has_fts = fetch_all(
        connection,  # type: ignore[arg-type]
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='product_search_fts' LIMIT 1",
    )
    tokens = _meaningful_tokens(normalized)
    if has_fts and tokens:
        fts_query = " AND ".join(f'"{token}"' for token in tokens)
        rows = fetch_all(
            connection,  # type: ignore[arg-type]
            "SELECT p.product_id, p.product_name, p.brand, p.category, "
            "p.pack_size, p.unit_type FROM product_search_fts f "
            "JOIN dim_products p ON p.product_id = f.product_id "
            "WHERE product_search_fts MATCH ? ORDER BY bm25(product_search_fts) "
            "LIMIT 30",
            (fts_query,),
        )
        if rows:
            return rows

    # This fallback keeps older serving databases usable until their next rebuild.
    # It is inexpensive for the current 400-row catalogue; rebuilt databases use FTS5.
    return fetch_all(
        connection,  # type: ignore[arg-type]
        "SELECT product_id, product_name, brand, category, pack_size, unit_type "
        "FROM dim_products ORDER BY product_id",
    )


def resolve_product_query(
    query: str,
    *,
    database_path: Path = DEFAULT_DB_PATH,
    limit: int = 5,
) -> ProductResolution:
    """Return a confident product match or a small ranked candidate set."""

    normalized_query = normalize_search_text(query)
    if not normalized_query:
        return ProductResolution(status="not_found", query=query)
    query_tokens = set(_meaningful_tokens(normalized_query))

    with read_only_connection(database_path) as connection:
        rows = _product_rows(connection, query)

    ranked: list[ProductCandidate] = []
    for row in rows:
        product_id = normalize_search_text(str(row["product_id"]))
        name = normalize_search_text(str(row["product_name"]))
        searchable = normalize_search_text(
            f"{row['product_name']} {row['brand']} {row['category']} "
            f"{row['pack_size']} {row['unit_type']}"
        )
        # Candidate discovery may use category text, but confidence should favor
        # tokens present in the actual product name or brand.
        product_tokens = set(name.split()) | set(
            normalize_search_text(str(row["brand"])).split()
        )
        matched_tokens = sum(
            1
            for token in query_tokens
            if max(
                (fuzz.ratio(token, product_token) for product_token in product_tokens),
                default=0.0,
            )
            >= 75
        )
        coverage = matched_tokens / len(query_tokens) if query_tokens else 0.0
        brand = normalize_search_text(str(row["brand"]))
        brand_similarity = max(
            (fuzz.ratio(token, brand) for token in query_tokens),
            default=0.0,
        )
        brand_score = brand_similarity if brand_similarity >= 75 else 0.0
        score = (
            100.0
            if normalized_query in {product_id, name}
            else round(
                min(
                    100.0,
                    0.40 * fuzz.token_set_ratio(normalized_query, searchable)
                    + 0.25 * fuzz.WRatio(normalized_query, name)
                    + 20.0 * coverage
                    + 0.15 * brand_score,
                ),
                2,
            )
        )
        if score >= 35:
            ranked.append(
                ProductCandidate(
                    sku=str(row["product_id"]),
                    product_name=str(row["product_name"]),
                    brand=str(row["brand"]),
                    category=str(row["category"]),
                    pack_size=int(row["pack_size"]),
                    unit_type=str(row["unit_type"]),
                    score=score,
                )
            )

    ranked.sort(key=lambda item: (-item.score, item.product_name, item.sku))
    candidates = tuple(ranked[:limit])
    if not candidates:
        return ProductResolution(status="not_found", query=query)

    top = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else 0.0
    exact = normalized_query in {
        normalize_search_text(top.sku),
        normalize_search_text(top.product_name),
    }
    confidently_ahead = top.score >= 72 and top.score - second_score >= 6
    status: ResolutionStatus = "resolved" if exact or confidently_ahead else "ambiguous"
    if status == "ambiguous":
        candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.score >= top.score - 6
        )
    return ProductResolution(status=status, query=query, candidates=candidates)


def resolve_location_query(
    query: str,
    *,
    database_path: Path = DEFAULT_DB_PATH,
    limit: int = 3,
) -> LocationResolution:
    """Resolve a user location against live warehouse IDs, cities, and regions."""

    normalized_query = normalize_search_text(query)
    for removable in ("warehouse", "location", "region", "near"):
        normalized_query = " ".join(
            word for word in normalized_query.split() if word != removable
        )
    if not normalized_query:
        return LocationResolution(status="not_found", query=query)

    with read_only_connection(database_path) as connection:
        rows = fetch_all(
            connection,
            "SELECT warehouse_id, warehouse_city, region FROM dim_warehouses "
            "ORDER BY warehouse_id",
        )

    candidates: list[LocationCandidate] = []
    for row in rows:
        values = (
            str(row["warehouse_id"]),
            str(row["warehouse_city"]),
            str(row["region"]),
        )
        score = max(
            fuzz.WRatio(normalized_query, normalize_search_text(value))
            for value in values
        )
        if score >= 50:
            candidates.append(
                LocationCandidate(
                    warehouse_id=values[0],
                    warehouse_city=values[1],
                    region=values[2],
                    score=round(float(score), 2),
                )
            )

    candidates.sort(key=lambda item: (-item.score, item.warehouse_id))
    selected = tuple(candidates[:limit])
    if not selected:
        return LocationResolution(status="not_found", query=query)
    second_score = selected[1].score if len(selected) > 1 else 0.0
    confidently_ahead = selected[0].score >= 55 and selected[0].score - second_score >= 4
    return LocationResolution(
        status="resolved" if confidently_ahead else "ambiguous",
        query=query,
        candidates=selected,
    )
