import ast
import re
import statistics
from itertools import combinations

# ── Semantic domain vocabulary ────────────────────────────────────────────────
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

COLLABORATOR_NOUN_DOMAINS: dict[str, set[str]] = {
    "persistence":  {"db", "repo", "repository", "store", "database",
                     "session", "conn", "connection", "cursor", "orm",
                     # FIX A: file/stream collaborators added
                     "file", "writer", "reader", "buffer", "output", "input"},
    "network":      {"client", "http", "api", "request", "socket",
                     "endpoint", "proxy", "gateway",
                     # FIX A: socket aliases added
                     "sock", "stream", "pipe", "channel", "some_socket"},
    "auth":         {"auth", "jwt", "token", "sso", "oauth", "permissions"},
    "notification": {"mailer", "smtp", "email", "sms", "notifier",
                     "pusher", "slack", "webhook"},
    "presentation": {"renderer", "template", "view", "html", "pdf",
                     "serializer", "formatter"},
    "computation":  {"calculator", "scorer", "ranker", "analyzer",
                     "estimator", "model", "processor"},
    "validation":   {"validator", "checker", "sanitizer", "schema"},
    "parsing":      {"parser", "decoder", "transformer", "mapper"},
}

# FIX B: Attributes that create false cohesion — excluded from LCOM calculation
LCOM_NOISE_ATTRS = {
    "logger", "log", "config", "cfg", "settings", "debug",
    "verbose", "name", "type", "mode", "flag", "enabled",
}

DEFAULT_WEIGHTS = {
    "body_domain_div":       0.38,
    "effective_domain_div":  0.28,
    "lcom":                  0.18,
    "object_diversity":      0.10,
    "size_factor":           0.04,
    "responsibility_factor": 0.02,
}


def _tokenize_name(name: str) -> list[str]:
    tokens = []
    for part in name.split("_"):
        sub = re.sub(r"([A-Z])", r" \1", part).strip()
        tokens.extend(sub.lower().split())
    return tokens


def _classify_domains(method_name: str) -> set[str]:
    tokens = set(_tokenize_name(method_name))
    domains: set[str] = set()
    for domain, keywords in SEMANTIC_DOMAINS.items():
        if tokens & keywords:
            domains.add(domain)
    for domain, keywords in NOUN_DOMAINS.items():
        if tokens & keywords:
            domains.add(domain)
    full = method_name.lower()
    for domain, keywords in COLLABORATOR_NOUN_DOMAINS.items():
        if full in keywords:
            domains.add(domain)
    return domains or {"other"}


def _classify_body_domains(func_node: ast.FunctionDef) -> set[str]:

    domains: set[str] = set()

    local_aliases: dict[str, set[str]] = {}

    for node in ast.walk(func_node):

        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            collab = node.value.attr.lower()
            for domain, keywords in COLLABORATOR_NOUN_DOMAINS.items():
                if collab in keywords:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            local_aliases.setdefault(target.id, set()).add(domain)

        # self.collaborator.method() — 2-level chain
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
        ):
            collab = node.func.value.attr.lower()
            method = node.func.attr.lower()

            collab_matched = False
            for domain, keywords in COLLABORATOR_NOUN_DOMAINS.items():
                if collab in keywords:
                    domains.add(domain)
                    collab_matched = True

            # Only use verb domain if collaborator was unrecognized
            # Prevents self.db.write() collapsing everything into persistence
            if not collab_matched:
                for domain, keywords in SEMANTIC_DOMAINS.items():
                    if method in keywords:
                        domains.add(domain)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Attribute)
            and isinstance(node.func.value.value.value, ast.Name)
            and node.func.value.value.value.id == "self"
        ):
            collab = node.func.value.value.attr.lower()
            method = node.func.attr.lower()
            for domain, keywords in COLLABORATOR_NOUN_DOMAINS.items():
                if collab in keywords:
                    domains.add(domain)
            for domain, keywords in SEMANTIC_DOMAINS.items():
                if method in keywords:
                    domains.add(domain)

        # standalone function calls: save_user(), send_email(), open(), etc.
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        ):
            fname = node.func.id.lower()
            if fname in {"open", "openfile"}:
                domains.add("persistence")
            tokens = set(_tokenize_name(fname))
            for domain, keywords in SEMANTIC_DOMAINS.items():
                if tokens & keywords:
                    domains.add(domain)

            if fname in local_aliases:
                domains |= local_aliases[fname]

        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id != "self"
            and node.func.value.id in local_aliases
        ):
            domains |= local_aliases[node.func.value.id]

        # self.X = ... assignments — X itself may be a domain noun
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    attr_tokens = set(_tokenize_name(target.attr))
                    for domain, keywords in NOUN_DOMAINS.items():
                        if attr_tokens & keywords:
                            domains.add(domain)

    self_compares = sum(
        1 for n in ast.walk(func_node)
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Attribute)
        and isinstance(n.left.value, ast.Name)
        and n.left.value.id == "self"
    )
    if self_compares >= 2:
        domains.add("__dispatch__")

    return domains or {"other"}


