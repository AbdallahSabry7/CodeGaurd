"""
DIP Analyser — Test Harness
============================
One VIOLATION + one PASS example per rule (DIP001–DIP006),
covering edge cases raised by the improved analyser.

Run directly:
    python dip_test_harness.py
"""

import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dependancy_principle          import get_dip_report


# ── Rule 1: DIP001 — __init__ parameter typed with a concrete class ──────────

RULE1_VIOLATION = """
class MySQLConnection:
    def execute(self, sql: str): ...

class UserRepository:
    def __init__(self, db: MySQLConnection) -> None:
        self.db = db
"""

RULE1_PASS = """
from abc import ABC, abstractmethod

class IDatabase(ABC):
    @abstractmethod
    def execute(self, sql: str): ...

class UserRepository:
    def __init__(self, db: IDatabase) -> None:
        self.db = db
"""


# ── Rule 2: DIP002 — Method parameter typed with a concrete class ─────────────

RULE2_VIOLATION = """
class SmtpMailer:
    def send(self, to: str, body: str): ...

class NotificationService:
    def notify(self, mailer: SmtpMailer, recipient: str) -> None:
        mailer.send(recipient, "Hello")
"""

RULE2_PASS = """
from typing import Protocol

class IMailer(Protocol):
    def send(self, to: str, body: str) -> None: ...

class NotificationService:
    def notify(self, mailer: IMailer, recipient: str) -> None:
        mailer.send(recipient, "Hello")
"""


# ── Rule 3: DIP003 — Direct instantiation of a concrete class ────────────────

RULE3_VIOLATION = """
class DiskLogger:
    def log(self, msg: str): ...

class OrderService:
    def __init__(self) -> None:
        self.logger = DiskLogger()   # hard-wired dependency

    def place_order(self, item: str) -> None:
        self.logger.log(f"Order placed: {item}")
"""

RULE3_PASS = """
from abc import ABC, abstractmethod

class ILogger(ABC):
    @abstractmethod
    def log(self, msg: str) -> None: ...

class OrderService:
    def __init__(self, logger: ILogger) -> None:
        self.logger = logger           # injected

    def place_order(self, item: str) -> None:
        self.logger.log(f"Order placed: {item}")
"""


# ── Rule 4: DIP004 — Class-level attribute annotated with a concrete class ────

RULE4_VIOLATION = """
class RedisCache:
    def get(self, key: str): ...
    def set(self, key: str, value: object): ...

class SessionManager:
    cache: RedisCache          # concrete annotation at class level

    def __init__(self, cache: RedisCache) -> None:
        self.cache = cache
"""

RULE4_PASS = """
from typing import Protocol

class ICache(Protocol):
    def get(self, key: str) -> object: ...
    def set(self, key: str, value: object) -> None: ...

class SessionManager:
    cache: ICache              # abstraction annotation

    def __init__(self, cache: ICache) -> None:
        self.cache = cache
"""


# ── Rule 5: DIP005 — Class inherits from a concrete class ────────────────────

RULE5_VIOLATION = """
class BaseFileWriter:
    def write(self, path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

class CompressedFileWriter(BaseFileWriter):   # inherits concrete impl
    def write(self, path: str, data: bytes) -> None:
        import zlib
        super().write(path, zlib.compress(data))
"""

RULE5_PASS = """
from abc import ABC, abstractmethod

class IWriter(ABC):
    @abstractmethod
    def write(self, path: str, data: bytes) -> None: ...

class CompressedFileWriter(IWriter):
    def write(self, path: str, data: bytes) -> None:
        import zlib
        with open(path, "wb") as f:
            f.write(zlib.compress(data))
"""


# ── Rule 6: DIP006 — Method return type is a concrete class ──────────────────

RULE6_VIOLATION = """
class PostgresConnection:
    def query(self, sql: str): ...

class ConnectionPool:
    def acquire(self) -> PostgresConnection:   # leaks concrete type
        return PostgresConnection()
"""

RULE6_PASS = """
from abc import ABC, abstractmethod

class IConnection(ABC):
    @abstractmethod
    def query(self, sql: str): ...

class ConnectionPool:
    def __init__(self, connections: list) -> None:
        self._pool = connections

    def acquire(self) -> IConnection:          # returns abstraction; no instantiation here
        return self._pool.pop()
"""


