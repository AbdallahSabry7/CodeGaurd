import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from ISP_detect import get_isp_report


RULE1_VIOLATION = """
from abc import ABC

class IAnimal(ABC):
    def eat(self): pass
    def sleep(self): pass
    def run(self): pass
    def swim(self): pass
    def fly(self): pass
    def climb(self): pass
    def hunt(self): pass
    def migrate(self): pass
    def hibernate(self): pass
"""

RULE1_PASS = """
from abc import ABC

class ISwimmable(ABC):
    def swim(self): pass

class IFlyable(ABC):
    def fly(self): pass

class Duck(ISwimmable, IFlyable):
    def swim(self):
        print("swimming")
    def fly(self):
        print("flying")
"""

# ── Rule 2: Responsibility Mixing ────────────────────────────
RULE2_VIOLATION = """
from abc import ABC

class IUserService(ABC):
    def login(self, user, password): pass
    def logout(self, user): pass
    def send_email(self, user, message): pass
    def cache_session(self, token): pass
    def log_activity(self, user, action): pass
    def render_profile(self, user): pass
"""

RULE2_PASS = """
from abc import ABC

class IAuthService(ABC):
    def login(self, user, password): pass
    def logout(self, user): pass

class IEmailService(ABC):
    def send_email(self, user, message): pass

class IProfileRenderer(ABC):
    def render_profile(self, user): pass
"""

# ── Rule 3: Parameter Bloat ───────────────────────────────────
RULE3_VIOLATION = """
from abc import ABC

class IReportBuilder(ABC):
    def build(self, title, author, date, footer, header, font, page_size): pass
    def export(self, path, fmt, dpi, compress, encrypt, watermark): pass
"""

RULE3_PASS = """
from abc import ABC
from dataclasses import dataclass

@dataclass
class ReportConfig:
    title: str
    author: str
    date: str

class IReportBuilder(ABC):
    def build(self, config: ReportConfig): pass
    def export(self, path: str): pass
"""

# ── Rule 4: Unused Interface Methods ─────────────────────────
RULE4_VIOLATION = """
from abc import ABC

class IRepository(ABC):
    def find_by_id(self, id): pass
    def find_all(self): pass
    def save(self, entity): pass
    def delete(self, id): pass
    def count(self): pass
    def exists(self, id): pass

class ReadOnlyCache(IRepository):
    def find_by_id(self, id):
        return self._cache.get(id)
    def find_all(self):
        return list(self._cache.values())
    def save(self, entity):
        raise NotImplementedError
    def delete(self, id):
        raise NotImplementedError
    def count(self):
        raise NotImplementedError
    def exists(self, id):
        raise NotImplementedError
"""

RULE4_PASS = """
from abc import ABC

class IReadable(ABC):
    def find_by_id(self, id): pass
    def find_all(self): pass

class ReadOnlyCache(IReadable):
    def find_by_id(self, id):
        return self._cache.get(id)
    def find_all(self):
        return list(self._cache.values())
"""

# ── Rule 5: Forced Implementation ────────────────────────────
RULE5_VIOLATION = """
from abc import ABC

class IFullCRUD(ABC):
    def create(self, data): pass
    def read(self, id): pass
    def update(self, id, data): pass
    def delete(self, id): pass
    def bulk_delete(self, ids): pass

class LogViewer(IFullCRUD):
    def create(self, data):
        pass
    def read(self, id):
        return self._logs.get(id)
    def update(self, id, data):
        pass
    def delete(self, id):
        pass
    def bulk_delete(self, ids):
        pass
"""

RULE5_PASS = """
from abc import ABC

class IReadable(ABC):
    def read(self, id): pass

class LogViewer(IReadable):
    def read(self, id):
        return self._logs.get(id)
"""

# ── Rule 6: Client Role Segregation ──────────────────────────
RULE6_VIOLATION = """
from abc import ABC

class IMediaPlayer(ABC):
    def play(self): pass
    def pause(self): pass
    def stop(self): pass
    def record(self): pass
    def encode(self): pass
    def stream(self): pass

class AudioPlayer(IMediaPlayer):
    def play(self):
        self._audio.start()
    def pause(self):
        self._audio.pause()
    def stop(self):
        self._audio.stop()
    def record(self):
        raise NotImplementedError
    def encode(self):
        raise NotImplementedError
    def stream(self):
        raise NotImplementedError
"""

