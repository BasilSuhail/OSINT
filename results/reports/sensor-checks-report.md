# Sensor cross-checks — claim vs machine (WS-C step 3)

This run: 30 stories with claims, 30 claims, 0 confirmed, 28 unconfirmed, 2 previously confirmed kept, 1905 stories scored.

Checks touched in the last 24 h:

| verdict | claim | owners | corroboration | story |
|---|---|---|---|---|
| confirmed | disaster | 3 | 0.875 | Typhoon Maysak kills two and forces thousands to evacuate in China |
| confirmed | earthquake | 1 | 0.500 | Philippine town seeks immediate airlift of food to ease hunger in quake-hit villages |
| unconfirmed | disaster | 1 | 0.000 | 157 houses for Wayanad landslide survivors to be completed by September 30, says Minister |
| unconfirmed | disaster | 2 | 0.500 | Severe storms in China bring tornadoes and landslides that have killed 15 people |
| unconfirmed | disaster | 1 | 0.000 | Flood watch issued for 5 US states through weekend: See full list |
| unconfirmed | disaster | 1 | 0.000 | J&amp;K: Heavy rain triggers landslide near Kwar power project site, blocks Doda-Kishtwar highway |
| unconfirmed | disaster | 1 | 0.000 | Venomous snakes escape breeding farms in southern China during flooding |
| unconfirmed | disaster | 1 | 0.000 | India floods sweep away thousands of gas cylinders |
| unconfirmed | disaster | 1 | 0.000 | Taiwan braces for powerful typhoon after floods in China kill dozens |
| unconfirmed | disaster | 1 | 0.000 | The real reason Gurgaon floods every year isn't rain |
| unconfirmed | disaster | 1 | 0.000 | Flood sweeps away over 100 animals from zoo in southern China |
| unconfirmed | disaster | 1 | 0.000 | Kerala HC to hear suo motu proceedings on July 2024 landslide in Wayanad |
| unconfirmed | disaster | 1 | 0.000 | Whoopi Goldberg stranded in Italy amid volcano eruption |
| unconfirmed | disaster | 1 | 0.000 | Tornadoes kill 17 in central China as Typhoon Bavi looms offshore |
| unconfirmed | disaster | 1 | 0.000 | Heavy rains trigger flash floods in Doda, damage houses and roads |
| unconfirmed | disaster | 1 | 0.000 | Deadly  landslide buries tunnel construction site in India |
| unconfirmed | disaster | 1 | 0.000 | Viral AI fakes flood social media as Iran mourns Khamenei |
| unconfirmed | disaster | 1 | 0.000 | 'The water just came so fast': Typhoon triggers floods and rare tornadoes in China |
| unconfirmed | disaster | 1 | 0.000 | Eight killed after landslide hits girls' school in Bangladesh |
| unconfirmed | disaster | 1 | 0.000 | Floods, landslides affect several Arunachal districts |
| unconfirmed | disaster | 1 | 0.000 | Mass cleanup underway after severe flooding in China |
| unconfirmed | disaster | 2 | 0.500 | Watch: Heavy rain sends 3,000 LPG cylinders floating down river in Maharashtra's Raigad |
| unconfirmed | disaster | 2 | 0.500 | China, Taiwan brace for Typhoon Bavi; likely to make landfall in ‌eastern Fujian on July 11 |
| unconfirmed | earthquake | 1 | 0.000 | UN launches appeal for $388 million in Venezuela quake relief |
| unconfirmed | earthquake | 1 | 0.000 | After quake, Venezuelans left to deal with trauma and grief |
| unconfirmed | earthquake | 1 | 0.000 | Venezuelan earthquake survivors make the hard shift from rescue to recovery |
| unconfirmed | earthquake | 1 | 0.000 | Venezuela ‘fully compliant’ with aid efforts, US official says, amid criticism of official quake response |
| unconfirmed | earthquake | 6 | 0.969 | Death toll from Venezuela's earthquakes rises to 3,342 |
| unconfirmed | earthquake | 1 | 0.000 | Quake-hit Venezuela's push for a swift debt deal raises fears of future crisis |
| unconfirmed | wildfire | 1 | 0.000 | Wildfire in France burns 11,000 acres as Europe battles its third heatwave |

Rules are declared constants (`sensor-rules-v1.0`): earthquake→USGS, wildfire→FIRMS, disaster→GDACS, market crash→market drawdown. `confirmed` never downgrades — evidence snapshots outlive sensor retention. `corroboration` = corroboration-v1.0: each extra independent owner halves the remaining doubt; a sensor confirmation halves it once more.
