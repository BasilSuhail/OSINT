"""FIPS 10-4 → ISO 3166-1 alpha-2 country code mapping.

GDELT's ActionGeo_CountryCode column speaks FIPS 10-4, the panel speaks ISO2.
The two alphabets overlap treacherously (FIPS GM is Germany, FIPS GA is
Gambia, FIPS CH is China...), so this table is explicit and exhaustive rather
than clever. Codes with no ISO2 home (oceans, disputed rocks) are simply
absent; callers should count unmapped codes for provenance rather than guess.
"""

from __future__ import annotations

#: FIPS 10-4 → ISO 3166-1 alpha-2. Kosovo maps to the XK user-assigned code,
#: Gaza Strip and West Bank both fold into PS (Palestine) to match the panel.
FIPS_TO_ISO2: dict[str, str] = {
    "AA": "AW",  # Aruba
    "AC": "AG",  # Antigua and Barbuda
    "AE": "AE",  # United Arab Emirates
    "AF": "AF",  # Afghanistan
    "AG": "DZ",  # Algeria
    "AJ": "AZ",  # Azerbaijan
    "AL": "AL",  # Albania
    "AM": "AM",  # Armenia
    "AN": "AD",  # Andorra
    "AO": "AO",  # Angola
    "AQ": "AS",  # American Samoa
    "AR": "AR",  # Argentina
    "AS": "AU",  # Australia
    "AU": "AT",  # Austria
    "AV": "AI",  # Anguilla
    "AY": "AQ",  # Antarctica
    "BA": "BH",  # Bahrain
    "BB": "BB",  # Barbados
    "BC": "BW",  # Botswana
    "BD": "BM",  # Bermuda
    "BE": "BE",  # Belgium
    "BF": "BS",  # Bahamas
    "BG": "BD",  # Bangladesh
    "BH": "BZ",  # Belize
    "BK": "BA",  # Bosnia and Herzegovina
    "BL": "BO",  # Bolivia
    "BM": "MM",  # Myanmar (Burma)
    "BN": "BJ",  # Benin
    "BO": "BY",  # Belarus
    "BP": "SB",  # Solomon Islands
    "BR": "BR",  # Brazil
    "BT": "BT",  # Bhutan
    "BU": "BG",  # Bulgaria
    "BX": "BN",  # Brunei
    "BY": "BI",  # Burundi
    "CA": "CA",  # Canada
    "CB": "KH",  # Cambodia
    "CD": "TD",  # Chad
    "CE": "LK",  # Sri Lanka
    "CF": "CG",  # Congo (Brazzaville)
    "CG": "CD",  # Congo (Kinshasa, DRC)
    "CH": "CN",  # China
    "CI": "CL",  # Chile
    "CJ": "KY",  # Cayman Islands
    "CK": "CC",  # Cocos (Keeling) Islands
    "CM": "CM",  # Cameroon
    "CN": "KM",  # Comoros
    "CO": "CO",  # Colombia
    "CQ": "MP",  # Northern Mariana Islands
    "CS": "CR",  # Costa Rica
    "CT": "CF",  # Central African Republic
    "CU": "CU",  # Cuba
    "CV": "CV",  # Cape Verde
    "CW": "CK",  # Cook Islands
    "CY": "CY",  # Cyprus
    "DA": "DK",  # Denmark
    "DJ": "DJ",  # Djibouti
    "DO": "DM",  # Dominica
    "DR": "DO",  # Dominican Republic
    "EC": "EC",  # Ecuador
    "EG": "EG",  # Egypt
    "EI": "IE",  # Ireland
    "EK": "GQ",  # Equatorial Guinea
    "EN": "EE",  # Estonia
    "ER": "ER",  # Eritrea
    "ES": "SV",  # El Salvador
    "ET": "ET",  # Ethiopia
    "EZ": "CZ",  # Czechia
    "FI": "FI",  # Finland
    "FJ": "FJ",  # Fiji
    "FK": "FK",  # Falkland Islands
    "FM": "FM",  # Micronesia
    "FO": "FO",  # Faroe Islands
    "FP": "PF",  # French Polynesia
    "FR": "FR",  # France
    "GA": "GM",  # Gambia
    "GB": "GA",  # Gabon
    "GG": "GE",  # Georgia
    "GH": "GH",  # Ghana
    "GI": "GI",  # Gibraltar
    "GJ": "GD",  # Grenada
    "GK": "GG",  # Guernsey
    "GL": "GL",  # Greenland
    "GM": "DE",  # Germany
    "GP": "GP",  # Guadeloupe
    "GQ": "GU",  # Guam
    "GR": "GR",  # Greece
    "GT": "GT",  # Guatemala
    "GV": "GN",  # Guinea
    "GY": "GY",  # Guyana
    "GZ": "PS",  # Gaza Strip → Palestine
    "HA": "HT",  # Haiti
    "HK": "HK",  # Hong Kong
    "HO": "HN",  # Honduras
    "HR": "HR",  # Croatia
    "HU": "HU",  # Hungary
    "IC": "IS",  # Iceland
    "ID": "ID",  # Indonesia
    "IM": "IM",  # Isle of Man
    "IN": "IN",  # India
    "IO": "IO",  # British Indian Ocean Territory
    "IR": "IR",  # Iran
    "IS": "IL",  # Israel
    "IT": "IT",  # Italy
    "IV": "CI",  # Cote d'Ivoire
    "IZ": "IQ",  # Iraq
    "JA": "JP",  # Japan
    "JE": "JE",  # Jersey
    "JM": "JM",  # Jamaica
    "JO": "JO",  # Jordan
    "KE": "KE",  # Kenya
    "KG": "KG",  # Kyrgyzstan
    "KN": "KP",  # North Korea
    "KR": "KI",  # Kiribati
    "KS": "KR",  # South Korea
    "KT": "CX",  # Christmas Island
    "KU": "KW",  # Kuwait
    "KV": "XK",  # Kosovo (user-assigned ISO2)
    "KZ": "KZ",  # Kazakhstan
    "LA": "LA",  # Laos
    "LE": "LB",  # Lebanon
    "LG": "LV",  # Latvia
    "LH": "LT",  # Lithuania
    "LI": "LR",  # Liberia
    "LO": "SK",  # Slovakia
    "LS": "LI",  # Liechtenstein
    "LT": "LS",  # Lesotho
    "LU": "LU",  # Luxembourg
    "LY": "LY",  # Libya
    "MA": "MG",  # Madagascar
    "MB": "MQ",  # Martinique
    "MC": "MO",  # Macau
    "MD": "MD",  # Moldova
    "MF": "YT",  # Mayotte
    "MG": "MN",  # Mongolia
    "MH": "MS",  # Montserrat
    "MI": "MW",  # Malawi
    "MJ": "ME",  # Montenegro
    "MK": "MK",  # North Macedonia
    "ML": "ML",  # Mali
    "MN": "MC",  # Monaco
    "MO": "MA",  # Morocco
    "MP": "MU",  # Mauritius
    "MR": "MR",  # Mauritania
    "MT": "MT",  # Malta
    "MU": "OM",  # Oman
    "MV": "MV",  # Maldives
    "MX": "MX",  # Mexico
    "MY": "MY",  # Malaysia
    "MZ": "MZ",  # Mozambique
    "NC": "NC",  # New Caledonia
    "NE": "NU",  # Niue
    "NF": "NF",  # Norfolk Island
    "NG": "NE",  # Niger
    "NH": "VU",  # Vanuatu
    "NI": "NG",  # Nigeria
    "NL": "NL",  # Netherlands
    "NO": "NO",  # Norway
    "NP": "NP",  # Nepal
    "NR": "NR",  # Nauru
    "NS": "SR",  # Suriname
    "NU": "NI",  # Nicaragua
    "NZ": "NZ",  # New Zealand
    "PA": "PY",  # Paraguay
    "PC": "PN",  # Pitcairn Islands
    "PE": "PE",  # Peru
    "PK": "PK",  # Pakistan
    "PL": "PL",  # Poland
    "PM": "PA",  # Panama
    "PO": "PT",  # Portugal
    "PP": "PG",  # Papua New Guinea
    "PS": "PW",  # Palau
    "PU": "GW",  # Guinea-Bissau
    "QA": "QA",  # Qatar
    "RE": "RE",  # Reunion
    "RI": "RS",  # Serbia
    "RM": "MH",  # Marshall Islands
    "RN": "MF",  # Saint Martin
    "RO": "RO",  # Romania
    "RP": "PH",  # Philippines
    "RQ": "PR",  # Puerto Rico
    "RS": "RU",  # Russia
    "RW": "RW",  # Rwanda
    "SA": "SA",  # Saudi Arabia
    "SB": "PM",  # Saint Pierre and Miquelon
    "SC": "KN",  # Saint Kitts and Nevis
    "SE": "SC",  # Seychelles
    "SF": "ZA",  # South Africa
    "SG": "SN",  # Senegal
    "SH": "SH",  # Saint Helena
    "SI": "SI",  # Slovenia
    "SL": "SL",  # Sierra Leone
    "SM": "SM",  # San Marino
    "SN": "SG",  # Singapore
    "SO": "SO",  # Somalia
    "SP": "ES",  # Spain
    "ST": "LC",  # Saint Lucia
    "SU": "SD",  # Sudan
    "SV": "SJ",  # Svalbard
    "SW": "SE",  # Sweden
    "SX": "GS",  # South Georgia
    "SY": "SY",  # Syria
    "SZ": "CH",  # Switzerland
    "TB": "BL",  # Saint Barthelemy
    "TD": "TT",  # Trinidad and Tobago
    "TH": "TH",  # Thailand
    "TI": "TJ",  # Tajikistan
    "TK": "TC",  # Turks and Caicos Islands
    "TL": "TK",  # Tokelau
    "TN": "TO",  # Tonga
    "TO": "TG",  # Togo
    "TP": "ST",  # Sao Tome and Principe
    "TS": "TN",  # Tunisia
    "TT": "TL",  # Timor-Leste
    "TU": "TR",  # Turkey
    "TV": "TV",  # Tuvalu
    "TW": "TW",  # Taiwan
    "TX": "TM",  # Turkmenistan
    "TZ": "TZ",  # Tanzania
    "UG": "UG",  # Uganda
    "UK": "GB",  # United Kingdom
    "UP": "UA",  # Ukraine
    "US": "US",  # United States
    "UV": "BF",  # Burkina Faso
    "UY": "UY",  # Uruguay
    "UZ": "UZ",  # Uzbekistan
    "VC": "VC",  # Saint Vincent and the Grenadines
    "VE": "VE",  # Venezuela
    "VI": "VG",  # British Virgin Islands
    "VM": "VN",  # Vietnam
    "VQ": "VI",  # US Virgin Islands
    "WA": "NA",  # Namibia
    "WE": "PS",  # West Bank → Palestine
    "WF": "WF",  # Wallis and Futuna
    "WI": "EH",  # Western Sahara
    "WS": "WS",  # Samoa
    "WZ": "SZ",  # Eswatini (Swaziland)
    "YM": "YE",  # Yemen
    "ZA": "ZM",  # Zambia
    "ZI": "ZW",  # Zimbabwe
}
