# News severity human-check sheet — news-llm-v1

Generated 2026-07-22 · seed 591 · 50 rows.

## The scale

- `routine` 0.00 to 0.20 — policy, business, sport — nothing happened to anyone
- `tension` 0.20 to 0.40 — protest, strike, diplomatic rupture — no violence
- `violence` 0.40 to 0.60 — violence without confirmed death, or mass displacement
- `grave` 0.60 to 0.80 — confirmed deaths (1-9), or serious armed attack
- `mass_casualty` 0.80 to 1.00 — 10+ dead, massacre, mass-fatality disaster

## How to fill this in

For each row, judge the **headline**, not the model's answer.

- **human band** — which band the headline belongs in. This is the column that matters; fill it for every row.
- **human severity** — optional. Only if you want to disagree on the number within a band.
- **rationale ok** — `ok` if the stated reason is true and blunt, `no` if it is wrong, softened, or cites something the headline does not say.

Leave a row entirely blank to skip it. Blank rows are not counted as agreement — they are dropped.

| headline | model severity | model band | model rationale | human severity | human band | rationale ok |
|---|---|---|---|---|---|---|
| Russian scientists developing about 25 systems for ITER installation — minister | 0.0 | routine | No harm occurred; scientists are developing systems for a nuclear fusion project. |  | routine | ok |
| 100 years on, Paris mosque remains a symbol of diversity | 0.0 | routine | No violence or harm occurred. |  | routine | ok |
| This Japanese Workshop Builds Racing Engines By Hand | 0.0 | routine | No harm occurred; this is a business activity. |  | routine | ok |
| The Queensland government promised to put victims first. But it has buried a report from domestic violence survivors | 0.0 | routine | No violence or deaths occurred, only a political decision to withhold information. | 0.15 | routine | ok |
| Man Builds 3rd-Gen Yenko Camaro With 1,150 HP And Japanese Wide Body Kit | 0.0 | routine | A car was modified with high horsepower and a body kit. |  | routine | ok |
| SOP framed for identifying, initiating action against unauthorised institutions in health sector | 0.0 | routine | No violence or deaths occurred; this is a policy framework. |  | routine | ok |
| Many Christian voters in the US see Trump as ‘chosen’ by God to lead | 0.0 | routine | No violence or harm occurred, only a political opinion. |  | routine | ok |
| Water Plants Under Fire in the Gulf Are Crucial to Civilians | 0.0 | routine | No violence or casualties occurred. | 0.45 | violence | no |
| (LEAD) N. Korea's premier to visit China to mark 65th anniv. of signing of friendship treaty: KCNA | 0.0 | routine | A diplomatic visit occurred with no violence or casualties. |  | routine | ok |
| Sumenep expands tourism villages to support local economy | 0.0 | routine | No harm occurred; this is a routine economic development initiative. |  | routine | ok |
| US Launches Attacks on Iran for Sixth Consecutive Night | 0.8 | mass_casualty | The headline indicates a confirmed armed attack with implied fatalities exceeding the 10+ threshold. | 0.70 | grave | no |
| MOEX Index drops below 2,100 points for first time since Dec 2022 — trading data | 0.0 | routine | A financial market decline occurred with no violence or casualties. |  | routine | ok |
| US attacks Iran for 11th consecutive night | 0.8 | mass_casualty | The headline indicates a confirmed armed attack with no specific death toll provided. | 0.72 | grave | no |
| Fact check: Viral video does not show Iranian Navy destroying ship in Strait of Hormuz amid renewed hostilities | 0.0 | routine | The headline explicitly states that no ship was destroyed and no hostilities occurred. | 0.10 | routine | no |
| Guelaguetza, Oaxaca’s world renowned ethnic festival, gets underway | 0.0 | routine | A cultural festival began without any reported harm or violence. |  | routine | ok |
| The week in pictures: The end of the World Cup, heatwaves and wildfires, war in Ukraine | 0.0 | routine | The headline lists unrelated events including a sports conclusion, weather, and a war, but provides no specific details confirming casualties or violence. | 0.15 | routine | ok |
| Canada gives share of bridge profits to US to get Trump nod | 0.0 | routine | No violence or deaths occurred; this is a financial policy agreement. |  | routine | ok |
| After brief burst of rain, monsoon in dry phase, deficit rises to 18% | 0.0 | routine | No people were harmed in this weather event. |  | routine | ok |
| Who is who in UK PM Andy Burnham's new cabinet | 0.0 | routine | No violence or harm occurred; this is a routine political announcement about cabinet appointments. |  | routine | ok |
| World Cup 2026: England hold on against Mexico while Norway oust Brazil | 0.0 | routine | No violence or deaths occurred in this sports match. |  | routine | ok |
| Out of space, Vietnam's most populous city to stack cars, motorbikes into automated towers | 0.0 | routine | No harm occurred; this is a logistical project to manage traffic. |  | routine | ok |
| Prince William makes decision on attending Harry's Invictus Games event | 0.0 | routine | No violence or harm occurred, only a political decision regarding attendance. |  | routine | no |
| Powerful storm engulfs Istanbul, reducing visibility | 0.0 | routine | No deaths or violence occurred, only weather conditions. |  | routine | ok |
| Blake Lively attends 2026 FIFA World Cup after Taylor Swift wedding ditch | 0.0 | routine | Celebrities attended a sports event following a wedding announcement. |  | routine | no |
| Tariff hike: Brazil leads fight against forced labor despite US claims | 0.0 | routine | No violence or deaths occurred; this is a policy dispute regarding labor practices. |  | routine | ok |
| Russia’s Lis interceptor unit destroys 37 Ukrainian UAVs overnight | 0.45 | violence | Ukrainian drones were destroyed without any confirmed deaths or casualties. |  | violence | ok |
| Kuwait says Iranian attacks damaged vital facilities | 0.45 | violence | Iranian attacks damaged vital facilities in Kuwait without confirmed deaths. | 0.55 | violence | ok |
| Ukraine to get new prime minister amid major government reshuffle | 0.0 | routine | A government reshuffle involves administrative changes and does not involve violence or deaths. |  | routine | ok |
| The US mounts pressure across 3 maritime flashpoints. How should China respond? | 0.2 | tension | Diplomatic pressure and military positioning occurred without confirmed violence or casualties. |  | tension | ok |
| The great political masquerade in Kenya | 0.0 | routine | No specific violent event or casualties are mentioned in the headline. |  | routine | ok |
| ‘Five Star Chef' winner Dom Taylor dies at 44 | 0.6 | grave | One person was killed. | 0.60 | grave | no |
| V-C running varsity unilaterally, allege Kannur University Syndicate members | 0.0 | routine | No violence or deaths occurred in this administrative dispute. |  | routine | ok |
| Hungary opens investigation into former FM Szijjarto's Russia ties | 0.0 | routine | No violence or deaths occurred; only an investigation was opened. |  | routine | ok |
| Owner of Michelin-starred restaurant in South Korea faces jail for ant-topped sorbet | 0.0 | routine | No violence or harm occurred. |  | routine | ok |
| UK man charged with murder of right-wing ex-MP Ann Widdecombe | 0.6 | grave | One person was charged with murder, but no deaths have been confirmed. | 0.70 | grave | no |
| Prince William finds a cause for celebration as Harry pushes Invictus forward | 0.0 | routine | No violence or harm occurred, only a sports event and a public statement. |  | routine | no |
| Russian drivers face petrol shortages after Ukrainian strikes on Russian energy infrastructure | 0.6 | grave | Ukrainian strikes on Russian energy infrastructure caused petrol shortages for Russian drivers. | 0.45 | violence | no |
| Engineers building Solar panels are using exact replicas of honeycombs made by Bees to ensure ... | 0.0 | routine | No harm occurred; this is a routine engineering project. |  | routine | ok |
| Aamir Khan's parenting advice every Indian parent should hear | 0.0 | routine | No harm occurred; this is a parenting advice article. |  | routine | ok |
| EU Commission objects to France's planned social media ban | 0.0 | routine | A policy dispute occurred with no violence or deaths. |  | routine | ok |
| The African fishermen who blame Chinese trawlers for their woes | 0.2 | tension | Fishermen blamed Chinese trawlers for their economic woes without any confirmed violence or deaths. |  | tension | ok |
| Trump says US will give Patriot missile licence to Ukraine | 0.0 | routine | A policy announcement regarding military equipment licensing. | 0.20 | tension | ok |
| China’s imports from Africa surge after Beijing expands zero-tariff policy | 0.0 | routine | No violence or harm occurred; this is a trade policy update. |  | routine | ok |
| Northern Ireland's deputy first minster was 'floored' by news of Donaldson arrest | 0.0 | routine | No violence or harm occurred; this is a political news report about an arrest. |  | routine | ok |
| Taylor defends Sarah Henderson’s triple-zero calls as SA police investigate claimed Telstra-outage death | 0.6 | grave | One person was killed in a Telstra outage. | 0.35 | tension | no |
| ‘Groundless’: China dismisses Japanese protest over live-fire drill within Okinotori EEZ | 0.25 | tension | A diplomatic dispute occurred with no confirmed violence or deaths. |  | tension | ok |
| US dollar hits record high in Iran as rial weakens amid renewed regional conflict | 0.0 | routine | No violence or deaths occurred; this is a financial market event. |  | routine | ok |
| March to Parliament: Protesters’ anger extends beyond paper leaks | 0.25 | tension | Protesters expressed anger over paper leaks without confirmed violence or deaths. |  | tension | ok |
| One hotel ordered to shut, two eateries fined in food safety inspection in Ernakulam | 0.0 | routine | No violence or deaths occurred, only administrative penalties for food safety violations. |  | routine | ok |
| Battle of bigwigs in Ol Kalou polls | 0.25 | tension | Political infighting occurred without confirmed violence or casualties. | 0.15 | routine | ok |