def _get_decorators(func_node: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for d in func_node.decorator_list:
        if isinstance(d, ast.Name):
            names.add(d.id)
        elif isinstance(d, ast.Attribute):
            names.add(d.attr)
    return names


def _analyze_constructor(init_node: ast.FunctionDef) -> dict:
    """
    Parse __init__ to count how many distinct domain-mapped collaborators
    are injected. A constructor that wires self.db, self.mailer, self.renderer,
    and self.cache is one of the strongest possible SRP violations.
    """
    injected_domains: set[str] = set()
    collaborator_names: set[str] = set()

    for node in ast.walk(init_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    attr = target.attr.lower()
                    attr_tokens = set(_tokenize_name(attr))
                    for domain, keywords in COLLABORATOR_NOUN_DOMAINS.items():
                        if attr in keywords or attr_tokens & keywords:
                            injected_domains.add(domain)
                            collaborator_names.add(attr)
                    for domain, keywords in NOUN_DOMAINS.items():
                        if attr_tokens & keywords:
                            injected_domains.add(domain)

    n_domains = len(injected_domains)
    injection_score = min(1.0, max(0.0, (n_domains - 1) / 3))

    return {
        "injected_domains": sorted(injected_domains),
        "collaborator_count": len(collaborator_names),
        "injection_score": round(injection_score, 2),
    }


class SRPAnalyzerEnhanced(ast.NodeVisitor):
    def __init__(self, weights: dict | None = None):
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}
        self.report: dict[str, dict] = {}

    # ── AST helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _self_attrs(func_node: ast.FunctionDef) -> set[str]:
        return {
            node.attr
            for node in ast.walk(func_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }

    @staticmethod
    def _external_objects(func_node: ast.FunctionDef) -> set[str]:
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
        branch_types = (
            ast.If, ast.For, ast.While, ast.ExceptHandler,
            ast.With, ast.Assert, ast.comprehension,
        )
        return 1 + sum(1 for n in ast.walk(func_node) if isinstance(n, branch_types))

    @staticmethod
    def _classify_delegator(func_node: ast.FunctionDef) -> tuple[bool, bool]:
        """
        Returns (is_thin, is_cross_domain).
        is_thin:         True when the body has ≤2 meaningful statements.
        is_cross_domain: True when delegated callees span 2+ distinct domains.
        """
        call_stmts = [
            n for n in func_node.body
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        ]
        non_trivial = [
            n for n in func_node.body
            if not isinstance(n, (ast.Return, ast.Pass))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))
        ]
        total_meaningful = len(call_stmts) + len(non_trivial)
        is_thin = total_meaningful <= 2

        if not is_thin:
            return False, False

        body_domains = _classify_body_domains(func_node) - {"other"}
        is_cross_domain = len(body_domains) >= 2

        return True, is_cross_domain

    # ── Score sub-components ─────────────────────────────────────────────────

    @staticmethod
    def _jaccard_diversity(methods_info: list[dict]) -> float:
        sets = [set(m["objects_used"]) for m in methods_info if m["objects_used"]]
        if len(sets) < 2:
            return 0.0
        dists = [
            1 - len(a & b) / len(a | b)
            for a, b in combinations(sets, 2)
        ]
        return sum(dists) / len(dists)

    @staticmethod
    def _lcom_score(methods_info: list[dict], collaborator_attrs: set[str]) -> float:
        """
        LCOM with collaborator-weighted attribute sets.
        FIX B: noise attributes (logger, config, type) excluded so they don't
        create false cohesion between otherwise unrelated methods.
        """
        def weighted_attr_set(attrs: list[str]) -> set[str]:
            result = set()
            for a in attrs:
                if a in LCOM_NOISE_ATTRS:   # FIX B: skip noise
                    continue
                result.add(a)
                if a in collaborator_attrs:
                    result.add(f"__collab__{a}__1")
                    result.add(f"__collab__{a}__2")
            return result

        attr_sets = [weighted_attr_set(m["self_attrs"]) for m in methods_info]
        if not any(attr_sets):
            return 0.0
        if len(attr_sets) < 2:
            return 0.0
        total_pairs = len(attr_sets) * (len(attr_sets) - 1) // 2
        shared = sum(1 for a, b in combinations(attr_sets, 2) if a & b)
        return 1.0 - (shared / total_pairs)

    @staticmethod
    def _domain_diversity(methods_info: list[dict]) -> float:
        meaningful = {
            d
            for m in methods_info
            for d in m["domains"]
            if d != "other"
        }
        return min(1.0, max(0.0, (len(meaningful) - 1) / 1.5))

    @staticmethod
    def _body_domain_diversity(methods_info: list[dict]) -> float:
        """
        Domain diversity using body-scanned domains.
        __dispatch__ counts as a real domain (type-dispatch = multiple responsibilities).
        """
        meaningful = {
            d
            for m in methods_info
            for d in m["body_domains"]
            if d != "other"   # __dispatch__ is intentionally kept
        }
        return min(1.0, max(0.0, (len(meaningful) - 1) / 1.5))

    @staticmethod
    def _size_factor(methods_info: list[dict]) -> float:
        lines = [m["line_count"] for m in methods_info]
        n = len(lines)
        avg = sum(lines) / n
        large_ratio = sum(1 for l in lines if l > 30) / n
        if n >= 2 and avg > 0:
            cv = statistics.stdev(lines) / avg
            cv_factor = min(1.0, cv / 2.0)
        else:
            cv_factor = 0.0
        return min(1.0, (large_ratio + cv_factor) / 2)

    # ── Constructor collaborator detection ────────────────────────────────────

    @staticmethod
    def _detect_collaborator_attrs(class_node: ast.ClassDef) -> set[str]:
        collaborators: set[str] = set()
        for n in class_node.body:
            if isinstance(n, ast.FunctionDef) and n.name == "__init__":
                for node in ast.walk(n):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                            ):
                                attr = target.attr.lower()
                                attr_tokens = set(_tokenize_name(attr))
                                for keywords in COLLABORATOR_NOUN_DOMAINS.values():
                                    if attr in keywords or attr_tokens & keywords:
                                        collaborators.add(target.attr)
                                        break
                                for keywords in NOUN_DOMAINS.values():
                                    if attr_tokens & keywords:
                                        collaborators.add(target.attr)
                                        break
        return collaborators

    # ── Main visitor ─────────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = node.name
        methods_info: list[dict] = []
        constructor_info: dict = {}

        collaborator_attrs = self._detect_collaborator_attrs(node)

        for n in node.body:
            if not isinstance(n, ast.FunctionDef):
                continue

            if n.name == "__init__":
                constructor_info = _analyze_constructor(n)
                continue

            if n.name.startswith("__") and n.name.endswith("__"):
                continue

            decorators = _get_decorators(n)
            if "property" in decorators:
                continue
            is_static = bool(decorators & {"staticmethod", "classmethod"})

            lines = (n.end_lineno or n.lineno) - n.lineno + 1
            parts = re.split(r"(?<=[a-z])(?:And|Or)(?=[A-Z])", n.name)
            is_thin, is_cross_domain_delegator = self._classify_delegator(n)
            body_domains = _classify_body_domains(n)

            methods_info.append({
                "name":                      n.name,
                "objects_used":              list(self._external_objects(n)),
                "self_attrs":                list(self._self_attrs(n)),
                "domains":                   _classify_domains(n.name),
                "body_domains":              body_domains,
                "responsibilities":          [p.lower() for p in parts if p],
                "line_count":                lines,
                "complexity":                self._complexity(n),
                "is_static":                 is_static,
                "is_thin_delegator":         is_thin,
                "is_cross_domain_delegator": is_cross_domain_delegator,
            })

        if not methods_info:
            self.report[class_name] = {
                "srp_violation_score": 0.0,
                "status": "Pass",
                "confidence": "high",
                "is_violation": False,
                "methods": [],
                "diagnostics": {},
                "constructor": constructor_info,
            }
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

        domain_div      = self._domain_diversity(methods_info)
        body_domain_div = self._body_domain_diversity(methods_info)
        lcom            = self._lcom_score(methods_info, collaborator_attrs)
        obj_diversity   = self._jaccard_diversity(methods_info)
        size_factor     = self._size_factor(methods_info)

        n_methods = len(methods_info)

        safe_delegator_count = sum(
            1 for m in methods_info
            if m["is_thin_delegator"] and not m["is_cross_domain_delegator"]
        )
        delegator_ratio      = sum(1 for m in methods_info if m["is_thin_delegator"]) / n_methods
        safe_delegator_ratio = safe_delegator_count / n_methods

        effective_domain_div      = domain_div * (1 - 0.5 * safe_delegator_ratio)
        effective_body_domain_div = body_domain_div

        w = self.weights

        if n_methods == 1:
            solo_domains = {
                d for d in methods_info[0]["body_domains"] if d != "other"
            }
            n_solo = len(solo_domains)
            if n_solo >= 2:
                # 2 domains → 0.40, 3 domains → 0.60, 4+ → capped at 0.80
                srp_violation_score = min(0.80, 0.20 + n_solo * 0.20)
            else:
                srp_violation_score = 0.0
        else:
            srp_violation_score = (
                w["object_diversity"]      * obj_diversity
                + w["effective_domain_div"]  * effective_domain_div
                + w["lcom"]                  * lcom
                + w["body_domain_div"]       * effective_body_domain_div
                + w["size_factor"]           * size_factor
                + w["responsibility_factor"] * responsibility_factor
            )

        injection_score   = constructor_info.get("injection_score", 0.0)
        constructor_boost = injection_score * 0.25
        srp_violation_score = min(1.0, srp_violation_score + constructor_boost)

        detected_domains = sorted(
            {d for m in methods_info for d in m["domains"]} - {"other"}
        )
        body_detected_domains = sorted(
            {d for m in methods_info for d in m["body_domains"]} - {"other"}
        )

        base_threshold     = 0.18
        adaptive_threshold = base_threshold - max(0.0, (4 - n_methods) * 0.05)

        if srp_violation_score > adaptive_threshold + 0.05:
            status, confidence = "Violation", "high"
        elif srp_violation_score > adaptive_threshold:
            status, confidence = "Review", "low"
        else:
            status, confidence = "Pass", "high"

        is_violation = status == "Violation"

        self.report[class_name] = {
            "srp_violation_score": round(srp_violation_score * 100, 1),
            "status":     status,
            "confidence": confidence,
            "is_violation": is_violation,
            "methods":    [m["name"] for m in methods_info],
            "constructor": constructor_info,
            "diagnostics": {
                "domain_diversity":          round(domain_div, 2),
                "effective_domain_div":      round(effective_domain_div, 2),
                "body_domain_diversity":     round(body_domain_div, 2),
                "effective_body_domain_div": round(effective_body_domain_div, 2),
                "lcom":                      round(lcom, 2),
                "object_diversity":          round(obj_diversity, 2),
                "responsibility_factor":     round(responsibility_factor, 2),
                "size_factor":               round(size_factor, 2),
                "delegator_ratio":           round(delegator_ratio, 2),
                "safe_delegator_ratio":      round(safe_delegator_ratio, 2),
                "constructor_boost":         round(constructor_boost, 3),
                "injection_score":           injection_score,
                "adaptive_threshold":        round(adaptive_threshold * 100, 1),
                "detected_domains":          detected_domains,
                "body_detected_domains":     body_detected_domains,
                "collaborator_attrs":        sorted(collaborator_attrs),
                "weights_used":              {k: round(v, 3) for k, v in self.weights.items()},
                "single_method_scoring":     n_methods == 1,   # FIX E: flag for debugging
            },
        }

        for child in ast.walk(node):
            if isinstance(child, ast.ClassDef) and child is not node:
                self.visit_ClassDef(child)


