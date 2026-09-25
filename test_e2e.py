"""End-to-end test — runs the full nine-step Jan Samadhan pipeline against a live server.
Usage: python3 test_e2e.py [base_url]
"""
import sys, time, random, requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011"
FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILS.append(name)


def register(role, org="", expertise=""):
    email = f"{role}.{random.randint(100000,999999)}@example.com"
    r = requests.post(f"{BASE}/api/register", json={
        "name": role.title() + " Test", "email": email, "password": "password123",
        "role": role, "org": org, "expertise": expertise,
    })
    check(f"register {role}", r.status_code == 200, r.text[:200])
    d = r.json()
    return d["token"], d["user"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    # 1) five accounts, one per role
    citizen_tok, citizen = register("citizen")
    expert_tok, expert = register("expert")
    college_tok, college = register("college", org="ABC Institute of Technology",
                                     expertise="water, civil, iot, environmental")
    industry_tok, industry = register("industry", org="RuralTech Startup")
    gov_tok, gov = register("government", org="Dept. of Higher & Technical Education")

    # duplicate-email registration must fail
    r = requests.post(f"{BASE}/api/register", json={
        "name": "dup", "email": citizen["email"], "password": "password123", "role": "citizen"})
    check("duplicate email rejected", r.status_code == 409)

    # wrong password login must fail
    r = requests.post(f"{BASE}/api/login", json={"email": citizen["email"], "password": "wrongpass"})
    check("wrong password rejected", r.status_code == 401)

    # correct login
    r = requests.post(f"{BASE}/api/login", json={"email": citizen["email"], "password": "password123"})
    check("citizen login", r.status_code == 200)

    # 2) citizen submits a problem -> AI triage
    r = requests.post(f"{BASE}/api/problems", headers=auth(citizen_tok), json={
        "title": "Water shortage in village",
        "description": "Tanker urgent, no clean water for three days, borewell dry.",
        "location": "Test Village, Jharkhand",
    })
    check("submit problem", r.status_code == 200, r.text[:200])
    pid = r.json()["id"]
    check("AI triage assigned Water category", r.json()["category"] == "Water", r.json())
    check("AI triage assigned a priority", r.json()["priority"] in ("High", "Medium", "Low"))

    # a non-citizen cannot submit a problem
    r = requests.post(f"{BASE}/api/problems", headers=auth(expert_tok), json={
        "title": "Should fail", "description": "Wrong role tries to submit a problem here."})
    check("non-citizen cannot submit problem", r.status_code == 403)

    # 3) expert verifies -> 4) AI matches colleges
    r = requests.post(f"{BASE}/api/problems/{pid}/verify", headers=auth(expert_tok),
                       json={"approve": True, "note": "Looks legitimate"})
    check("expert verifies", r.status_code == 200, r.text[:200])
    check("AI matched at least one college", len(r.json().get("matches", [])) >= 1, r.json())

    detail = requests.get(f"{BASE}/api/problems/{pid}", headers=auth(citizen_tok)).json()
    check("status is 'matched' after verification", detail["status"] == "matched", detail["status"])
    check("matched college has our college id", any(m["college_id"] == college["id"] for m in detail["matches"]))

    # 5) college accepts and builds a solution
    r = requests.post(f"{BASE}/api/problems/{pid}/accept", headers=auth(college_tok))
    check("college accepts problem", r.status_code == 200, r.text[:200])

    r = requests.post(f"{BASE}/api/problems/{pid}/solution", headers=auth(college_tok), json={
        "title": "IoT water-level + purification unit",
        "description": "Low-cost IoT sensor network plus a solar purification unit for the village.",
        "team": "3 students + 1 faculty mentor",
    })
    check("college submits solution", r.status_code == 200, r.text[:200])

    # 6) industry supports with funding
    r = requests.post(f"{BASE}/api/problems/{pid}/support", headers=auth(industry_tok), json={
        "kind": "funding", "amount": 50000, "note": "CSR grant",
    })
    check("industry supports with funding", r.status_code == 200, r.text[:200])

    # 7) government approves, then implements
    r = requests.post(f"{BASE}/api/problems/{pid}/decision", headers=auth(gov_tok),
                       json={"action": "approve", "note": "Approved for rollout"})
    check("government approves", r.status_code == 200, r.text[:200])

    r = requests.post(f"{BASE}/api/problems/{pid}/decision", headers=auth(gov_tok),
                       json={"action": "implement", "note": "Deployed in the field"})
    check("government marks implemented", r.status_code == 200, r.text[:200])

    # 8) citizen gives feedback
    r = requests.post(f"{BASE}/api/problems/{pid}/feedback", headers=auth(citizen_tok), json={
        "rating": 5, "comment": "Water is flowing again, thank you!",
    })
    check("citizen gives feedback", r.status_code == 200, r.text[:200])

    # duplicate feedback must be rejected
    r = requests.post(f"{BASE}/api/problems/{pid}/feedback", headers=auth(citizen_tok), json={
        "rating": 4, "comment": "again"})
    check("duplicate feedback rejected", r.status_code == 409)

    # 9) dashboard reflects everything
    r = requests.get(f"{BASE}/api/dashboard", headers=auth(gov_tok))
    check("dashboard reachable", r.status_code == 200)
    dash = r.json()
    check("dashboard shows implemented problem", dash["by_status"].get("implemented", 0) >= 1, dash["by_status"])
    check("dashboard shows funding total", dash["funding_total"] >= 50000, dash["funding_total"])
    check("dashboard shows avg rating", dash["avg_rating"] > 0, dash["avg_rating"])

    # full detail record sanity check
    final = requests.get(f"{BASE}/api/problems/{pid}", headers=auth(gov_tok)).json()
    check("final status is implemented", final["status"] == "implemented", final["status"])
    check("event timeline has all 8 stages", len(final["events"]) >= 8, len(final["events"]))
    check("solution recorded", len(final["solutions"]) == 1)
    check("support recorded", len(final["support"]) == 1)
    check("feedback recorded", len(final["feedback"]) == 1)

    # role-based visibility: another citizen must not see this problem in "mine"
    other_tok, other = register("citizen")
    others_list = requests.get(f"{BASE}/api/problems", headers=auth(other_tok)).json()
    check("other citizen cannot see this problem", all(p["id"] != pid for p in others_list))

    print(f"\n{len(FAILS)} failing checks out of a full run." if FAILS else "\nALL CHECKS PASSED.")
    if FAILS:
        print("Failed:", FAILS)
        sys.exit(1)


if __name__ == "__main__":
    main()
