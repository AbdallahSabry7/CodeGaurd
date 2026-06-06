"""
Calibration test suite for the improved SRP analyzer.
Each fixture is a named module-level constant; the examples list drives the runner.
"""
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from SRP_Detection_Final import get_srp_report

# ── SRP001 VIOLATION — body-blind: generic method names hide cross-domain calls ──
SRP001_VIOLATION = """
class OrderProcessor:
    def __init__(self):
        self.db = Database()
        self.mailer = Mailer()
        self.renderer = HtmlRenderer()

    def process(self, order_id):
        record = self.db.query("SELECT * FROM orders WHERE id=?", order_id)
        self.renderer.render("order_template", record)
        self.mailer.send(record["email"], "Your order", "Done")

    def handle(self, event):
        data = self.db.query("SELECT * FROM events WHERE id=?", event)
        self.mailer.send(data["contact"], "Event", str(data))
        self.renderer.render("event_template", data)
"""

SRP001_PASS = """
class OrderProcessor:
    def __init__(self):
        self.db = Database()

    def process(self, order_id):
        return self.db.query("SELECT * FROM orders WHERE id=?", order_id)

    def handle(self, order_id):
        return self.db.update(order_id, {"status": "handled"})
"""

# ── SRP002 VIOLATION — constructor injects 5 cross-domain collaborators ──────
SRP002_VIOLATION = """
class GodService:
    def __init__(self, db, mailer, renderer, auth, validator):
        self.db = db
        self.mailer = mailer
        self.renderer = renderer
        self.auth = auth
        self.validator = validator

    def run(self, payload):
        if self.auth.check(payload["token"]):
            if self.validator.validate(payload):
                self.db.save(payload)
                self.mailer.send(payload["email"], "ok", "done")
                return self.renderer.render("success", payload)
"""

SRP002_PASS = """
class AuthenticatedSaver:
    def __init__(self, db, auth):
        self.db = db
        self.auth = auth

    def run(self, payload):
        if self.auth.check(payload["token"]):
            self.db.save(payload)
"""

# ── SRP003 VIOLATION — disjoint collaborators: db used by persistence methods,
#                       mailer used only by notification methods ─────────────
SRP003_VIOLATION = """
class MixedService:
    def __init__(self):
        self.db = Database()
        self.mailer = Mailer()
        self.name = "service"

    def save_record(self, data):
        return self.db.insert(data)

    def delete_record(self, rid):
        self.db.delete(rid)

    def send_confirmation(self, email, body):
        self.mailer.send(email, "Confirm", body)

    def send_digest(self, emails, summary):
        for e in emails:
            self.mailer.send(e, "Digest", summary)
"""

SRP003_PASS = """
class RecordStore:
    def __init__(self):
        self.db = Database()

    def save_record(self, data):
        return self.db.insert(data)

    def delete_record(self, rid):
        self.db.delete(rid)
"""

# ── SRP004 VIOLATION — And/Or in method names signals split responsibilities ─
SRP004_VIOLATION = """
class Processor:
    def validateAndSave(self, data):
        if data.get("id"):
            self.store.save(data)

    def fetchAndRender(self, uid):
        row = self.store.get(uid)
        return self.view.render(row)
"""

SRP004_PASS = """
class Validator:
    def validate(self, data):
        return bool(data.get("id"))

    def sanitize(self, data):
        return {k: v for k, v in data.items() if v is not None}
"""

# ── SRP005 VIOLATION — cross-domain thin delegators must NOT get discount ────
SRP005_VIOLATION = """
class ShipOrder:
    def __init__(self):
        self.db = Database()
        self.mailer = Mailer()
        self.renderer = HtmlRenderer()

    def execute(self, order_id):
        self.db.save({"id": order_id, "status": "shipped"})
        self.mailer.send("user@example.com", "Shipped", "Your order shipped")

    def notify_and_persist(self, user_id, message):
        self.db.update(user_id, {"notified": True})
        self.mailer.send("x@x.com", "note", message)

    def prepare_and_dispatch(self, payload):
        self.renderer.render("invoice", payload)
        self.mailer.send(payload["email"], "Invoice", "see attachment")
"""

SRP005_PASS = """
class OrderShipper:
    def __init__(self):
        self.db = Database()

    def execute(self, order_id):
        self.db.save({"id": order_id, "status": "shipped"})

    def cancel(self, order_id):
        self.db.update(order_id, {"status": "cancelled"})
"""

# ── EDGE1 VIOLATION — custom weights accepted; body_domain_div boosted ───────
EDGE1_CUSTOM_WEIGHTS_VIOLATION = """
class DataService:
    def __init__(self):
        self.db = Database()
        self.mailer = Mailer()

    def get_user(self, uid): return self.db.find(uid)
    def save_user(self, u): self.db.save(u)
    def notify_user(self, uid, msg): self.mailer.send(uid, "note", msg)
"""

EDGE1_CUSTOM_WEIGHTS_PASS = """
class DataService:
    def __init__(self):
        self.db = Database()

    def get_user(self, uid): return self.db.find(uid)
    def save_user(self, u): self.db.save(u)
    def delete_user(self, uid): self.db.delete(uid)
"""

# ── EDGE2 VIOLATION — stateless utility must not be penalised ────────────────
EDGE2_STATELESS_PASS = """
class StringUtils:
    @staticmethod
    def slugify(text):
        return text.lower().replace(" ", "-")

    @staticmethod
    def truncate(text, max_len):
        return text[:max_len] + "..." if len(text) > max_len else text

    @staticmethod
    def capitalize_words(text):
        return " ".join(w.capitalize() for w in text.split())
"""