## Auditor notes

Filled by hand, one pass, headline-only. Where the number inside a band looked fine I left `human severity` blank rather than restating the model's figure.

Recurring failures worth naming:

- **Fatalities invented to justify a band.** Both Iran strike rows are scored `mass_casualty` off a rationale that either admits no death toll exists or says one is "implied". A multi-night state bombing campaign is a serious armed attack, so `grave` is defensible — `mass_casualty` is not, because nothing in the headline counts bodies.
- **"Under fire" read as no violence.** The Gulf water-plant row is scored 0.0 on the claim that no violence occurred, in a headline whose subject is infrastructure being shot at.
- **Death confirmed vs death claimed.** The Telstra row is graded as a confirmed killing; the headline says police are investigating a *claimed* death. The Widdecombe row is the mirror image — scored `grave`, but the rationale asserts no death is confirmed while the headline reports a murder charge. Right band, wrong reason, so it is not evidence the model understood anything.
- **Consequence restated instead of a reason.** The petrol-shortage row justifies `grave` by repeating the headline. Fuel queues are not deaths; that one is `violence` at most.
- **Padding.** "A political decision", "a public statement", "a wedding announcement" appear in rows where the headline says none of those things. Band is right, reasoning is filler.

One genuine scale problem, not a model bug: a chef's obituary lands in `grave` because the band is written as "confirmed deaths (1-9)" with no cause qualifier. Scored it `grave` as the scale is written, but the scale should say whether a non-violent death belongs there at all before this sheet is used to compute agreement.
