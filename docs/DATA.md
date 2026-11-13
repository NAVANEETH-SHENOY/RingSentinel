# Data

Everything in the "observed" sections comes from the schema report the owner generated on the real HI-Small files with `scripts/inspect_schema.py` (12 Nov 2026). Items marked **verify** have not been checked against a source.

## Dataset

IBM synthetic anti-money-laundering transactions, variant **HI-Small** (higher illicit ratio, small), downloaded from Kaggle ("IBM Transactions for Anti-Money Laundering (AML)"). The data is synthetic; no real customer data is involved.

**Download history.** The first download had 10 columns and no label column. It was replaced on 12 Nov 2026 by the corrected download, which has an 11th column, `Is Laundering`. Everything below describes the corrected file; the checksums in `data/raw/MANIFEST.json` are for it.

Citation (authors, title and venue confirmed on the NeurIPS proceedings page; **verify** page numbers, URL form and BibTeX before the final README):

Altman, E., Blanuša, J., von Niederhäusern, L., Egressy, B., Anghel, A., Atasu, K. (2023). Realistic Synthetic Financial Transactions for Anti-Money Laundering Models. NeurIPS 2023, Datasets and Benchmarks Track. https://proceedings.neurips.cc/paper_files/paper/2023/hash/5f38404edff6f3f642d6fa5892479c42-Abstract.html

Licence: the paper's supplement says the Kaggle data is published under a "Community Data License Agreement". **Not verified** which variant of that agreement applies, or what it requires of this project. The owner should copy the licence line from the Kaggle page, and the Kaggle page's own citation instructions, into this file.

## Files (raw, not committed; checksums are in `data/raw/MANIFEST.json`)

| File | Size (bytes) | Rows / lines | SHA-256 |
| --- | --- | --- | --- |
| HI-Small_Trans.csv | 475,664,283 | 5,078,345 rows, 11 columns | b19d39f515523373f991b689c07e11e7b0b95c17a2c27a87d91584ae16c5b040 |
| HI-Small_Patterns.txt | 328,161 | 4,318 lines: 3,209 transactions, 370 BEGIN and 370 END lines | 7c5029d7ff0baaf01dba98d9ac2c51c98de288bc37317f4ee5edc44eeef3cb37 |

## Observed columns of HI-Small_Trans.csv

| # | Raw name | Internal name | Observed |
| --- | --- | --- | --- |
| 0 | Timestamp | ts | Text `YYYY/MM/DD HH:MM`, minute resolution, no timezone. Text range 2022/09/01 00:00 to 2022/09/18 16:18, although the paper describes a 10-day window |
| 1 | From Bank | src_bank | Text with leading zeros (e.g. 010, 03208) |
| 2 | Account | src_account | Opaque id such as 8000EBD30. Some ids look like numbers in scientific notation, so ids must never be type-inferred |
| 3 | To Bank | dst_bank | As above |
| 4 | Account | dst_account | The raw header repeats the name "Account" |
| 5 | Amount Received | amount_received | 0.000001 up to 1,046,302,363,293.48 |
| 6 | Receiving Currency | recv_currency | 15 values (below) |
| 7 | Amount Paid | amount_paid | Same range; equal to Amount Received in every sample row, may differ across currencies |
| 8 | Payment Currency | pay_currency | 15 values |
| 9 | Payment Format | payment_format | Cheque 1,864,331; Credit Card 1,323,324; ACH 600,797; Cash 490,891; Reinvestment 481,056; Wire 171,855; Bitcoin 146,091 |
| 10 | Is Laundering | is_illicit (label source) | Numeric 0 or 1, no empty cells. 5,177 rows are 1 (0.1019 percent) |

Currencies (receiving counts): US Dollar 1,879,341; Euro 1,172,017; Swiss Franc 237,884; Yuan 206,551; Shekel 194,988; Rupee 192,065; UK Pound 181,255; Ruble 157,361; Yen 156,319; Bitcoin 148,151; Canadian Dollar 141,357; Australian Dollar 138,511; Mexican Peso 111,030; Saudi Riyal 89,971; Brazil Real 71,544.