# ── EDGE3 VIOLATION — pure persistence repo must always pass ─────────────────
EDGE3_COHESIVE_REPO_PASS = """
class UserRepository:
    def __init__(self):
        self.db = Database()

    def find(self, uid):
        return self.db.query("SELECT * FROM users WHERE id=?", uid)

    def save(self, user):
        self.db.insert("users", user)

    def delete(self, uid):
        self.db.delete("users", uid)

    def list_all(self):
        return self.db.query("SELECT * FROM users")
"""


# ── Test runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    examples = [
        # ── violations ───────────────────────────────────────────────────────
        ("SRP001 VIOLATION — body-blind generic methods     (OrderProcessor)", SRP001_VIOLATION,              "Violation"),
        ("SRP002 VIOLATION — constructor injects 5 deps     (GodService)",     SRP002_VIOLATION,              "Violation"),
        ("SRP003 VIOLATION — disjoint collaborator usage    (MixedService)",   SRP003_VIOLATION,              "Violation"),
        ("SRP004 VIOLATION — And/Or method names            (Processor)",      SRP004_VIOLATION,              "Review"),
        ("SRP005 VIOLATION — cross-domain thin delegators   (ShipOrder)",      SRP005_VIOLATION,              "Violation"),
        ("EDGE1  VIOLATION — custom weights accepted        (DataService)",     EDGE1_CUSTOM_WEIGHTS_VIOLATION,"Violation"),
        # ── clean passes ─────────────────────────────────────────────────────
        ("SRP001 PASS      — single-domain body             (OrderProcessor)", SRP001_PASS,                   "Pass"),
        ("SRP002 PASS      — two focused collaborators      (AuthenticatedSaver)", SRP002_PASS,               "Pass"),
        ("SRP003 PASS      — persistence-only methods       (RecordStore)",    SRP003_PASS,                   "Pass"),
        ("SRP004 PASS      — single-concern validation      (Validator)",      SRP004_PASS,                   "Pass"),
        ("SRP005 PASS      — single-domain delegators       (OrderShipper)",   SRP005_PASS,                   "Pass"),
        ("EDGE1  PASS      — custom weights, cohesive       (DataService)",    EDGE1_CUSTOM_WEIGHTS_PASS,     "Pass"),
        ("EDGE2  PASS      — stateless utility              (StringUtils)",    EDGE2_STATELESS_PASS,          "Pass"),
        ("EDGE3  PASS      — pure persistence repo          (UserRepository)", EDGE3_COHESIVE_REPO_PASS,      "Pass"),
    ]

    passed = failed = 0
    failures = []

    for title, code, expected in examples:
        # EDGE1 uses custom weights to verify FIX 2
        weights = {"body_domain_div": 0.50, "lcom": 0.10} if "EDGE1" in title else None
        report = get_srp_report(code, weights=weights)
        result = report[0] if report else {}
        got    = result.get("status", "Error")
        ok     = (got == expected)
        symbol = "✓" if ok else "✗"

        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((title, expected, got, result.get("reason", "")))

        print(f"\n{'═' * 74}")
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<10}  Got: {got}   Score: {result.get('score', '—')}%")
        print('═' * 74)

        diag = result.get("diagnostics", {})
        ctor = result.get("constructor", {})

        if got in ("Violation", "Review"):
            fired: list[str] = []
            bdd = diag.get("effective_body_domain_div", 0)
            if bdd > 0.2:
                bd = diag.get("body_detected_domains", [])
                fired.append(f"body-detected domains: {', '.join(bd)}")
            if diag.get("effective_domain_div", 0) > 0.2:
                nd = diag.get("detected_domains", [])
                fired.append(f"name-inferred domains: {', '.join(nd)}")
            if diag.get("lcom", 0) > 0.5:
                collabs = diag.get("collaborator_attrs", [])
                fired.append(f"disjoint collaborators: {', '.join(collabs[:4]) or 'none tracked'}")
            if ctor.get("injection_score", 0) > 0.3:
                fired.append(
                    f"constructor injects {ctor.get('collaborator_count', 0)} collaborators "
                    f"across domains: {', '.join(ctor.get('injected_domains', []))}"
                )
            if diag.get("responsibility_factor", 0) > 0:
                fired.append("'And'/'Or' in method names")
            safe_r = diag.get("safe_delegator_ratio", 0)
            all_r  = diag.get("delegator_ratio", 0)
            if all_r > 0 and safe_r < all_r:
                fired.append(
                    f"cross-domain thin delegators "
                    f"({int((all_r - safe_r) * 100)}% of methods — penalty NOT reduced)"
                )

            for i, detail in enumerate(fired, 1):
                tag = f"SRP{i:03d}" if i <= 5 else "EDGE "
                print(f"  [{tag}]  {detail}")
        else:
            print(f"  {result.get('reason', 'No violations detected.')}")

        if diag.get("weights_used"):
            w = diag["weights_used"]
            print(f"  Weights   : body_div={w.get('body_domain_div', '—'):.2f}  "
                  f"lcom={w.get('lcom', '—'):.2f}  "
                  f"domain_div={w.get('effective_domain_div', '—'):.2f}  "
                  f"obj_div={w.get('object_diversity', '—'):.2f}")

    print(f"\n{'═' * 74}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(examples)} examples")

    if failures:
        print("\n  FAILURES:")
        for title, exp, got, reason in failures:
            print(f"    ✗ {title}")
            print(f"      Expected {exp!r}, got {got!r}")
            print(f"      Reason: {reason}")
        sys.exit(1)
    else:
        print("\n  All tests passed ✓")
        sys.exit(0)