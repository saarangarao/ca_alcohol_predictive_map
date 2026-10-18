# Data dictionary

## ABC Daily Data Export (downloaded 2026-10-12; 129,653 records, 26 columns)
Load with: read_csv(..., skip=1, all_varchar=true). Line 1 is a banner, the file ends with a blank line.

| Layout name | Real CSV column | Use | Notes / sample values |
|---|---|---|---|
| License Type | License Type | channel key | 2-char text, keep leading zero ("20", "47", "02"); 79 distinct |
| File Number | File Number | outlet ID | 8-char text ("00677645"); 96,563 distinct in 129,653 rows |
| License or Application | Lic or App | filter | LIC 108,243 / APP 21,410; keep LIC |
| Type Status | Type Status | filter | ACTIVE 118,683; PEND 7,703; SUREND 2,304; REVPEN 510; SUSPEN 323; R64B 130 |
| Type Original Issue Dates | Type Orig Iss Date | cohort add-on | blank for applications; format TBD |
| Expiration Dates | Expir Date | not used | |
| Fee Codes | Fee Codes | not used | meaning TBD |
| Duplicate Counts | Dup Counts | dedupe | blank for 110,567 rows, else "001".."010"+; meaning TBD |
| Master Indicator | Master Ind | dedupe | Y 110,368 / N 19,285; meaning TBD |
| Term in Number of Months | Term in # of Months | not used | always 12 |
| Geo Code / District | Geo Code, District | not used | |
| Primary Name, DBA Name | Primary Name, DBA Name | PRIVATE | never output |
| Premise Street Address 1,2 | Prem Addr 1, Prem Addr 2 | PRIVATE | never output |
| Premise City | Prem City | not a join key | free text |
| Premise State | Prem State | filter = CA | CA 126,405; blank (a space, not NULL) 1,291; others OR, WA, NY... |
| Premise Zip | Prem Zip | zip5 key | may be ZIP+4 ("90033-2028"); blank for 1,291 rows |
| Mail Street 1,2 / City / State / Zip | Mail Addr 1, Mail Addr 2, Mail City, Mail State, Mail Zip | PRIVATE | not used |
| Premise County | Prem County | grouping | uppercase text ("LOS ANGELES") |
| Premise Census Tract Number | Prem Census Tract # | tract add-on (A8) | EXISTS; "2032.00"; blank for 4,314 rows |

## ACS 2024 5-year (B01003, B19013, B01002), 1,808 ZCTAs per file (1,802 in the CA ZIP range)
- Two header rows; row 2 (GEO_ID = "Geography") holds labels. Trailing comma creates an empty extra column.
- Non-numeric values: income "-" (212), "250,000+" (17), "2,500-" (1); median age "-" (61).

## Derived tables
Built by `src/ingest_abc.py` (Phase 1), `src/ingest_acs.py` (Phase 2) and `src/build_features.py` (Phase 3).

- `clean_outlets`: one row per (file_number, channel); active issued licenses, premise state CA, retail channels only (OFF_SALE, ON_SALE_CORE), valid 5-digit ZIP. 70,402 rows.
- `filter_attrition`, `bad_zip`, `join_misses_abc`, `join_report`, `acs_missing`: audit tables that record what each step removed or failed to match.
- `acs_clean`: ACS values for California ZIPs with population >= POP_FLOOR (1,000), plus land area, coordinates and county.

### zip_features (1,419 rows, one per zip5)
| Column | Definition | Unit | Source |
|---|---|---|---|
| zip5 | 5-digit ZIP / ZCTA key (text) | - | last 5 chars of ACS GEO_ID |
| city | most common premise city among the ZIP's outlets; a label only, never a join key | text | ABC |
| county_fips, county | county with the largest land overlap with the ZCTA | text | Census ZCTA-county relationship file |
| lat, lon | ZCTA internal point | degrees | Census Gazetteer |
| land_sqmi | land area | square miles | Census Gazetteer |
| population, population_moe | B01003_001 estimate and margin of error | people | ACS 2024 5-year |
| median_income, median_income_moe | B19013_001; "250,000+" is kept as 250000; NULL where ACS gives "-" or "2,500-" | 2024 dollars | ACS 2024 5-year |
| income_top_coded | true if ACS reported "250,000+" | boolean | ACS |
| median_age, median_age_moe | B01002_001 (total) | years | ACS 2024 5-year |
| outlets_off | distinct OFF_SALE outlets (license types 20, 21) | count | ABC |
| outlets_on_core | distinct ON_SALE_CORE outlets (types 40, 41, 42, 47, 48, 61) | count | ABC |
| off_per_1k, on_per_1k | outlets / population * 1000 | per 1,000 residents | derived |
| on_share | outlets_on_core / (outlets_on_core + outlets_off); NULL if both are 0 | ratio 0-1 | derived |
| pop_density | population / land_sqmi | people per square mile | derived |
| log_population, log_income, log_pop_density | natural log; log_income is NULL where income is NULL | - | derived |
| log1p_off_per_1k, log1p_on_per_1k | ln(1 + density) | - | derived |
| visitor_heavy | true if either log1p density exceeds Q3 + 3 x IQR (Tukey far-out fence, FENCE_K in build_features.py); flags ZIPs whose outlets serve non-residents (tourists, travelers, downtown workers). Flagged, never deleted. 26 ZIPs. | boolean | derived |

Known gaps: median_income is NULL for 28 ZIPs; on_share is NULL for the 31 ZIPs with zero outlets; city is NULL for those same ZIPs.
