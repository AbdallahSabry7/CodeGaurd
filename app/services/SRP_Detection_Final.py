import ast
import re
import statistics
from itertools import combinations

# ── Semantic domain vocabulary ────────────────────────────────────────────────
# Maps conceptual "areas of concern" to the verb tokens that signal them.
SEMANTIC_DOMAINS: dict[str, set[str]] = {
    "persistence":  {"save", "store", "write", "persist", "insert", "update",
                     "delete", "remove", "create", "drop", "migrate", "commit"},
    "retrieval":    {"get", "fetch", "load", "read", "find", "search", "query",
                     "list", "retrieve", "select", "filter"},
    "presentation": {"render", "display", "show", "print", "format", "draw",
                     "view", "output", "report", "build"},
    "network":      {"send", "receive", "post", "request", "connect",
                     "disconnect", "upload", "download", "publish", "subscribe"},
    "notification": {"notify", "email", "alert", "message", "push", "broadcast"},
    "validation":   {"validate", "check", "verify", "assert", "ensure",
                     "sanitize", "inspect"},
    "parsing":      {"parse", "decode", "deserialize", "extract", "convert",
                     "transform", "serialize", "encode", "map"},
    "computation":  {"calculate", "compute", "process", "analyze", "evaluate",
                     "estimate", "score", "rank"},
    "auth":         {"login", "logout", "authenticate", "authorize", "register",
                     "sign", "permit", "hash"},
}

# PATCH 1 — Noun-based domain lookup
# Generic orchestrator verbs (handle, run, execute) obscure violations because
# the *noun* half of the name is more diagnostic in those cases.
NOUN_DOMAINS: dict[str, set[str]] = {
    "persistence":  {"record", "row", "entity", "migration", "schema",
                     "table", "database", "db", "repo", "repository"},
    "network":      {"request", "response", "payload", "socket",
                     "connection", "endpoint", "api", "http", "url"},
    "auth":         {"token", "session", "credential", "permission",
                     "role", "password", "user", "account"},
    "notification": {"email", "sms", "webhook", "slack", "mailer",
                     "digest", "subscription"},
    "presentation": {"template", "html", "page", "view", "report",
                     "pdf", "csv", "layout", "widget"},
    "computation":  {"metric", "stat", "score", "summary", "aggregate",
                     "forecast", "model"},
    "validation":   {"rule", "constraint", "schema", "policy", "limit"},
}


def _tokenize_name(name: str) -> list[str]:
    """
    Split a snake_case or camelCase identifier into lowercase tokens.
      'fetchUserAndSendEmail' → ['fetch', 'user', 'and', 'send', 'email']
      'save_to_database'      → ['save', 'to', 'database']
    """
    tokens = []
    for part in name.split("_"):
        sub = re.sub(r"([A-Z])", r" \1", part).strip()
        tokens.extend(sub.lower().split())
    return tokens


def _classify_domains(method_name: str) -> set[str]:
    """
    Return all semantic domains the method name signals.
    Scans both verb tokens (SEMANTIC_DOMAINS) and noun tokens (NOUN_DOMAINS)
    so that names like 'handle_payment' or 'run_migration' are not invisible.
    """
    tokens = set(_tokenize_name(method_name))
    domains: set[str] = set()
    for domain, keywords in SEMANTIC_DOMAINS.items():
        if tokens & keywords:
            domains.add(domain)
    # PATCH 1: also scan nouns
    for domain, keywords in NOUN_DOMAINS.items():
        if tokens & keywords:
            domains.add(domain)
    return domains or {"other"}


# PATCH 2 — Decorator helpers
def _get_decorators(func_node: ast.FunctionDef) -> set[str]:
    """Return the bare names of all decorators on a function node."""
    names: set[str] = set()
    for d in func_node.decorator_list:
        if isinstance(d, ast.Name):
            names.add(d.id)
        elif isinstance(d, ast.Attribute):
            names.add(d.attr)
    return names


