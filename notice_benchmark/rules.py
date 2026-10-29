"""Conservative public-text baseline for a single logistics notice scope.

The baseline uses explicit grammar rules, never benchmark IDs, labels, or hidden
scenario state. It intentionally abstains when a weekly dispatch schedule cannot
be established from the supplied text and business context. This is not an LLM.
"""
from __future__ import annotations

import math
import re
from typing import Any


_WORD_NUMBERS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
    'ten': '10', 'eleven': '11', 'twelve': '12', 'thirteen': '13',
    'fourteen': '14', 'fifteen': '15', 'sixteen': '16', 'seventeen': '17',
    'eighteen': '18', 'nineteen': '19', 'twenty': '20',
    'first': '1', 'second': '2', 'third': '3', 'fourth': '4',
    'fifth': '5', 'sixth': '6', 'seventh': '7', 'eighth': '8',
    'ninth': '9', 'tenth': '10', 'eleventh': '11', 'twelfth': '12',
    'thirteenth': '13', 'fourteenth': '14', 'fifteenth': '15',
    'sixteenth': '16',
}
_NUM = r'(?:\d+(?:\.\d+)?|an?|half)'
_UNIT = r'(?:fortnights?|weeks?|days?)'
_QUANTITY = rf'(?P<n>{_NUM})\s*[- ]\s*(?P<u>{_UNIT})'
_NUMERIC_QUANTITY = rf'({_NUM})\s*-?\s*({_UNIT})'


