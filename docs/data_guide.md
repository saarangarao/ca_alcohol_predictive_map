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
