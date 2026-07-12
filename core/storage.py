import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)

    def ensure_table(self, p):
        cols = ", ".join(f"{k} {v}" for k, v in p.schema.items())
        pk = ", ".join(p.pk)
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {p.name} ({cols}, PRIMARY KEY ({pk}))")
        self.conn.commit()

    def upsert(self, p, rows):
        if not rows:
            return
        keys = list(p.schema.keys())
        ph = ",".join("?" * len(keys))
        updates = ",".join(f"{k}=excluded.{k}" for k in keys if k not in p.pk)
        pk = ",".join(p.pk)
        sql = (f"INSERT INTO {p.name} ({','.join(keys)}) VALUES ({ph}) "
               f"ON CONFLICT({pk}) DO UPDATE SET {updates}")
        self.conn.executemany(sql, [[r.get(k) for k in keys] for r in rows])
        self.conn.commit()

    def close(self):
        self.conn.close()
