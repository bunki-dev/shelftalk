"""Generate the demo warehouse: two years of weekly sales for Bluegum Market, a fictional
Australian grocery chain. Deterministic (seeded), so every build produces identical data.

    python -m shelftalk.generate path/to/shelftalk.db

The patterns are realistic on purpose, so questions have interesting answers: summer drinks,
a Christmas spike, winter soups, promo uplift by mechanic, own-brand growth, stores that
opened mid-period, and a store refit that dipped sales for a month.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 20261125
FIRST_WEEK = date(2024, 11, 4)  # a Monday
NUM_WEEKS = 104

STORES = [
    # suburb, state, region, format, floor area, opened (None = before the data starts)
    ("Parramatta", "NSW", "Metro", "Supermarket", 3800, None),
    ("Chatswood", "NSW", "Metro", "Supermarket", 3500, None),
    ("Bondi Junction", "NSW", "Metro", "Metro", 1600, None),
    ("Newcastle", "NSW", "Regional", "Supermarket", 3200, None),
    ("Wollongong", "NSW", "Regional", "Supermarket", 3000, None),
    ("Dubbo", "NSW", "Regional", "Local", 1400, None),
    ("Penrith", "NSW", "Metro", "Supermarket", 3600, date(2025, 6, 2)),
    ("Hawthorn", "VIC", "Metro", "Metro", 1500, None),
    ("Box Hill", "VIC", "Metro", "Supermarket", 3700, None),
    ("Richmond", "VIC", "Metro", "Metro", 1300, None),
    ("Werribee", "VIC", "Metro", "Supermarket", 3400, None),
    ("Geelong", "VIC", "Regional", "Supermarket", 3300, None),
    ("Ballarat", "VIC", "Regional", "Local", 1500, None),
    ("Bendigo", "VIC", "Regional", "Local", 1450, None),
    ("Fortitude Valley", "QLD", "Metro", "Metro", 1400, None),
    ("Chermside", "QLD", "Metro", "Supermarket", 3600, None),
    ("Southport", "QLD", "Metro", "Supermarket", 3300, None),
    ("Townsville", "QLD", "Regional", "Supermarket", 3000, None),
    ("Toowoomba", "QLD", "Regional", "Local", 1400, date(2025, 3, 3)),
    ("Subiaco", "WA", "Metro", "Metro", 1350, None),
    ("Joondalup", "WA", "Metro", "Supermarket", 3500, None),
    ("Fremantle", "WA", "Metro", "Local", 1500, None),
    ("Glenelg", "SA", "Metro", "Metro", 1300, None),
    ("Modbury", "SA", "Metro", "Supermarket", 3200, None),
    ("Mount Gambier", "SA", "Regional", "Local", 1350, None),
    ("Hobart", "TAS", "Metro", "Supermarket", 3000, None),
    ("Launceston", "TAS", "Regional", "Local", 1400, None),
    ("Belconnen", "ACT", "Metro", "Supermarket", 3300, None),
]
REFIT_STORE, REFIT_START, REFIT_WEEKS = "Box Hill", date(2025, 8, 4), 4

# name, brand, category, subcategory, regular price, cost ratio, base weekly units per large store, season
PRODUCTS = [
    ("Bananas 1kg", "Fresh Fields", "Fruit & Veg", "Fruit", 3.90, 0.62, 520, "flat"),
    ("Hass Avocado each", "Fresh Fields", "Fruit & Veg", "Fruit", 2.50, 0.55, 380, "summer"),
    ("Strawberries 250g", "Fresh Fields", "Fruit & Veg", "Fruit", 4.50, 0.58, 300, "spring"),
    ("Mangoes each", "Fresh Fields", "Fruit & Veg", "Fruit", 3.00, 0.55, 260, "summer_peak"),
    ("Brown Onions 1kg", "Fresh Fields", "Fruit & Veg", "Vegetables", 3.50, 0.50, 240, "flat"),
    ("Baby Spinach 120g", "Fresh Fields", "Fruit & Veg", "Vegetables", 3.00, 0.52, 260, "flat"),
    ("Broccoli each", "Fresh Fields", "Fruit & Veg", "Vegetables", 2.80, 0.55, 230, "winter"),
    ("Sweet Potato 1kg", "Fresh Fields", "Fruit & Veg", "Vegetables", 4.00, 0.50, 180, "winter"),
    ("Chicken Breast Fillets 500g", "Paddock Co", "Meat & Seafood", "Poultry", 9.50, 0.70, 310, "flat"),
    ("Lean Beef Mince 500g", "Highland Grazing", "Meat & Seafood", "Beef", 10.00, 0.72, 280, "flat"),
    ("Lamb Leg Roast 2kg", "Highland Grazing", "Meat & Seafood", "Lamb", 32.00, 0.74, 70, "winter"),
    ("Beef Sausages 1kg", "Highland Grazing", "Meat & Seafood", "Beef", 11.00, 0.66, 190, "bbq"),
    ("Tasmanian Salmon 250g", "Southern Ocean", "Meat & Seafood", "Seafood", 12.00, 0.72, 150, "flat"),
    ("Tiger Prawns 500g", "Southern Ocean", "Meat & Seafood", "Seafood", 18.00, 0.70, 60, "christmas"),
    ("Bluegum Chicken Breast 1kg", "Bluegum", "Meat & Seafood", "Poultry", 13.00, 0.66, 160, "flat"),
    ("Full Cream Milk 2L", "Southern Cross Dairy", "Dairy & Eggs", "Milk", 3.60, 0.72, 600, "flat"),
    ("Bluegum Full Cream Milk 2L", "Bluegum", "Dairy & Eggs", "Milk", 3.10, 0.70, 480, "flat"),
    ("Greek Yoghurt 1kg", "Alpine Creamery", "Dairy & Eggs", "Yoghurt", 7.00, 0.62, 210, "flat"),
    ("Tasty Cheddar 500g", "Southern Cross Dairy", "Dairy & Eggs", "Cheese", 9.00, 0.64, 230, "flat"),
    ("Bluegum Tasty Cheese 500g", "Bluegum", "Dairy & Eggs", "Cheese", 7.50, 0.60, 170, "flat"),
    ("Free Range Eggs 12pk", "Sunny Hill Farm", "Dairy & Eggs", "Eggs", 7.20, 0.66, 330, "flat"),
    ("Salted Butter 250g", "Southern Cross Dairy", "Dairy & Eggs", "Butter", 5.20, 0.65, 190, "christmas"),
    ("Custard 1L", "Alpine Creamery", "Dairy & Eggs", "Desserts", 4.20, 0.58, 90, "christmas"),
    ("Wholemeal Sandwich Loaf", "Golden Crust", "Bakery", "Bread", 4.50, 0.48, 360, "flat"),
    ("Bluegum White Bread 700g", "Bluegum", "Bakery", "Bread", 2.50, 0.50, 420, "flat"),
    ("Sourdough Loaf", "Golden Crust", "Bakery", "Bread", 6.50, 0.45, 160, "flat"),
    ("Hot Cross Buns 6pk", "Golden Crust", "Bakery", "Seasonal", 5.50, 0.42, 20, "easter"),
    ("Fruit Mince Pies 6pk", "Golden Crust", "Bakery", "Seasonal", 5.00, 0.42, 10, "christmas_peak"),
    ("Wholemeal Wraps 8pk", "Golden Crust", "Bakery", "Wraps", 4.50, 0.48, 170, "flat"),
    ("Rolled Oats 750g", "Morning Mill", "Pantry", "Breakfast", 4.20, 0.50, 180, "winter"),
    ("Bluegum Rolled Oats 1kg", "Bluegum", "Pantry", "Breakfast", 2.80, 0.48, 160, "winter"),
    ("Wheat Biscuits 1.2kg", "Morning Mill", "Pantry", "Breakfast", 6.50, 0.55, 200, "flat"),
    ("Brown Rice 1kg", "Riverland Grains", "Pantry", "Rice & Pasta", 4.00, 0.50, 150, "flat"),
    ("Spaghetti 500g", "Nonna's Table", "Pantry", "Rice & Pasta", 2.20, 0.45, 260, "flat"),
    ("Bluegum Spaghetti 500g", "Bluegum", "Pantry", "Rice & Pasta", 1.20, 0.50, 230, "flat"),
    ("Diced Tomatoes 400g", "Nonna's Table", "Pantry", "Canned Food", 1.80, 0.48, 290, "winter"),
    ("Chicken Noodle Soup 500g", "Harvest Pantry", "Pantry", "Canned Food", 3.50, 0.50, 120, "winter_peak"),
    ("Tuna in Springwater 95g", "Harbour Kitchen", "Pantry", "Canned Food", 1.80, 0.52, 340, "flat"),
    ("Chickpeas 400g", "Harvest Pantry", "Pantry", "Canned Food", 1.60, 0.50, 150, "flat"),
    ("Extra Virgin Olive Oil 750ml", "Coastal Grove", "Pantry", "Oils", 14.00, 0.66, 110, "flat"),
    ("Peanut Butter 380g", "Nutty Bros", "Pantry", "Spreads", 5.50, 0.52, 160, "flat"),
    ("Yeast Spread 220g", "Harvest Pantry", "Pantry", "Spreads", 6.00, 0.45, 140, "flat"),
    ("Honey 500g", "Golden Hive", "Pantry", "Spreads", 7.50, 0.58, 90, "winter"),
    ("Instant Coffee 200g", "Daybreak Roasters", "Pantry", "Hot Drinks", 14.00, 0.55, 150, "winter"),
    ("Tea Bags 100pk", "Daybreak Roasters", "Pantry", "Hot Drinks", 5.00, 0.48, 120, "winter"),
    ("Chocolate Biscuits 200g", "Crunch Club", "Snacks & Confectionery", "Biscuits", 4.65, 0.45, 300, "flat"),
    ("Salt & Vinegar Chips 175g", "Crunch Club", "Snacks & Confectionery", "Chips", 4.50, 0.40, 330, "summer"),
    ("Corn Chips 300g", "Fiesta Pantry", "Snacks & Confectionery", "Chips", 4.00, 0.42, 200, "summer"),
    ("Milk Chocolate Block 180g", "Cocoa Lane", "Snacks & Confectionery", "Chocolate", 5.50, 0.44, 280, "christmas"),
    ("Chocolate Eggs 150g", "Cocoa Lane", "Snacks & Confectionery", "Chocolate", 6.00, 0.40, 15, "easter"),
    ("Bluegum Rice Crackers 100g", "Bluegum", "Snacks & Confectionery", "Crackers", 1.60, 0.46, 210, "flat"),
    ("Natural Almonds 400g", "Nutty Bros", "Snacks & Confectionery", "Nuts", 9.00, 0.62, 120, "christmas"),
    ("Cola 1.25L", "Fizz Co", "Drinks", "Soft Drinks", 3.40, 0.38, 420, "summer"),
    ("Cola 24 x 375ml", "Fizz Co", "Drinks", "Soft Drinks", 24.00, 0.45, 90, "summer_peak"),
    ("Sparkling Water 1.25L", "Fizz Co", "Drinks", "Water", 1.90, 0.36, 300, "summer"),
    ("Bluegum Spring Water 24pk", "Bluegum", "Drinks", "Water", 7.50, 0.42, 110, "summer_peak"),
    ("Orange Juice 2L", "Sunshine Squeeze", "Drinks", "Juice", 6.00, 0.55, 210, "flat"),
    ("Sports Drink 600ml", "Peak Fuel", "Drinks", "Sports Drinks", 3.50, 0.40, 200, "summer"),
    ("Iced Coffee 500ml", "Daybreak Roasters", "Drinks", "Dairy Drinks", 3.80, 0.50, 230, "summer"),
    ("Vanilla Ice Cream 2L", "Frosty Farm", "Frozen", "Ice Cream", 8.00, 0.48, 190, "summer_peak"),
    ("Ice Blocks 10pk", "Frosty Farm", "Frozen", "Ice Cream", 6.50, 0.42, 120, "summer_peak"),
    ("Frozen Peas 1kg", "Frosty Farm", "Frozen", "Vegetables", 3.50, 0.50, 200, "winter"),
    ("Frozen Mixed Berries 500g", "Frosty Farm", "Frozen", "Fruit", 6.00, 0.55, 150, "flat"),
    ("Beef Pies 4pk", "Pie Society", "Frozen", "Meals", 7.00, 0.48, 140, "winter_peak"),
    ("Bluegum Fish Fingers 1kg", "Bluegum", "Frozen", "Seafood", 8.50, 0.55, 110, "flat"),
    ("Pizza Margherita 400g", "Nonna's Table", "Frozen", "Meals", 6.50, 0.45, 170, "flat"),
    ("Dishwashing Liquid 1L", "Sparkle", "Household", "Cleaning", 4.50, 0.40, 160, "flat"),
    ("Bluegum Toilet Paper 24pk", "Bluegum", "Household", "Paper", 11.00, 0.55, 190, "flat"),
    ("Toilet Paper 18pk", "SoftTouch", "Household", "Paper", 13.50, 0.55, 170, "flat"),
    ("Laundry Liquid 2L", "Sparkle", "Household", "Laundry", 16.00, 0.50, 110, "flat"),
    ("Paper Towel 4pk", "SoftTouch", "Household", "Paper", 6.00, 0.52, 130, "flat"),
    ("Bin Liners 50pk", "Bluegum", "Household", "Cleaning", 4.00, 0.45, 120, "flat"),
    ("Sunscreen SPF50 200ml", "SunGuard", "Health & Beauty", "Sun Care", 15.00, 0.48, 70, "summer_peak"),
    ("Toothpaste 110g", "BrightSmile", "Health & Beauty", "Oral Care", 4.50, 0.40, 170, "flat"),
    ("Shampoo 400ml", "Silk & Co", "Health & Beauty", "Hair Care", 8.00, 0.42, 110, "flat"),
    ("Cold & Flu Tablets 24pk", "WellPlus", "Health & Beauty", "Medicine", 12.00, 0.45, 50, "winter_peak"),
    ("Bluegum Tissues 200pk", "Bluegum", "Health & Beauty", "Tissues", 2.50, 0.45, 130, "winter"),
]

PROMO_TYPES = [("Half price", 0.50, 2.4), ("Price drop", 0.80, 1.45), ("Multi-buy", 0.75, 1.7)]
FORMAT_SCALE = {"Supermarket": 1.0, "Metro": 0.55, "Local": 0.45}
STATE_SCALE = {"NSW": 1.05, "VIC": 1.0, "QLD": 0.97, "WA": 0.95, "SA": 0.9, "TAS": 0.85, "ACT": 0.92}
# How much shoppers lean towards the own brand, and how hard each category responds to promotions.
OWN_BRAND_AFFINITY = {"NSW": 0.95, "VIC": 1.05, "QLD": 1.15, "WA": 0.9, "SA": 1.2, "TAS": 1.3, "ACT": 0.85}
PROMO_SENSITIVITY = {
    "Drinks": 1.3,
    "Snacks & Confectionery": 1.25,
    "Household": 1.15,
    "Frozen": 1.1,
    "Health & Beauty": 1.05,
    "Pantry": 1.0,
    "Meat & Seafood": 0.95,
    "Dairy & Eggs": 0.85,
    "Bakery": 0.8,
    "Fruit & Veg": 0.7,
}
FIRST_NAMES = [
    "Olivia",
    "Jack",
    "Charlotte",
    "Noah",
    "Amelia",
    "William",
    "Isla",
    "Oliver",
    "Mia",
    "Leo",
    "Ava",
    "Henry",
    "Grace",
    "Lucas",
    "Chloe",
    "Thomas",
    "Zara",
    "Ethan",
    "Ruby",
    "Arjun",
    "Priya",
    "Wei",
    "Mei",
    "Hamish",
    "Sienna",
    "Kai",
    "Anika",
    "Lachlan",
    "Harper",
    "Tom",
]


def _season_factor(kind: str, week: date) -> float:
    doy = week.timetuple().tm_yday
    summer = np.cos((doy - 15) / 365 * 2 * np.pi)  # +1 mid-Jan (southern summer), -1 mid-July
    christmas = 1.0 if (week.month == 12 and week.day >= 8) else 0.0
    easter = 1.0 if (week.month == 3 and week.day >= 10) or (week.month == 4 and week.day <= 20) else 0.0
    table = {
        "flat": 1.0,
        "summer": 1 + 0.25 * summer,
        "summer_peak": 1 + 0.55 * summer,
        "winter": 1 - 0.22 * summer,
        "winter_peak": 1 - 0.5 * summer,
        "spring": 1 + 0.3 * np.sin((doy - 250) / 365 * 2 * np.pi),
        "bbq": 1 + 0.3 * summer + 0.4 * christmas,
        "christmas": 1 + 0.9 * christmas,
        "christmas_peak": 0.2 + 14 * christmas,
        "easter": 0.3 + 12 * easter,
    }
    return max(0.05, float(table[kind]))


def build(path: Path) -> None:
    rng = np.random.default_rng(SEED)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)

    weeks = [FIRST_WEEK + timedelta(weeks=i) for i in range(NUM_WEEKS)]
    db.executemany(
        "INSERT INTO weeks VALUES (?,?,?,?,?,?)",
        [
            (
                w.isoformat(),
                int(w.isocalendar().week),
                w.strftime("%Y-%m"),
                f"{w.year}-Q{(w.month - 1) // 3 + 1}",
                w.year,
                _season(w),
            )
            for w in weeks
        ],
    )
    db.executemany(
        "INSERT INTO stores VALUES (?,?,?,?,?,?,?,?)",
        [
            (i + 1, f"Bluegum {s[0]}", s[0], s[1], s[2], s[3], (s[5] or date(2019, 1, 1)).isoformat(), s[4])
            for i, s in enumerate(STORES)
        ],
    )
    db.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
        [
            (i + 1, p[0], p[1], p[2], p[3], int(p[1] == "Bluegum"), round(p[4] * p[5], 2), p[4])
            for i, p in enumerate(PRODUCTS)
        ],
    )

    # Promotions: national, 1-2 week runs, about 8 promo weeks per product per year.
    promos: dict[tuple[int, int], tuple[str, float, float]] = {}
    for pid, p in enumerate(PRODUCTS, start=1):
        w = int(rng.integers(0, 6))
        while w < NUM_WEEKS:
            name, ratio, uplift = PROMO_TYPES[int(rng.integers(0, len(PROMO_TYPES)))]
            for k in range(int(rng.integers(1, 3))):
                if w + k < NUM_WEEKS:
                    promos[(pid, w + k)] = (name, round(p[4] * ratio, 2), uplift)
            w += int(rng.integers(5, 9))
    db.executemany(
        "INSERT INTO promotions VALUES (?,?,?,?,?)",
        [(i + 1, pid, weeks[w].isoformat(), v[0], v[1]) for i, ((pid, w), v) in enumerate(sorted(promos.items()))],
    )

    # Sales: base x store size x season x trend x promo x noise.
    rows = []
    for sid, s in enumerate(STORES, start=1):
        store_scale = FORMAT_SCALE[s[3]] * STATE_SCALE[s[1]] * (0.85 if s[2] == "Regional" else 1.0)
        store_scale *= float(rng.normal(1.0, 0.08))
        for pid, p in enumerate(PRODUCTS, start=1):
            own_brand = p[1] == "Bluegum"
            for wi, w in enumerate(weeks):
                if s[5] and w < s[5]:
                    continue
                ramp = min(1.0, 0.55 + 0.05 * ((w - s[5]).days // 7)) if s[5] else 1.0
                refit = (
                    0.6
                    if (s[0] == REFIT_STORE and REFIT_START <= w < REFIT_START + timedelta(weeks=REFIT_WEEKS))
                    else 1.0
                )
                trend = 1 + (0.18 if own_brand else 0.04) * wi / NUM_WEEKS  # own brand grows faster
                promo = promos.get((pid, wi))
                lift = 1 + (promo[2] - 1) * PROMO_SENSITIVITY[p[2]] if promo else 1.0
                affinity = OWN_BRAND_AFFINITY[s[1]] * (1.12 if s[2] == "Regional" else 1.0) if own_brand else 1.0
                mean = p[6] * store_scale * _season_factor(p[7], w) * trend * ramp * refit * lift * affinity
                units = int(rng.poisson(max(mean, 0.1) * float(rng.lognormal(0, 0.12))))
                price = promo[1] if promo else p[4]
                cost = round(p[4] * p[5], 2)
                rows.append(
                    (
                        w.isoformat(),
                        sid,
                        pid,
                        units,
                        round(units * price, 2),
                        round(units * cost, 2),
                        int(promo is not None),
                    )
                )
    db.executemany("INSERT INTO sales VALUES (?,?,?,?,?,?,?)", rows)

    # Loyalty members, with personal details the agent must never read.
    members = []
    tiers = np.array(["Bronze", "Silver", "Gold"])
    for mid in range(1, 4001):
        name = FIRST_NAMES[int(rng.integers(0, len(FIRST_NAMES)))]
        home = int(rng.integers(1, len(STORES) + 1))
        tier = tiers[int(rng.choice(3, p=[0.62, 0.28, 0.10]))]
        spend = float(rng.gamma(2.2, {"Bronze": 900, "Silver": 1900, "Gold": 3600}[tier]))
        members.append(
            (
                mid,
                name,
                f"{name.lower()}.{mid}@example.com",
                f"04{rng.integers(10000000, 99999999)}",
                home,
                str(tier),
                (date(2019, 1, 1) + timedelta(days=int(rng.integers(0, 2100)))).isoformat(),
                round(spend, 2),
                int(spend / rng.uniform(45, 80)),
            )
        )
    db.executemany("INSERT INTO loyalty_members VALUES (?,?,?,?,?,?,?,?,?)", members)

    db.executescript(INDEXES)
    db.commit()
    db.execute("VACUUM")
    db.close()


def _season(w: date) -> str:
    return {
        12: "Summer",
        1: "Summer",
        2: "Summer",
        3: "Autumn",
        4: "Autumn",
        5: "Autumn",
        6: "Winter",
        7: "Winter",
        8: "Winter",
    }.get(w.month, "Spring")


SCHEMA = """
CREATE TABLE weeks (week_start TEXT PRIMARY KEY, week_of_year INTEGER, month TEXT, quarter TEXT,
                    year INTEGER, season TEXT);