RULE6_PASS = """
from abc import ABC

class IPlayable(ABC):
    def play(self): pass
    def pause(self): pass
    def stop(self): pass

class AudioPlayer(IPlayable):
    def play(self):
        self._audio.start()
    def pause(self):
        self._audio.pause()
    def stop(self):
        self._audio.stop()
"""

# ── Rule 7: Cross-Class Disjoint Usage ───────────────────────
RULE7_VIOLATION = """
from abc import ABC

class IDocument(ABC):
    def read_text(self): pass
    def read_metadata(self): pass
    def write_text(self, text): pass
    def write_metadata(self, meta): pass
    def render_pdf(self): pass
    def render_html(self): pass

class TextExtractor(IDocument):
    def read_text(self):
        return self._doc.text()
    def read_metadata(self):
        return self._doc.meta()
    def write_text(self, text): pass
    def write_metadata(self, meta): pass
    def render_pdf(self): pass
    def render_html(self): pass

class HtmlRenderer(IDocument):
    def read_text(self): pass
    def read_metadata(self): pass
    def write_text(self, text): pass
    def write_metadata(self, meta): pass
    def render_pdf(self): pass
    def render_html(self):
        return self._engine.to_html(self._doc)
"""

RULE7_PASS = """
from abc import ABC

class IDocumentReader(ABC):
    def read_text(self): pass
    def read_metadata(self): pass

class IHtmlRenderer(ABC):
    def render_html(self): pass

class TextExtractor(IDocumentReader):
    def read_text(self):
        return self._doc.text()
    def read_metadata(self):
        return self._doc.meta()

class HtmlRenderer(IHtmlRenderer):
    def render_html(self):
        return self._engine.to_html(self._doc)
"""

# ── Rule 8: Standalone Class Role Mixing ─────────────────────
RULE8_VIOLATION = """
class TelephoneDirectory:
    def __init__(self):
        self.telephonedirectory = {}
    def add_entry(self, name, number):
        self.telephonedirectory[name] = number
    def delete_entry(self, name):
        self.telephonedirectory.pop(name)
    def update_entry(self, name, number):
        self.telephonedirectory[name] = number
    def lookup_number(self, name):
        return self.telephonedirectory[name]
    def search_by_prefix(self, prefix):
        return {k: v for k, v in self.telephonedirectory.items() if k.startswith(prefix)}
    def render_display(self, fmt):
        return "\\n".join(f"{k}: {v}" for k, v in self.telephonedirectory.items())
    def display_summary(self):
        print(f"Total entries: {len(self.telephonedirectory)}")
"""

RULE8_PASS = """
class TelephoneDirectory:
    def __init__(self):
        self._data = {}
    def add_entry(self, name, number):
        self._data[name] = number
    def delete_entry(self, name):
        self._data.pop(name)
    def update_entry(self, name, number):
        self._data[name] = number
    def lookup_number(self, name):
        return self._data[name]
"""

# ── Rule 9: Type-Dispatch Multiplexing ───────────────────────
RULE9_VIOLATION = """
class Writer:
    def __init__(self, type: int) -> None:
        self.type = type

    def write(self, contents: bytearray):
        if self.type == 0:
            with open("random_file.txt", "w") as output_file:
                output_file.write(contents)
        elif self.type == 1:
            self.some_socket.write(contents)
        elif self.type == 2:
            self.db.write()
"""

RULE9_PASS = """
from abc import ABC

class IWriter(ABC):
    def write(self, contents: bytearray): pass

class FileWriter(IWriter):
    def write(self, contents: bytearray):
        with open("random_file.txt", "w") as f:
            f.write(contents)

class SocketWriter(IWriter):
    def write(self, contents: bytearray):
        self.socket.write(contents)

class DatabaseWriter(IWriter):
    def write(self, contents: bytearray):
        self.db.write(contents)
"""

# ── Rule 10: Interface Inheritance Depth ─────────────────────
RULE10_VIOLATION = """
from abc import ABC

class IBase(ABC):
    def base_op(self): pass

class IMid(IBase):
    def mid_op(self): pass

class ILeaf(IMid):
    def leaf_op(self): pass

class IDeep(ILeaf):
    def deep_op(self): pass
"""

