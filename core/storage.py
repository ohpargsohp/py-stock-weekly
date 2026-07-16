import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)

    def ensure_table(self, p):
        cols = ", ".join(f"{k} {v}" for k, v in p.schema.items())
        pk = ", ".join(p.pk)
        existing_cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({p.name})")]
        if existing_cols and set(p.schema.keys()) - set(existing_cols):
            # provider 的 schema/pk 改了(例如新增欄位),既有表結構跟不上——
            # SQLite 不能直接改 PRIMARY KEY,用「建新表、搬舊資料、換名」升級。
            # 新欄位在舊資料上補 NULL,不用假資料填充。
            shared = [k for k in p.schema if k in existing_cols]
            self.conn.execute(f"ALTER TABLE {p.name} RENAME TO {p.name}_old")
            self.conn.execute(
                f"CREATE TABLE {p.name} ({cols}, PRIMARY KEY ({pk}))")
            self.conn.execute(
                f"INSERT INTO {p.name} ({','.join(shared)}) "
                f"SELECT {','.join(shared)} FROM {p.name}_old")
            self.conn.execute(f"DROP TABLE {p.name}_old")
            self.conn.commit()
            return
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
