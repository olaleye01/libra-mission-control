import re
import sqlite3
import time


def register(route, ApiError):
    @route("GET", "/api/clients")
    def listing(req, query, body):
        with req.app.store.connect() as con:
            rows = con.execute("""SELECT c.id,c.name,COUNT(s.id) AS shipment_count
                FROM clients c LEFT JOIN shipments s ON s.client_id=c.id
                GROUP BY c.id ORDER BY c.id""").fetchall()
        return {"clients": [dict(r) for r in rows]}

    @route("POST", "/api/clients")
    def create(req, query, body):
        name = body.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[\w &'().-]{2,60}", name.strip()):
            raise ApiError(400, "Client name must contain 2–60 letters, numbers or ordinary punctuation.")
        name = name.strip()
        try:
            with req.app.store.connect() as con:
                cursor = con.execute("INSERT INTO clients(name,created_at) VALUES(?,?)", (name, time.time()))
                client_id = cursor.lastrowid
                req.app.store.audit(con, "client_created", {"id": client_id, "name": name})
        except sqlite3.IntegrityError:
            raise ApiError(409, "A client with this name already exists.")
        return {"client": {"id": client_id, "name": name, "shipment_count": 0}}