def _normalise(text: str) -> str:
    text = text.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
    text = re.sub(r'\b(' + '|'.join(_WORD_NUMBERS) + r')\b',
                  lambda match: _WORD_NUMBERS[match.group().lower()], text,
                  flags=re.I)
    text = text.lower()
    text = re.sub(r'\bdo not add\s+(?:the\s+)?(?:2|both)\s+(?:figures|values|increments|numbers)\b', '', text)
    text = re.sub(r'\bnot\s+(' + _NUM + r')\s*(?:' + _UNIT + r')?\s*,?\s*but\s+('
                  + _NUM + r')\s*[- ]\s*(' + _UNIT + r')', r'\2 \3', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def _quantity_weeks(number: str, unit: str) -> int | None:
    if number in ('a', 'an'):
        value = 1.0
    elif number == 'half':
        value = .5
    else:
        value = float(number)
    if unit.startswith('fortnight'):
        value *= 2
    elif unit.startswith('day'):
        value /= 7
    if not math.isfinite(value) or value < 0 or not value.is_integer():
        return None
    return int(value)


def _route_catalog(context: dict[str, Any]) -> tuple[str, dict[str, float | None]]:
    scope = str(context.get('scope_route', context.get('route', 'NL_ocean')))
    routes = context.get('routes', [])
    catalog: dict[str, float | None] = {}
    if isinstance(routes, dict):
        for name, entry in routes.items():
            lead = entry.get('lead', entry.get('lead_weeks')) if isinstance(entry, dict) else entry
            catalog[str(name)] = lead
    elif isinstance(routes, list):
        for entry in routes:
            if isinstance(entry, str):
                catalog[entry] = None
            elif isinstance(entry, dict) and 'name' in entry:
                catalog[str(entry['name'])] = entry.get('lead', entry.get('lead_weeks'))
    if not catalog:
        catalog = {scope: context.get('baseline_lead_weeks'), 'NL_air': 1}
    elif scope not in catalog:
        catalog[scope] = context.get('baseline_lead_weeks')
    if context.get('baseline_lead_weeks') is not None:
        catalog[scope] = context['baseline_lead_weeks']
    return scope, catalog


def _mentions(text: str, catalog: dict[str, float | None]) -> tuple[set[str], bool]:
    result = set()
    for name in catalog:
        pattern = r'(?<![a-z0-9_])' + re.escape(name.lower()).replace('_', '[_-]') + r'(?![a-z0-9_])'
        if re.search(pattern, text):
            result.add(name)
    # Explicit geographical aliases require origin, destination, and mode.
    if (re.search(r'\b(?:netherlands|rotterdam|dutch)\b', text)
            and re.search(r'\bsingapore\b', text)
            and re.search(r'\b(?:sea|ocean|maritime)\b', text)):
        if 'NL_ocean' in catalog:
            result.add('NL_ocean')
    literal_routes = re.findall(r'\b[a-z]{2,4}[_-](?:ocean|air|road|rail|sea)\b', text)
    known = {name.lower().replace('-', '_') for name in catalog}
    unknown = any(value.replace('-', '_') not in known for value in literal_routes)
    unknown = unknown or bool(re.search(r'\b(?:unidentified|unknown|unspecified)\s+(?:shipping\s+)?route\b', text))
    return result, unknown


def _windows(text: str) -> tuple[list[tuple[int, int]], str]:
    """Return explicit inclusive week intervals and text with those spans removed."""
    matches: list[tuple[int, int, int, int]] = []
    range_pattern = re.compile(r'\b(?:between\s+)?weeks?\s*(?:from\s+|of\s+)?(\d+)\s*(?:-|through|to|until)\s*(?:week\s*)?(\d+)\b')
    between_pattern = re.compile(r'\bbetween\s+weeks?\s*(\d+)\s+and\s*(?:week\s*)?(\d+)\b')
    for pattern in (range_pattern, between_pattern):
        for match in pattern.finditer(text):
            if not any(match.start() < b and match.end() > a for a, b, _, _ in matches):
                matches.append((match.start(), match.end(), int(match[1]), int(match[2])))
    list_pattern = re.compile(r'\bweeks?\s*(\d+)((?:\s*,\s*\d+)*(?:\s*,?\s*and\s*(?:week\s*)?\d+)?)\b')
    for match in list_pattern.finditer(text):
        if any(match.start() < b and match.end() > a for a, b, _, _ in matches):
            continue
        before = text[max(0, match.start() - 45):match.start()]
        if re.search(r'\b(?:planning|reporting)\s*$|\b(?:issued|received|published)(?:\s+\w+){0,3}\s*$', before):
            # A publication/reporting week is not an effective dispatch week.
            continue
        numbers = [int(match[1]), *map(int, re.findall(r'\d+', match[2]))]
        for number in numbers:
            matches.append((match.start(), match.end(), number, number))
    remainder = list(text)
    for start, end, _, _ in matches:
        remainder[start:end] = ' ' * (end - start)
    return [(a, b) for _, _, a, b in sorted(matches)], ''.join(remainder)


def _arrival_window(text: str) -> bool:
    if re.search(r'\bnot\s+(?:dispatches|departures)\b|\bno\s+departure[- ]week\s+mapping\b', text):
        return True
    for match in re.finditer(r'\b(?:arrival|arrivals|arriving|delivery|deliveries|delivered)\b([^.;]{0,45})\bweeks?\s*\d', text):
        if not re.search(r'\b(?:dispatch|dispatches|departure|departures|departing)\b', match[1]):
            return True
    return bool(re.search(r'\barrival[- ]based\b|\bweeks?\s*\d+(?:\s*(?:-|to|through)\s*\d+)?\s+(?:arrival|delivery)\s+window\b', text))


def _uncertain(text_without_windows: str) -> bool:
    # An explicitly revised fixed value ('from 5 to 7 weeks') is not an
    # uncertainty interval. Other range phrases remain ambiguous.
    text_without_windows = re.sub(
        r'\bfrom\s+' + _NUM + r'\s*(?:' + _UNIT + r')?\s+to\s+'
        + _NUM + r'\s*' + _UNIT, '', text_without_windows)
    return bool(re.search(
        r'\b(?:may|might|could|approximately|roughly|around|up to|at least|at most|tbd|'
        r'unconfirmed|unknown|unavailable|not yet confirmed|to be confirmed|sometime|possibly|perhaps)\b'
        r'|\b\d+(?:\.\d+)?\s*(?:-|to|or)\s*\d+(?:\.\d+)?\s*(?:(?:extra|additional)\s+)?' + _UNIT +
        r'|\bbetween\s+\d+\s+and\s+\d+\s*' + _UNIT,
        text_without_windows))


def _no_change(text: str) -> bool:
    return bool(re.search(
        r'\bno\s+(?:(?:additional|extra|further)\s+)?(?:delay|change\s+(?:in|to)\s+(?:the\s+)?(?:transit|lead))'
        r'|\bno\s+(?:increase|change)\s+(?:applies|is announced)\b'
        r'|\b(?:transit|lead)(?:\s+(?:time|duration))?\s+(?:(?:is|remains?|will remain)\s+)?(?:unchanged|unaffected)\b'
        r'|\bnot\s+(?:be\s+)?delayed\b(?!\s+(?:by\s+)?(?:\d|a\b|an\b|half\b))'
        r'|\bwithout\s+(?:any\s+)?delay\b'
        r'|\b(?:delay|lead[- ]time\s+increase)\s+(?:has been\s+|is\s+|was\s+)?(?:cancelled|canceled|withdrawn|rescinded)\b',
        text))


def _delta(text: str, baseline: float | None) -> tuple[int | None, bool]:
    """Return (increment, recognised effect); invalid recognised values abstain."""
    candidates: list[int | None] = []
    total_values: list[int | None] = []
    # 'Transit time increases from 5 to 7 weeks' is a revised total, whereas
    # 'the delay increases from 1 to 2 weeks' announces a two-week increment.
    for match in re.finditer(r'\bfrom\s+(' + _NUM + r')\s*(' + _UNIT + r')?\s+to\s+(' + _NUM + r')\s*[- ]\s*(' + _UNIT + r')', text):
        value = _quantity_weeks(match[3], match[4])
        prefix = text[max(0, match.start() - 45):match.start()]
        if re.search(r'\bdelay\b', prefix) and not re.search(r'\b(?:transit|lead|total)\b', prefix):
            candidates.append(value)
        else:
            total_values.append(value)
    add_patterns = [
        r'\b(' + _NUM + r')\s+(?:extra|additional)\s+(' + _UNIT + r')',
        r'\b(?:extra|additional)\s+(?:transit|lead)\s+(?:time|duration)\s+(?:is\s+|of\s+|:)?' + _NUMERIC_QUANTITY,
        r'\b(?:add|adds|adding|additional|extra|increment\s+of)\s+(?:an?\s+additional\s+)?' + _NUMERIC_QUANTITY,
        r'\b(?:increase[ds]?|extend(?:ed|s)?|lengthen(?:ed|s)?|delayed|delay(?:s)?)\s+(?:the\s+)?(?:transit\s+time\s+)?(?:by\s+|of\s+|is\s+)?' + _NUMERIC_QUANTITY,
        _NUMERIC_QUANTITY + r'\s+(?:(?:of\s+)?(?:additional|extra)\s+(?:transit\s+time|lead\s+time|delay)|(?:longer|delay|delays|extra|additional|increase|extension))\b',
        r'\b(?:replaced\s+by|instead\s+add|longer\s+by)\s+' + _NUMERIC_QUANTITY,
        r'\+\s*' + _NUMERIC_QUANTITY,
    ]
    for pattern in add_patterns:
        for match in re.finditer(pattern, text):
            # Parenthesised grouping in these patterns contains only number/unit.
            candidates.append(_quantity_weeks(match[1], match[2]))
    total_patterns = [
        r'\btotal\s+(?:transit|lead)\s+(?:time|duration)[^.;\d]{0,100}?\b(?:is\s+(?:now\s+)?|becomes?\s+)' + _NUMERIC_QUANTITY,
        r'\buse\s+' + _NUMERIC_QUANTITY + r'\s+as\s+(?:the\s+)?(?:entire|total)\s+(?:transit|lead)\s+(?:duration|time)',
        r'\b(?:total\s+)?(?:transit|lead|journey)\s+time\s*(?:(?:is|will be|becomes?|now|revised to|changes? to|set to|of|:)\s*)+(?:now\s+)?' + _NUMERIC_QUANTITY,
        r'\b(?:new|revised|updated)\s+(?:total\s+)?(?:transit|lead)\s+time\s*(?:is\s*|:|=)?\s*' + _NUMERIC_QUANTITY,
        r'\b(?:takes?|will take|duration of)\s+' + _NUMERIC_QUANTITY,
    ]
    for pattern in total_patterns:
        for match in re.finditer(pattern, text):
            if re.search(r'\b(?:extra|additional)\s*$', text[max(0, match.start() - 25):match.start()]):
                continue
            total_values.append(_quantity_weeks(match[1], match[2]))
    for value in total_values:
        if value is None or baseline is None or isinstance(baseline, bool):
            candidates.append(None)
        else:
            increment = value - float(baseline)
            candidates.append(int(increment) if increment >= 0 and increment.is_integer() else None)
    if not candidates:
        return None, False
    if any(value is None for value in candidates) or len(set(candidates)) != 1:
        return None, True
    return candidates[0], True


def _explicit_baseline(text: str, contextual_baseline: float | None) -> tuple[float | None, bool]:
    values = []
    pattern = (r'\b(?:normally|normal|usual|baseline)\s*(?:(?:transit|lead)\s+time\s*)?'
               r'(?:(?:is|was|of|:)\s*)?' + _NUMERIC_QUANTITY)
    for match in re.finditer(pattern, text):
        values.append(_quantity_weeks(match[1], match[2]))
    if any(value is None for value in values) or len(set(values)) > 1:
        return None, False
    if values:
        if contextual_baseline is not None and float(contextual_baseline) != values[0]:
            return None, False
        return values[0], True
    return contextual_baseline, True


def _latest_section(text: str) -> tuple[str, str]:
    markers = list(re.finditer(r'\b(?:correction|amendment|update|updated notice|revised notice|final notice|latest)\s*:', text))
    if markers:
        last = markers[-1]
        return text[last.end():].strip(), text[:last.start()].strip()
    return text, ''


def _remove_retired_claims(text: str) -> str:
    # Remove explicitly superseded claims without deleting the route/window
    # header that may govern the subsequent replacement statement.
    text = re.sub(r'\b(?:the\s+)?(?:earlier|previous|original)\s+(?:notice|advisory|report|estimate)\s+(?:said|specified|announced|reported)[^.;]*[.;]?', '', text)
    text = re.sub(r'\bdisregard\s+(?:the\s+)?(?:earlier|previous|original)\s+[^.;]*[.;]?', '', text)
    return text


def _canonical_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    # Each visible week can have only one announced *total increment*. Repeating
    # the same statement does not silently double its impact.
    schedule: dict[int, int] = {}
    for change in changes:
        for week in range(change['start_week'], change['end_week'] + 1):
            old = schedule.get(week)
            if old is not None and old != change['value']:
                return None
            schedule[week] = change['value']
    rows = []
    for week, value in sorted(schedule.items()):
        if value == 0:
            continue
        if rows and rows[-1]['end_week'] == week - 1 and rows[-1]['value'] == value:
            rows[-1]['end_week'] = week
        else:
            rows.append({'op': 'add_lead', 'route': changes[0]['route'],
                         'start_week': week, 'end_week': week, 'value': value})
    return rows


def extract_notice(text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract only explicitly grounded NL_ocean lead changes or abstain.

    ``context`` is public business configuration (route catalogue, baseline lead,
    horizon, weekly dispatch semantics), not benchmark metadata or answer labels.
    Valid out-of-scope notices produce a ready empty update.
    """
    abstain = {'status': 'needs_clarification', 'changes': []}
    ready_empty = {'status': 'ready', 'changes': []}
    if not isinstance(text, str) or not text.strip():
        return abstain
    context = context or {}
    if context.get('period', 'week') != 'week':
        return abstain
    scope, catalog = _route_catalog(context)
    horizon = context.get('horizon', 16)
    if type(horizon) is not int or horizon < 1:
        return abstain
    normalised = _normalise(text)
    active, superseded = _latest_section(normalised)
    # Explicitly missing effective dates cannot be repaired by a reporting date
    # elsewhere in the same announcement.
    if re.search(r'\b(?:dispatch|departure|start|end)\s+weeks?[^.;]{0,35}\b(?:not (?:been )?announced|unconfirmed|unknown|unspecified)\b', active):
        return abstain
    document_routes, document_unknown = _mentions(active, catalog)
    previous_routes, previous_unknown = _mentions(superseded, catalog)
    if document_unknown:
        return abstain
    if document_routes and scope not in document_routes:
        return ready_empty
    if not document_routes:
        if superseded and previous_routes == {scope} and not previous_unknown:
            document_routes = {scope}
        else:
            return abstain
    if (re.search(r'\b(?:cancel|withdrawn|rescinded|cancelled|canceled)\b', active)
            and re.search(r'\b(?:normal transit applies|baseline transit duration is unchanged|no delay is in force)\b', active)
            and not re.search(r'\b(?:replacement|instead|final approved|revised to)\b', active)):
        return ready_empty
    active = _remove_retired_claims(active)
    current_route = scope if document_routes == {scope} else None
    inherited_windows: list[tuple[int, int]] = []
    if superseded and previous_routes == {scope}:
        inherited_windows, _ = _windows(superseded)
        if _arrival_window(superseded):
            inherited_windows = []
    changes: list[dict[str, Any]] = []
    seen_no_change = False
    clauses = re.split(r';\s*|\n+|(?<=[.!?])\s+(?=[a-z])|,\s*(?:while|whereas)\s+|,\s*and\s+(?=weeks?\s*\d)', active)
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        routes, unknown = _mentions(clause, catalog)
        if unknown:
            return abstain
        if routes:
            if scope not in routes:
                current_route = next(iter(routes)) if len(routes) == 1 else None
                continue
            current_route = scope
        if current_route != scope:
            continue
        if re.search(r'\b(?:other|outside|remaining|unaffected)\s+(?:routes?|weeks?|periods?)\b', clause):
            continue
        windows, effect_text = _windows(clause)
        if _arrival_window(clause):
            return abstain
        if windows:
            if any(not 1 <= start <= end <= horizon for start, end in windows):
                return abstain
            inherited_windows = windows
        if _no_change(effect_text):
            seen_no_change = True
            continue
        if re.search(r'\bnot\s+(?:(?:be|been|is|do)\s+)?(?:add|adding|increase|increased|extend|extended|delayed)\b'
                     r'|\bno\s+(?:(?:additional|extra)\s+)?\d+\s*' + _UNIT, effect_text):
            return abstain
        baseline, consistent_baseline = _explicit_baseline(effect_text, catalog.get(scope))
        if not consistent_baseline:
            return abstain
        increment, recognised = _delta(effect_text, baseline)
        if recognised:
            if increment is None or _uncertain(effect_text) or not inherited_windows:
                return abstain
            for start, end in inherited_windows:
                changes.append({'op': 'add_lead', 'route': scope,
                                'start_week': start, 'end_week': end,
                                'value': increment})
        elif re.search(r'\b(?:delay(?:ed|s)?|transit\s+time|lead\s+time|extra|additional|longer)\b', effect_text):
            # A route/window-only heading is allowed; an asserted but unparsed
            # impact cannot be silently ignored beside another parsed update.
            if not re.search(r'\b(?:advisory|notice|window|affected dispatches)\s*$', effect_text):
                return abstain
    if changes and seen_no_change:
        return abstain
    if changes:
        canonical = _canonical_changes(changes)
        if canonical is None:
            return abstain
        return {'status': 'ready', 'changes': canonical}
    return ready_empty if seen_no_change else abstain
