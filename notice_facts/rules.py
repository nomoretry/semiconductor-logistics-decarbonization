"""Frozen transparent grammar baseline; no source IDs, URLs or label lookup."""
import re

WORDS={"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"fourteen":14}
NUMBER=r"(?:\d[\d,]*(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|fourteen)"
PATTERN=re.compile(rf"(?P<a>{NUMBER})(?:\s*(?:-|–|to)\s*(?P<b>{NUMBER}))?\s*-?\s*(?P<unit>days?|weeks?|hours?|miles?)\b",re.I)


def number(s):
    return WORDS[s.lower()] if s.lower() in WORDS else float(s.replace(",",""))


def extract(text):
    lower=text.lower()
    if not re.search(r"transit|voyage|journey|delay|sailing|transport|shipment",lower):return {"facts":[]}
    facts=[]
    for match in PATTERN.finditer(text):
        low=number(match["a"]);high=number(match["b"]) if match["b"] else low
        unit=match["unit"].lower().rstrip("s")
        if unit=="mile":metric="additional_distance"
        elif re.search(r"improv|shorten|reduc",lower):metric="transit_reduction"
        elif re.search(r"add|extra|longer|extend",lower):metric="journey_extension"
        elif "delay" in lower:metric="delay"
        else:metric="transit_time"
        qualifier=("target" if re.search(r"\baim\b|\btarget",lower) else "average" if "average" in lower
                   else "approximate" if re.search(r"approx|around|about|estimated",lower)
                   else "range" if low!=high else "stated")
        fact={"metric":metric,"low":low,"high":high,"unit":unit,"qualifier":qualifier,"evidence":text}
        if fact not in facts:facts.append(fact)
    return {"facts":facts}