Other observations:
- **The label column exists in the corrected download** (`Is Laundering`, 5,177 positives). The older 10-column download did not have it; the ingestor still accepts that layout and then falls back to pattern-only labels.
- The file is **not in time order** (first row 2022/09/01 00:20, last row 2022/09/10 23:37, maximum 2022/09/18 16:18).
- Many rows are self-transfers, e.g. Payment Format "Reinvestment" with the same account on both sides.
- The same account string appeared on the sender and receiver side with different bank codes in one sample row (a 0.01 cheque). The ingest report counts accounts seen with more than one bank, so the choice of node identity can be revisited with data (see the decision log in `docs/PROJECT_EXPLAINER.md`).

## Observed layout of HI-Small_Patterns.txt

Blocks of `BEGIN LAUNDERING ATTEMPT - <TYPE>[:  <detail>]`, then transaction lines, then `END LAUNDERING ATTEMPT - <TYPE>`. Each transaction line has the 10 transaction fields followed by a label field, `1`. 370 blocks: CYCLE 54, GATHER-SCATTER 51, BIPARTITE 49, FAN-OUT 48, SCATTER-GATHER 44, STACK 43, RANDOM 41, FAN-IN 40.

## How labels are built

1. `is_illicit` is the CSV `Is Laundering` column (1 = laundering). If a 10-column file is used instead, `is_illicit` is 1 only for rows matched to a pattern line, and the ingest report says `label_source: patterns_file_only`.
2. Each pattern line is matched to a CSV row on all ten transaction fields (n-th identical line to n-th identical row). A matched row gets `ring_id` (1-based block number) and `ring_type`.
3. Cross-check: all 3,209 pattern lines matched, and every matched row has `Is Laundering = 1` (`pattern_rows_with_csv_label_zero` is 0 in the ingest report). Two independent sources agree, which supports the matching.

**Labels versus rings (important for honest evaluation).** The CSV marks 5,177 transactions as laundering, but the patterns file describes only 3,209 of them, in 370 rings. The other 1,968 (38.0 percent) are positives that belong to no known ring. Consequences:
- Transaction-level metrics use all 5,177 positives.
- Ring-level recall can only be measured on the 370 pattern rings, so it says nothing about the 38 percent of positives that have no ring structure on file.
- A ring detector cannot be scored on those 1,968 rows as rings; they matter only for transaction-level numbers.

An earlier version of this file estimated the gap at "roughly a tenth" from a rounded figure in the paper. That estimate was unverified and is superseded by the counts above.

**Positive rate by split** (from `split_meta.json` [generated] and the events table, HI-Small, seed 42):

| Split | Rows | Positives | Positive rate | Positives in a pattern ring |
| --- | --- | --- | --- | --- |
| train | 3,046,861 | 2,297 | 0.075 percent | 1,177 |
| val | 1,015,602 | 1,082 | 0.107 percent | 693 |
| test | 1,015,882 | 1,798 | 0.177 percent | 1,339 |

The positive rate rises with time, so the test split is not the same distribution as train. Report this next to every test result.

## Real versus derived fields

| Field | Kind |
| --- | --- |
| ts, src_bank, src_account, dst_bank, dst_account, amount_received, recv_currency, amount_paid, pay_currency, payment_format | Real (as provided; the data itself is synthetic) |
| event_id | Derived: 0-based row position in the raw file |
| amount_inr | Derived: amount_paid times a fixed INR rate per payment currency. The rates in `config/fx_rates_inr.json` are **approximate placeholders, not verified** |
| is_illicit | Real: the dataset's own `Is Laundering` label (the data itself is synthetic) |
| ring_id, ring_type | Derived from the patterns file as described above (only 3,209 of the 5,177 positives have one) |
| split, ring_split | Derived from timestamps (Stage 01 split) |
| derived_ip_id, derived_device_id, derived_vpa_handle_id | Derived and synthetic: invented per account by `backend/ringsentinel/noise.py` from account strings and the seed only (label-blind), used only to stress-test hub control, never as detection signal. Written to `noise.parquet` [generated] |
| Feature columns (`features.parquet` [generated]) | Derived from the real transfer columns; no label is read |

## Node identity

The graph uses the account string alone as the node id. The ingest report shows only 8 account strings that appear under more than one bank, so merging them changes almost nothing; banks stay as attributes in the event table.
