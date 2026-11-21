#!/usr/bin/env python3
"""Pull real per-hull stats from the SC Unpacked dataset and reduce them to a
compact local file.

Source: StarCitizenWiki/scunpacked-data (community extraction of the game files).
This is the detail layer the rotation page was missing: shield HP, stock DPS,
alpha, quantum range and speed, claim time, mass, cargo grids.

The upstream ships.json is ~43 MB; we only need a slice, so it gets cached once
and reduced. Run: python3 ingest.py [--force]
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache")
SRC = "https://raw.githubusercontent.com/StarCitizenWiki/scunpacked-data/master/ships.json"
OUT = os.path.join(DATA, "ship_stats.json")


def norm(s):
    s = (s or "").lower().replace("mk ii", "mk2").replace("mk i", "mk1")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s)


def get_raw(force=False):
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, "scunpacked_ships.json")
    if os.path.exists(dest) and not force:
        return json.load(open(dest))
    req = urllib.request.Request(SRC, headers={"User-Agent": "whatshouldifly/0.2"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
    with open(dest, "wb") as fh:
        fh.write(raw)
    return json.loads(raw)


def num(v, default=None):
    return v if isinstance(v, (int, float)) else default


def extract(rec):
    sysd = rec.get("Systems") or {}
    weapons = (sysd.get("Weapons") or {}).get("Summary") or {}
    fixed = weapons.get("FixedWeapons") or {}
    turret = weapons.get("TurretWeapons") or {}
    missiles = (sysd.get("Missiles") or {}).get("Summary") or {}
    qt = rec.get("QuantumTravel") or {}
    ins = rec.get("Insurance") or {}
    shields = rec.get("ShieldsTotal") or {}
    propulsion = rec.get("Propulsion") or {}

    dps = num(fixed.get("DpsTotal"), 0) + num(turret.get("DpsTotal"), 0)
    alpha = num(fixed.get("AlphaTotal"), 0) + num(turret.get("AlphaTotal"), 0)

    # stock loadout: what the ship actually comes with, so a new player knows
    # whether they need to buy guns before it's usable
    guns = []
    for w in (fixed.get("Weapons") or []) + (turret.get("Weapons") or []):
        if w.get("Name"):
            guns.append({"name": w["Name"], "dps": num(w.get("Dps"), 0)})

    qt_range_km = None
    if num(qt.get("Range")):
        qt_range_km = round(qt["Range"] / 1000.0)
    qt_speed = num(qt.get("Speed"))
    qt_speed_kms = round(qt_speed / 1000.0) if qt_speed else None

    return {
        "name": rec.get("Name"),
        "manufacturer": rec.get("Manufacturer"),
        "role": rec.get("Role") or "",
        "career": rec.get("Career") or "",
        "crew": num(rec.get("Crew")),
        "seats": num(rec.get("Seats")),
        "cargo_scu": num(rec.get("Cargo")),
        "shield_hp": num(shields.get("Hp"), num(rec.get("ShieldHp"))),
        "shield_regen": num(shields.get("Regen")),
        "dps": round(dps, 1) if dps else None,
        "alpha": round(alpha, 1) if alpha else None,
        "missiles": num(missiles.get("Count")),
        "guns": guns[:8],
        "qt_range_km": qt_range_km,
        "qt_speed_kms": qt_speed_kms,
        "qt_spool_s": num(qt.get("SpoolTime")),
        "claim_min": round(ins["StandardClaimTime"], 1) if num(ins.get("StandardClaimTime")) else None,
        "mass_kg": num(rec.get("MassTotal")),
        "length_m": num(rec.get("Length")),
        "width_m": num(rec.get("Width")),
        "height_m": num(rec.get("Height")),
        "h2_fuel": num(propulsion.get("FuelCapacity")),
        "is_spaceship": bool(rec.get("IsSpaceship")),
        "is_vehicle": bool(rec.get("IsVehicle")),
        "is_power_suit": bool(rec.get("IsPowerSuit")),
        "description": (rec.get("DescriptionText") or rec.get("Description") or "").strip(),
    }


# Schedule names that don't match the dataset's naming. Keys are the names as
# they appear in data/iae_2956.json; values are exact dataset names.
ALIASES = {
    "600i Explorer": "Origin 600i",
    "600i Touring": "Origin 600i Touring",
    "85x": "Origin 85X Limited",
    "A2 Hercules": "Crusader A2 Hercules Starlifter",
    "C2 Hercules": "Crusader C2 Hercules Starlifter",
    "M2 Hercules": "Crusader M2 Hercules Starlifter",
    "Ares Inferno": "Crusader Ares Star Fighter Inferno",
    "Ares Ion": "Crusader Ares Star Fighter Ion",
    "Ballista": "Anvil HM6 Ballista",
    "Centurion": "Anvil HM6 Centurion",
    "Spartan": "Anvil HM6 Spartan",
    "C8R Pisces": "Anvil C8R Pisces Rescue",
    "C8X Pisces Expedition": "Anvil C8X Pisces Expedition",
    "Constellation Andromeda": "RSI Constellation Mk IV Andromeda",
    "Constellation Aquila": "RSI Constellation Mk IV Aquila",
    "Constellation Phoenix": "RSI Constellation Mk IV Phoenix",
    "Constellation Taurus": "RSI Constellation Mk IV Taurus",
    "Dragonfly Black": "Drake Dragonfly",
    "Aurora Mk II": "RSI Aurora Mk II",
    "Nox": "Aopoa Nox",
    "Mule": "Drake Mule",
    "Pitbull": "Drake Pitbull",
    "Vulture": "Drake Vulture",
    "Corsair": "Drake Corsair",
    "Cutter": "Drake Cutter",
    "Cutlass Black": "Drake Cutlass Black",
    "Cutlass Blue": "Drake Cutlass Blue",
    "Cutlass Steel": "Drake Cutlass Steel",
    "Prospector": "MISC Prospector",
    "Freelancer": "MISC Freelancer",
    "Freelancer MAX": "MISC Freelancer MAX",
    "Freelancer MIS": "MISC Freelancer MIS",
    "Freelancer DUR": "MISC Freelancer DUR",
    "Hull A": "MISC Hull A",
    "Hull B": "MISC Hull B",
    "Hull C": "MISC Hull C",
    "Starfarer": "MISC Starfarer",
    "Starfarer Gemini": "MISC Starfarer Gemini",
    "Reliant Kore": "MISC Reliant Kore",
    "Reliant Tana": "MISC Reliant Tana",
    "Reliant Sen": "MISC Reliant Sen",
    "Reliant Mako": "MISC Reliant Mako",
    "Starlancer MAX": "MISC Starlancer MAX",
    "Starlancer TAC": "MISC Starlancer TAC",
    "Avenger Titan": "Aegis Avenger Titan",
    "Avenger Stalker": "Aegis Avenger Stalker",
    "Avenger Warlock": "Aegis Avenger Warlock",
    "Avenger Titan Renegade": "Aegis Avenger Titan Renegade",
    "Gladius": "Aegis Gladius",
    "Gladius Valiant": "Aegis Gladius Valiant",
    "Sabre": "Aegis Sabre",
    "Sabre Comet": "Aegis Sabre Comet",
    "Sabre Firebird": "Aegis Sabre Firebird",
    "Sabre Peregrine": "Aegis Sabre Peregrine",
    "Eclipse": "Aegis Eclipse",
    "Hammerhead": "Aegis Hammerhead",
    "Reclaimer": "Aegis Reclaimer",
    "Redeemer": "Aegis Redeemer",
    "Retaliator": "Aegis Retaliator",
    "Vanguard Warden": "Aegis Vanguard Warden",
    "Vanguard Sentinel": "Aegis Vanguard Sentinel",
    "Vanguard Harbinger": "Aegis Vanguard Harbinger",
    "Vanguard Hoplite": "Aegis Vanguard Hoplite",
    "Tiburon": "Aegis Tiburon",
    "Arrow": "Anvil Arrow",
    "Asgard": "Anvil Asgard",
    "Carrack": "Anvil Carrack",
    "F7C Hornet Mk II": "Anvil F7C Hornet Mk II",
    "F7C-M Super Hornet Mk II": "Anvil F7C-M Super Hornet Mk II",
    "F7C-R Hornet Tracker Mk II": "Anvil F7C-R Hornet Tracker Mk II",
    "F7C-S Hornet Ghost Mk II": "Anvil F7C-S Hornet Ghost Mk II",
    "F8C Lightning": "Anvil F8C Lightning",
    "Gladiator": "Anvil Gladiator",
    "Hawk": "Anvil Hawk",
    "Hurricane": "Anvil Hurricane",
    "Paladin": "Anvil Paladin",
    "Terrapin": "Anvil Terrapin",
    "Terrapin Medic": "Anvil Terrapin Medic",
    "Valkyrie": "Anvil Valkyrie",
    "A1 Spirit": "Crusader A1 Spirit",
    "C1 Spirit": "Crusader C1 Spirit",
    "Intrepid": "Crusader Intrepid",
    "Mercury Star Runner": "Crusader Mercury Star Runner",
    "Cyclone": "Tumbril Cyclone",
    "Cyclone AA": "Tumbril Cyclone AA",
    "Cyclone MT": "Tumbril Cyclone MT",
    "Cyclone RC": "Tumbril Cyclone RC",
    "Cyclone RN": "Tumbril Cyclone RN",
    "Cyclone TR": "Tumbril Cyclone TR",
    "Nova": "Tumbril Nova",
    "Storm": "Tumbril Storm",
    "Storm AA": "Tumbril Storm AA",
    "ATLS": "Argo ATLS",
    "ATLS GEO": "Argo ATLS GEO",
    "MOLE": "Argo MOLE",
    "RAFT": "Argo RAFT",
    "SRV": "Argo SRV",
    "MPUV Cargo": "Argo MPUV Cargo",
    "MPUV Personnel": "Argo MPUV Personnel",
    "MPUV Tractor": "Argo MPUV Tractor",
    "CSV-SM": "Argo CSV-SM",
    "Mustang Alpha": "Consolidated Outland Mustang Alpha",
    "Mustang Beta": "Consolidated Outland Mustang Beta",
    "Mustang Delta": "Consolidated Outland Mustang Delta",
    "Mustang Gamma": "Consolidated Outland Mustang Gamma",
    "Nomad": "Consolidated Outland Nomad",
    "ROC": "Greycat ROC",
    "ROC-DS": "Greycat ROC-DS",
    "PTV": "Greycat PTV",
    "STV": "Greycat STV",
    "UTV": "Greycat UTV",
    "HoverQuad": "Greycat HoverQuad",
    "MDC": "Greycat MDC",
    "MTC": "Greycat MTC",
    "Basher": "Greycat Basher",
    "Shiv": "Greycat Shiv",
    "MOTH": "Argo MOTH",
    "Fury": "Mirai Fury",
    "Fury LX": "Mirai Fury LX",
    "Fury MX": "Mirai Fury MX",
    "Guardian": "Mirai Guardian",
    "Guardian MX": "Mirai Guardian MX",
    "Guardian QI": "Mirai Guardian QI",
    "Pulse": "Mirai Pulse",
    "Pulse LX": "Mirai Pulse LX",
    "L-21 Wolf": "Kruger L-21 Wolf",
    "L-22 Alpha Wolf": "Kruger L-22 Alpha Wolf",
    "P-52 Merlin": "Kruger P-52 Merlin",
    "P-72 Archimedes": "Kruger P-72 Archimedes",
    "S-65 Stingray": "Kruger S-65 Stingray",
    "Razor": "Mirai Razor",
    "Razor EX": "Mirai Razor EX",
    "Razor LX": "Mirai Razor LX",
    "Galaxy": "RSI Galaxy",
    "Skylark": "RSI Skylark",
    "Apollo Medivac": "RSI Apollo Medivac",
    "Apollo Triage": "RSI Apollo Triage",
    "Hermes": "RSI Hermes",
    "Lynx": "RSI Lynx",
    "Mantis": "RSI Mantis",
    "Meteor": "RSI Meteor",
    "Perseus": "RSI Perseus",
    "Polaris": "RSI Polaris",
    "Salvation": "RSI Salvation",
    "Scorpius": "RSI Scorpius",
    "Scorpius Antares": "RSI Scorpius Antares",
    "Ursa": "RSI Ursa",
    "Ursa Medivac": "RSI Ursa Medivac",
    "Zeus Mk II CL": "RSI Zeus Mk II CL",
    "Zeus Mk II ES": "RSI Zeus Mk II ES",
    "890 Jump": "Origin 890 Jump",
    "100i": "Origin 100i",
    "125a": "Origin 125a",
    "135c": "Origin 135c",
    "300i": "Origin 300i",
    "315p": "Origin 315p",
    "325a": "Origin 325a",
    "350r": "Origin 350r",
    "400i": "Origin 400i",
    "M50": "Origin M50",
    "M80": "Origin M80",
    "X1": "Origin X1",
    "X1 Force": "Origin X1 Force",
    "X1 Velocity": "Origin X1 Velocity",
    "Buccaneer": "Drake Buccaneer",
    "Caterpillar": "Drake Caterpillar",
    "Clipper": "Drake Clipper",
    "Cutter Rambler": "Drake Cutter Rambler",
    "Cutter Scout": "Drake Cutter Scout",
    "Golem": "Drake Golem",
    "Golem OX": "Drake Golem OX",
    "Herald": "Drake Herald",
    "Ironclad": "Drake Ironclad",
    "Ironclad Assault": "Drake Ironclad Assault",
    "Kraken": "Drake Kraken",
    "Kraken Privateer": "Drake Kraken Privateer",
    "Pioneer": "Drake Pioneer",
    "Idris-P": "Aegis Idris-P",
    "Javelin": "Aegis Javelin",
    "Khartu-al": "Aopoa Khartu-al",
    "San'tok.yāi": "Aopoa San'tok.yāi",
    "Defender": "Banu Defender",
    "Blade": "Esperia Blade",
    "Glaive": "Esperia Glaive",
    "Prowler": "Esperia Prowler",
    "Prowler Utility": "Esperia Prowler Utility",
    "Stinger": "Esperia Stinger",
    "Talon": "Esperia Talon",
    "Talon Shrike": "Esperia Talon Shrike",
    "Railen": "Banu Souli Railen",
    "Syulen": "Gatac Syulen",
    "Tyilui": "Gatac Tyilui",
    "Fortune": "MISC Fortune",
    "Starlite": "MISC Starlite",
}


def build_index(raw):
    """name-normalized -> extracted stats, plus a manufacturer-stripped alias map."""
    out = {}
    by_full = {}
    for rec in raw:
        full = rec.get("Name") or ""
        if not full:
            continue
        stats = extract(rec)
        by_full[full] = stats
        out.setdefault(norm(full), stats)
        parts = full.split(" ", 1)
        if len(parts) == 2:
            out.setdefault(norm(parts[1]), stats)
    return out, by_full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download the 43MB source")
    args = ap.parse_args()

    raw = get_raw(args.force)
    print(f"source records: {len(raw)}")

    idx, by_full = build_index(raw)

    sched = json.load(open(os.path.join(DATA, "iae_2956.json")))
    names = sorted({n for d in sched["days"] for n in d["ships"] if n != "__ALL__"})

    resolved, unmatched = {}, []
    for n in names:
        hit = None
        alias = ALIASES.get(n)
        if alias and alias in by_full:
            hit = by_full[alias]
        if hit is None:
            hit = idx.get(norm(n))
        if hit is None:
            # last resort: exact-ish containment on normalized tokens
            target = norm(n)
            cands = [s for k, s in idx.items() if k.startswith(target) or target.startswith(k)]
            hit = cands[0] if cands else None
        if hit is None:
            unmatched.append(n)
        else:
            resolved[n] = hit

    print(f"resolved {len(resolved)}/{len(names)} scheduled hulls")
    if unmatched:
        print("unmatched:", unmatched)

    out = {"source": SRC, "ships": resolved}
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"wrote {OUT} ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
