"""Pools of fictional names. All entities in the sandbox are fictional so that no answer can be
recalled from parametric memory."""
from __future__ import annotations

import random

SURNAMES = """Lindqvist Okafor Moreau Haldane Ibarra Szabo Nakamura Oduya Petrenko Valdés Castell Brennick
Aaltonen Mbeki Quiroga Sørlie Tanaka Vasquez Whitcombe Yildiz Zelenko Abernathy Ferreira Kowalczyk
Lindgren Mattheus Navarro Oyelaran Pellegrini Rasmussen Sandoval Thorvald Uchenna Varga Wenzel
Achterberg Bianchi Calloway Duarte Ekstrom Fairbairn Grünwald Hargreave Ilunga Jovanović Kaczmarek""".split()

FIRST = """Ana Bilal Chiara Dmitri Elif Farah Gustav Hana Ines Jonas Kaveh Lena Mateo Noor Oskar Priya
Quentin Rosa Sven Tamsin Uri Vera Wren Ximena Yusuf Zara""".split()

JOURNALS = ["Annals of Riverine Systems", "Journal of Applied Lattice Dynamics", "Transactions on Sparse Inference",
            "Coastal Sediment Letters", "Review of Synthetic Phonology", "Proceedings in Quiet Computing",
            "Journal of Alpine Hydrology", "Letters in Mesoscale Ecology", "Archives of Polymer Fatigue",
            "Journal of Cold-Region Materials", "Studies in Computational Pragmatics", "Glacial Acoustics Quarterly"]
VENUES = ["ICLRX", "NeurIPSX", "ICMLX", "ACLX", "KDDX", "WWWX"]  # fictional venue names
TOPICS = ["sediment transport", "lattice relaxation", "sparse recovery", "phoneme drift", "thermal fatigue",
          "glacial melt", "seed dispersal", "token memorization", "graph sparsification", "ice-shelf acoustics",
          "soil carbon flux", "wind-farm wakes", "retrieval calibration", "polymer creep", "tidal mixing"]
METHODS = ["A Stochastic Model of", "Bounds on", "Measuring", "Revisiting", "Scaling Laws for", "On the Stability of",
           "Long-Run Estimates of", "A Field Study of", "Learning", "Capacity Limits of"]

STATIONS = ["K-17", "B-04", "T-22", "M-09", "R-31", "S-12", "L-08", "N-26"]

NEWS_OUTLETS = ["The Meridian Ledger", "Northgate Observer", "Valley Courier", "The Harbor Dispatch",
                "Kestrel Daily", "Ironbridge Gazette", "The Lantern Post"]
NEWS_SUBJECTS = ["the Halvorsen Dam inspection", "the Corvane rail extension", "the Pell River flood audit",
                 "the Tessaly school census", "the Brightwater housing survey", "the Ostrava port expansion",
                 "the Marlow wind-farm review", "the Quell Valley water report"]
NEWS_FIGURES = [("households affected", "households"), ("kilometres of track", "km"), ("homes inspected", "homes"),
                ("students enrolled", "students"), ("turbines approved", "turbines"), ("litres per second", "L/s")]

BRANDS = ["Altrion", "Bexa", "Corvel", "Dunmark", "Elyra", "Fennix", "Gravio", "Halcyon", "Iridex", "Jovaro"]
PRODUCTS = [("portable power bank", "battery capacity", "mAh"), ("trail headlamp", "maximum output", "lumens"),
            ("bench multimeter", "basic DC accuracy", "%"), ("e-reader", "screen resolution", "ppi"),
            ("electric kettle", "rated power", "W"), ("smart thermostat", "standby power", "W"),
            ("cordless drill", "max torque", "Nm"), ("dehumidifier", "extraction rate", "L/day")]
SHOPS = ["northwind-goods", "parcelpoint", "voltmart", "kitebay-store", "lumen-outlet", "harbor-supply"]

AGENCIES = ["Bureau of Inland Waters", "Office of Regional Statistics", "Coastal Survey Agency",
            "Department of Transit Planning", "Institute for Soil Records", "National Fisheries Office"]
DATASETS = [("county water-quality index", "nitrate level at site", "mg/L"),
            ("regional freight volumes", "annual tonnage at depot", "kt"),
            ("coastal erosion survey", "retreat rate at transect", "m/yr"),
            ("school transport census", "daily riders on route", "riders"),
            ("soil carbon inventory", "organic carbon at plot", "t/ha")]
PLACES = ["Ardmore", "Belcliff", "Corran", "Dunvale", "Eskridge", "Fallowmere", "Glenhurst", "Hollins"]

LIBRARIES = ["quillfetch", "sparrowdb", "lattice-rpc", "tidepool", "brackish", "cobaltq", "fernlog", "vellum-cli"]
PARAMS = [("request timeout", "s", "timeout"), ("connection pool size", "connections", "pool_size"),
          ("retry backoff base", "ms", "backoff_ms"), ("max batch size", "records", "max_batch"),
          ("cache TTL", "s", "cache_ttl"), ("page size limit", "items", "page_limit")]

WIKI_SUBJECTS = [("Mount Eskara", "summit elevation", "m"), ("Lake Orsund", "maximum depth", "m"),
                 ("Halberd Bridge", "main span length", "m"), ("Cape Venn Lighthouse", "focal height", "m"),
                 ("Tarn Valley Railway", "line length", "km"), ("Ostrel Glacier", "surface area", "km²")]

FORUM_NAMES = ["openboard", "netlounge", "shareit-forum"]


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(SURNAMES)}"


def slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:48]


def gtin(rng: random.Random) -> str:
    """A 13-digit GTIN with a valid check digit."""
    digits = [rng.randint(0, 9) for _ in range(12)]
    digits[0] = rng.choice([4, 5, 7, 8, 9])
    s = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits))
    check = (10 - s % 10) % 10
    return "".join(map(str, digits + [check]))
