"""Guess what a column *means* from its name.

A column called ``email`` in a ``VARCHAR(255)`` is not just "some text": it
should look like an email address and it is personal data. This module holds
those rules of thumb in one place, so DDL import (FR2) and sample learning
(FR3) agree.

The rules are deliberately simple keyword matches; users can always correct
the result in the schema editor or via ``PATCH /v1/schemas/{id}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PERSON_TABLE_HINTS = (
    "customer",
    "user",
    "person",
    "people",
    "employee",
    "member",
    "patient",
    "contact",
    "client",
    "account_holder",
    "author",
    "student",
)


_DEFAULT_CATEGORIES = {
    "method": ["card", "bank_transfer", "wallet", "cash"],
    "segment": ["consumer", "small_business", "enterprise"],
    "tier": ["bronze", "silver", "gold"],
    "channel": ["web", "mobile", "store", "partner"],
}


@dataclass
class Semantic:
    """The inferred meaning of a column: a type, a subtype, PII and value hints."""

    type: str
    subtype: str | None = None
    pii: bool = False
    hints: dict[str, Any] = field(default_factory=dict)


def _tokens(name: str) -> list[str]:
    """Split ``customerEmailAddress`` / ``customer_email`` into lowercase words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [t for t in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if t]


def infer_semantic(column_name: str, table_name: str = "", sql_type: str | None = None) -> Semantic | None:
    """Infer a semantic type from a column name (and optionally its table and SQL type).

    Returns ``None`` when the name gives no useful hint.
    """
    tokens = _tokens(column_name)
    name = "_".join(tokens)
    if not tokens:
        return None
    last = tokens[-1]
    table = table_name.lower()
    is_text_sql = sql_type in (None, "string", "text")

    # --- identifiers that are personal data ------------------------------
    if "email" in tokens or "mail" == last:
        return Semantic("email", pii=True)
    if any(t in tokens for t in ("phone", "mobile", "tel", "telephone", "fax")):
        return Semantic("phone", pii=True)
    if name in ("ssn", "social_security_number", "national_id", "tax_id", "passport_number",
                "passport", "drivers_license", "nin"):
        return Semantic("string", subtype="ssn", pii=True)
    if name in ("ip", "ip_address", "ipv4", "client_ip"):
        return Semantic("string", subtype="ipv4", pii=True)
    if name in ("iban", "card_number", "credit_card", "credit_card_number", "account_number"):
        return Semantic("string", subtype="account_number", pii=True)

    # --- names -------------------------------------------------------------
    if name in ("first_name", "firstname", "given_name", "fname"):
        return Semantic("name", subtype="first", pii=True)
    if name in ("last_name", "lastname", "surname", "family_name", "lname"):
        return Semantic("name", subtype="last", pii=True)
    if name in ("full_name", "fullname", "customer_name", "contact_name", "user_name",
                "employee_name", "patient_name", "holder_name", "account_holder_name"):
        return Semantic("name", subtype="full", pii=True)
    if name == "name" and is_text_sql:
        if any(h in table for h in PERSON_TABLE_HINTS):
            return Semantic("name", subtype="full", pii=True)
        if "compan" in table or "merchant" in table or "vendor" in table or "supplier" in table:
            return Semantic("string", subtype="company")
        return Semantic("string", subtype="product")
    if name in ("company", "company_name", "merchant", "merchant_name", "employer", "vendor_name"):
        return Semantic("string", subtype="company")
    if name in ("product_name", "title", "item_name"):
        return Semantic("string", subtype="product")
    if name in ("username", "login", "handle"):
        return Semantic("string", subtype="username", pii=True)

    # --- addresses -----------------------------------------------------------
    if name in ("address", "street", "street_address", "address_line1", "address_line_1",
                "address1", "address_line2", "address2", "home_address", "billing_address",
                "shipping_address"):
        return Semantic("address", subtype="street", pii=True)
    if last == "city" or name == "town":
        return Semantic("address", subtype="city")
    if name in ("state", "province", "region", "state_code", "state_province"):
        return Semantic("address", subtype="state")
    if name in ("zip", "zipcode", "zip_code", "postcode", "postal_code", "postalcode"):
        return Semantic("address", subtype="zip", pii=True)
    if name in ("country", "country_code", "country_name"):
        return Semantic("address", subtype="country")
    if name in ("latitude", "lat"):
        return Semantic("float", hints={"min": -90.0, "max": 90.0, "decimals": 6})
    if name in ("longitude", "lng", "lon", "long"):
        return Semantic("float", hints={"min": -180.0, "max": 180.0, "decimals": 6})

    # --- dates -------------------------------------------------------------
    if name in ("dob", "date_of_birth", "birth_date", "birthdate", "birthday"):
        return Semantic("date", pii=True, hints={"min": "1940-01-01", "max": "2007-12-31"})
    if last == "at" or last in ("timestamp", "ts", "datetime", "time"):
        return Semantic("datetime")
    if last == "date" or last == "on" or name in ("date",):
        return Semantic("date")

    # --- flags, money, counts ---------------------------------------------
    if tokens[0] in ("is", "has", "can", "was", "should") or last in ("flag", "enabled", "active"):
        return Semantic("bool")
    if last in ("amount", "price", "total", "cost", "subtotal", "balance", "revenue", "fee",
                "salary", "income", "spend", "value") and sql_type in (None, "float", "int"):
        return Semantic("float", hints={"min": 0.0, "distribution": "lognormal", "decimals": 2})
    if last in ("quantity", "qty", "units") and sql_type in (None, "int", "float"):
        return Semantic("int", hints={"min": 1, "max": 10})
    if last == "age" and sql_type in (None, "int", "float"):
        return Semantic("int", hints={"min": 18, "max": 90})
    if last in ("rating", "stars", "score") and sql_type in (None, "int"):
        return Semantic("int", hints={"min": 1, "max": 5})
    if last in ("percent", "pct", "rate", "ratio") and sql_type in (None, "float"):
        return Semantic("float", hints={"min": 0.0, "max": 1.0, "decimals": 4})

    # --- free text and categories ----------------------------------------
    if last in ("description", "notes", "note", "comment", "comments", "bio", "review",
                "message", "summary", "body", "feedback", "reason"):
        return Semantic("text")
    if last in ("url", "website", "link", "homepage"):
        return Semantic("string", subtype="url")
    if last == "currency" or name == "currency_code":
        return Semantic("category", hints={"allowed_values": ["USD", "EUR", "GBP", "CAD", "JPY"],
                                           "weights": [0.6, 0.2, 0.1, 0.06, 0.04]})
    if last in ("status", "state") and is_text_sql:
        return Semantic("category", hints={"allowed_values": ["pending", "active", "completed",
                                                              "cancelled"]})
    if last in ("method", "segment", "tier", "channel") and is_text_sql:
        return Semantic("category", hints={"allowed_values": _DEFAULT_CATEGORIES[last]})
    if last in ("type", "category", "kind") and is_text_sql:
        return Semantic("category")
    if name in ("gender", "sex"):
        return Semantic("category", pii=True,
                        hints={"allowed_values": ["female", "male", "non-binary"],
                               "weights": [0.49, 0.49, 0.02]})
    return None


#: Column names that are personal data even if their values look harmless.
def is_pii_name(column_name: str, table_name: str = "") -> bool:
    """True when the column name alone suggests personal data."""
    sem = infer_semantic(column_name, table_name)
    return bool(sem and sem.pii)
