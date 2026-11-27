"""Import BNMIT's published 2026 placement report into the SQLite database."""

import csv
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "placement_data.db"
COMPANY_CSV = BASE_DIR / "resources" / "placements_2026.csv"
SUMMARY_CSV = BASE_DIR / "resources" / "placement_summary_2026.csv"
SOURCE_URL = "https://www.bnmit.org/wp-content/uploads/2026/08/Placement-Report-2022-26-1.pdf"


def ensure_column(connection, table, column, declaration):
    current_columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    if column not in current_columns:
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}')


def optional_number(value):
    return float(value) if value not in (None, "") else None


def import_report():
    with sqlite3.connect(DATABASE) as connection:
        ensure_column(connection, "placements", "Category", "TEXT NOT NULL DEFAULT 'Historical Placement'")
        ensure_column(connection, "placements", "Salary LPA Reported", "TEXT")
        ensure_column(connection, "placements", "Source URL", "TEXT")
        ensure_column(connection, "placements", "Report Status", "TEXT")
        ensure_column(connection, "placements", "Notes", "TEXT")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS placement_summary (
                year INTEGER NOT NULL,
                cohort TEXT NOT NULL,
                metric TEXT NOT NULL,
                AIML REAL,
                CSE REAL,
                ISE REAL,
                ECE REAL,
                EEE REAL,
                Mech REAL,
                total REAL,
                value REAL,
                unit TEXT,
                report_status TEXT,
                source_url TEXT,
                notes TEXT,
                PRIMARY KEY (year, cohort, metric)
            )
            """
        )
        connection.execute(
            'DELETE FROM placements WHERE year = 2026 AND "Source URL" = ?', (SOURCE_URL,)
        )
        connection.execute(
            "DELETE FROM placement_summary WHERE year = 2026 AND source_url = ?", (SOURCE_URL,)
        )

        with COMPANY_CSV.open(newline="", encoding="utf-8-sig") as source:
            company_rows = list(csv.DictReader(source))
        for row in company_rows:
            connection.execute(
                """
                INSERT INTO placements (
                    Company, AIML, CSE, ISE, ECE, EEE, Mech,
                    "Total Placed", "Salary LPA", year, Category,
                    "Salary LPA Reported", "Source URL", "Report Status", Notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["Company"], int(row["AIML"]), int(row["CSE"]), int(row["ISE"]),
                    int(row["ECE"]), int(row["EEE"]), int(row["Mech"]),
                    int(row["Total Placed"]), optional_number(row["Salary LPA"]),
                    int(row["Year"]), row["Category"], row["Salary LPA Reported"],
                    row["Source URL"], row["Report Status"], row["Notes"],
                ),
            )

        with SUMMARY_CSV.open(newline="", encoding="utf-8-sig") as source:
            summary_rows = list(csv.DictReader(source))
        for row in summary_rows:
            connection.execute(
                """
                INSERT INTO placement_summary (
                    year, cohort, metric, AIML, CSE, ISE, ECE, EEE, Mech,
                    total, value, unit, report_status, source_url, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["Year"]), row["Cohort"], row["Metric"],
                    optional_number(row["AIML"]), optional_number(row["CSE"]),
                    optional_number(row["ISE"]), optional_number(row["ECE"]),
                    optional_number(row["EEE"]), optional_number(row["Mech"]),
                    optional_number(row["Total"]), optional_number(row["Value"]),
                    row["Unit"], row["Report Status"], row["Source URL"], row["Notes"],
                ),
            )

        company_count = connection.execute(
            'SELECT COUNT(*) FROM placements WHERE year = 2026 AND "Source URL" = ?', (SOURCE_URL,)
        ).fetchone()[0]
        summary_count = connection.execute(
            "SELECT COUNT(*) FROM placement_summary WHERE year = 2026 AND source_url = ?", (SOURCE_URL,)
        ).fetchone()[0]

    print(f"Imported {company_count} company records and {summary_count} official summary metrics for 2026.")


if __name__ == "__main__":
    import_report()
