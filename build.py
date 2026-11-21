#!/usr/bin/env python3
"""Build whatshouldifly — a static page answering "what's free to rent today,
and is any of it worth buying."

Data: UEX API 2.0 (public, no key for GET) + local IAE schedule file.
Output: docs/index.html + docs/data.json (self-contained, no JS deps).

Run:  python3 build.py            (writes site/)
      python3 build.py --dry      (prints the rotation, no write)
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SITE = os.path.join(HERE, "docs")

UEX = "https://api.uexcorp.uk/2.0"
CACHE = os.path.join(HERE, "cache")

REFERRAL_CODE = "STAR-HRKX-L6ND"
REFERRAL_URL = "https://robertsspaceindustries.com/enlist?referral=" + REFERRAL_CODE


def fetch(name, path):
    """GET a UEX endpoint, caching to disk so reruns don't hammer the API.

    Falls back to a stale cache rather than failing the whole build: the daily
    cron shouldn't stop publishing because UEX had a bad morning.
    """
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, name + ".json")
    fresh = False
    if os.path.exists(dest):
        age = datetime.now().timestamp() - os.path.getmtime(dest)
        fresh = age < 6 * 3600
        if fresh:
            with open(dest) as fh:
                return json.load(fh)
    try:
        req = urllib.request.Request(UEX + path, headers={"User-Agent": "whatshouldifly/0.1"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode())
        with open(dest, "w") as fh:
            json.dump(payload, fh)
        return payload
    except Exception as exc:
        if os.path.exists(dest):
            print(f"  ! {name}: fetch failed ({exc}); using cached copy", file=sys.stderr)
            with open(dest) as fh:
                return json.load(fh)
        raise


def norm(s):
    s = (s or "").lower()
    s = s.replace("mk ii", "mk2").replace("mk i", "mk1")
    # fold accents so "San'tok.yāi" matches a plain-ASCII key
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def build_index(vehicles, buys, pledges, rentals):
    """Normalized name -> best-known facts."""
    out = {}
    for v in vehicles:
        key = norm(v.get("name"))
        out[key] = {
            "name": v.get("name"),
            "company": v.get("company_name"),
            "crew": v.get("crew"),
            "scu": v.get("scu"),
            "roles": [r for r in (
                "cargo", "mining", "salvage", "medical", "racing",
                "exploration", "military", "starter", "ground_vehicle",
                "passenger", "refuel", "repair", "stealth", "bomber",
                "interdiction", "research", "science", "datarunner",
            ) if v.get("is_" + r)],
            "concept": bool(v.get("is_concept")),
            "slug": v.get("slug"),
        }
    # cheapest in-game purchase per ship
    for row in buys:
        key = norm(row.get("vehicle_name"))
        rec = out.setdefault(key, {"name": row.get("vehicle_name"), "roles": []})
        price = row.get("price_buy")
        if not price:
            continue
        if "buy" not in rec or price < rec["buy"]["auec"]:
            rec["buy"] = {"auec": price, "where": row.get("terminal_name")}
    # pledge price (fresh money)
    for row in pledges:
        key = norm(row.get("vehicle_name"))
        rec = out.setdefault(key, {"name": row.get("vehicle_name"), "roles": []})
        price = row.get("price_warbond") or row.get("price")
        if price:
            rec["pledge"] = {"usd": price, "warbond": bool(row.get("price_warbond"))}
    # normal rental price (for reference: what it costs outside the event)
    for row in rentals:
        key = norm(row.get("vehicle_name"))
        rec = out.setdefault(key, {"name": row.get("vehicle_name"), "roles": []})
        price = row.get("price_rent")
        if price and ("rent" not in rec or price < rec["rent"]["auec"]):
            rec["rent"] = {"auec": price, "where": row.get("terminal_name")}
    return out


def money(n):
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}k"
    return str(n)


def crew_int(v):
    """UEX returns crew as a string, sometimes a comma list ('4,7') = min,max."""
    s = str(v or "").strip()
    if not s:
        return 1
    nums = [int(x) for x in re.findall(r"\d+", s)]
    return min(nums) if nums else 1


# Per-hull advice for ships a new player actually asks about. Anything not
# listed falls through to role-based guidance. Keep these to one useful line:
# what the ship is FOR, and whether to buy it or just fly it free.
NOTES = {
    "avengertitan": "The default answer for a first ship. 8 SCU, one seat, guns enough to take a starter bounty. Fly it free, then buy it in-game — it's the cheapest real ship you can own.",
    "auroramk2": "The free loaner you already have. Don't rent it, don't buy it. Fly it until you know what you want.",
    "gladius": "The PvP benchmark. Light fighter, agile, no cargo. If combat is your loop, this is the ship you measure every other fighter against.",
    "gladiusvaliant": "Same hull as the Gladius with a different loadout and paint. Fly whichever is free; don't pay a premium for the variant.",
    "sabre": "Stealth fighter. Lower signature, harder to spot on radar — good for ambush, worse in a straight brawl than the Gladius.",
    "eclipse": "Torpedo bomber. One pass, one kill, then you leave. Slow to turn and useless in a dogfight; judge it on a single bounty, not a furball.",
    "hammerhead": "Six turrets, no pilot guns. It exists to be crewed. Renting it solo tells you nothing — bring friends or skip it.",
    "reclaimer": "The big salvage ship: 420 SCU, claw, drones. This is the highest-earning solo industrial loop in the game, and it's slow. Rent it free and run one wreck before you commit.",
    "vulture": "Small salvage. Solo, cheap to run, and the honest entry point to the salvage loop — this is the one to try before the Reclaimer.",
    "prospector": "Solo mining. The most reliable money-maker for a new player. Rent it, mine one haul, sell it, and you'll understand the economy.",
    "mole": "Three-person mining. More ore per run, but you need crew. Solo it and you're paying for seats you aren't using.",
    "cutlassblack": "The do-everything mid-game ship: 46 SCU, turret, room for a friend. If you only ever buy one ship in-game, this is the argument.",
    "cutlassred": "Cutlass with medical beds. Same hull, different job — worth it only if you fly with people who get shot.",
    "freelancermax": "120 SCU on a solo hull. The best pure hauler you can buy in-game at the low end.",
    "constellationandromeda": "Multi-crew gunship and hauler. Strong solo, much stronger with a second seat. The step up from a Cutlass.",
    "retaliator": "Torpedo bomber with a modular belly. Big alpha strike, needs a crew to be worth the price.",
    "redeemer": "Gunship that wants four people. Enormous firepower, terrible solo. Only rent it if you have a crew.",
    "carrack": "Exploration flagship with a med bay, hangar and rover. Not a money-maker — it's a home base. Rent it to see what the endgame feels like.",
    "c2hercules": "The big hauler. 600+ SCU. Boring to fly, excellent to earn with.",
    "corsair": "Drake's armed explorer. Lots of guns, decent cargo, crew of four. Popular because it does everything adequately.",
    "vanguardwarden": "Long-range heavy fighter with interior space. Expensive, tanky, and forgiving — a good 'I fly alone a lot' combat pick.",
    "vanguardsentinel": "Vanguard with an EMP and better sensors. Same hull, more utility, less raw damage.",
    "890jump": "The yacht. Not a tool, a statement. Rent it once to walk around it, then go back to earning.",
    "polaris": "Capital torpedo boat. Needs a crew and a reason. Rent it for the spectacle.",
    "idrisp": "Frigate. Stock-limited in waves — if you want to see one fly, be at the terminal on time.",
    "javelin": "Destroyer. The biggest thing most players will ever stand on. Wave-limited; treat it as a field trip.",
    "kraken": "Carrier. Sells out in waves. Rent it to land a ship on a ship.",
    "perseus": "Best in Show winner. Heavy gunship; the community voted it the ship of the year.",
    "ironcladassault": "Drake's armored hauler. Best in Show finalist — cargo with guns.",
    "m80": "Origin's new mid-size. Best in Show finalist; fast, expensive, stylish.",
    "galaxy": "Modular hull: cargo, medical, or refinery module. The concept is the appeal — judge the base ship, not the brochure.",
    "liberator": "Open-air vehicle carrier. Niche: it moves ground vehicles and small ships. Rent it if you run a fleet, skip it if you fly solo.",
    "terrapin": "Armored scout. Survives things it shouldn't. No cargo, no guns worth mentioning.",
    "terrapinmedic": "Terrapin with a med bed. A rescue ship for group play.",
    "c8rpisces": "Tiny medical ship that fits in a Carrack. Cheap, useful, unglamorous.",
    "arrow": "The cheap light fighter. Fast and fragile — the ship you learn combat in, not the one you win in.",
    "f7chornetmk2": "Medium fighter, the military standard. More armor than an Arrow, less agility.",
    "f8clightning": "Top-tier fighter. Expensive in-game, superb in a fight.",
    "hurricane": "Two-seat fighter: pilot guns plus a turret. Strong with a gunner, mediocre alone.",
    "eclipse": "Torpedo bomber — one big pass, then leave.",
    "khartual": "Alien light fighter. Fast, twitchy, no cargo. A taste of Xi'an engineering.",
    "defender": "Banu multi-crew fighter with interior space. Unusual and capable; needs a second seat to shine.",
    "talon": "Esperia light fighter. Cheap alien fighter; fun, not optimal.",
    "railensyulen": "Gatac alien hulls — visually the most interesting ships at the show.",
    "hyun": "New Gatac industrial ship: mining and salvage in one hull. Worth a look if you like the industrial loops.",
    "nomad": "Starter-plus: 24 SCU, a tractor beam, and a livable cabin. The step between a starter and a Cutlass.",
    "intrepid": "Crusader starter. Small cargo, solo, cheap.",
    "cutter": "Drake starter. Rugged, cheap, no frills — a legitimate first ship.",
    "hullc": "The serious hauler. Massive cargo, needs escorts and a plan.",
    "starlancermax": "MISC mid-size hauler with teeth. Popular all-rounder.",
    "atls": "Greycat power suit. Not a ship — it moves cargo. Rent it to see if you like hauling on foot.",
    "roc": "Ground mining vehicle. Fits in a Cutlass; a genuinely good solo money loop.",
    "cyclone": "Ground buggy. Cheap in-game, fun, not essential.",
    "nova": "Tank. Slow, heavily armed, wants a crew.",
    "sanTokyai": "Aopoa heavy fighter. Alien, agile, expensive.",
    "prowler": "Esperia dropship. Boarding and insertion; niche but cool.",
    "stinger": "Esperia medium fighter.",
    "blade": "Esperia light fighter, Vanduul-derived.",
    "glaive": "Esperia heavy fighter, Vanduul-derived.",

    # --- Origin: all fast, all expensive, all style over utility ---
    "100i": "Origin's entry ship. Fast, polished, 2 SCU. The starter for someone who cares how the ship looks.",
    "125a": "100i with guns. Still a starter; you're paying for the badge, not the firepower.",
    "135c": "The cargo variant of the 100 series. 6 SCU, still tiny — fine as a runabout, not a hauler.",
    "300i": "Origin's mid starter. Quick, comfortable, 8 SCU. A nicer Avenger Titan for twice the price.",
    "315p": "300i with a tractor beam and better scanners. Exploration-flavored, not exploration-capable.",
    "325a": "300i with guns. Fast and stylish; a legitimate light fighter if you like the look.",
    "350r": "The fast one. Racing pedigree, no cargo. Rent it for the speed, buy it only if racing is your thing.",
    "400i": "Origin's solo explorer. Beautiful, quick, roomy for one. Not a money-maker — a good 'live aboard' ship.",
    "600iexplorer": "Big luxury explorer. Two decks, a rover, no real earning loop. Rent it to see what the top end feels like.",
    "600itouring": "Same hull, passenger version. Only worth it if you fly with people and want them comfortable.",
    "85x": "Origin's tiny runabout. 0 SCU, no bed. A shuttle, not a ship you'll keep.",
    "m50": "Racing ship. Zero cargo, zero guns worth mentioning. Rent it to feel the handling, then go back to work.",
    "m80": "Origin's new mid-size. Best in Show finalist — fast, expensive, and stylish. Judge it on looks, because the stats won't win you over.",

    # --- Anvil ---
    "asgard": "Anvil's big multi-role. Cargo, guns, and a crew requirement. Rent it if you have friends online.",
    "ballista": "Anti-air missile platform. Ground vehicle, not a ship. Devastating against aircraft, useless as transport.",
    "c8xpiscesexpedition": "Tiny expedition shuttle. Fits in a Carrack, gets you around. Cheap and genuinely useful.",
    "gladiator": "Torpedo bomber with a turret. Old design, still functional — one big hit, then leave.",
    "hawk": "Light fighter with an EMP. Good for disabling, not for killing. Niche but fun.",
    "hurricane": "Two-seat fighter: pilot guns plus a turret. Strong with a gunner, mediocre alone.",
    "paladin": "Anvil gunship. Wants a crew; big guns, slow turns.",
    "spartan": "Armored personnel carrier. Ground vehicle — moves people, not cargo.",
    "valkyrie": "Dropship. Moves troops and vehicles. Rent it only if you're playing with a group.",
    "centurion": "Anvil's ground combat vehicle. Anti-personnel, not anti-ship.",

    # --- Crusader ---
    "a1spirit": "Bomber variant of the Spirit. One big payload, fast in and out. Solo-friendly.",
    "a2hercules": "The flying fortress. Massive cargo, massive guns, needs crew. Rent it for the spectacle.",
    "c1spirit": "Crusader's mid cargo runner. Fast, 64 SCU, soloable. A legitimate alternative to a Freelancer.",
    "c2hercules": "The big hauler. 600+ SCU. Boring to fly, excellent to earn with.",
    "m2hercules": "C2 with armor and guns. Same cargo, more teeth, more crew.",
    "mercurystarrunner": "Fast data-runner with cargo. Soloable, quick, good-looking. A popular all-rounder.",
    "intrepid": "Crusader's starter. Small cargo, solo, cheap. Fine first ship, nothing special.",

    # --- Drake ---
    "buccaneer": "Drake's cheap fighter. Fast, fragile, hits hard. A good 'learn to fight' hull.",
    "caterpillar": "Modular cargo monster. Massive capacity, slow, needs crew to defend.",
    "clipper": "Drake's new mid-size. Cargo plus guns. The Cutlass's bigger sibling.",
    "corsair": "Drake's armed explorer. Lots of guns, decent cargo, crew of four. Popular because it does everything adequately.",
    "cutlassblue": "Cutlass with prisoner pods and better shields. Bounty-hunting variant; niche.",
    "cutlasssteel": "Cutlass with more armor and troops. Dropship-flavored; only for group play.",
    "cutterrambler": "Cutter with a living space. Same cheap hull, more comfort.",
    "cutterscout": "Cutter with scanners. Exploration-flavored starter.",
    "dragonflyblack": "Hover bike. Fits in a Cutlass or Freelancer. Cheap fun, no real earning loop.",
    "golem": "Drake's industrial hull. New, mining-flavored — worth a look if you like the industrial loops.",
    "golemox": "Golem with more capacity. Same idea, bigger.",
    "herald": "Data runner. Fast, no cargo, niche. Rent it once for the speed.",
    "ironclad": "Drake's armored freighter. Cargo with guns. Big crew requirement.",
    "mule": "Tiny cargo runabout. 0 SCU officially, but it moves boxes. Cheap and oddly charming.",
    "pitbull": "Drake's light fighter. Cheap, fast, no frills.",
    "vulture": "Small salvage. Solo, cheap to run, and the honest entry point to the salvage loop — this is the one to try before the Reclaimer.",

    # --- MISC / Mirai / Kruger ---
    "fortune": "MISC's new industrial hull. Worth a look if mining or salvage interests you.",
    "freelancer": "The classic mid cargo ship. 66 SCU, soloable, armed. Still a solid buy in-game.",
    "freelancerdur": "Freelancer built for range and scanning. Exploration variant; less cargo.",
    "freelancermis": "Freelancer with missiles. Combat-hauler hybrid; fun, not optimal.",
    "hulla": "Small hauler. Cheap entry to cargo running.",
    "hullb": "Mid hauler. More capacity, still soloable.",
    "fury": "Mirai's snub fighter. Tiny, fast, no quantum drive of its own — needs a carrier.",
    "furylx": "Fury with better handling. Racing-flavored snub.",
    "furymx": "Fury with more guns. The combat snub.",
    "guardian": "Mirai's new fighter. Worth a look; the snub lineage grown up.",
    "guardianmx": "Guardian combat variant.",
    "guardianqi": "Guardian variant with different loadout.",
    "l21wolf": "Kruger's light fighter. Cheap, nimble.",
    "l22alphawolf": "The upgunned Wolf. Still cheap, still nimble.",
    "p52merlin": "Snub fighter that comes with a Constellation. Tiny, no quantum. Fun, not a ship you buy.",
    "p72archimedes": "Racing snub. Same deal — a toy that rides inside a bigger ship.",
    "prospector": "Solo mining. The most reliable money-maker for a new player. Rent it, mine one haul, sell it, and you'll understand the economy.",
    "reliantkore": "MISC's odd rotating-hull cargo ship. Cheap, weird, functional.",
    "reliantmako": "Reliant news van. Scanning and broadcasting; niche.",
    "reliantsen": "Reliant science variant. Research-flavored.",
    "relianttana": "Reliant combat variant. The most useful of the Reliants.",
    "starfarer": "Flying fuel refinery. Refuels other ships; a support role, needs crew.",
    "starfarergemini": "Starfarer with more guns and armor. Military fuel support.",
    "starlancermax": "MISC mid-size hauler with teeth. Popular all-rounder.",
    "starlancertac": "Starlancer combat variant. More guns, less cargo.",
    "starlite": "MISC's small new hull. Worth a look.",
    "s65stingray": "Kruger's racing ship. Fast, no cargo.",
    "razor": "Racing ship. Zero utility, pure speed.",
    "razorex": "Razor variant. Same idea.",
    "razorlx": "Razor variant. Same idea.",
    "meteor": "MISC's small fighter. Cheap, fast.",
    "skylark": "RSI's new small hull. Worth a look if you like RSI design.",

    # --- Argo / Greycat / Consolidated Outland ---
    "atlsgeo": "ATLS power suit, mining variant. Moves ore, not cargo.",
    "csvsm": "Argo's small cargo vehicle. Ground-based hauling.",
    "moth": "Argo's new hull. Industrial support.",
    "mpuvcargo": "Tiny cargo shuttle. Moves boxes between ships. No quantum drive.",
    "mpuvpersonnel": "Tiny people shuttle. Same deal, seats instead of cargo.",
    "mpuvtractor": "MPUV with a tractor beam. Oddly useful around a hangar.",
    "raft": "Argo's cargo hauler. 192 SCU, soloable, industrial. A real alternative to a Freelancer MAX.",
    "srv": "Argo's salvage rescue tug. Tows wrecks; support role.",
    "hoverquad": "Hover quad. Cheap ground fun.",
    "mustangalpha": "Consolidated Outland's starter. Cheap, fast, 4 SCU. The other free-loaner tier.",
    "mustangbeta": "Mustang with a living space. Starter-plus.",
    "mustanggammma": "Mustang racing variant.",
    "mustanggamma": "Mustang racing variant.",
    "mustangdelta": "Mustang combat variant. Cheap fighter.",
    "nomad": "Starter-plus: 24 SCU, a tractor beam, and a livable cabin. The step between a starter and a Cutlass.",
    "ptv": "Greycat's golf cart. The cheapest vehicle in the game. Buy it in-game for pocket change.",
    "roc": "Ground mining vehicle. Fits in a Cutlass; a genuinely good solo money loop.",
    "roc-ds": "Two-seat ROC. More ore, needs a partner.",
    "stv": "Greycat's small transport. Ground runabout.",
    "utv": "Greycat utility vehicle. Ground support.",
    "mdс": "Greycat's new utility hull.",
    "mdc": "Greycat's new utility hull.",
    "mtc": "Greycat's new transport hull.",
    "basher": "Greycat's industrial ground vehicle.",
    "shiv": "Greycat's small ground vehicle.",
    "cycloneaa": "Cyclone with anti-air missiles. Ground support.",
    "cyclonemt": "Cyclone with a turret. Ground combat.",
    "cyclonerc": "Cyclone racing variant.",
    "cyclonern": "Cyclone recon variant.",
    "cyclonert": "Cyclone transport variant.",
    "nova": "Tank. Slow, heavily armed, wants a crew.",
    "storm": "Tumbril's ground vehicle. Combat-flavored.",
    "stormaa": "Storm anti-air variant.",

    # --- Aegis leftovers ---
    "avengerstalker": "Avenger with prisoner pods. Bounty-hunting variant; the Titan is the better buy.",
    "avengertitanrenegade": "Titan with a different loadout and paint. Same hull — don't pay a premium for the variant.",
    "avengerwarlock": "Avenger with an EMP. Disables ships instead of killing them. Niche.",
    "vanguardharbinger": "Vanguard bomber variant. Torpedoes instead of guns.",
    "vanguardhoplite": "Vanguard dropship. Moves troops; niche.",
    "sabrecomet": "Sabre with a different loadout. Same hull.",
    "sabrefirebird": "Sabre with missiles. More alpha, less agility.",
    "sabreperegrine": "Sabre racing variant.",
    "sabreravenex": "Sabre stealth variant with EMP. Rare; judge it on feel.",
    "tiburon": "Aegis's new heavy fighter. Big guns, wants a crew.",
    "eclipse": "Torpedo bomber. One pass, one kill, then you leave. Slow to turn and useless in a dogfight; judge it on a single bounty, not a furball.",

    # --- Alien ---
    "khartual": "Alien light fighter. Fast, twitchy, no cargo. A taste of Xi'an engineering.",
    "nox": "Aopoa hover bike. Fast, alien, no cargo.",
    "santokyai": "Aopoa heavy fighter. Alien, agile, expensive.",
    "defender": "Banu multi-crew fighter with interior space. Unusual and capable; needs a second seat to shine.",
    "talonshrike": "Talon with missiles. Esperia light fighter variant.",
    "prowlerutility": "Prowler as a utility hull. Dropship without the troops.",
    "railensyulen": "Gatac alien hulls — visually the most interesting ships at the show.",
    "syulen": "Gatac's alien starter. Genuinely different design; worth flying once.",
    "tyilui": "Gatac's new alien hull.",
    "stinger": "Esperia medium fighter.",
    "scorpius": "RSI's two-seat fighter. Strong with a gunner, mediocre alone.",
    "scorpiusantares": "Scorpius with an EMP. Disables instead of kills.",
    "salvation": "RSI's new hull. Worth a look if you like RSI design.",
    "hermes": "RSI's new mid-size. Cargo-flavored.",
    "lynx": "RSI's ground rover. Exploration support.",
    "ursa": "RSI's rover. Fits in a Constellation or Carrack. Ground exploration.",
    "ursamedivac": "Ursa with medical beds. Rescue rover.",
    "zeusmk2cl": "RSI's mid cargo ship. Soloable, good capacity. A legitimate alternative to a Freelancer.",
    "zeusmk2es": "Zeus exploration variant. Less cargo, more range.",
    "constellationaquila": "Constellation built for exploration — rover, scanners, less cargo.",
    "constellationphoenix": "Constellation as a luxury yacht. Expensive, comfortable, not efficient.",
    "constellationtaurus": "Constellation as a pure hauler. The most practical of the family.",
    "mantis": "Quantum interdiction ship. Pulls other ships out of quantum. PvP tool, niche solo.",
    "paladin": "Anvil gunship. Wants a crew; big guns, slow turns.",
    "vulkan": "Repair and refuel support ship. Group play.",
    "apollomedivac": "Medical ship with beds and a med bay. Group play; useless solo.",
    "apollotriage": "Apollo medical variant. Same job, different tier of care.",

    # --- remaining schedule entries ---
    "aresinferno": "Ares heavy fighter built around one enormous ballistic cannon. Kills big ships, struggles against small ones.",
    "aresion": "Ares heavy fighter built around one enormous laser cannon. Same tradeoff — capital-killer, not a dogfighter.",
    "cyclonetr": "Cyclone transport variant. Moves people or boxes on the ground.",
    "f7cmsuperhornetmk2": "Hornet with more guns and a turret. Stronger than the base Hornet, still a medium fighter.",
    "f7crhornettrackermk2": "Hornet built for scanning and tracking. Recon variant.",
    "f7cshornetghostmk2": "Hornet with stealth coatings and lower signature. Ambush fighter.",
    "pulse": "Mirai hover bike. Fast, cheap, no cargo.",
    "pulselx": "Pulse variant with a different look. Same bike.",
    "rocds": "Two-seat ROC. More ore, needs a partner.",
    "railen": "Banu cargo hauler. Alien design, real capacity.",
    "santokyai": "Aopoa heavy fighter. Alien, agile, expensive.",
    "x1": "Origin hover bike. Fast, stylish, no cargo.",
    "x1force": "X1 with more armor and guns.",
    "x1velocity": "X1 racing variant.",
}


def verdict(rec):
    """One line, the actual advice. Curated where it exists, role-based otherwise."""
    key = norm(rec.get("name"))
    if key in NOTES:
        return NOTES[key]
    roles = set(rec.get("roles") or [])
    buy = rec.get("buy")
    pledge = rec.get("pledge")
    crew = crew_int(rec.get("crew"))
    if "starter" in roles:
        return ("Starter hull. Fly it free and decide whether the game is for you — "
                "there's no reason to pledge for it.")
    if "mining" in roles:
        return "Mining. Rent it free, run one haul, sell the ore — then buy it in-game if the loop grabs you."
    if "salvage" in roles:
        return "Salvage. Slower to learn than mining, better payout curve once you know where wrecks are."
    if "medical" in roles:
        return "Medical. Useless solo, genuinely useful if you fly with people who get shot."
    if "ground_vehicle" in roles:
        return "Ground vehicle. Cheap in-game — rent it free, buy it only if you use it weekly."
    if "cargo" in roles and (rec.get("scu") or 0) >= 40:
        return f"Hauler: {rec.get('scu')} SCU. Boring to fly, reliable to earn with. Try before you buy."
    if crew >= 3:
        return f"Crew ship ({crew} seats minimum). Solo it and you're paying for empty chairs."
    if "military" in roles:
        return "Combat hull. One bounty run tells you more than any stat sheet."
    if buy:
        return f"Ownable in-game for {money(buy['auec'])} aUEC. Fly it free first, then decide."
    if pledge:
        return f"${pledge['usd']} on the pledge store — only worth it if this week convinces you."
    return "Fly it free, judge for yourself."


def rotation_for(now, sched):
    """Which day-window contains `now`, plus what's still rentable from the last 48h."""
    active, previous = None, []
    for d in sched["days"]:
        start = datetime.fromisoformat(d["start_utc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(d["end_utc"].replace("Z", "+00:00"))
        if start <= now < end:
            active = d
        elif now - timedelta(hours=sched["rental_hours"]) <= end <= now:
            previous.append(d)
    return active, previous


def render(now, sched, idx, active, previous, stock):
    today_ships = []
    finale = False
    if active:
        names = active["ships"]
        if "__ALL__" in names:
            finale = True
            # 284 hulls is a wall, not a page. Even "everything with curated
            # advice" is 196 cards. On finale day show the ones a new player
            # should actually spend a 48-hour rental on, and say so plainly.
            picks = [
                "avengertitan", "auroramk2", "cutter", "intrepid", "nomad",
                "prospector", "vulture", "mole", "roc", "reclaimer",
                "cutlassblack", "freelancermax", "c1spirit", "zeusmk2cl",
                "constellationandromeda", "constellationtaurus", "raft", "hullb",
                "gladius", "arrow", "f7chornetmk2", "sabre", "buccaneer",
                "vanguardwarden", "scorpius", "hurricane", "eclipse",
                "carrack", "corsair", "mercurystarrunner", "c2hercules",
                "polaris", "idrisp", "javelin", "890jump", "perseus",
                "khartual", "syulen", "defender", "san'tok.yai",
            ]
            names = []
            for k in picks:
                rec = idx.get(norm(k))
                if rec and rec.get("name"):
                    names.append(rec["name"])
            names = sorted(set(names), key=str.lower)
        for n in names:
            rec = idx.get(norm(n), {"name": n, "roles": []})
            today_ships.append(rec)
    # dedupe by name, keep order
    seen, ships = set(), []
    for r in today_ships:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        ships.append(r)

    # rank: starter > money loops > single-seat combat > crew > rest
    def rank(r):
        roles = set(r.get("roles") or [])
        if "starter" in roles:
            return 0
        if roles & {"mining", "salvage"}:
            return 1
        if "cargo" in roles:
            return 2
        if "military" in roles and crew_int(r.get("crew")) == 1:
            return 3
        if "ground_vehicle" in roles:
            return 4
        return 5

    ships.sort(key=rank)

    still = []
    for d in previous:
        for n in d["ships"]:
            if n == "__ALL__":
                continue
            rec = idx.get(norm(n))
            if rec and rec["name"] not in seen:
                seen.add(rec["name"])
                still.append(rec)

    next_day = None
    if active:
        for d in sched["days"]:
            if d["day"] == active["day"] + 1:
                next_day = d
                break

    end = datetime.fromisoformat(sched["free_fly"]["end_utc"].replace("Z", "+00:00"))
    hours_left = max(0, int((end - now).total_seconds() // 3600))

    # Off-season: the event is over, but people will keep clicking shared links.
    # Don't show an empty page — show the hulls worth renting with normal aUEC,
    # which is the same advice minus the "free" part.
    off_season = active is None
    if off_season:
        evergreen = []
        for k in ("avengertitan", "cutlassblack", "prospector", "vulture",
                  "freelancermax", "constellationandromeda", "nomad", "roc"):
            if k in idx:
                evergreen.append(idx[k])
        ships = evergreen
        seen = {r["name"] for r in evergreen}
        still = []

    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": sched["event"],
        "venue": sched["venue"],
        "active_day": active["day"] if active else None,
        "active_makers": active["makers"] if active else [],
        "active_window_end_utc": active["end_utc"] if active else None,
        "finale": finale,
        "off_season": off_season,
        "total_rentable": (len([r for r in idx.values() if r.get("name")]) if finale else len(ships)),
        "hours_left": hours_left,
        "ships": [
            {
                "name": r["name"],
                "company": r.get("company"),
                "crew": r.get("crew"),
                "scu": r.get("scu"),
                "roles": r.get("roles") or [],
                "buy_auec": (r.get("buy") or {}).get("auec"),
                "buy_where": (r.get("buy") or {}).get("where"),
                "pledge_usd": (r.get("pledge") or {}).get("usd"),
                "rent_auec": (r.get("rent") or {}).get("auec"),
                "verdict": verdict(r),
            }
            for r in ships
        ],
        "still_rentable": [
            {"name": r["name"], "buy_auec": (r.get("buy") or {}).get("auec")}
            for r in still[:12]
        ],
        "next_day": {
            "day": next_day["day"],
            "makers": next_day["makers"],
        } if next_day else None,
        "stock_limited": stock,
        "referral": {"code": REFERRAL_CODE, "url": REFERRAL_URL, "uec": 50000},
    }


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="What's free to rent at IAE right now, and whether any of it is worth buying. Updated daily.">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Free 48-hour rentals at IAE, with one honest line on each hull: fly it, skip it, or here's what it costs in-game.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://gravitydeficient.github.io/whatshouldifly/">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="Free 48-hour rentals at IAE, with one honest line on each hull.">
<style>
  :root {{
    --bg:#0b0e14; --panel:#141922; --line:#232b38; --ink:#e6ecf5;
    --dim:#8b98ad; --hot:#39d0ff; --good:#5ee3a1; --warn:#ffc861;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  header {{ padding:32px 20px 20px; border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,#101828,var(--bg)); }}
  .wrap {{ max-width:920px; margin:0 auto; }}
  h1 {{ font-size:clamp(26px,5vw,40px); margin:0 0 6px; letter-spacing:-.02em; }}
  .sub {{ color:var(--dim); }}
  .badge {{ display:inline-block; font-size:12px; letter-spacing:.14em;
    text-transform:uppercase; color:var(--hot); border:1px solid var(--hot);
    padding:3px 8px; border-radius:999px; margin-bottom:14px; }}
  main {{ padding:24px 20px 60px; }}
  .card {{ background:var(--panel); border:1px solid var(--line);
    border-radius:14px; padding:16px 18px; margin:12px 0; }}
  .card h2 {{ margin:0 0 4px; font-size:19px; }}
  .meta {{ color:var(--dim); font-size:13px; margin-bottom:8px; }}
  .verdict {{ color:var(--ink); }}
  .num {{ color:var(--good); font-weight:600; }}
  .tag {{ display:inline-block; font-size:11px; letter-spacing:.08em;
    text-transform:uppercase; color:var(--dim); border:1px solid var(--line);
    border-radius:6px; padding:1px 6px; margin:2px 4px 2px 0; }}
  .call {{ border-left:3px solid var(--warn); padding-left:12px; }}
  .cta {{ margin-top:28px; padding:20px; border-radius:14px;
    background:linear-gradient(135deg,#132a3d,#0f1a24); border:1px solid #1f3d52; }}
  .cta a {{ color:var(--hot); font-weight:600; text-decoration:none; }}
  footer {{ color:var(--dim); font-size:12px; padding:0 20px 40px; }}
  footer a {{ color:var(--dim); }}
  ul {{ margin:6px 0 0; padding-left:18px; }}
  @media (max-width:520px) {{
    header {{ padding:24px 16px 16px; }}
    main {{ padding:18px 16px 48px; }}
    .card {{ padding:14px; border-radius:12px; }}
    .card h2 {{ font-size:17px; }}
    h1 {{ font-size:26px; }}
  }}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="badge">{badge}</div>
  <h1>What should I fly today?</h1>
  <div class="sub">{header_sub}</div>
</div></header>
<main><div class="wrap">
  <div class="card call">
    <h2>{rot_heading}</h2>
    <div class="meta">{rot_meta}</div>
    {directions}
    {next_line}
  </div>
  {stock_block}
  {cards}
  {still_block}
  <div class="cta">
    <strong>New account?</strong> {cta_lead}
    Make the account with a referral code and you start with <span class="num">50,000 UEC</span>
    instead of nothing — the code can only be added at signup or in the first 24 hours.<br>
    Every valid code pays the same 50,000 — the only thing it decides is who gets credit for
    referring you. This one belongs to the person who built this page:<br>
    <a href="{ref_url}">{code}</a>
  </div>
</div></main>
<footer><div class="wrap">
  Rental, purchase and pledge figures from the <a href="https://uexcorp.space">UEX Corp</a> community API
  ({generated}) — crowdsourced, so treat prices as a guide, not a promise.
  {footer_note} Not affiliated with CIG.
</div></footer>
</body>
</html>
"""


def crew_label(v):
    s = str(v or "").strip()
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if not nums:
        return None
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return f"{lo} crew"
    return f"{lo}–{hi} crew"


def card(s):
    tags = "".join(f'<span class="tag">{t}</span>' for t in s["roles"])
    bits = []
    crew = crew_label(s["crew"])
    if crew:
        bits.append(crew)
    if s["scu"]:
        bits.append(f"{s['scu']} SCU")
    if s["buy_auec"]:
        bits.append(f'own it for <span class="num">{money(s["buy_auec"])} aUEC</span>')
    elif s["rent_auec"]:
        bits.append(f'rents for {money(s["rent_auec"])} aUEC normally')
    if s["pledge_usd"]:
        bits.append(f'${s["pledge_usd"]} to pledge')
    meta = " · ".join(bits)
    return f"""  <div class="card">
    <h2>{s['name']}</h2>
    <div class="meta">{s['company'] or ''} {('· ' + meta) if meta else ''}</div>
    <div>{tags}</div>
    <p class="verdict">{s['verdict']}</p>
  </div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--now", help="ISO timestamp override (testing)")
    args = ap.parse_args()

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))

    with open(os.path.join(DATA, "iae_2956.json")) as fh:
        sched = json.load(fh)

    vehicles = fetch("vehicles", "/vehicles").get("data") or []
    buys = fetch("vehicles_purchases_prices_all", "/vehicles_purchases_prices_all").get("data") or []
    pledges = fetch("vehicles_prices", "/vehicles_prices").get("data") or []
    rentals = fetch("vehicles_rentals_prices_all", "/vehicles_rentals_prices_all").get("data") or []

    idx = build_index(vehicles, buys, pledges, rentals)
    active, previous = rotation_for(now, sched)
    stock = [s for s in sched["stock_limited"]
             if abs((datetime.fromisoformat(s["date_utc"] + "T00:00:00+00:00") - now).days) <= 2]
    page = render(now, sched, idx, active, previous, stock)

    if args.dry:
        print(json.dumps({k: page[k] for k in
                          ("generated_utc", "active_day", "active_makers",
                           "hours_left", "next_day")}, indent=2))
        print(f"\n{len(page['ships'])} ships in today's rotation")
        for s in page["ships"]:
            print(f"  {s['name']:<26} buy={money(s['buy_auec']):>7}  {s['verdict'][:60]}")
        return

    os.makedirs(SITE, exist_ok=True)
    with open(os.path.join(SITE, "data.json"), "w") as fh:
        json.dump(page, fh, indent=2)

    makers = " + ".join(page["active_makers"]) if page["active_makers"] else "Finale — everything at once"
    if page["finale"]:
        makers = (f"Finale — everything at once. All {page['total_rentable']} hulls are rentable "
                  f"right now; below are the ones worth your 48 hours.")
    if page["off_season"]:
        makers = "IAE is over. These are the hulls worth renting with plain aUEC — same advice, no free fly."
    next_line = ""
    if page["next_day"]:
        next_line = (f'<div class="meta">Tomorrow: {page["next_day"]["makers"][0]} '
                     f'({page["next_day"]["day"]} of 15).</div>')
    stock_block = ""
    if page["stock_limited"]:
        lines = []
        for s in page["stock_limited"]:
            ships = ", ".join(s["ships"])
            lines.append(f"<li>{ships} — waves at {', '.join(s['waves_utc'])} UTC on {s['date_utc']}</li>")
        stock_block = ('<div class="card call"><h2>Stock-limited hulls</h2>'
                       f'<div class="meta">These sell out in waves. Miss one, wait for the next.</div>'
                       f'<ul>{"".join(lines)}</ul></div>')
    cards = "\n".join(card(s) for s in page["ships"])
    still_block = ""
    if page["still_rentable"]:
        items = ", ".join(r["name"] for r in page["still_rentable"])
        still_block = (f'<div class="card"><h2>Still flyable from earlier days</h2>'
                       f'<div class="meta">Rented on the previous rotation — a 48-hour rental '
                       f'outlives the hall, so these should still be in your hangar.</div>'
                       f'<div>{items}</div></div>')

    if page["off_season"]:
        header_sub = ("The expo has ended, but the question doesn't: these are the hulls worth "
                      "your aUEC, with what each one is actually for.")
        badge = "IAE 2956 · wrapped"
        title = "What should I fly? — Star Citizen ship guide"
        rot_meta = "Rentals and purchases are in-game aUEC. Prices move with patches."
        rot_heading = "The shortlist"
        directions = ""
        cta_lead = "Star Citizen is free to try with a free-fly event; the next one usually lands around Luminalia in December."
        footer_note = ""
    else:
        header_sub = ("Free 48-hour rentals at the Tobin Expo Center, and one honest line on each. "
                      f"<strong>{page['hours_left']} hours left</strong> of the free fly.")
        badge = "IAE 2956 · live now"
        title = "What should I fly today? — IAE 2956"
        rot_meta = "Rotation flips at 16:00 UTC. Rentals last 48 hours — grab these before the hall changes."
        rot_heading = f"Today: {makers}"
        directions = ('<div class="meta">Getting there: New Babbage Interstellar Spaceport, then the '
                      'Metroloop to Tobin Expo Center. Rentals are at the Traveler kiosks in the hall '
                      'before the main floor.</div>')
        cta_lead = "Free to play until the 27th, no purchase needed."
        footer_note = "Schedule from RSI's published IAE 2956 rotation."

    html = HTML.format(
        title=title,
        badge=badge,
        header_sub=header_sub,
        rot_heading=rot_heading,
        rot_meta=rot_meta,
        directions=directions,
        cta_lead=cta_lead,
        footer_note=footer_note,
        hours_left=page["hours_left"],
        makers=makers,
        next_line=next_line,
        stock_block=stock_block,
        cards=cards,
        still_block=still_block,
        ref_url=REFERRAL_URL,
        code=REFERRAL_CODE,
        generated=page["generated_utc"],
    )
    with open(os.path.join(SITE, "index.html"), "w") as fh:
        fh.write(html)
    # CNAME is written only once a custom domain is actually pointed at Pages —
    # a stale CNAME file makes GitHub redirect the github.io URL to a dead host.
    if os.environ.get("WSIF_DOMAIN"):
        with open(os.path.join(SITE, "CNAME"), "w") as fh:
            fh.write(os.environ["WSIF_DOMAIN"] + "\n")
    with open(os.path.join(SITE, ".nojekyll"), "w") as fh:
        fh.write("")
    print(f"wrote {SITE}/index.html — day {page['active_day']}, {len(page['ships'])} ships, "
          f"{page['hours_left']}h left")


if __name__ == "__main__":
    sys.exit(main())