CREATE TABLE stores (store_id INTEGER PRIMARY KEY, store_name TEXT, suburb TEXT, state TEXT, region TEXT,
                     format TEXT, opened_date TEXT, floor_area_sqm INTEGER);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_name TEXT, brand TEXT, category TEXT,
                       subcategory TEXT, is_own_brand INTEGER, unit_cost REAL, regular_price REAL);
CREATE TABLE promotions (promo_id INTEGER PRIMARY KEY, product_id INTEGER, week_start TEXT, promo_type TEXT,
                         promo_price REAL);
CREATE TABLE sales (week_start TEXT, store_id INTEGER, product_id INTEGER, units INTEGER, revenue REAL,
                    cost REAL, on_promo INTEGER);
CREATE TABLE loyalty_members (member_id INTEGER PRIMARY KEY, first_name TEXT, email TEXT, phone TEXT,
                              home_store_id INTEGER, tier TEXT, joined_date TEXT, spend_last_12m REAL,
                              visits_last_12m INTEGER);
"""
INDEXES = """
CREATE INDEX ix_sales_week ON sales(week_start);
CREATE INDEX ix_sales_store ON sales(store_id);
CREATE INDEX ix_sales_product ON sales(product_id);
CREATE INDEX ix_promotions_product ON promotions(product_id, week_start);
"""


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "shelftalk.db")
    build(out)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