class SRPAnalyzerEnhanced(ast.NodeVisitor):
    def __init__(self):
        self.report: dict[str, dict] = {}

    # ── AST helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _self_attrs(func_node: ast.FunctionDef) -> set[str]:
        """All `self.X` attribute names accessed in a method."""
        return {
            node.attr
            for node in ast.walk(func_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }

    @staticmethod
    def _external_objects(func_node: ast.FunctionDef) -> set[str]:
        """Non-self names invoked as call targets (e.g. `db.query()` → `db`)."""
        objs: set[str] = set()
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id != "self"
                ):
                    objs.add(node.func.value.id)
                elif isinstance(node.func, ast.Name):
                    objs.add(node.func.id)
        return objs

    @staticmethod
    def _complexity(func_node: ast.FunctionDef) -> int:
        """Rough cyclomatic complexity: branching nodes + 1."""
        branch_types = (
            ast.If, ast.For, ast.While, ast.ExceptHandler,
            ast.With, ast.Assert, ast.comprehension,
        )
        return 1 + sum(1 for n in ast.walk(func_node) if isinstance(n, branch_types))

    # PATCH 4 — Facade/delegator detection
    @staticmethod
    def _is_thin_delegator(func_node: ast.FunctionDef) -> bool:
        """
        True when a method body is essentially pure delegation:
        ≤3 non-return statements that are all external calls.
        These are coordinator/facade methods that legitimately span domains.
        """
        non_return = [
            n for n in func_node.body
            if not isinstance(n, (ast.Return, ast.Pass, ast.Expr))
            or (
                isinstance(n, ast.Expr)
                and not isinstance(n.value, ast.Call)
            )
        ]
        # Count actual call-expression statements
        call_stmts = [
            n for n in func_node.body
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        ]
        total_meaningful = len(non_return) + len(call_stmts)
        return total_meaningful <= 2

    # ── Score sub-components ─────────────────────────────────────────────────

    @staticmethod
    def _jaccard_diversity(methods_info: list[dict]) -> float:
        """
        Average pairwise Jaccard *distance* of external-object sets.
        High value means methods depend on very different collaborators.
        """
        sets = [set(m["objects_used"]) for m in methods_info if m["objects_used"]]
        if len(sets) < 2:
            return 0.0
        dists = [
            1 - len(a & b) / len(a | b)
            for a, b in combinations(sets, 2)
        ]
        return sum(dists) / len(dists)

    @staticmethod
    def _lcom_score(methods_info: list[dict]) -> float:
        """
        Lack-of-Cohesion-of-Methods (0 = fully cohesive, 1 = no sharing).

        PATCH 2 (stateless fix): if no method touches self.* at all, the
        class is a stateless utility helper — LCOM is undefined/meaningless
        for it and must not penalise it.
        """
        attr_sets = [set(m["self_attrs"]) for m in methods_info]
        # PATCH 2: stateless classes get 0, not 1
        if not any(attr_sets):
            return 0.0
        if len(attr_sets) < 2:
            return 0.0
        total_pairs = len(attr_sets) * (len(attr_sets) - 1) // 2
        shared = sum(1 for a, b in combinations(attr_sets, 2) if a & b)
        return 1.0 - (shared / total_pairs)

    @staticmethod
    def _domain_diversity(methods_info: list[dict]) -> float:
        """
        Fraction of distinct semantic concern areas covered (excluding 'other').
        ≤1 domain → 0.0 (no signal); ≥5 domains → 1.0 (clear violation).
        """
        meaningful = {
            d
            for m in methods_info
            for d in m["domains"]
            if d != "other"
        }
        return min(1.0, max(0.0, (len(meaningful) - 1) / 4))

    # PATCH 5 — size_factor replacement
    @staticmethod
    def _size_factor(methods_info: list[dict]) -> float:
        """
        Original mean-based size_factor punished a single large method even
        when it was a single-concern workhorse.

        Replacement: proportion of methods that are individually large (>30
        lines), blended with coefficient of variation to catch uneven
        complexity spread. Neither alone is sufficient.
        """
        lines = [m["line_count"] for m in methods_info]
        n = len(lines)
        avg = sum(lines) / n

        large_ratio = sum(1 for l in lines if l > 30) / n

        if n >= 2 and avg > 0:
            cv = statistics.stdev(lines) / avg  # coefficient of variation
            cv_factor = min(1.0, cv / 2.0)
        else:
            cv_factor = 0.0

        return min(1.0, (large_ratio + cv_factor) / 2)

    # ── Main visitor ─────────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = node.name
        methods_info: list[dict] = []

        for n in node.body:
            if not isinstance(n, ast.FunctionDef):
                continue

            if n.name.startswith("__") and n.name.endswith("__"):
                continue

            decorators = _get_decorators(n)
            if "property" in decorators:
                # @property accessors are data-interface, not a responsibility.
                # Including them inflates LCOM and domain diversity spuriously.
                continue
            is_static = bool(decorators & {"staticmethod", "classmethod"})

            lines = (n.end_lineno or n.lineno) - n.lineno + 1

            # Legacy: explicit And/Or split in method name
            parts = re.split(r"(?<=[a-z])(?:And|Or)(?=[A-Z])", n.name)

            methods_info.append({
                "name":              n.name,
                "objects_used":      list(self._external_objects(n)),
                "self_attrs":        list(self._self_attrs(n)),
                "domains":           _classify_domains(n.name),
                "responsibilities":  [p.lower() for p in parts if p],
                "line_count":        lines,
                "complexity":        self._complexity(n),
                "is_static":         is_static,
                "is_thin_delegator": self._is_thin_delegator(n),
            })

        if not methods_info:
            self.report[class_name] = {
                "srp_violation_score": 0.0,
                "status": "Pass",
                "confidence": "high",
                "is_violation": False,
                "methods": [],
                "diagnostics": {},
            }
            # PATCH — recurse into nested class definitions
            for child in ast.walk(node):
                if isinstance(child, ast.ClassDef) and child is not node:
                    self.visit_ClassDef(child)
            return

        all_resp = {r for m in methods_info for r in m["responsibilities"]}
        n_resp = len(all_resp)
        responsibility_factor = 0.0 if n_resp <= 1 else (n_resp - 1) / n_resp

        total_objects = sum(len(m["objects_used"]) for m in methods_info)
        object_factor = (
            max(0, total_objects - len(methods_info)) / total_objects
            if total_objects else 0.0
        )

        domain_div    = self._domain_diversity(methods_info)
        lcom          = self._lcom_score(methods_info)
        obj_diversity = self._jaccard_diversity(methods_info)
        size_factor   = self._size_factor(methods_info)  # PATCH 5

        n_methods = len(methods_info)
        delegator_ratio = sum(1 for m in methods_info if m["is_thin_delegator"]) / n_methods
        effective_domain_div = domain_div * (1 - 0.5 * delegator_ratio)

        srp_violation_score = (
            0.30 * obj_diversity             # methods depend on unrelated collaborators
            + 0.25 * effective_domain_div    # spans distinct concern areas (facade-adjusted)
            + 0.20 * lcom                    # structural cohesion (classic LCOM)
            + 0.15 * size_factor             # large/complex method spread (PATCH 5)
            + 0.10 * responsibility_factor   # legacy And/Or name heuristic
            + 0.00 * object_factor           # retired: subsumed by obj_diversity
        )

        detected_domains = sorted(
            {d for m in methods_info for d in m["domains"]} - {"other"}
        )

        # PATCH 3 — Three-tier output + adaptive threshold
        # Small classes (few chances to recover via shared attrs) use a lower
        # threshold; large classes get a slightly higher bar for specificity.
        base_threshold = 0.40
        adaptive_threshold = base_threshold - max(0.0, (4 - n_methods) * 0.05)

        if srp_violation_score > adaptive_threshold + 0.15:
            status, confidence = "Violation", "high"
        elif srp_violation_score > adaptive_threshold:
            status, confidence = "Review", "low"
        else:
            status, confidence = "Pass", "high"

        is_violation = status == "Violation"

        self.report[class_name] = {
            "srp_violation_score": round(srp_violation_score * 100, 1),
            "status": status,
            "confidence": confidence,
            "is_violation": is_violation,
            "methods": [m["name"] for m in methods_info],
            "diagnostics": {
                "domain_diversity":        round(domain_div, 2),
                "effective_domain_div":    round(effective_domain_div, 2),
                "lcom":                    round(lcom, 2),
                "object_diversity":        round(obj_diversity, 2),
                "responsibility_factor":   round(responsibility_factor, 2),
                "size_factor":             round(size_factor, 2),
                "delegator_ratio":         round(delegator_ratio, 2),
                "adaptive_threshold":      round(adaptive_threshold * 100, 1),
                "detected_domains":        detected_domains,
            },
        }

        # PATCH — recurse into nested class definitions
        for child in ast.walk(node):
            if isinstance(child, ast.ClassDef) and child is not node:
                self.visit_ClassDef(child)