def get_srp_report(code: str, weights: dict | None = None) -> list[dict]:
    """
    Analyze Python source code for Single Responsibility Principle violations.

    Args:
        code:    Python source as a string.
        weights: Optional dict to override scoring weights.

    Returns:
        List of result dicts for classes with violations, or a global Pass.
    """
    try:
        tree = ast.parse(code)
        analyzer = SRPAnalyzerEnhanced(weights=weights)
        analyzer.visit(tree)

        if not analyzer.report:
            return [{
                "status":     "Pass",
                "confidence": "high",
                "reason":     "No classes detected.",
            }]

        results = []
        for class_name, data in analyzer.report.items():
            status = data["status"]
            
            if status not in ("Violation", "Review"):
                continue

            diag         = data.get("diagnostics", {})
            ctor         = data.get("constructor", {})
            score        = data["srp_violation_score"]
            conf         = data["confidence"]
            domains      = diag.get("detected_domains", [])
            body_domains = diag.get("body_detected_domains", [])

            fired: list[str] = []
            
            # Heuristic checks
            if diag.get("object_diversity", 0) > 0.5:
                fired.append("methods depend on unrelated collaborators")
            if diag.get("effective_domain_div", 0) > 0.2:
                fired.append(f"name-inferred domains: {', '.join(domains)}")
            if diag.get("effective_body_domain_div", 0) > 0.2:
                extra = [d for d in body_domains if d not in domains]
                if extra:
                    fired.append(f"body-detected extra domains: {', '.join(extra)}")
                else:
                    fired.append(f"body scan confirms cross-domain activity: {', '.join(body_domains)}")
            if "__dispatch__" in body_domains:
                fired.append("type-dispatch flag (self.attr == literal) signals multiple responsibilities")
            if diag.get("lcom", 0) > 0.5:
                collabs = diag.get("collaborator_attrs", [])
                if collabs:
                    fired.append(f"disjoint collaborator usage ({', '.join(collabs[:4])})")
                else:
                    fired.append("methods share few instance variables (low cohesion)")
            if diag.get("size_factor", 0) > 0.3:
                fired.append("large/complex methods spread across the class")
            if diag.get("responsibility_factor", 0) > 0:
                fired.append("'And'/'Or' in method names signals multiple responsibilities")
            if ctor.get("injection_score", 0) > 0.3:
                n_c   = ctor.get("collaborator_count", 0)
                inj_d = ctor.get("injected_domains", [])
                fired.append(f"constructor injects {n_c} collaborators across domains: {', '.join(inj_d)}")
            if diag.get("delegator_ratio", 0) > 0.5:
                cross = diag.get("safe_delegator_ratio", 0) < diag.get("delegator_ratio", 0)
                note  = "cross-domain" if cross else "same-domain"
                fired.append(
                    f"note: {int(diag['delegator_ratio']*100)}% thin delegators "
                    f"({note} — {'penalty applied' if cross else 'penalty reduced'})"
                )

            reason_str     = "; ".join(fired) if fired else "multiple heuristics fired"
            threshold_note = f" (threshold: {diag.get('adaptive_threshold', 18)}%)"

            if status == "Review":
                reason_msg = (
                    f"Class '{class_name}' scored {score}%{threshold_note} — "
                    f"borderline result, manual review recommended. {reason_str}."
                )
            else:
                reason_msg = (
                    f"Class '{class_name}' scored {score}%{threshold_note} — {reason_str}."
                )

            results.append({
                "class":      class_name,
                "status":     status,
                "confidence": conf,
                "score":      score,
                "reason":     reason_msg,
            })

        if not results:
            return [{
                "status":     "Pass",
                "confidence": "high",
                "reason":     "No violations detected.",
            }]

        return results

    except SyntaxError as e:
        return [{"status": "Error", "reason": f"Syntax error: {e}", "suggestion": "Fix the syntax before analysis."}]
    except Exception as e:
        return [{"status": "Error", "reason": f"Unexpected error: {e}", "suggestion": "N/A"}]