"""
Import manually reviewed review_spots.csv into spot_whitelist table,
then update ner_locations.in_whitelist flags.
"""

import sqlite3
import csv

DB_PATH = "japan_travel.db"
INPUT_CSV = "review_spots.csv"


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spot_whitelist (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name_zh  TEXT NOT NULL UNIQUE,
            posts    INTEGER,
            mentions INTEGER,
            source   TEXT DEFAULT 'manual'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wl_name ON spot_whitelist(name_zh)")

    inserted = 0
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if str(row.get("add_to_whitelist", "0")).strip() != "1":
                continue
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO spot_whitelist (name_zh, posts, mentions) VALUES (?,?,?)",
                    (row["entity"], int(row["posts"]), int(row["mentions"])),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
            except Exception as e:
                print(f"  skip {row['entity']}: {e}")

    conn.commit()
    print(f"Inserted {inserted} spots into spot_whitelist")

    # update ner_locations.in_whitelist
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ner_locations)")]
    if "in_whitelist" not in cols:
        conn.execute("ALTER TABLE ner_locations ADD COLUMN in_whitelist INTEGER DEFAULT 0")
    else:
        conn.execute("UPDATE ner_locations SET in_whitelist=0")

    whitelist = {r[0] for r in conn.execute("SELECT name_zh FROM spot_whitelist")}
    updated = 0
    for (entity,) in conn.execute("SELECT DISTINCT entity FROM ner_locations"):
        if entity in whitelist:
            conn.execute("UPDATE ner_locations SET in_whitelist=1 WHERE entity=?", (entity,))
            updated += 1
    conn.commit()

    print(f"NER entities matched: {updated} / {len(whitelist)} whitelist spots")
    conn.close()


if __name__ == "__main__":
    main()
