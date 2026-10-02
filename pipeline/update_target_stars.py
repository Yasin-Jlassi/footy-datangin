import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from pipeline.enrich_players import get_wikidata_dob

dsn = "postgresql://postgres.migvkquntwadnudpmdcs:footydatangin@aws-1-eu-west-3.pooler.supabase.com:6543/postgres?sslmode=require"
conn = psycopg2.connect(dsn)

targets = [
    ("Moisés Caicedo", "%Mois%Caicedo%"),
    ("Félix Torres", "%Torres Caicedo%"),
    ("Lamine Yamal", "%Lamine Yamal%"),
    ("Kylian Mbappé", "%Mbapp%"),
    ("Harry Kane", "%Harry Kane%"),
    ("Lionel Messi", "%Messi%"),
    ("Cristiano Ronaldo", "%Cristiano Ronaldo%"),
    ("Declan Rice", "%Declan Rice%"),
    ("Bukayo Saka", "%Bukayo Saka%"),
    ("Phil Foden", "%Phil Foden%"),
    ("William Saliba", "%Saliba%"),
    ("Virgil van Dijk", "%van Dijk%"),
]

with conn:
    with conn.cursor() as cur:
        for search_term, pattern in targets:
            dob = get_wikidata_dob(search_term)
            if dob:
                cur.execute("UPDATE player_master SET birth_date = %s WHERE full_name ILIKE %s RETURNING full_name, birth_date;", (dob, pattern))
                updated = cur.fetchall()
                for name, d in updated:
                    clean_name = name.encode('ascii', 'replace').decode()
                    print(f"[OK] {clean_name} -> {d}")
            else:
                print(f"[SKIP] {search_term} -> not found")

conn.close()
print("Done updating target stars!")