def get_srp_report(code: str) -> list[dict]:
    try:
        tree = ast.parse(code)
        analyzer = SRPAnalyzerEnhanced()
        analyzer.visit(tree)

        if not analyzer.report:
            return [{
                "status": "Pass",
                "confidence": "high",
                "reason": "No classes detected.",
                "suggestion": "Define a class to see SRP analysis.",
            }]

        results = []
        for class_name, data in analyzer.report.items():
            diag   = data.get("diagnostics", {})
            score  = data["srp_violation_score"]
            status = data["status"]
            conf   = data["confidence"]
            domains = diag.get("detected_domains", [])

            if status in ("Violation", "Review"):
                fired: list[str] = []
                if diag.get("object_diversity", 0) > 0.5:
                    fired.append("methods depend on unrelated collaborators")
                if diag.get("effective_domain_div", 0) > 0.2:
                    fired.append(f"spans domains: {', '.join(domains)}")
                if diag.get("lcom", 0) > 0.5:
                    fired.append("methods share few instance variables (low cohesion)")
                if diag.get("size_factor", 0) > 0.3:
                    fired.append("large/complex methods spread across the class")
                if diag.get("responsibility_factor", 0) > 0:
                    fired.append("'And'/'Or' in method names")
                if diag.get("delegator_ratio", 0) > 0.5:
                    fired.append(
                        f"note: {int(diag['delegator_ratio']*100)}% of methods are thin "
                        "delegators — may be a facade/coordinator"
                    )

                reason_str = "; ".join(fired) if fired else "multiple heuristics fired"
                domain_hint = f" one per domain ({', '.join(domains)})" if domains else ""
                threshold_note = f" (threshold: {diag.get('adaptive_threshold', 40)}%)"

                if status == "Review":
                    results.append({
                        "class":      class_name,
                        "status":     "Review",
                        "confidence": conf,
                        "score":      score,
                        "reason":     (
                            f"Class '{class_name}' scored {score}%{threshold_note} — "
                            f"borderline result, manual review recommended. {reason_str}."
                        ),
                        "suggestion": (
                            f"Inspect '{class_name}' for mixed concerns,{domain_hint}. "
                            "Score is in the uncertain zone; context matters here."
                        ),
                        "diagnostics": diag,
                    })
                else:
                    results.append({
                        "class":      class_name,
                        "status":     "Violation",
                        "confidence": conf,
                        "score":      score,
                        "reason":     (
                            f"Class '{class_name}' scored {score}%{threshold_note} — "
                            f"{reason_str}."
                        ),
                        "suggestion": (
                            f"Split '{class_name}' into focused classes,{domain_hint}."
                        ),
                        "diagnostics": diag,
                    })
            else:
                results.append({
                    "class":      class_name,
                    "status":     "Pass",
                    "confidence": conf,
                    "score":      score,
                    "reason":     f"Class '{class_name}' appears cohesive (score: {score}%).",
                    "suggestion": "No refactor needed.",
                    "diagnostics": diag,
                })

        return results

    except SyntaxError as e:
        return [{"status": "Error", "reason": f"Syntax error: {e}", "suggestion": "Fix the syntax before analysis."}]
    except Exception as e:
        return [{"status": "Error", "reason": f"Unexpected error: {e}", "suggestion": "N/A"}]