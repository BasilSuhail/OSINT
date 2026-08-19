# Validator — local-LLM claim extraction (WS-G step 1)

This run: 2664 stories in window, 6 extracted, 0 already done, 0 failed.

Latest extractions:

| countries | event type | casualties | story |
|---|---|---|---|
| IT | none | — | Venice art installation grapples with its Jewish history at 61st International Art Exhibition |
| — | none | — | What to watch this week: Larry David's new HBO comedy, talking sheep, and Kim Novak |
| — | none | — | After 50-years of Jewish outreach, pioneering American Rabbi Ephraim Buchwald steps down |
| IR US | none | — | Countries must reject Iran efforts to control Hormuz, UN agency document says |
| IL EG | none | — | Israeli, Egyptian senior officers discuss Gaza in Cairo meeting - report |
| UA MC | none | 1 | Ukraine wants joint investigation in Monaco bomb case after suspect found dead, top prosecutor says |
| IL | none | — | Natural Intelligence marketing firm wins Dun award for advancing women in Israeli high-tech sector |
| US | none | — | As U.S. turns 250, retired judges hit the road to defend judicial independence |
| — | none | — | Scientists identify nearby 'super-Earth' as promising candidate in search for alien life - study |
| IN | none | — | Andhra Pradesh police being misused to target critics, alleges YSRCP’s Lakshmi Parvathi |
| IN | none | — | UDF members to head Syndicate panels in Calicut University |
| IN | none | — | Delhi HC seeks Centre’s stand on Ambassador Hotel’s plea against show-cause notice for eviction |
| IN | none | — | Sliding rupee value comes as a blessing for Telangana’s Musi project |
| IR US | none | — | Push for diplomacy  continues even as strikes in Iran, Hormuz intensify, US official says |
| ZA | none | — | Broos confirms he’s not staying as Bafana coach |
| ZA | none | — | LIVE | Madlanga Commission of Inquiry Day 137 | Friday, 10 July 2026 |
| IN | none | — | Abolish adjustment charges, roll back smart meters: CPI(M) to Andhra Pradesh govt |
| GB | none | — | SIR: Residents flag purple stickers pasted despite no enumeration forms being distributed |
| IN GB | none | — | India lays out tariffs and quotas for U.K. vehicles under trade deal |
| IN | none | — | ‘When will ED freeze temple funds?' Derek O'Brien questions TMC accounts freeze |
| IN | none | — | ₹200 crore sanctioned for tap water to every home in Machilipatnam: Kollu Ravindra |
| TR | none | — | E20 costlier to produce than pure petrol: Government |
| IN | none | — | Karnataka CM inaugurates Syed Mohammad Gesu Daraz Research Academy at Khwaja Banda Nawaz Dargah |
| IN | none | — | Calcutta High Court allows Trinamool to operate frozen accounts under judicial watch |
| IN | none | — | SIR: Anomalies and unmapped voters could land 30% forms for scrutiny in Telangana |

The model is *another noisy annotator*, never a judge: rows carry model + prompt version, and nothing downstream consumes them until agreement with the human-checked sample (`make validator-audit`) is measured and published.
