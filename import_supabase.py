import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()                      # lit le fichier .env
URI = os.getenv("DATABASE_URL")    # récupère l'URI sans l'écrire dans le code
engine = create_engine(URI)

df = pd.read_json("maroc_villes_villages.json")
df.to_sql("localites", engine, if_exists="replace", index=False, chunksize=2000, method="multi")
print("Import OK :", len(df), "lignes")

with engine.begin() as c:
    c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    c.execute(text("ALTER TABLE localites ADD COLUMN geom geography(Point, 4326)"))
    c.execute(text("UPDATE localites SET geom = ST_MakePoint(longitude, latitude)"))
    c.execute(text("CREATE INDEX ON localites USING GIST (geom)"))
print("PostGIS OK")