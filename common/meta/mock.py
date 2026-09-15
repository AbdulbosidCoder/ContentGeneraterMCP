"""Deterministic stand-in for GraphClient, used when no Meta app is configured.

Output is generated from RNGs seeded by the user / username / hashtag, so the
same inputs always return the same data. Captions mix content styles
(interactive, party, critical, educational, ...) and engagement follows hidden
per-style, per-format and per-hashtag weights, so classification and "what
works" analysis have real patterns to find.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from common.config import MOCK_PREFIX
from common.text import extract_hashtags

_NOW = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)

NICHES: dict[str, dict[str, Any]] = {
    "coffee": {
        "brand": "Roasters",
        "subjects": ["our Ethiopian single origin", "the cold brew kit", "a 60-second pour-over", "latte art",
                     "the autumn seasonal blend", "our roastery floor"],
        "hashtags": {"coffeelover": 1.1, "specialtycoffee": 1.6, "pourover": 1.4, "coldbrew": 1.3,
                     "latteart": 1.8, "coffeetime": 0.8, "baristalife": 1.2, "smallbatch": 1.0},
    },
    "fitness": {
        "brand": "Strength Co",
        "subjects": ["a 20-minute dumbbell circuit", "deadlift form", "mobility for desk workers",
                     "a high-protein breakfast", "progressive overload", "rest days"],
        "hashtags": {"fitness": 0.8, "homeworkout": 1.5, "strengthtraining": 1.3, "mobility": 1.4,
                     "fitnesstips": 1.7, "gymmotivation": 0.9, "mealprep": 1.2, "transformation": 1.9},
    },
    "skincare": {
        "brand": "Skin Lab",
        "subjects": ["our vitamin C serum", "a 3-step night routine", "SPF", "barrier repair",
                     "the new gel cleanser", "ingredient layering"],
        "hashtags": {"skincare": 0.9, "skincareroutine": 1.5, "glowingskin": 1.2, "spf": 1.3,
                     "cleanbeauty": 1.1, "skintok": 1.0, "beforeandafter": 1.9, "selfcare": 0.8},
    },
    "travel": {
        "brand": "Wander Collective",
        "subjects": ["a weekend in Lisbon", "packing light", "hidden beaches in Crete", "budget travel in Japan",
                     "sunrise hikes", "local food markets"],
        "hashtags": {"travel": 0.7, "travelgram": 0.9, "hiddengems": 1.6, "traveltips": 1.7,
                     "slowtravel": 1.3, "wanderlust": 1.0, "budgettravel": 1.5, "itinerary": 1.4},
    },
    "fashion": {
        "brand": "Atelier",
        "subjects": ["one blazer styled 5 ways", "the linen collection", "a capsule wardrobe", "thrift flips",
                     "our fabric sourcing", "fall layering"],
        "hashtags": {"ootd": 1.0, "capsulewardrobe": 1.6, "sustainablefashion": 1.4, "styleinspo": 1.2,
                     "grwm": 1.7, "slowfashion": 1.1, "outfitideas": 1.5, "fashion": 0.7},
    },
}

# Caption templates per content style; the weight shapes engagement.
STYLES: dict[str, tuple[float, list[str]]] = {
    "interactive": (1.5, [
        "Which do you prefer: {subject} or something new? Tell us in the comments!",
        "GIVEAWAY: tag two friends and follow us to win {subject}.",
        "Quick poll: would you try {subject}? Vote below.",
    ]),
    "party_event": (1.3, [
        "Launch party this Friday night! Join us for {subject}, music and good people.",
        "Pop-up event this weekend: come celebrate {subject} with us.",
        "Thank you for coming to last night's party. Here are the best moments with {subject}.",
    ]),
    "critical_opinion": (1.2, [
        "Unpopular opinion: most advice about {subject} is wrong. Here's why.",
        "We stopped doing {subject} the 'industry way'. Honest thoughts on what's broken.",
        "Let's be real about {subject}: overpriced, overhyped, or worth it?",
    ]),
    "educational": (1.35, [
        "3 steps to master {subject}. Save this for later.",
        "Beginner's guide to {subject}: what we wish we knew.",
        "Myth vs. fact: {subject} explained in 60 seconds.",
    ]),
    "promotional": (0.7, [
        "20% off {subject} this week only. Link in bio.",
        "Now available: {subject}. Shop today before it sells out.",
    ]),
    "behind_the_scenes": (1.1, [
        "Behind the scenes: how we make {subject}.",
        "A day in our studio working on {subject}.",
    ]),
    "testimonial": (1.0, [
        "\"Best decision I made this year\": our customer Maya on {subject}.",
        "Real results from our community after trying {subject}.",
    ]),
    "inspirational": (0.9, [
        "Small steps every day. {subject} reminded us why we started.",
        "Slow mornings and {subject}. Take a breath today.",
    ]),
}
FORMATS = {"IMAGE": 0.8, "CAROUSEL_ALBUM": 1.25, "REELS": 1.6}
GENERIC_TAGS = {"smallbusiness": 1.0, "community": 0.9, "behindthescenes": 1.2, "tips": 1.1}


def _seed(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16))


def _niche(key: str) -> tuple[str, dict[str, Any]]:
    lowered = key.lower()
    for name, niche in NICHES.items():
        if name in lowered or lowered in niche["hashtags"]:
            return name, niche
    names = sorted(NICHES)
    name = names[int(hashlib.sha256(lowered.encode()).hexdigest(), 16) % len(names)]
    return name, NICHES[name]


def _mock_id(rng: random.Random) -> str:
    return str(rng.randint(10**16, 10**17 - 1))


def generate_posts(
    key: str, count: int, platform: str = "instagram", author: str | None = None, force_tag: str | None = None
) -> list[dict[str, Any]]:
    rng = _seed("posts", platform, key, force_tag or "")
    _, niche = _niche(force_tag or key)
    followers = rng.randint(5_000, 120_000)
    weights = {**niche["hashtags"], **GENERIC_TAGS}
    posts = []
    for index in range(count):
        style = rng.choice(list(STYLES))
        style_weight, templates = STYLES[style]
        media_type = rng.choices(list(FORMATS), weights=[4, 3, 3])[0] if platform == "instagram" else \
            rng.choice(["IMAGE", "VIDEO", "TEXT"])
        tags = rng.sample(list(niche["hashtags"]), k=rng.randint(2, 4))
        if force_tag and force_tag not in tags:
            tags.insert(0, force_tag)
        if rng.random() < 0.3:
            tags.append(rng.choice(list(GENERIC_TAGS)))
        # ~15% of posts use no hashtags, so hashtag suggestions have something to fill in.
        if rng.random() < 0.15 and not force_tag:
            tags = []
        text = rng.choice(templates).format(subject=rng.choice(niche["subjects"]))
        caption = f"{MOCK_PREFIX} {text}" + ("\n\n" + " ".join(f"#{t}" for t in tags) if tags else "")

        boost = style_weight * FORMATS.get(media_type, 1.0)
        for tag in tags:
            boost *= weights.get(tag, 1.0) ** 0.5
        likes = int(followers * 0.02 * boost * rng.uniform(0.6, 1.4))
        comments = int(likes * rng.uniform(0.01, 0.05) * (3 if style == "interactive" else 1))
        reach = int(likes * rng.uniform(8, 15))
        post_id = _mock_id(rng)
        posts.append({
            "external_id": post_id,
            "platform": platform,
            "author": author,
            "caption": caption,
            "hashtags": extract_hashtags(caption),
            "media_type": media_type,
            "media_url": None,
            "permalink": f"https://www.instagram.com/p/MOCK{post_id[-10:]}/" if platform == "instagram"
            else f"https://www.facebook.com/{post_id}",
            "published_at": (_NOW - timedelta(days=index * 3 + rng.randint(0, 2))).isoformat(),
            "like_count": None if rng.random() < 0.08 else likes,
            "comments_count": comments,
            "shares_count": int(likes * rng.uniform(0.005, 0.03)),
            "insights": {"reach": reach, "saved": int(likes * rng.uniform(0.02, 0.1)),
                         "views": int(reach * rng.uniform(1.1, 2.5))} if author is None else {},
            "is_mock": True,
        })
    return posts


class MockGraphClient:
    is_mock = True

    def __init__(self, seed: str) -> None:
        self.seed = seed
        self.niche_key, _ = _niche(seed)

    def me(self) -> dict[str, Any]:
        rng = _seed("me", self.seed)
        return {"id": f"mock-{_mock_id(rng)}", "name": f"{MOCK_PREFIX} Demo Facebook User", "email": None,
                "picture_url": None}

    def list_pages(self) -> list[dict[str, Any]]:
        rng = _seed("pages", self.seed)
        brand = NICHES[self.niche_key]["brand"]
        handle = f"demo_{self.niche_key}_{rng.randint(10, 99)}"
        return [
            {
                "id": f"mockpage-{_mock_id(rng)}",
                "name": f"{MOCK_PREFIX} {self.niche_key.title()} {brand}",
                "access_token": f"mock-page-token-{self.seed}",
                "picture_url": None,
                "followers_count": rng.randint(2_000, 40_000),
                "instagram": {"id": f"mockig-{_mock_id(rng)}", "username": handle,
                              "name": f"{MOCK_PREFIX} {self.niche_key.title()} {brand}",
                              "followers_count": rng.randint(5_000, 120_000)},
            },
            {
                "id": f"mockpage-{_mock_id(rng)}",
                "name": f"{MOCK_PREFIX} {brand} Community",
                "access_token": f"mock-page-token-{self.seed}-2",
                "picture_url": None,
                "followers_count": rng.randint(500, 5_000),
                "instagram": None,
            },
        ]

    def ig_account(self, ig_user_id: str) -> dict[str, Any]:
        rng = _seed("igacct", ig_user_id)
        return {"id": ig_user_id, "username": f"demo_{self.niche_key}", "followers_count": rng.randint(5_000, 120_000),
                "media_count": rng.randint(100, 900)}

    def ig_media(self, ig_user_id: str, limit: int = 50, with_insights: bool = True) -> list[dict[str, Any]]:
        return generate_posts(f"{self.seed}:{ig_user_id}:{self.niche_key}", limit, "instagram")

    def ig_media_insights(self, media_id: str) -> dict[str, Any]:
        rng = _seed("insights", media_id)
        reach = rng.randint(1_000, 50_000)
        return {"reach": reach, "saved": rng.randint(10, 800), "shares": rng.randint(5, 400), "views": reach * 2}

    def business_discovery(self, ig_user_id: str, username: str, limit: int = 25) -> dict[str, Any]:
        rng = _seed("bd", username)
        name, niche = _niche(username)
        profile = {"id": _mock_id(rng), "username": username,
                   "name": f"{MOCK_PREFIX} {username.replace('_', ' ').title()} {niche['brand']}",
                   "followers_count": rng.randint(4_000, 250_000), "media_count": rng.randint(120, 1_800)}
        return {"profile": profile, "media": generate_posts(f"competitor:{username}", limit, "instagram", author=username)}

    def hashtag_id(self, ig_user_id: str, hashtag: str) -> str:
        return f"mockhashtag-{int(hashlib.sha256(hashtag.encode()).hexdigest()[:12], 16)}"

    def hashtag_media(
        self, ig_user_id: str, hashtag_id: str, hashtag: str, edge: str = "top_media", limit: int = 25
    ) -> list[dict[str, Any]]:
        return generate_posts(f"hashtag:{edge}", limit, "instagram", author=None, force_tag=hashtag)

    def ig_publishing_limit(self, ig_user_id: str) -> dict[str, Any]:
        return {"quota_usage": 0, "quota_total": 50}

    def ig_publish(self, ig_user_id: str, caption: str, media_type: str, media_url: str) -> dict[str, Any]:
        media_id = f"mockmedia-{int(hashlib.sha256((caption + media_url).encode()).hexdigest()[:12], 16)}"
        return {"id": media_id, "permalink": None}

    def page_posts(self, page_id: str, page_token: str, limit: int = 50) -> list[dict[str, Any]]:
        return generate_posts(f"{self.seed}:{page_id}:{self.niche_key}", limit, "facebook")

    def page_publish(
        self, page_id: str, page_token: str, message: str, image_url: str | None = None, link: str | None = None
    ) -> dict[str, Any]:
        post_id = f"{page_id}_mock{int(hashlib.sha256(message.encode()).hexdigest()[:10], 16)}"
        return {"id": post_id, "permalink": None}

    def ads_archive(self, search_terms: str, country: str, limit: int = 20) -> list[dict[str, Any]]:
        rng = _seed("ads", search_terms.lower(), country)
        pages = ["Northwind Goods", "Brightside Studio", "Evergreen Labs", "Lumen & Co"]
        angles = ["Limited-time offer on", "Why thousands switched to", "New arrival:", "Free shipping on"]
        return [{
            "id": _mock_id(rng),
            "page_name": f"{MOCK_PREFIX} {rng.choice(pages)}",
            "ad_creative_bodies": [f"{MOCK_PREFIX} {rng.choice(angles)} {search_terms} (variant {i + 1})."],
            "ad_delivery_start_time": (_NOW - timedelta(days=rng.randint(1, 120))).date().isoformat(),
            "publisher_platforms": ["facebook", "instagram"],
            "country": country,
            "is_mock": True,
        } for i in range(limit)]