RULE10_PASS = """
from abc import ABC

class IReader(ABC):
    def read(self): pass

class IWriter(ABC):
    def write(self, data): pass

class IReadWrite(IReader, IWriter):
    pass
"""

# ── Rule 11: Optional Method Pattern ─────────────────────────
RULE11_VIOLATION = """
from abc import ABC

class IWorker(ABC):
    def work(self): pass
    def stop(self): pass
    def pause(self): pass
    def status(self): pass

class SimpleWorker(IWorker):
    def work(self):
        print("working")
    def stop(self):
        print("stopped")
    def pause(self):
        return False
    def status(self):
        return 0
"""

RULE11_PASS = """
from abc import ABC

class IBasicWorker(ABC):
    def work(self): pass
    def stop(self): pass

class SimpleWorker(IBasicWorker):
    def work(self):
        print("working")
    def stop(self):
        print("stopped")
"""

# ── Rule 12: Boolean Flag Dispatch ───────────────────────────
RULE12_VIOLATION = """
class DataFetcher:
    def __init__(self, use_cache: bool):
        self.use_cache = use_cache

    def fetch(self, key):
        if self.use_cache:
            return self._cache.get(key)
        return self._db.get(key)

    def invalidate(self, key):
        if self.use_cache:
            self._cache.delete(key)
        else:
            pass

    def stats(self):
        if self.use_cache:
            return self._cache.stats()
        return {}
"""

RULE12_PASS = """
class DbFetcher:
    def fetch(self, key):
        return self._db.get(key)
    def invalidate(self, key):
        pass
    def stats(self):
        return {}

class CachedFetcher:
    def fetch(self, key):
        return self._cache.get(key)
    def invalidate(self, key):
        self._cache.delete(key)
    def stats(self):
        return self._cache.stats()
"""

# ── Rule 13: God Class ────────────────────────────────────────
RULE13_VIOLATION = """
class UserManager:
    def create_user(self, name, email): pass
    def delete_user(self, user_id): pass
    def update_user(self, user_id, data): pass
    def get_user(self, user_id): pass
    def list_users(self): pass
    def authenticate(self, email, password): pass
    def reset_password(self, user_id): pass
    def send_welcome_email(self, user_id): pass
    def log_activity(self, user_id, action): pass
    def export_users_csv(self): pass
    def import_users_csv(self, file_path): pass
"""

RULE13_PASS = """
class UserRepository:
    def create(self, name, email): pass
    def delete(self, user_id): pass
    def update(self, user_id, data): pass
    def get(self, user_id): pass
    def list_all(self): pass

class AuthService:
    def authenticate(self, email, password): pass
    def reset_password(self, user_id): pass

class UserNotifier:
    def send_welcome_email(self, user_id): pass
"""

# ── Rule 14: Coarse-Grained Parameter Dependency ─────────────
RULE14_VIOLATION = """
from abc import ABC

class IStorage(ABC):
    def read(self, key): pass
    def write(self, key, value): pass
    def delete(self, key): pass
    def list_keys(self): pass
    def exists(self, key): pass
    def clear(self): pass

class ReportGenerator:
    def generate(self, storage: IStorage, report_id: str):
        data = storage.read(report_id)
        return data
"""

RULE14_PASS = """
from abc import ABC

class IReadable(ABC):
    def read(self, key): pass

class ReportGenerator:
    def generate(self, storage: IReadable, report_id: str):
        data = storage.read(report_id)
        return data
"""


