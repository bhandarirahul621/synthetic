"""Pools of realistic words, names and places, drawn from Faker.

Calling Faker once per row is slow (about 20-50 microseconds a call, so
minutes for millions of rows). Instead we ask Faker for a few hundred values
once, then pick from that pool with numpy, which is fast and vectorised.

Faker is seeded from our numpy generator, so pools are reproducible (FR10).
Note that Faker's word lists can change between Faker releases; the Faker
version is part of what ``ENGINE_VERSION`` pins.
"""

from __future__ import annotations

import numpy as np
from faker import Faker

POOL_SIZE = 400


def _faker(rng: np.random.Generator) -> Faker:
    fake = Faker("en_US")
    fake.seed_instance(int(rng.integers(0, 2**31 - 1)))
    return fake


def _unique(values: list[str]) -> np.ndarray:
    return np.array(list(dict.fromkeys(values)), dtype=object)


def make_pool(kind: str, rng: np.random.Generator, size: int = POOL_SIZE) -> np.ndarray:
    """Return an array of distinct example values of the given ``kind``."""
    fake = _faker(rng)
    makers = {
        "first": fake.first_name,
        "last": fake.last_name,
        "street_name": fake.street_name,
        "city": fake.city,
        "state": fake.state_abbr,
        "country": fake.country,
        "company": fake.company,
        "word": fake.word,
        "username": fake.user_name,
        "adjective": lambda: fake.word(ext_word_list=_ADJECTIVES),
        "noun": lambda: fake.word(ext_word_list=_NOUNS),
    }
    if kind not in makers:
        raise KeyError(kind)
    target = min(size, _MAX_DISTINCT.get(kind, size))
    maker = makers[kind]
    values = _unique([maker() for _ in range(target * 3)])
    return values[:target]


# A few lists of our own so product names look like products.
_ADJECTIVES = [
    "Classic", "Compact", "Deluxe", "Eco", "Essential", "Everyday", "Premium", "Pro", "Smart",
    "Ultra", "Vintage", "Wireless", "Organic", "Portable", "Rugged", "Slim", "Modern", "Mini",
    "Max", "Lite", "Heavy-Duty", "Ergonomic", "Waterproof", "Handmade", "Insulated",
]
_NOUNS = [
    "Backpack", "Blender", "Bottle", "Chair", "Desk Lamp", "Headphones", "Jacket", "Kettle",
    "Keyboard", "Mug", "Notebook", "Pillow", "Running Shoes", "Speaker", "Sunglasses", "Tent",
    "Toaster", "Towel", "Wallet", "Watch", "Yoga Mat", "Camera", "Charger", "Monitor", "Scarf",
    "Skillet", "Thermos", "Umbrella", "Vacuum", "Webcam",
]
_MAX_DISTINCT = {"state": 50, "adjective": len(_ADJECTIVES), "noun": len(_NOUNS)}

#: Reserved example domains (RFC 2606) so generated emails can never reach a real inbox.
EMAIL_DOMAINS = np.array(["example.com", "example.org", "example.net"], dtype=object)
