"""
Jan Samadhan — backend API server.
Pure Python standard library only (http.server + sqlite3 + hmac). No pip install needed.

Run:
    python3 server.py
Then open http://localhost:8000 in a browser.

Workflow (problem.status):
submitted -> verified -> matched -> in_progress -> solution_submitted
-> funded -> approved -> implemented   (+ rejected at verification)
"""
import os, re, json, time, sqlite3, hashlib, hmac, base64, secrets, mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
DB_PATH = os.environ.get("JAN_SAMADHAN_DB", str(HERE / "jan_samadhan.db"))
FRONTEND_DIR = HERE / "frontend"
SECRET = os.environ.get("JAN_SAMADHAN_SECRET", "dev-secret-change-me-before-real-deployment")
ROLES = {"citizen", "expert", "college", "industry", "government"}
PORT = int(os.environ.get("PORT", "8000"))

# ------------------------------------------------------------------ database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, salt TEXT,
  role TEXT, org TEXT DEFAULT '', expertise TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS problems(
  id INTEGER PRIMARY KEY, citizen_id INT, title TEXT, description TEXT, location TEXT,
  category TEXT, priority TEXT, ai_summary TEXT, status TEXT, college_id INT, created_at REAL);
CREATE TABLE IF NOT EXISTS matches(
  id INTEGER PRIMARY KEY, problem_id INT, college_id INT, score REAL,
  UNIQUE(problem_id, college_id));
