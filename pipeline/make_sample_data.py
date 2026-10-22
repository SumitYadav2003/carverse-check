"""
Generate a small, made-up dataset in the exact layout of DVSA's anonymised MOT files.

Used by CI to run the whole pipeline (ingest -> dbt -> load into Django) on every push,
without the 13 GB of real data. It deliberately reproduces every quirk found in the real
2024 files, so the tests exercise the same cleaning rules:

  - monthly results/items files are comma-separated; lookup tables are pipe-separated
  - the header line is repeated inside each monthly file
  - exact copies of tests (with their defect rows copied too)
  - copies that disagree (first-use date within the same year, or vehicle class)
  - a make containing a comma, quoted:            "IVECO ,MOTORHOME"
  - a model containing a quote, backslash-escaped: "STREETZONE 50 2T 12\\""
  - DVSA placeholders: first-use date 1971-01-01 and make UNCLASSIFIED
  - defect IDs missing from the lookup table

Usage:
    python pipeline/make_sample_data.py data/raw/sample

The seed is fixed, so the output is identical on every run. Never load this into your real
warehouse: set MOT_WAREHOUSE to a separate file first (CI does).
"""

import random
import sys
from pathlib import Path

RESULT_HEADER = ("test_id,vehicle_id,test_date,test_class_id,test_type,test_result,test_mileage,"
                 "postcode_area,make,model,colour,fuel_type,cylinder_capacity,first_use_date,"
                 "completed_date")
ITEM_HEADER = "test_id,rfr_id,rfr_type_code,mot_test_rfr_location_type_id,dangerous_mark,completed_date"

MODELS = [("FORD", "FIESTA"), ("VAUXHALL", "CORSA"), ("VOLKSWAGEN", "GOLF"),
          ("IVECO ,MOTORHOME", "DAILY"), ("PEUGEOT", 'STREETZONE 50 2T 12"'),
          ("UNCLASSIFIED", "UNCLASSIFIED")]
RFR_IDS = [30329, 31194, 32017, 88888]          # 88888 is deliberately not in the lookup
MONTHS = ["04", "05", "06", "07", "08", "09", "10", "11", "12"]
TESTS_PER_MONTH = 600


def csv_value(value):
    if '"' in value:
        return '"' + value.replace('"', '\\"') + '"'   # DVSA escapes quotes with a backslash
    if "," in value:
        return f'"{value}"'
    return value


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python pipeline/make_sample_data.py data/raw/sample")
    out = Path(sys.argv[1]) / "extracted"
    rng = random.Random(2024)
    test_id = 100_000

    for month in MONTHS:
        results, items = [RESULT_HEADER], [ITEM_HEADER]
        for k in range(TESTS_PER_MONTH):
            test_id += 1
            make, model = rng.choice(MODELS)
            first_use = f"20{rng.randint(5, 20):02d}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}"
            if rng.random() < 0.01:
                first_use = "1971-01-01"
            completed = f"2024-{month}-1{k % 9}T10:00:00.000Z"
            row = [str(test_id), str(test_id * 3), f"2024-{month}-1{k % 9}",
                   rng.choice(["4"] * 9 + ["3", "7", "2"]), rng.choice(["NT"] * 8 + ["RT"]),
                   rng.choices(["P", "F", "PRS", "ABR"], [70, 22, 6, 2])[0],
                   rng.choice([f"{rng.randint(1000, 200000)}.0", ""]), "LE",
                   csv_value(make), csv_value(model), "RED", "PE", "1242", first_use, completed]
            lines = [",".join(row)] * rng.choices([1, 2, 3], [65, 30, 5])[0]
            if rng.random() < 0.03:                      # copy disagreeing on the exact date
                alt = row.copy(); alt[13] = first_use[:4] + "-12-31"; lines.append(",".join(alt))
            if rng.random() < 0.01:                      # copy disagreeing on the class
                alt = row.copy(); alt[3] = "7"; lines.append(",".join(alt))
            results += lines
            for _ in range(rng.randint(0, 3)):
                item = (f"{test_id},{rng.choice(RFR_IDS)},{rng.choice('FPAM')},{rng.randint(1, 30)},"
                        f"{rng.choice(['', '', 'D'])},{completed}")
                items += [item] * len(lines)             # copied tests have copied defects
            if k % 200 == 199:                           # repeated header lines
                results.append(RESULT_HEADER)
                items.append(ITEM_HEADER)
        write(out / "results" / f"test_result_2024{month}.csv", results)
        write(out / "items" / f"test_item_2024{month}.csv", items)

    lookups = out / "lookups"
    classes = ["1", "2", "3", "4", "5", "7"]
    detail = ["rfr_id|test_class_id|test_item_id|minor_item|rfr_deficiency_category|rfr_desc|"
              "rfr_loc_marker|rfr_insp_manual_desc|rfr_advisory_text|test_item_set_section_id"]
    for rfr, section in [(30329, 1), (31194, 2), (32017, 1)]:
        detail += [f'{rfr}|{c}|10|N|Major|brake pipe corroded "badly"|N|x|corroded|{section}'
                   for c in classes]
    write(lookups / "item_detail.csv", detail)
    group = ["test_item_id|test_class_id|parent_id|test_item_set_section_id|item_name"]
    for c in classes:
        group += [f"0|{c}|0|0|Vehicle", f"1|{c}|0|1|Brakes", f"2|{c}|0|2|Lamps"]
    write(lookups / "item_group.csv", group)
    write(lookups / "mdr_fuel_types.csv", ["type_code|fuel_type", "PE|Petrol", "DI|Diesel"])
    write(lookups / "mdr_test_outcome.csv",
          ["result_code|result", "P|Pass", "F|Fail", "PRS|PRS", "ABR|Aborted", "ABA|Abandoned",
           "ABRVE|Aborted by VE", "R|Refused"])
    write(lookups / "mdr_test_type.csv",
          ["type_code|test_type", "NT|Normal Test", "RT|Re-Test", "ES|Statutory Appeal",
           "EI|Inverted Appeal", "PL|Partial Retest Left VTS", "PV|Partial Retest Repaired at VTS"])
    print(f"Sample data written to {out}")


if __name__ == "__main__":
    main()
