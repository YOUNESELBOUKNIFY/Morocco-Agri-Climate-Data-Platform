"""Database tools: connection to Supabase (PostgreSQL + PostGIS) and SQL tools for the agent."""

import os
import re

from sqlalchemy import create_engine, text

_engine = None
_backup_done = False
TABLE = "localites"
FORBIDDEN = re.compile(r"\b(DROP\s+TABLE|DROP\s+SCHEMA|DROP\s+DATABASE|TRUNCATE|GRANT|REVOKE)\b", re.I)


def init_db(url: str | None = None):
    """Open the connection. Uses `url`, otherwise the DATABASE_URL environment variable."""
    global _engine
    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is missing (.env file or Kaggle secret).")
    _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_engine():
    """Return the connection, opening it automatically from DATABASE_URL if needed."""
    if _engine is None:
        init_db()
    return _engine


def _fmt(result, limit: int = 30) -> str:
    rows = result.fetchmany(limit)
    if not rows:
        return "(aucune ligne)"
    lines = [" | ".join(result.keys())] + [" | ".join(map(str, r)) for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------- tools ----

def run_select(sql: str) -> str:
    """Read-only SQL query on the database (max 30 rows)."""
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        return "Refusé : run_select accepte uniquement des SELECT. Utilise run_change pour modifier."
    with get_engine().connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        try:
            return _fmt(c.execute(text(sql)))
        except Exception as e:
            return f"Erreur SQL : {e}"


def run_change(sql: str, reason: str) -> str:
    """Propose ONE modification. Runs only after the human types 'y'. Backs up the table first."""
    global _backup_done
    if FORBIDDEN.search(sql):
        return "Refusé : ce type d'instruction est interdit."

    print("\n" + "=" * 60)
    print(f"🛠️  MODIFICATION PROPOSÉE : {reason}\n\n{sql}")
    print("=" * 60)
    if input("Exécuter ? [y/N] ").strip().lower() != "y":
        return "Refusé par l'humain. Ne la relance pas ; propose autre chose ou arrête."

    with get_engine().begin() as c:
        if not _backup_done:
            c.execute(text(f"DROP TABLE IF EXISTS {TABLE}_backup"))
            c.execute(text(f"CREATE TABLE {TABLE}_backup AS SELECT * FROM {TABLE}"))
            _backup_done = True
            print(f"(sauvegarde créée : {TABLE}_backup)")
        try:
            n = c.execute(text(sql)).rowcount
        except Exception as e:
            return f"Erreur SQL, rien n'a été modifié : {e}"
    return f"OK, {n} ligne(s) modifiée(s)."


# ---------------------------------------------------- tool descriptions ----

DB_FUNCS = {"run_select": run_select, "run_change": run_change}

DB_TOOLS = [
    {"type": "function", "function": {
        "name": "run_select",
        "description": (
            "Exécute une requête SQL en LECTURE SEULE (SELECT) sur la table PostgreSQL/PostGIS "
            "localites (id, nom, nom_ar, latitude, longitude, region, geonames_id, "
            "geom geography(Point,4326)). Renvoie 30 lignes max : utilise COUNT(*) et LIMIT."),
        "parameters": {"type": "object",
                       "properties": {"sql": {"type": "string"}},
                       "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "run_change",
        "description": (
            "Propose UNE modification (UPDATE, DELETE, ALTER TABLE, CREATE INDEX) de la table "
            "localites. L'humain doit la valider. Prévisualise toujours avant avec run_select."),
        "parameters": {"type": "object",
                       "properties": {
                           "sql": {"type": "string"},
                           "reason": {"type": "string",
                                      "description": "Ce que ça corrige et combien de lignes environ"}},
                       "required": ["sql", "reason"]}}},
]