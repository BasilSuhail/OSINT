"""CAMEO event-code filter + FIPS → ISO 3166-1 alpha-2 mapping.

Pure data tables used by `gdelt_fetcher`. Kept separate so they can be unit
tested in isolation and so adding countries does not invite changes to the
HTTP-handling fetcher module.
"""

from __future__ import annotations

#: CAMEO root codes treated as conflict-relevant for the composite stress
#: index. The CAMEO 2.0 codebook (Schrodt) groups events into 20 root codes;
#: 01-13 are cooperative behaviour (consult, appeal, aid, etc.) and 14-20 are
#: escalatory. Only the escalatory codes feed the composite.
CAMEO_CONFLICT_ROOT_CODES: frozenset[int] = frozenset(
    {
        14,  # PROTEST
        15,  # EXHIBIT FORCE POSTURE
        16,  # REDUCE RELATIONS
        17,  # COERCE
        18,  # ASSAULT
        19,  # FIGHT
        20,  # USE UNCONVENTIONAL MASS VIOLENCE
    }
)

#: CAMEO root code → a short human label, from the CAMEO 2.0 codebook's
#: twenty root categories (Schrodt). GDELT's event export carries no
#: headline — it is a structured record of actor, action and place — so
#: without this a dot on the map renders as the literal string "gdelt"
#: and tells the reader nothing (#733).
#:
#: All twenty are here, not just the conflict subset the composite keeps,
#: so the label stays correct if the ingest filter is ever widened.
CAMEO_ROOT_LABELS: dict[int, str] = {
    1: "Public statement",
    2: "Appeal",
    3: "Express intent to cooperate",
    4: "Consult",
    5: "Diplomatic cooperation",
    6: "Material cooperation",
    7: "Provide aid",
    8: "Yield",
    9: "Investigate",
    10: "Demand",
    11: "Disapprove",
    12: "Reject",
    13: "Threaten",
    14: "Protest",
    15: "Exhibit force posture",
    16: "Reduce relations",
    17: "Coerce",
    18: "Assault",
    19: "Fight",
    20: "Mass violence",
}


def cameo_root_label(event_root_code: str | int | None) -> str | None:
    """Short human label for a CAMEO root code, or None if unrecognised.

    Returning None rather than a placeholder keeps the caller honest: a
    row whose code we cannot read should not claim to describe an action.
    """
    if event_root_code is None:
        return None
    try:
        code = int(str(event_root_code).strip())
    except (TypeError, ValueError):
        return None
    return CAMEO_ROOT_LABELS.get(code)


#: FIPS 10-4 country code → ISO 3166-1 alpha-2 code. GDELT v2 reports the
#: action-country in the legacy FIPS notation; the composite worker and the
#: events table speak ISO. This table covers the panel countries plus the
#: most frequently observed conflict-context countries. Missing FIPS codes
#: cause the event to be tagged with country=None.
FIPS_TO_ISO: dict[str, str] = {
    "AF": "AF",  # Afghanistan
    "AG": "DZ",  # Algeria
    "AL": "AL",  # Albania
    "AR": "AR",  # Argentina
    "AS": "AU",  # Australia
    "AU": "AT",  # Austria
    "BA": "BH",  # Bahrain
    "BE": "BE",  # Belgium
    "BG": "BD",  # Bangladesh
    "BL": "BO",  # Bolivia
    "BO": "BY",  # Belarus
    "BR": "BR",  # Brazil
    "BU": "BG",  # Bulgaria
    "CA": "CA",  # Canada
    "CB": "KH",  # Cambodia
    "CG": "CD",  # Democratic Republic of the Congo
    "CH": "CN",  # China
    "CI": "CL",  # Chile
    "CO": "CO",  # Colombia
    "CU": "CU",  # Cuba
    "CY": "CY",  # Cyprus
    "DA": "DK",  # Denmark
    "DR": "DO",  # Dominican Republic
    "EC": "EC",  # Ecuador
    "EG": "EG",  # Egypt
    "EN": "EE",  # Estonia
    "ER": "ER",  # Eritrea
    "ES": "SV",  # El Salvador
    "ET": "ET",  # Ethiopia
    "EZ": "CZ",  # Czechia
    "FI": "FI",  # Finland
    "FR": "FR",  # France
    "GG": "GE",  # Georgia
    "GM": "DE",  # Germany
    "GR": "GR",  # Greece
    "HK": "HK",  # Hong Kong
    "HO": "HN",  # Honduras
    "HR": "HR",  # Croatia
    "HU": "HU",  # Hungary
    "IC": "IS",  # Iceland
    "ID": "ID",  # Indonesia
    "IN": "IN",  # India
    "IR": "IR",  # Iran
    "IS": "IL",  # Israel
    "IT": "IT",  # Italy
    "IV": "CI",  # Ivory Coast
    "IZ": "IQ",  # Iraq
    "JA": "JP",  # Japan
    "JO": "JO",  # Jordan
    "KE": "KE",  # Kenya
    "KS": "KR",  # South Korea
    "KU": "KW",  # Kuwait
    "KZ": "KZ",  # Kazakhstan
    "LE": "LB",  # Lebanon
    "LH": "LT",  # Lithuania
    "LU": "LU",  # Luxembourg
    "LY": "LY",  # Libya
    "MA": "MG",  # Madagascar
    "MO": "MA",  # Morocco
    "MX": "MX",  # Mexico
    "MY": "MY",  # Malaysia
    "NG": "NE",  # Niger
    "NI": "NG",  # Nigeria
    "NL": "NL",  # Netherlands
    "NO": "NO",  # Norway
    "NP": "NP",  # Nepal
    "NU": "NI",  # Nicaragua
    "NZ": "NZ",  # New Zealand
    "PE": "PE",  # Peru
    "PK": "PK",  # Pakistan
    "PL": "PL",  # Poland
    "PM": "PA",  # Panama
    "PO": "PT",  # Portugal
    "RO": "RO",  # Romania
    "RP": "PH",  # Philippines
    "RS": "RU",  # Russia
    "SA": "SA",  # Saudi Arabia
    "SF": "ZA",  # South Africa
    "SN": "SG",  # Singapore
    "SP": "ES",  # Spain
    "SU": "SD",  # Sudan
    "SY": "SY",  # Syria
    "SZ": "CH",  # Switzerland
    "TH": "TH",  # Thailand
    "TS": "TN",  # Tunisia
    "TU": "TR",  # Turkey
    "TW": "TW",  # Taiwan
    "UK": "GB",  # United Kingdom
    "UP": "UA",  # Ukraine
    "US": "US",  # United States
    "UV": "BF",  # Burkina Faso
    "VE": "VE",  # Venezuela
    "VM": "VN",  # Vietnam
    "WI": "EH",  # Western Sahara
    "YM": "YE",  # Yemen
    "ZI": "ZW",  # Zimbabwe
}


def fips_to_iso(fips: str | None) -> str | None:
    """Translate a FIPS country code to ISO 3166-1 alpha-2.

    Returns None when the input is empty or the FIPS code is not in the table.
    """
    if not fips:
        return None
    return FIPS_TO_ISO.get(fips.upper())


def is_conflict_event(event_root_code: str | int | None) -> bool:
    """Whether the CAMEO root code falls into the conflict-relevant bucket."""
    if event_root_code is None:
        return False
    try:
        code = int(event_root_code)
    except (TypeError, ValueError):
        return False
    return code in CAMEO_CONFLICT_ROOT_CODES