# ── Edge cases ────────────────────────────────────────────────────────────────

# Optional[Concrete] in a method param should still be caught (DIP002)
EDGE1_OPTIONAL_VIOLATION = """
from typing import Optional

class HdfsClient:
    def upload(self, path: str): ...

class BackupJob:
    def run(self, client: Optional[HdfsClient] = None) -> None:
        if client:
            client.upload("/backup")
"""

EDGE1_OPTIONAL_PASS = """
from typing import Optional, Protocol

class IStorageClient(Protocol):
    def upload(self, path: str) -> None: ...

class BackupJob:
    def run(self, client: Optional[IStorageClient] = None) -> None:
        if client:
            client.upload("/backup")
"""

# Dict[str, Concrete] attribute should be caught (DIP004)
EDGE2_GENERIC_VIOLATION = """
from typing import Dict

class SqliteStore:
    def get(self, key: str): ...

class Registry:
    stores: Dict[str, SqliteStore]    # concrete in generic value

    def __init__(self) -> None:
        self.stores = {}
"""

EDGE2_GENERIC_PASS = """
from typing import Dict, Protocol

class IStore(Protocol):
    def get(self, key: str) -> object: ...

class Registry:
    stores: Dict[str, IStore]

    def __init__(self) -> None:
        self.stores = {}
"""

# *args: Concrete should be caught (DIP002)
EDGE3_VARARGS_VIOLATION = """
class HtmlRenderer:
    def render(self, content: str) -> str: ...

class Pipeline:
    def run(self, *renderers: HtmlRenderer) -> None:
        for r in renderers:
            r.render("<p>hi</p>")
"""

EDGE3_VARARGS_PASS = """
from typing import Protocol

class IRenderer(Protocol):
    def render(self, content: str) -> str: ...

class Pipeline:
    def run(self, *renderers: IRenderer) -> None:
        for r in renderers:
            r.render("<p>hi</p>")
"""

# Annotated[Concrete, metadata] should be caught (DIP001)
EDGE4_ANNOTATED_VIOLATION = """
from typing import Annotated

class MongoClient:
    def find(self, query: dict): ...

class ProductRepo:
    def __init__(self, client: Annotated[MongoClient, "injected"]) -> None:
        self.client = client
"""

EDGE4_ANNOTATED_PASS = """
from typing import Annotated, Protocol

class IDocumentStore(Protocol):
    def find(self, query: dict) -> list: ...

class ProductRepo:
    def __init__(self, client: Annotated[IDocumentStore, "injected"]) -> None:
        self.client = client
"""

# PEP 604 union (Foo | None) should be caught (DIP002)
EDGE5_PEP604_VIOLATION = """
class LocalFileSystem:
    def read(self, path: str) -> bytes: ...

class DataLoader:
    def load(self, fs: LocalFileSystem | None) -> bytes | None:
        return fs.read("/data") if fs else None
"""

EDGE5_PEP604_PASS = """
from abc import ABC, abstractmethod

class IFileSystem(ABC):
    @abstractmethod
    def read(self, path: str) -> bytes: ...

class DataLoader:
    def load(self, fs: IFileSystem | None) -> bytes | None:
        return fs.read("/data") if fs else None
"""

# DIP003 inside an async method should be caught
EDGE6_ASYNC_VIOLATION = """
class HttpClient:
    async def get(self, url: str) -> bytes: ...

class FeedFetcher:
    async def fetch(self, url: str) -> bytes:
        client = HttpClient()          # instantiated inside async method
        return await client.get(url)
"""

EDGE6_ASYNC_PASS = """
from abc import ABC, abstractmethod

class IHttpClient(ABC):
    @abstractmethod
    async def get(self, url: str) -> bytes: ...

class FeedFetcher:
    def __init__(self, client: IHttpClient) -> None:
        self.client = client

    async def fetch(self, url: str) -> bytes:
        return await self.client.get(url)
"""


