"""Servidor local do site de resultados de kart.

Serve o index.html e guarda as corridas num banco SQLite (kart.db) nesta mesma pasta.
Rode com:  python server.py   (ou dê dois cliques em "Abrir Kart.bat")
"""
import json
import os
import sqlite3
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

PORT = 8787
BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "kart.db")

RACE_COLS = {  # campo no site -> coluna no banco
    "id": "id", "kind": "kind", "session": "session",
    "title": "title", "venue": "venue", "track": "track", "date": "date", "time": "time",
    "fileName": "file_name", "fieldSize": "field_size", "fastest": "fastest",
    "fastestName": "fastest_name", "winnerName": "winner_name",
    "ref": "ref", "notes": "notes",
}
JSON_FIELDS = {"ref", "notes"}  # guardados como JSON (referências da sessão e anotações por piloto)
RESULT_COLS = {
    "pos": "pos", "no": "kart_no", "code": "code", "name": "name", "comment": "comment", "laps": "laps",
    "best": "best", "total": "total", "diff": "diff", "gap": "gap", "s1": "s1", "s2": "s2", "s3": "s3", "top": "top_speed",
    "avg": "avg_speed", "bestSpeed": "best_lap_speed", "bestLapNo": "best_lap_no",
}

LAP_COLS = {  # tempo de volta a volta de cada piloto
    "lap": "lap", "tod": "time_of_day", "leaderLap": "leader_lap", "time": "lap_time", "speed": "speed",
    "sf": "sf_speed", "sfTime": "sf_time", "s1": "s1", "s2": "s2", "s3": "s3", "pit": "pit",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    id TEXT PRIMARY KEY,
    title TEXT, venue TEXT, track TEXT, date TEXT, time TEXT, file_name TEXT,
    field_size INTEGER, fastest REAL, fastest_name TEXT, winner_name TEXT,
    imported_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS results (
    race_id TEXT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    ord INTEGER,
    pos INTEGER, kart_no TEXT, code TEXT, name TEXT, comment TEXT, laps INTEGER,
    best REAL, total REAL, diff TEXT, gap TEXT, s1 REAL, top_speed REAL,
    avg_speed REAL, best_lap_speed REAL, best_lap_no INTEGER
);
CREATE TABLE IF NOT EXISTS laps (
    race_id TEXT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    code TEXT,
    lap INTEGER, time_of_day TEXT, leader_lap INTEGER, lap_time REAL, speed REAL,
    sf_speed REAL, sf_time REAL, s1 REAL, s2 REAL, s3 REAL, pit INTEGER
);
CREATE INDEX IF NOT EXISTS idx_laps_race ON laps(race_id, code);
CREATE INDEX IF NOT EXISTS idx_results_race ON results(race_id);
CREATE INDEX IF NOT EXISTS idx_results_code ON results(code);
"""


# colunas que entraram depois da primeira versão do banco
MIGRATIONS = {"races": ["kind TEXT", "session TEXT", "ref TEXT", "notes TEXT"], "results": ["s2 REAL", "s3 REAL"]}


def migrate(con):
    for table, cols in MIGRATIONS.items():
        existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col.split()[0] not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col}")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def list_races():
    with connect() as con:
        races = []
        for r in con.execute("SELECT * FROM races ORDER BY date, time"):
            race = {k: (json.loads(r[c]) if k in JSON_FIELDS and r[c] else r[c]) for k, c in RACE_COLS.items()}
            rows = con.execute("SELECT * FROM results WHERE race_id = ? ORDER BY ord", (r["id"],))
            race["results"] = [{k: x[c] for k, c in RESULT_COLS.items()} for x in rows]
            for res in race["results"]:
                laps = con.execute(
                    "SELECT * FROM laps WHERE race_id = ? AND code IS ? ORDER BY lap", (r["id"], res["code"]))
                lap_list = [{k: l[c] for k, c in LAP_COLS.items()} for l in laps]
                for l in lap_list:
                    l["pit"] = bool(l["pit"])
                if lap_list:
                    res["lapTimes"] = lap_list
            races.append(race)
        return races


def save_race(race_id, race):
    with connect() as con:
        cols = list(RACE_COLS.values())
        vals = [race_id if k == "id" else json.dumps(race.get(k), ensure_ascii=False) if k in JSON_FIELDS and race.get(k) is not None
                else race.get(k) for k in RACE_COLS]
        con.execute(
            f"INSERT INTO races ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
            f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols[1:])}",
            vals,
        )
        con.execute("DELETE FROM results WHERE race_id = ?", (race_id,))
        rcols = ["race_id", "ord"] + list(RESULT_COLS.values())
        con.executemany(
            f"INSERT INTO results ({','.join(rcols)}) VALUES ({','.join('?' * len(rcols))})",
            [[race_id, i] + [x.get(k) for k in RESULT_COLS] for i, x in enumerate(race.get("results", []))],
        )
        con.execute("DELETE FROM laps WHERE race_id = ?", (race_id,))
        lcols = ["race_id", "code"] + list(LAP_COLS.values())
        con.executemany(
            f"INSERT INTO laps ({','.join(lcols)}) VALUES ({','.join('?' * len(lcols))})",
            [[race_id, x.get("code")] + [l.get(k) for k in LAP_COLS]
             for x in race.get("results", []) for l in (x.get("lapTimes") or [])],
        )


def delete_race(race_id):
    with connect() as con:
        con.execute("DELETE FROM races WHERE id = ?", (race_id,))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def race_id(self):
        prefix = "/api/races/"
        return unquote(self.path[len(prefix):]) if self.path.startswith(prefix) else None

    def do_GET(self):
        if self.path == "/api/races":
            return self.send_json(list_races())
        if ".db" in self.path:
            return self.send_error(404)
        return super().do_GET()

    def do_PUT(self):
        rid = self.race_id()
        if not rid:
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            save_race(rid, json.loads(self.rfile.read(length)))
            self.send_json({"ok": True})
        except Exception as e:  # devolve o erro para o site mostrar
            self.send_json({"error": str(e)}, 400)

    def do_DELETE(self):
        rid = self.race_id()
        if not rid:
            return self.send_error(404)
        delete_race(rid)
        self.send_json({"ok": True})

    def end_headers(self):
        # sem cache: depois de atualizar o site, o navegador sempre pega a versão nova
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # sem poluir a janela com cada requisição


def main():
    with connect() as con:
        con.executescript(SCHEMA)
        migrate(con)
    url = f"http://localhost:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"O servidor já está rodando. Abrindo {url}")
        webbrowser.open(url)
        return
    print(f"Kart rodando em {url}")
    print(f"Banco de dados: {DB_PATH}")
    print("Deixe esta janela aberta enquanto usa o site. Feche-a para desligar.")
    threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