CREATE TABLE IF NOT EXISTS solutions(
  id INTEGER PRIMARY KEY, problem_id INT, college_id INT, title TEXT, description TEXT,
  team TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS support(
  id INTEGER PRIMARY KEY, problem_id INT, industry_id INT, kind TEXT, amount REAL DEFAULT 0,
  note TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY, problem_id INT, citizen_id INT, rating INT, comment TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, problem_id INT, status TEXT, actor TEXT, note TEXT, at REAL);
"""


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def q(sql, args=(), one=False):
    c = db()
    try:
        with c:
            cur = c.execute(sql, args)
            if cur.description is None:
                return cur.lastrowid
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        c.close()
    return (rows[0] if rows else None) if one else rows


def init_db():
    c = db()
    c.executescript(SCHEMA)
    c.commit()
    c.close()


def log_event(pid, status, actor, note="", set_status=True):
    q("INSERT INTO events(problem_id,status,actor,note,at) VALUES(?,?,?,?,?)",
      (pid, status, actor, note, time.time()))
    if set_status:
        q("UPDATE problems SET status=? WHERE id=?", (status, pid))


class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


def get_problem(pid, *allowed):
    p = q("SELECT * FROM problems WHERE id=?", (pid,), one=True)
    if not p:
        raise ApiError(404, "Problem not found")
    if allowed and p["status"] not in allowed:
        raise ApiError(409, f"Problem is '{p['status']}', expected {' or '.join(allowed)}")
    return p


# ------------------------------------------------------------------------ auth
def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid):
    payload = json.dumps({"uid": uid, "exp": int(time.time()) + 7 * 86400}).encode()
    p64 = b64u(payload)
    sig = hmac.new(SECRET.encode(), p64.encode(), hashlib.sha256).hexdigest()
    return f"{p64}.{sig}"


def verify_token(token):
    try:
        p64, sig = token.split(".", 1)
        expect = hmac.new(SECRET.encode(), p64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(unb64u(p64))
        if payload["exp"] < time.time():
            return None
        return payload["uid"]
    except Exception:
        return None


def current_user(headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(401, "Login required")
    uid = verify_token(auth[7:])
    if uid is None:
        raise ApiError(401, "Login required")
    u = q("SELECT id,name,email,role,org,expertise FROM users WHERE id=?", (uid,), one=True)
    if not u:
        raise ApiError(401, "Login required")
    return u


def require_role(u, *roles):
    if u["role"] not in roles:
        raise ApiError(403, "Your role cannot do this")


# --------------------------------------------------------------------- AI layer
CATS = {
    "Water": ["water", "पानी", "जल", "pipeline", "borewell", "tanker", "नल", "irrigation", "सिंचाई"],
    "Roads & Transport": ["road", "सड़क", "pothole", "गड्ढा", "traffic", "bridge", "पुल", "bus"],
    "Electricity": ["electric", "बिजली", "power", "transformer", "street light", "solar", "voltage"],
    "Sanitation & Waste": ["garbage", "कचरा", "waste", "drain", "नाली", "sewage", "toilet", "शौचालय", "गंदगी"],
    "Health": ["hospital", "अस्पताल", "disease", "बीमारी", "health", "medicine", "दवा", "doctor", "डॉक्टर", "dengue"],
    "Education": ["school", "स्कूल", "education", "शिक्षा", "teacher", "शिक्षक", "literacy"],
    "Agriculture": ["farm", "खेती", "crop", "फसल", "किसान", "farmer", "soil", "मिट्टी"],
    "Environment": ["pollution", "प्रदूषण", "forest", "पेड़", "climate", "plastic", "river", "नदी"],
    "Public Safety": ["crime", "चोरी", "accident", "दुर्घटना", "fire", "आग", "safety", "flood", "बाढ़"],
}
URGENT = ["urgent", "emergency", "death", "मौत", "accident", "दुर्घटना", "flood", "बाढ़", "fire", "आग",
          "outbreak", "epidemic", "contaminated", "danger", "खतरा"]
SKILLS = {
    "Water": ["water", "civil", "irrigation", "hydrology", "environmental", "iot"],
    "Roads & Transport": ["civil", "transport", "roads", "traffic", "gis", "software"],
    "Electricity": ["electrical", "power", "solar", "energy", "electronics", "iot"],
    "Sanitation & Waste": ["civil", "environmental", "waste", "chemical", "biotech"],
    "Health": ["medical", "health", "biotech", "biomedical", "pharmacy", "software", "ai"],
    "Education": ["education", "software", "elearning", "ai", "computer"],
    "Agriculture": ["agriculture", "agri", "iot", "biotech", "soil", "ai"],
    "Environment": ["environmental", "climate", "chemical", "civil", "iot", "gis"],
    "Public Safety": ["software", "ai", "civil", "electronics", "security", "gis"],
}
ALLOWED_CATS = list(CATS) + ["Other"]


def tok(s):
    return set(re.findall(r"[^\s,.;:!?()\-/]+", (s or "").lower()))


def ai_triage(title, desc):
    """Keyword-based triage — deterministic, offline, no external API needed.
    (An ANTHROPIC_API_KEY hook can be layered on top of this later if desired.)"""
    text = f"{title}. {desc}"
    t = text.lower()
    scores = {c: sum(k in t for k in ks) for c, ks in CATS.items()}
    cat = max(scores, key=scores.get) if any(scores.values()) else "Other"
    urgent = sum(k in t for k in URGENT)
    if urgent >= 2 or (urgent and cat in ("Health", "Public Safety", "Water")):
        prio = "High"
    elif urgent or len(t) > 300:
        prio = "Medium"
    else:
        prio = "Low"
    return {"category": cat, "priority": prio, "summary": text[:140]}


def match_colleges(p, top=3):
    words = tok(f"{p['title']} {p['description']} {p['category']}") | set(SKILLS.get(p["category"], []))
    ranked = []
    for c in q("SELECT id,expertise FROM users WHERE role='college'"):
        ex = tok(c["expertise"])
        ranked.append((c["id"], round(len(words & ex) / (len(ex) or 1), 3)))
    ranked.sort(key=lambda x: -x[1])
    return ranked[:top]


# --------------------------------------------------------------------- routes
def route_register(body):
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    role = body.get("role") or ""
    org = (body.get("org") or "").strip()
    expertise = (body.get("expertise") or "").strip()
    if role not in ROLES:
        raise ApiError(400, "Invalid role")
    if len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters")
    if not name or not email:
        raise ApiError(400, "Name and email are required")
    salt = secrets.token_hex(8)
    try:
        uid = q("INSERT INTO users(name,email,pw,salt,role,org,expertise) VALUES(?,?,?,?,?,?,?)",
                (name, email, hash_pw(password, salt), salt, role, org, expertise))
    except sqlite3.IntegrityError:
        raise ApiError(409, "Email already registered")
    return {"token": make_token(uid),
            "user": q("SELECT id,name,email,role,org FROM users WHERE id=?", (uid,), one=True)}


def route_login(body):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    u = q("SELECT * FROM users WHERE email=?", (email,), one=True)
    if not u or hash_pw(password, u["salt"]) != u["pw"]:
        raise ApiError(401, "Wrong email or password")
    return {"token": make_token(u["id"]),
            "user": {k: u[k] for k in ("id", "name", "email", "role", "org")}}


def route_create_problem(u, body):
    require_role(u, "citizen")
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    location = (body.get("location") or "").strip()
    if len(title) < 5 or len(description) < 10:
        raise ApiError(400, "Please describe the problem in more detail")
    ai = ai_triage(title, description)
    pid = q("INSERT INTO problems(citizen_id,title,description,location,category,priority,ai_summary,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (u["id"], title, description, location, ai["category"], ai["priority"], ai["summary"],
             "submitted", time.time()))
    log_event(pid, "submitted", u["name"], f"AI: {ai['category']} / {ai['priority']}", set_status=False)
    return {"id": pid, **ai}


def route_list_problems(u, qs):
    sql = "SELECT p.*, c.name AS citizen FROM problems p JOIN users c ON c.id=p.citizen_id WHERE 1=1"
    args = []
    if u["role"] == "citizen":
        sql += " AND p.citizen_id=?"; args.append(u["id"])
    elif u["role"] == "college":
        sql += " AND (p.college_id=? OR p.id IN (SELECT problem_id FROM matches WHERE college_id=?))"
        args += [u["id"], u["id"]]
    elif u["role"] == "industry":
        sql += " AND p.status IN ('in_progress','solution_submitted','funded','approved','implemented')"
    status = (qs.get("status") or [None])[0]
    if status:
        sql += " AND p.status=?"; args.append(status)
    sql += " ORDER BY CASE p.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, p.created_at DESC"
    return q(sql, tuple(args))


def route_problem_detail(u, pid):
    p = q("SELECT p.*, c.name AS citizen FROM problems p JOIN users c ON c.id=p.citizen_id WHERE p.id=?",
          (pid,), one=True)
    if not p:
        raise ApiError(404, "Problem not found")
    if u["role"] == "citizen" and p["citizen_id"] != u["id"]:
        raise ApiError(403, "Not your problem")
    p["matches"] = q("SELECT m.score, c.id AS college_id, c.name, c.org FROM matches m "
                      "JOIN users c ON c.id=m.college_id WHERE m.problem_id=? ORDER BY m.score DESC", (pid,))
    p["solutions"] = q("SELECT s.*, c.org AS college FROM solutions s JOIN users c ON c.id=s.college_id "
                        "WHERE s.problem_id=? ORDER BY s.id", (pid,))
    p["support"] = q("SELECT s.*, i.org AS industry, i.name AS industry_name FROM support s "
                      "JOIN users i ON i.id=s.industry_id WHERE s.problem_id=? ORDER BY s.id", (pid,))
    p["feedback"] = q("SELECT rating, comment, created_at FROM feedback WHERE problem_id=?", (pid,))
    p["events"] = q("SELECT status, actor, note, at FROM events WHERE problem_id=? ORDER BY id", (pid,))
    return p


def route_verify(u, pid, body):
    require_role(u, "expert", "government")
    get_problem(pid, "submitted")
    approve = bool(body.get("approve"))
    note = body.get("note") or ""
    if not approve:
        log_event(pid, "rejected", u["name"], note)
        return {"ok": True}
    category = body.get("category")
    priority = body.get("priority")
    if category in ALLOWED_CATS:
        q("UPDATE problems SET category=? WHERE id=?", (category, pid))
    if priority in ("High", "Medium", "Low"):
        q("UPDATE problems SET priority=? WHERE id=?", (priority, pid))
    log_event(pid, "verified", u["name"], note)
    ms = match_colleges(get_problem(pid))
    for cid, score in ms:
        q("INSERT OR IGNORE INTO matches(problem_id,college_id,score) VALUES(?,?,?)", (pid, cid, score))
    if ms:
        log_event(pid, "matched", "AI", f"{len(ms)} colleges matched")
    return {"ok": True, "matches": ms}


def route_accept(u, pid):
    require_role(u, "college")
    get_problem(pid, "matched")
    if not q("SELECT 1 FROM matches WHERE problem_id=? AND college_id=?", (pid, u["id"]), one=True):
        raise ApiError(403, "This problem was not matched to your college")
    q("UPDATE problems SET college_id=? WHERE id=?", (u["id"], pid))
    log_event(pid, "in_progress", u["org"] or u["name"], "Students + faculty team started")
    return {"ok": True}


def route_solution(u, pid, body):
    require_role(u, "college")
    p = get_problem(pid, "in_progress")
    if p["college_id"] != u["id"]:
        raise ApiError(403, "Your college is not assigned to this problem")
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    team = (body.get("team") or "").strip()
    if not title or not description:
        raise ApiError(400, "Title and description are required")
    q("INSERT INTO solutions(problem_id,college_id,title,description,team,created_at) VALUES(?,?,?,?,?,?)",
      (pid, u["id"], title, description, team, time.time()))
    log_event(pid, "solution_submitted", u["org"] or u["name"], title)
    return {"ok": True}


def route_support(u, pid, body):
    require_role(u, "industry")
    kind = body.get("kind")
    if kind not in ("funding", "technology", "mentorship"):
        raise ApiError(400, "kind must be funding, technology or mentorship")
    get_problem(pid, "solution_submitted", "funded")
    amount = max(float(body.get("amount") or 0), 0)
    note = body.get("note") or ""
    q("INSERT INTO support(problem_id,industry_id,kind,amount,note,created_at) VALUES(?,?,?,?,?,?)",
      (pid, u["id"], kind, amount, note, time.time()))
    log_event(pid, "funded", u["org"] or u["name"], f"{kind} {amount or ''}".strip())
    return {"ok": True}


def route_decision(u, pid, body):
    require_role(u, "government")
    action = body.get("action")
    note = body.get("note") or ""
    if action == "approve":
        get_problem(pid, "solution_submitted", "funded"); log_event(pid, "approved", u["name"], note)
    elif action == "implement":
        get_problem(pid, "approved"); log_event(pid, "implemented", u["name"], note)
    elif action == "reject":
        get_problem(pid, "solution_submitted", "funded"); log_event(pid, "in_progress", u["name"], "Sent back: " + note)
    else:
        raise ApiError(400, "action must be approve, implement or reject")
    return {"ok": True}


def route_feedback(u, pid, body):
    require_role(u, "citizen")
    p = get_problem(pid, "implemented")
    if p["citizen_id"] != u["id"]:
        raise ApiError(403, "Not your problem")
    rating = int(body.get("rating") or 0)
    if not 1 <= rating <= 5:
        raise ApiError(400, "Rating must be 1 to 5")
    if q("SELECT 1 FROM feedback WHERE problem_id=? AND citizen_id=?", (pid, u["id"]), one=True):
        raise ApiError(409, "Feedback already given")
    comment = body.get("comment") or ""
    q("INSERT INTO feedback(problem_id,citizen_id,rating,comment,created_at) VALUES(?,?,?,?,?)",
      (pid, u["id"], rating, comment, time.time()))
    log_event(pid, "feedback", u["name"], f"{rating}/5", set_status=False)
    return {"ok": True}


def route_dashboard():
    def by(col):
        return {r["k"]: r["n"] for r in q(f"SELECT {col} AS k, COUNT(*) AS n FROM problems GROUP BY {col}")}
    fb = q("SELECT AVG(rating) AS a, COUNT(*) AS n FROM feedback", one=True)
    return {
        "total": q("SELECT COUNT(*) AS n FROM problems", one=True)["n"],
        "by_status": by("status"), "by_category": by("category"), "by_priority": by("priority"),
        "avg_rating": round(fb["a"] or 0, 2), "feedback_count": fb["n"],
        "funding_total": q("SELECT COALESCE(SUM(amount),0) AS t FROM support WHERE kind='funding'", one=True)["t"],
        "colleges": q("SELECT COUNT(*) AS n FROM users WHERE role='college'", one=True)["n"],
        "industries": q("SELECT COUNT(*) AS n FROM users WHERE role='industry'", one=True)["n"],
    }


PID_RE = r"(\d+)"
API_ROUTES = [
    ("POST", r"^/api/register$", lambda u, pid, body, qs: route_register(body), False),
    ("POST", r"^/api/login$", lambda u, pid, body, qs: route_login(body), False),
    ("POST", rf"^/api/problems$", lambda u, pid, body, qs: route_create_problem(u, body), True),
    ("GET", rf"^/api/problems$", lambda u, pid, body, qs: route_list_problems(u, qs), True),
    ("GET", rf"^/api/problems/{PID_RE}$", lambda u, pid, body, qs: route_problem_detail(u, pid), True),
    ("POST", rf"^/api/problems/{PID_RE}/verify$", lambda u, pid, body, qs: route_verify(u, pid, body), True),
    ("POST", rf"^/api/problems/{PID_RE}/accept$", lambda u, pid, body, qs: route_accept(u, pid), True),
    ("POST", rf"^/api/problems/{PID_RE}/solution$", lambda u, pid, body, qs: route_solution(u, pid, body), True),
    ("POST", rf"^/api/problems/{PID_RE}/support$", lambda u, pid, body, qs: route_support(u, pid, body), True),
    ("POST", rf"^/api/problems/{PID_RE}/decision$", lambda u, pid, body, qs: route_decision(u, pid, body), True),
    ("POST", rf"^/api/problems/{PID_RE}/feedback$", lambda u, pid, body, qs: route_feedback(u, pid, body), True),
    ("GET", r"^/api/dashboard$", lambda u, pid, body, qs: route_dashboard(), True),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "JanSamadhan/1.0"

    def log_message(self, fmt, *args):
        pass  # keep console clean; flip on for debugging

    def _send_json(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)

        if not path.startswith("/api/"):
            return self._serve_static(path)

        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    return self._send_json(400, {"detail": "Invalid JSON body"})

        for m, pattern, fn, needs_auth in API_ROUTES:
            if m != method:
                continue
            match = re.match(pattern, path)
            if not match:
                continue
            try:
                u = current_user(self.headers) if needs_auth else None
                pid = int(match.group(1)) if match.groups() else None
                result = fn(u, pid, body, qs)
                return self._send_json(200, result)
            except ApiError as e:
                return self._send_json(e.code, {"detail": e.message})
            except Exception as e:  # pragma: no cover - defensive
                return self._send_json(500, {"detail": f"Server error: {e}"})
        self._send_json(404, {"detail": "Not found"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        safe = (FRONTEND_DIR / path.lstrip("/")).resolve()
        if FRONTEND_DIR not in safe.parents and safe != FRONTEND_DIR:
            return self._send_json(403, {"detail": "Forbidden"})
        if not safe.exists() or not safe.is_file():
            return self._send_json(404, {"detail": "Not found"})
        ctype = mimetypes.guess_type(str(safe))[0] or "application/octet-stream"
        data = safe.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    def seed_db():
    # Only create if the database is empty
    if q("SELECT COUNT(*) AS n FROM users", one=True)["n"] == 0:
        demo_users = [
            ("Demo Citizen", "citizen@demo.com", "citizen", ""),
            ("Demo Expert", "expert@demo.com", "expert", "civil, water"),
            ("Demo College", "college@demo.com", "college", "software, ai"),
            ("Demo Industry", "industry@demo.com", "industry", ""),
            ("Demo Gov", "gov@demo.com", "government", "")
        ]
        for name, email, role, exp in demo_users:
            salt = secrets.token_hex(8)
            q("INSERT INTO users(name,email,pw,salt,role,expertise) VALUES(?,?,?,?,?,?)",
              (name, email, hash_pw("123456", salt), salt, role, exp))
            
    init_db()
    seed_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Jan Samadhan running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