# ── Test runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    examples = [
        # ── violations ───────────────────────────────────────────────────────
        ("DIP001 VIOLATION — __init__ concrete param      (UserRepository)",  RULE1_VIOLATION,      "Violation"),
        ("DIP002 VIOLATION — method concrete param         (NotificationSvc)", RULE2_VIOLATION,      "Violation"),
        ("DIP003 VIOLATION — direct instantiation          (OrderService)",    RULE3_VIOLATION,      "Violation"),
        ("DIP004 VIOLATION — class attr concrete annot.   (SessionManager)",  RULE4_VIOLATION,      "Violation"),
        ("DIP005 VIOLATION — inherits concrete class       (CompressedWriter)", RULE5_VIOLATION,     "Violation"),
        ("DIP006 VIOLATION — return type is concrete       (ConnectionPool)",  RULE6_VIOLATION,      "Violation"),
        ("EDGE1  VIOLATION — Optional[Concrete] param      (BackupJob)",       EDGE1_OPTIONAL_VIOLATION,  "Violation"),
        ("EDGE2  VIOLATION — Dict[str, Concrete] attr      (Registry)",        EDGE2_GENERIC_VIOLATION,   "Violation"),
        ("EDGE3  VIOLATION — *args: Concrete               (Pipeline)",        EDGE3_VARARGS_VIOLATION,   "Violation"),
        ("EDGE4  VIOLATION — Annotated[Concrete, meta]     (ProductRepo)",     EDGE4_ANNOTATED_VIOLATION, "Violation"),
        ("EDGE5  VIOLATION — PEP 604  Foo | None param     (DataLoader)",      EDGE5_PEP604_VIOLATION,    "Violation"),
        ("EDGE6  VIOLATION — DIP003 inside async method    (FeedFetcher)",     EDGE6_ASYNC_VIOLATION,     "Violation"),
        # ── clean passes ─────────────────────────────────────────────────────
        ("DIP001 PASS      — ABC in __init__               (UserRepository)",  RULE1_PASS,      "Pass"),
        ("DIP002 PASS      — Protocol method param         (NotificationSvc)", RULE2_PASS,      "Pass"),
        ("DIP003 PASS      — dependency injected           (OrderService)",    RULE3_PASS,      "Pass"),
        ("DIP004 PASS      — class attr abstract annot.   (SessionManager)",  RULE4_PASS,      "Pass"),
        ("DIP005 PASS      — inherits ABC                  (CompressedWriter)", RULE5_PASS,     "Pass"),
        ("DIP006 PASS      — returns abstraction           (ConnectionPool)",  RULE6_PASS,      "Pass"),
        ("EDGE1  PASS      — Optional[Protocol] param      (BackupJob)",       EDGE1_OPTIONAL_PASS,  "Pass"),
        ("EDGE2  PASS      — Dict[str, Protocol] attr      (Registry)",        EDGE2_GENERIC_PASS,   "Pass"),
        ("EDGE3  PASS      — *args: Protocol               (Pipeline)",        EDGE3_VARARGS_PASS,   "Pass"),
        ("EDGE4  PASS      — Annotated[Protocol, meta]     (ProductRepo)",     EDGE4_ANNOTATED_PASS, "Pass"),
        ("EDGE5  PASS      — PEP 604  ABC | None param     (DataLoader)",      EDGE5_PEP604_PASS,    "Pass"),
        ("EDGE6  PASS      — async uses injected dep       (FeedFetcher)",     EDGE6_ASYNC_PASS,     "Pass"),
    ]

    passed = failed = 0
    failures = []

    for title, code, expected in examples:
        report = get_dip_report(code)
        got    = report["status"]
        ok     = (got == expected)
        symbol = "✓" if ok else "✗"

        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((title, expected, got, report["reason"]))

        print(f"\n{'═' * 74}")
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<10}  Got: {got}")
        print('═' * 74)

        if report["violations"]:
            for v in report["violations"]:
                rule_tag = v["message"].split()[0]           # e.g. "DIP001"
                rest     = v["message"][len(rule_tag):].strip()
                print(f"  [{rule_tag}]  line {v['line']}, col {v['col']}")
                print(f"  Detail    : {rest}")
        else:
            print(f"  {report['reason']}")

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