if __name__ == "__main__":
    examples = [
        # ── violations ───────────────────────────────────────────
        ("Rule 1  VIOLATION — Fat Interface          (IAnimal)",            RULE1_VIOLATION,  "Violation"),
        ("Rule 2  VIOLATION — Responsibility Mixing  (IUserService)",       RULE2_VIOLATION,  "Violation"),
        ("Rule 3  VIOLATION — Parameter Bloat        (IReportBuilder)",     RULE3_VIOLATION,  "Violation"),
        ("Rule 4  VIOLATION — Unused Interface Meth  (ReadOnlyCache)",      RULE4_VIOLATION,  "Violation"),
        ("Rule 5  VIOLATION — Forced Implementation  (LogViewer)",          RULE5_VIOLATION,  "Violation"),
        ("Rule 6  VIOLATION — Client Role Segreg.    (AudioPlayer)",        RULE6_VIOLATION,  "Violation"),
        ("Rule 7  VIOLATION — Cross-Class Disjoint   (IDocument)",          RULE7_VIOLATION,  "Violation"),
        ("Rule 8  VIOLATION — Standalone Role Mix    (TelephoneDirectory)", RULE8_VIOLATION,  "Violation"),
        ("Rule 9  VIOLATION — Type-Dispatch Mux      (Writer)",             RULE9_VIOLATION,  "Violation"),
        ("Rule 10 VIOLATION — Inheritance Depth      (IDeep)",              RULE10_VIOLATION, "Violation"),
        ("Rule 11 VIOLATION — Optional Method        (SimpleWorker)",       RULE11_VIOLATION, "Violation"),
        ("Rule 12 VIOLATION — Boolean Flag Dispatch  (DataFetcher)",        RULE12_VIOLATION, "Violation"),
        ("Rule 13 VIOLATION — God Class              (UserManager)",        RULE13_VIOLATION, "Violation"),
        ("Rule 14 VIOLATION — Coarse Param Dep       (ReportGenerator)",    RULE14_VIOLATION, "Violation"),
        # ── clean passes ─────────────────────────────────────────
        ("Rule 1  PASS      — Focused interfaces     (Duck)",               RULE1_PASS,  "Pass"),
        ("Rule 2  PASS      — One interface/domain   (IAuthService etc.)",  RULE2_PASS,  "Pass"),
        ("Rule 3  PASS      — Param objects          (ReportConfig)",       RULE3_PASS,  "Pass"),
        ("Rule 4  PASS      — Narrow interface       (IReadable)",          RULE4_PASS,  "Pass"),
        ("Rule 5  PASS      — Only what's needed     (LogViewer+IReadable)",RULE5_PASS,  "Pass"),
        ("Rule 6  PASS      — IPlayable only         (AudioPlayer)",        RULE6_PASS,  "Pass"),
        ("Rule 7  PASS      — Split by client        (IDocumentReader etc)",RULE7_PASS,  "Pass"),
        ("Rule 8  PASS      — Cohesive CRUD class    (TelephoneDirectory)", RULE8_PASS,  "Pass"),
        ("Rule 9  PASS      — One class per variant  (FileWriter etc.)",    RULE9_PASS,  "Pass"),
        ("Rule 10 PASS      — Shallow composition    (IReadWrite)",         RULE10_PASS, "Pass"),
        ("Rule 11 PASS      — Trimmed interface      (IBasicWorker)",       RULE11_PASS, "Pass"),
        ("Rule 12 PASS      — Separate classes       (DbFetcher etc.)",     RULE12_PASS, "Pass"),
        ("Rule 13 PASS      — Split by role          (UserRepository etc)", RULE13_PASS, "Pass"),
        ("Rule 14 PASS      — Narrow param type      (IReadable)",          RULE14_PASS, "Pass"),
    ]

    passed = failed = 0
    failures = []

    for title, code, expected in examples:
        report = get_isp_report(code)
        got    = report["status"]
        ok     = (got == expected) or (expected == "Violation" and got == "Violation")
        symbol = "✓" if ok else "✗"
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((title, expected, got, report["reason"]))

        print(f"\n{'═'*74}")
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<10}  Got: {got}")
        print('═'*74)
        if report["violations"]:
            for v in report["violations"]:
                target = v.get("interface", v.get("class", "Unknown"))
                print(f"  [{v['severity']}] {v['type']} — {target} (line {v.get('lineno','?')})")
                print(f"  Reason    : {v['reason']}")
                print(f"  Suggestion: {v['suggestion']}")
        else:
            print(f"  {report['reason']}")

    print(f"\n{'═'*74}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(examples)} examples")
    if failures:
        print("\n  FAILURES:")
        for title, exp, got, reason in failures:
            print(f"    ✗ {title}")
            print(f"      Expected {exp}, got {got}: {reason}")