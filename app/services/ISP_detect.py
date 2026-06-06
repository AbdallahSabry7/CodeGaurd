import ast
from collections import defaultdict
from itertools import combinations


class ISPDetector(ast.NodeVisitor):
    def __init__(self, method_threshold=6, unused_threshold=0.4):
        self.method_threshold  = method_threshold
        self.unused_threshold  = unused_threshold
        self.violations        = []
        self.current_class     = None
        self.current_interface = None
        self.interfaces        = {}   # iface_name → {methods, lineno, node}
        self.class_implements  = {}   # class_name → [base_names]
        self.class_attr_usage  = {}   # class_name → set of self.xxx names accessed/called
        self.class_methods     = {}   # class_name → [method_names]
        self.forced_methods    = {}   # class_name → {method_name: lineno}
        self.class_nodes       = {}   # class_name → ast.ClassDef node
        self.class_method_nodes = {}  # class_name → [ast.FunctionDef nodes]
        # Rule 14: parameter-level dependency tracking
        # Maps (class_name, param_name, param_type_hint) → set of called method names
        self.param_method_calls = {}  # class_name → list of (param_hint, {called_methods}, lineno)

    # ═══════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _is_interface(node):
        """
        Recognises interfaces by:
          - Name convention: class IFoo / class FooInterface
          - Direct inheritance from ABC or Protocol
        Concrete classes that merely implement an interface are NOT interfaces.
        """
        name = node.name
        if name.endswith("Interface") or (
            name.startswith("I") and len(name) > 1 and name[1].isupper()
        ):
            return True
        for base in node.bases:
            base_id = (
                base.id        if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else None
            )
            if base_id in ("ABC", "Protocol"):
                return True
        return False

    @staticmethod
    def _is_forced_body(func_node):
        """
        Returns True for stub / forced method bodies, including multi-line variants:
          - pass / ... (ellipsis)
          - raise NotImplementedError / NotImplemented
          - docstring-only body
          - docstring + any of the above
          - return / return None
          - any combination of the above with no real logic

        NOTE: Does NOT flag @abstractmethod decorated stubs — those are intentional.
        """
        # If decorated with @abstractmethod, the stub is intentional — skip
        for decorator in func_node.decorator_list:
            decorator_name = (
                decorator.id        if isinstance(decorator, ast.Name)
                else decorator.attr if isinstance(decorator, ast.Attribute)
                else None
            )
            if decorator_name == "abstractmethod":
                return False

        body = list(func_node.body)

        # Strip leading docstring
        if body and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                body = body[1:]

        if not body:   # docstring only
            return True

        def _is_stub_stmt(stmt):
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                if stmt.value.value is ...:
                    return True
            if isinstance(stmt, ast.Raise) and stmt.exc is not None:
                exc  = stmt.exc
                name = (
                    exc.id          if isinstance(exc, ast.Name)
                    else exc.func.id if (isinstance(exc, ast.Call)
                                         and isinstance(exc.func, ast.Name))
                    else None
                )
                if name in ("NotImplementedError", "NotImplemented"):
                    return True
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    return True
                if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                    return True
            return False

        return all(_is_stub_stmt(s) for s in body)

    @staticmethod
    def _count_params(func_node):
        """Total number of non-self parameters."""
        args  = func_node.args
        total = (
            len(args.args)
            + len(args.posonlyargs)
            + len(args.kwonlyargs)
            + (1 if args.vararg  else 0)
            + (1 if args.kwarg   else 0)
        )
        if args.args and args.args[0].arg == "self":
            total -= 1
        return total

    def _resolve_interface_methods(self, iface_name, _visited=None):
        """
        Returns the full set of method names for an interface,
        following its own inheritance chain (e.g. IChild extends IParent).
        Guards against circular inheritance with a visited set.
        Excludes __init__ and dunder methods to avoid inflating unused counts.
        """
        if _visited is None:
            _visited = set()
        if iface_name in _visited or iface_name not in self.interfaces:
            return set()
        _visited.add(iface_name)

        # Exclude __init__ and all other dunders (e.g. __len__, __contains__)
        # — implementors often don't call these on self, inflating unused counts
        methods = {
            m for m in self.interfaces[iface_name]["methods"]
            if not (m.startswith("__") and m.endswith("__"))
        }
        node = self.interfaces[iface_name]["node"]
        for base in node.bases:
            base_id = (
                base.id        if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else None
            )
            if base_id and base_id in self.interfaces:
                methods |= self._resolve_interface_methods(base_id, _visited)
        return methods

    def _all_interface_bases(self, class_name, _visited=None):
        """
        Returns every interface base reachable from a class,
        including through class inheritance (ClassB extends ClassA(IFoo)).
        Guards against circular inheritance.
        """
        if _visited is None:
            _visited = set()
        if class_name in _visited:
            return []
        _visited.add(class_name)

        ifaces = []
        for base in self.class_implements.get(class_name, []):
            if base in self.interfaces:
                ifaces.append(base)
            if base in self.class_implements:
                ifaces.extend(self._all_interface_bases(base, _visited))
        return ifaces

    def _interface_inheritance_depth(self, iface_name, _visited=None):
        """
        Returns the number of interface ancestors (not counting self).
        Used by Rule 10.
        """
        if _visited is None:
            _visited = set()
        if iface_name in _visited or iface_name not in self.interfaces:
            return 0
        _visited.add(iface_name)

        node = self.interfaces[iface_name]["node"]
        max_depth = 0
        for base in node.bases:
            base_id = (
                base.id        if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else None
            )
            if base_id and base_id in self.interfaces:
                depth = 1 + self._interface_inheritance_depth(base_id, _visited)
                max_depth = max(max_depth, depth)
        return max_depth

    @staticmethod
    def _classify_method_domain(method_name: str) -> str | None:
        """
        Returns a domain label for a method name using keyword matching.
        Returns None if the method doesn't match any known domain.
        Used by Rule 8 (standalone class role mixing).

        __str__ and __repr__ are intentionally excluded — they're universal
        and should not constitute a "ui" domain hit on their own.
        """
        # Universal dunders: never count as a domain
        UNIVERSAL_DUNDERS = {"__str__", "__repr__", "__init__", "__del__",
                             "__new__", "__hash__", "__eq__", "__ne__",
                             "__lt__", "__le__", "__gt__", "__ge__"}
        if method_name in UNIVERSAL_DUNDERS:
            return None

        domain_keywords = {
            "persistence": ["save", "load", "store", "fetch", "persist",
                            "insert", "update", "delete", "remove", "put",
                            "get", "add", "pop", "push"],
            "query":       ["lookup", "find", "search", "filter", "query",
                            "list", "count", "exists", "contains"],
            "network":     ["connect", "send", "receive", "request", "socket",
                            "stream", "download", "upload", "ping", "http"],
            "ui":          ["render", "draw", "display", "show", "hide", "paint",
                            "layout", "refresh", "repaint", "widget",
                            "format", "print"],
            "logging":     ["log", "trace", "debug", "audit", "monitor",
                            "report", "warn", "error", "info"],
            "cache":       ["cache", "invalidate", "expire", "flush",
                            "evict", "clear", "hit", "miss"],
            "auth":        ["login", "logout", "authenticate", "authorize",
                            "token", "password", "permission", "role"],
            "file":        ["open", "close", "seek", "tell", "truncate",
                            "rename", "copy", "move", "mkdir", "read", "write"],
        }
        name_lower = method_name.lower()
        for domain, keywords in domain_keywords.items():
            if any(kw in name_lower for kw in keywords):
                return domain
        return None

    # ═══════════════════════════════════════════════════════════
    #  Visitors
    # ═══════════════════════════════════════════════════════════

    def visit_ClassDef(self, node):
        bases   = [b.id for b in node.bases if isinstance(b, ast.Name)]
        methods = [f.name for f in node.body if isinstance(f, ast.FunctionDef)]
        method_nodes = [f for f in node.body if isinstance(f, ast.FunctionDef)]

        if self._is_interface(node):
            self.current_interface        = node.name
            self.interfaces[node.name]    = {
                "methods": methods,
                "lineno":  node.lineno,
                "node":    node,
            }
            self.detect_fat_interface(node, methods)
            self.detect_interface_role_mixing(node)
            self.detect_parameter_bloat(node)
            self.detect_interface_inheritance_depth(node)   # Rule 10
            self.current_interface = None
            return

        self.current_class                     = node.name
        self.class_methods[node.name]          = methods
        self.class_implements[node.name]       = bases
        self.class_attr_usage[node.name]       = set()
        self.forced_methods[node.name]         = {}
        self.class_nodes[node.name]            = node
        self.class_method_nodes[node.name]     = method_nodes
        self.param_method_calls[node.name]     = []

        for f in node.body:
            if isinstance(f, ast.FunctionDef):
                self.visit(f)

        self.detect_unused_interface_methods(node)
        self.detect_forced_methods(node)
        self.detect_client_role_segregation(node)
        self.detect_standalone_role_mixing(node)
        self.detect_type_dispatch(node)
        self.detect_god_class(node)                         # Rule 13
        self.detect_optional_method_pattern(node)          # Rule 11
        self.detect_boolean_flag_dispatch(node)            # Rule 12
        self.detect_coarse_parameter_dependency(node)      # Rule 14

        self.current_class = None

    def visit_FunctionDef(self, node):
        if not self.current_class:
            return

        # Forced / stub detection
        if node.name != "__init__" and self._is_forced_body(node):
            self.forced_methods[self.current_class][node.name] = node.lineno

        # Track every self.xxx access (superset of calls)
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name) and child.value.id == "self":
                    self.class_attr_usage[self.current_class].add(child.attr)

        # Rule 14: track method calls on typed parameters (excluding self)
        self._track_param_method_calls(node)

    def _track_param_method_calls(self, func_node):
        """
        For each annotated non-self parameter that looks like an interface type
        (name starts with 'I' + uppercase, or ends with 'Interface'),
        record which methods are called on it within the function body.
        """
        args = func_node.args.args
        if not args:
            return

        # Build map: param_name → type_hint_name (only for annotated params)
        param_types = {}
        for arg in args:
            if arg.arg == "self":
                continue
            if arg.annotation is None:
                continue
            hint = (
                arg.annotation.id   if isinstance(arg.annotation, ast.Name)
                else arg.annotation.attr if isinstance(arg.annotation, ast.Attribute)
                else None
            )
            if hint and (
                (hint.startswith("I") and len(hint) > 1 and hint[1].isupper())
                or hint.endswith("Interface")
            ):
                param_types[arg.arg] = hint

        if not param_types:
            return

        # Walk the function body and collect method calls on these params
        calls_on_param: dict[str, set] = defaultdict(set)
        for child in ast.walk(func_node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id in param_types
            ):
                param_name = child.func.value.id
                calls_on_param[param_name].add(child.func.attr)

        for param_name, called in calls_on_param.items():
            hint = param_types[param_name]
            self.param_method_calls[self.current_class].append(
                (hint, called, func_node.lineno)
            )

    # Post-visit hook — runs after the entire tree is walked
    def _post_visit(self):
        self.detect_cross_class_disjoint_usage()

    # ═══════════════════════════════════════════════════════════
    #  Detection rules
    # ═══════════════════════════════════════════════════════════

    # ── Rule 1: Fat Interface ─────────────────────────────────────
    def detect_fat_interface(self, node, methods):
        count = len(methods)
        if count > self.method_threshold:
            severity = "HIGH" if count > self.method_threshold + 2 else "MEDIUM"
            self.violations.append({
                "interface":  node.name,
                "lineno":     node.lineno,
                "severity":   severity,
                "type":       "Fat Interface",
                "reason": (
                    f"Has {count} methods — interfaces this large force clients "
                    f"to depend on methods they don't use."
                ),
                "suggestion": (
                    "Split into focused interfaces by responsibility "
                    "(e.g. IDataReader, IDataWriter, IRenderer)."
                ),
            })

    # ── Rule 2: Responsibility Mixing ─────────────────────────────
    def detect_interface_role_mixing(self, node):
        domain_keywords = {
            "persistence": ["save", "load", "store", "fetch", "read", "write",
                            "persist", "insert", "update", "delete", "remove"],
            "network":     ["connect", "send", "receive", "request", "socket",
                            "stream", "download", "upload", "ping", "http", "url"],
            "ui":          ["render", "draw", "display", "show", "hide", "paint",
                            "layout", "refresh", "repaint", "widget"],
            "logging":     ["log", "trace", "debug", "audit", "monitor",
                            "report", "warn", "error", "info"],
            "cache":       ["cache", "invalidate", "expire", "flush",
                            "evict", "clear", "hit", "miss"],
            "email":       ["email", "mail", "notify", "alert", "message",
                            "sms", "push", "broadcast"],
            "auth":        ["login", "logout", "authenticate", "authorize",
                            "token", "password", "permission", "role"],
            "file":        ["open", "close", "seek", "tell", "truncate",
                            "rename", "copy", "move", "mkdir"],
        }

        # Need at least 4 methods before role mixing is meaningful
        method_nodes = [f for f in node.body if isinstance(f, ast.FunctionDef)]
        if len(method_nodes) < 4:
            return

        domains = set()
        for f in method_nodes:
            name_lower = f.name.lower()
            for domain, keywords in domain_keywords.items():
                if any(kw in name_lower for kw in keywords):
                    domains.add(domain)

        if len(domains) >= 3:
            self.violations.append({
                "interface": node.name,
                "lineno":    node.lineno,
                "severity":  "HIGH",
                "type":      "Responsibility Mixing",
                "reason": (
                    f"Mixes {len(domains)} unrelated domains: "
                    f"{', '.join(sorted(domains))}."
                ),
                "suggestion": (
                    "Create one interface per domain: "
                    + ", ".join(
                        f"I{d.capitalize()}" for d in sorted(domains)
                    ) + "."
                ),
            })
        elif len(domains) == 2:
            self.violations.append({
                "interface": node.name,
                "lineno":    node.lineno,
                "severity":  "MEDIUM",
                "type":      "Responsibility Mixing",
                "reason":    f"Mixes 2 domains: {', '.join(sorted(domains))}.",
                "suggestion": (
                    "Consider separating into distinct interfaces for clarity."
                ),
            })

    # ── Rule 3: Parameter Bloat ───────────────────────────────────
    def detect_parameter_bloat(self, node):
        PARAM_THRESHOLD = 4
        bloated = [
            (f.name, self._count_params(f), f.lineno)
            for f in node.body
            if isinstance(f, ast.FunctionDef)
            and f.name != "__init__"
            and self._count_params(f) > PARAM_THRESHOLD
        ]
        if bloated:
            names = ", ".join(f"'{n}'({c} params)" for n, c, _ in bloated)
            self.violations.append({
                "interface": node.name,
                "lineno":    bloated[0][2],
                "severity":  "MEDIUM",
                "type":      "Parameter Bloat",
                "reason": (
                    f"Methods with too many parameters force clients to know "
                    f"about data they may not use: {names}."
                ),
                "suggestion": (
                    "Introduce parameter objects or split the method across "
                    "narrower interfaces so each client only sees what it needs."
                ),
            })

    # ── Rule 4: Unused Interface Methods ─────────────────────────
    def detect_unused_interface_methods(self, node):
        seen_pairs = set()
        for base in self._all_interface_bases(node.name):
            if base in seen_pairs:
                continue
            seen_pairs.add(base)

            interface_methods = self._resolve_interface_methods(base)
            if not interface_methods:
                continue

            defined = set(self.class_methods.get(node.name, []))
            used   = (self.class_attr_usage.get(node.name, set()) | defined) & interface_methods
            unused = interface_methods - used
            ratio  = len(unused) / len(interface_methods)

            if ratio >= 0.6:
                severity = "HIGH"
            elif ratio >= self.unused_threshold:
                severity = "MEDIUM"
            else:
                continue

            self.violations.append({
                "class":    node.name,
                "lineno":   node.lineno,
                "severity": severity,
                "type":     "Unused Interface Methods",
                "reason": (
                    f"Implements '{base}' but only uses "
                    f"{len(used)}/{len(interface_methods)} "
                    f"of its methods. Unused: {', '.join(sorted(unused))}."
                ),
                "suggestion": (
                    f"Break '{base}' into smaller interfaces so '{node.name}' "
                    f"only depends on what it actually uses."
                ),
            })

    # ── Rule 5: Forced Implementations ───────────────────────────
    def detect_forced_methods(self, node):
        forced = self.forced_methods[node.name]
        if not forced:
            return

        interface_methods = set()
        for base in self._all_interface_bases(node.name):
            interface_methods |= self._resolve_interface_methods(base)

        if not interface_methods:
            return

        # Only report stubs that belong to an interface contract
        # and are NOT decorated with @abstractmethod (those are intentional)
        interface_forced = {
            m: lineno
            for m, lineno in forced.items()
            if m in interface_methods
        }
        if not interface_forced:
            return

        severity = "HIGH" if len(interface_forced) >= 3 else "MEDIUM"
        for method, lineno in interface_forced.items():
            self.violations.append({
                "class":    node.name,
                "lineno":   lineno,
                "severity": severity,
                "type":     "Forced Implementation",
                "reason": (
                    f"Method '{method}' has a stub body "
                    f"(pass / raise NotImplementedError / return None / ...) "
                    f"— this class may be forced to implement methods it doesn't need."
                ),
                "suggestion": (
                    f"Check if '{method}' truly belongs to this class. "
                    f"If not, split the interface so this class only implements "
                    f"what it needs."
                ),
            })

    # ── Rule 6: Client Role Segregation ──────────────────────────
    def detect_client_role_segregation(self, node):
        existing_unused_targets = {
            v["class"] for v in self.violations
            if v.get("type") == "Unused Interface Methods"
            and v.get("class") == node.name
        }

        for base in self._all_interface_bases(node.name):
            if node.name in existing_unused_targets:
                continue
            interface_methods = self._resolve_interface_methods(base)
            if len(interface_methods) < 4:
                continue

            defined = set(self.class_methods.get(node.name, []))
            used   = (self.class_attr_usage.get(node.name, set()) | defined) & interface_methods
            unused = interface_methods - used

            if len(used) > 0 and len(unused) > len(used):
                self.violations.append({
                    "class":    node.name,
                    "lineno":   node.lineno,
                    "severity": "MEDIUM",
                    "type":     "Client Role Segregation",
                    "reason": (
                        f"'{node.name}' uses only {len(used)}/{len(interface_methods)} "
                        f"methods of '{base}' ({', '.join(sorted(used))}), "
                        f"suggesting the interface serves multiple unrelated client roles."
                    ),
                    "suggestion": (
                        f"Split '{base}' into role-specific interfaces so each "
                        f"client depends only on the methods it actually needs."
                    ),
                })

    # ── Rule 7: Cross-Class Disjoint Usage ───────────────────────
    def detect_cross_class_disjoint_usage(self):
        iface_to_classes = {}
        for cls_name, bases in self.class_implements.items():
            for base in bases:
                if base in self.interfaces:
                    iface_to_classes.setdefault(base, []).append(cls_name)

        # Deduplicate: fire at most once per interface (not once per pair)
        already_flagged_ifaces = set()

        for iface_name, implementors in iface_to_classes.items():
            if len(implementors) < 2:
                continue

            iface_methods = self._resolve_interface_methods(iface_name)
            if len(iface_methods) < 4:
                continue

            for i in range(len(implementors)):
                if iface_name in already_flagged_ifaces:
                    break
                for j in range(i + 1, len(implementors)):
                    if iface_name in already_flagged_ifaces:
                        break
                    cls_a = implementors[i]
                    cls_b = implementors[j]
                    used_a = (self.class_attr_usage.get(cls_a, set()) | set(self.class_methods.get(cls_a, []))) & iface_methods
                    used_b = (self.class_attr_usage.get(cls_b, set()) | set(self.class_methods.get(cls_b, []))) & iface_methods

                    if not used_a or not used_b:
                        continue

                    overlap = used_a & used_b
                    overlap_ratio = len(overlap) / max(len(used_a), len(used_b))

                    if overlap_ratio <= 0.25:
                        already_flagged_ifaces.add(iface_name)
                        self.violations.append({
                            "interface": iface_name,
                            "lineno":    self.interfaces[iface_name]["lineno"],
                            "severity":  "HIGH",
                            "type":      "Cross-Class Disjoint Usage",
                            "reason": (
                                f"'{cls_a}' uses {{{', '.join(sorted(used_a))}}} "
                                f"and '{cls_b}' uses {{{', '.join(sorted(used_b))}}} "
                                f"from '{iface_name}' with only "
                                f"{len(overlap)} method(s) in common — "
                                f"clear evidence the interface serves two unrelated clients."
                            ),
                            "suggestion": (
                                f"Split '{iface_name}' so '{cls_a}' and '{cls_b}' "
                                f"each get their own focused interface."
                            ),
                        })

    # ── Rule 8: Standalone Class Role Mixing ─────────────────────
    def detect_standalone_role_mixing(self, node):
        if self._all_interface_bases(node.name):
            return

        INCLUDE_DUNDERS = {"__len__", "__contains__"}
        public_methods = [
            f for f in self.class_method_nodes.get(node.name, [])
            if not f.name.startswith("_") or f.name in INCLUDE_DUNDERS
        ]

        if len(public_methods) < 3:
            return

        domain_methods: dict[str, list[str]] = defaultdict(list)
        for f in public_methods:
            domain = self._classify_method_domain(f.name)
            if domain:
                domain_methods[domain].append(f.name)

        # FIX: require ≥2 methods per domain to count as a significant domain hit
        # (previously was >= 1, causing single stray methods to trigger the rule)
        significant_domains = {
            d: ms for d, ms in domain_methods.items() if len(ms) >= 2
        }

        MUTATION_DOMAINS     = {"persistence", "file", "network", "cache", "auth"}
        PRESENTATION_DOMAINS = {"ui", "logging"}

        mutation_hits     = significant_domains.keys() & MUTATION_DOMAINS
        presentation_hits = significant_domains.keys() & PRESENTATION_DOMAINS

        fires = False
        mixed_domains = set()

        if mutation_hits and presentation_hits:
            fires = True
            mixed_domains = mutation_hits | presentation_hits
        elif len(significant_domains) >= 3:
            fires = True
            mixed_domains = set(significant_domains.keys())

        if not fires:
            return

        domain_summary = ", ".join(
            f"{d}({', '.join(significant_domains[d])})"
            for d in sorted(mixed_domains)
        )

        suggestions = ", ".join(
            f"I{d.capitalize()}Operations" if d in MUTATION_DOMAINS
            else f"I{d.capitalize()}"
            for d in sorted(mixed_domains)
        )

        self.violations.append({
            "class":    node.name,
            "lineno":   node.lineno,
            "severity": "MEDIUM",
            "type":     "Standalone Class Role Mixing",
            "reason": (
                f"'{node.name}' has no interface but bundles "
                f"{len(mixed_domains)} unrelated responsibilities: "
                f"{domain_summary}. "
                f"Clients that only need one role are forced to depend on all of them."
            ),
            "suggestion": (
                f"Extract an interface per responsibility: {suggestions}. "
                f"Each client then depends only on the interface it actually needs."
            ),
        })

    # ── Rule 9: Type-Dispatch Multiplexing ───────────────────────
    TYPE_PARAM_NAMES = {"type", "kind", "mode", "variant", "strategy"}

    def detect_type_dispatch(self, node):
        type_attrs: set[str] = set()

        init_node = next(
            (f for f in self.class_method_nodes.get(node.name, [])
             if f.name == "__init__"),
            None,
        )
        if init_node:
            for stmt in ast.walk(init_node):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr in self.TYPE_PARAM_NAMES
                        ):
                            type_attrs.add(target.attr)

                if isinstance(stmt, ast.AnnAssign):
                    target = stmt.target
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in self.TYPE_PARAM_NAMES
                    ):
                        type_attrs.add(target.attr)

        if not type_attrs:
            return

        dispatching_methods: list[tuple[str, int, set]] = []

        for func in self.class_method_nodes.get(node.name, []):
            if func.name == "__init__":
                continue
            branches = self._collect_type_dispatch_branches(func, type_attrs)
            if len(branches) >= 2:
                dispatching_methods.append((func.name, func.lineno, branches))

        if not dispatching_methods:
            return

        max_branches = max(len(b) for _, _, b in dispatching_methods)
        severity = "HIGH" if max_branches >= 3 else "MEDIUM"

        method_summary = ", ".join(
            f"'{name}'({len(br)} branches)"
            for name, _, br in dispatching_methods
        )

        self.violations.append({
            "class":    node.name,
            "lineno":   node.lineno,
            "severity": severity,
            "type":     "Type-Dispatch Multiplexing",
            "reason": (
                f"'{node.name}' uses a type-selector attribute "
                f"({', '.join(sorted(type_attrs))}) to branch into "
                f"{max_branches} distinct behaviours in: {method_summary}. "
                f"This packs multiple unrelated clients into one class — "
                f"every user of '{node.name}' implicitly depends on all variants."
            ),
            "suggestion": (
                f"Replace the type-dispatch with one class per variant "
                f"(e.g. FileWriter, NetworkWriter, DatabaseWriter) and extract "
                f"a shared interface (e.g. IWriter) with only the methods each "
                f"variant actually needs."
            ),
        })

    def _collect_type_dispatch_branches(
        self, func_node: ast.FunctionDef, type_attrs: set[str]
    ) -> set:
        branches: set = set()

        for node in ast.walk(func_node):
            if not isinstance(node, ast.If):
                continue

            for compare in self._extract_compares(node.test):
                left  = compare.left
                ops   = compare.ops
                comps = compare.comparators

                if len(ops) != 1 or not isinstance(ops[0], ast.Eq):
                    continue

                if (
                    isinstance(left, ast.Attribute)
                    and isinstance(left.value, ast.Name)
                    and left.value.id == "self"
                    and left.attr in type_attrs
                    and len(comps) == 1
                    and isinstance(comps[0], ast.Constant)
                ):
                    branches.add(comps[0].value)

                if (
                    isinstance(left, ast.Constant)
                    and len(comps) == 1
                    and isinstance(comps[0], ast.Attribute)
                    and isinstance(comps[0].value, ast.Name)
                    and comps[0].value.id == "self"
                    and comps[0].attr in type_attrs
                ):
                    branches.add(left.value)

        return branches

    @staticmethod
    def _extract_compares(test_node) -> list[ast.Compare]:
        if isinstance(test_node, ast.Compare):
            return [test_node]
        if isinstance(test_node, ast.BoolOp):
            result = []
            for value in test_node.values:
                result.extend(ISPDetector._extract_compares(value))
            return result
        return []

    # ── Rule 10: Interface Inheritance Depth ──────────────────────
    # NEW: An interface that inherits from 3+ other interfaces becomes a
    # de-facto fat interface. Every implementor is forced to implement the
    # entire ancestor chain, even if they only need a leaf subset.
    def detect_interface_inheritance_depth(self, node):
        DEPTH_THRESHOLD = 2  # more than 2 levels deep is a smell
        depth = self._interface_inheritance_depth(node.name)
        if depth <= DEPTH_THRESHOLD:
            return

        # Collect all ancestor interface names for the message
        ancestors = []
        def _collect_ancestors(iface_name, visited=None):
            if visited is None:
                visited = set()
            if iface_name in visited or iface_name not in self.interfaces:
                return
            visited.add(iface_name)
            iface_node = self.interfaces[iface_name]["node"]
            for base in iface_node.bases:
                base_id = (
                    base.id        if isinstance(base, ast.Name)
                    else base.attr if isinstance(base, ast.Attribute)
                    else None
                )
                if base_id and base_id in self.interfaces:
                    ancestors.append(base_id)
                    _collect_ancestors(base_id, visited)
        _collect_ancestors(node.name)

        severity = "HIGH" if depth >= 4 else "MEDIUM"
        self.violations.append({
            "interface": node.name,
            "lineno":    node.lineno,
            "severity":  severity,
            "type":      "Interface Inheritance Depth",
            "reason": (
                f"'{node.name}' has an inheritance depth of {depth} "
                f"(ancestors: {', '.join(ancestors)}). "
                f"Deep interface chains force implementors to satisfy the entire "
                f"ancestor contract even when they only need a small subset."
            ),
            "suggestion": (
                f"Flatten '{node.name}' — compose small focused interfaces at the "
                f"call site rather than inheriting them all into one deep hierarchy."
            ),
        })

    # ── Rule 11: Optional Method Pattern ─────────────────────────
    # NEW: Catches methods in concrete classes that always return a constant
    # (None, True, False, 0, "") — not a raise-stub, but a semantically empty
    # implementation that signals the class doesn't need the method.
    # Only fires when the class implements an interface (otherwise it's not ISP).
    def detect_optional_method_pattern(self, node):
        interface_methods = set()
        for base in self._all_interface_bases(node.name):
            interface_methods |= self._resolve_interface_methods(base)

        if not interface_methods:
            return

        optional_hits = []
        for func in self.class_method_nodes.get(node.name, []):
            if func.name == "__init__" or func.name not in interface_methods:
                continue
            # Skip stubs already caught by Rule 5
            if func.name in self.forced_methods.get(node.name, {}):
                continue
            # Skip @abstractmethod
            for decorator in func.decorator_list:
                dec_name = (
                    decorator.id        if isinstance(decorator, ast.Name)
                    else decorator.attr if isinstance(decorator, ast.Attribute)
                    else None
                )
                if dec_name == "abstractmethod":
                    break
            else:
                body = list(func.body)
                # Strip docstring
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        body = body[1:]

                # Exactly one statement: a return of a constant (not None — that's Rule 5)
                if len(body) == 1 and isinstance(body[0], ast.Return):
                    ret_val = body[0].value
                    if isinstance(ret_val, ast.Constant) and ret_val.value is not None:
                        optional_hits.append((func.name, func.lineno, repr(ret_val.value)))

        if not optional_hits:
            return

        for method, lineno, val in optional_hits:
            self.violations.append({
                "class":    node.name,
                "lineno":   lineno,
                "severity": "MEDIUM",
                "type":     "Optional Method Pattern",
                "reason": (
                    f"Method '{method}' always returns a constant ({val}), "
                    f"suggesting this class doesn't actually need it — "
                    f"it's satisfying the interface contract nominally."
                ),
                "suggestion": (
                    f"If '{method}' is not meaningful for '{node.name}', "
                    f"split the interface so this class only implements what it uses."
                ),
            })

    # ── Rule 12: Boolean Flag Dispatch ───────────────────────────
    # NEW: Catches classes that store boolean flags in __init__ and branch
    # on them in multiple methods — a disguised multi-variant class that
    # forces all clients to carry logic they don't need.
    # Complements Rule 9 (which only catches named type/kind/mode selectors).
    BOOL_PARAM_NAMES = {"is_async", "async_mode", "use_cache", "cached",
                        "compressed", "encrypted", "buffered", "lazy",
                        "strict", "verbose", "debug", "dry_run", "enabled"}

    def detect_boolean_flag_dispatch(self, node):
        bool_attrs: set[str] = set()

        init_node = next(
            (f for f in self.class_method_nodes.get(node.name, [])
             if f.name == "__init__"),
            None,
        )
        if not init_node:
            return

        # Collect self.<bool_attr> assignments in __init__
        for stmt in ast.walk(init_node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in self.BOOL_PARAM_NAMES
                    ):
                        bool_attrs.add(target.attr)
            if isinstance(stmt, ast.AnnAssign):
                target = stmt.target
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in self.BOOL_PARAM_NAMES
                ):
                    bool_attrs.add(target.attr)

        if not bool_attrs:
            return

        # Find methods that branch on these bool attrs in if/else
        branching_methods = []
        for func in self.class_method_nodes.get(node.name, []):
            if func.name == "__init__":
                continue
            hits = self._find_bool_flag_branches(func, bool_attrs)
            if hits:
                branching_methods.append((func.name, func.lineno, hits))

        # Only fire if the flag drives branching in 2+ methods
        # (a single method is acceptable; it's when behaviour is
        # systematically split across the whole class that it's ISP)
        if len(branching_methods) < 2:
            return

        flag_summary = ", ".join(sorted(bool_attrs))
        method_summary = ", ".join(f"'{n}'" for n, _, _ in branching_methods)

        self.violations.append({
            "class":    node.name,
            "lineno":   node.lineno,
            "severity": "MEDIUM",
            "type":     "Boolean Flag Dispatch",
            "reason": (
                f"'{node.name}' uses boolean flag(s) ({flag_summary}) set in "
                f"__init__ to branch into different behaviour across {len(branching_methods)} "
                f"methods ({method_summary}). This is a disguised multi-variant class — "
                f"clients that need only one variant are forced to carry the logic of all."
            ),
            "suggestion": (
                f"Split '{node.name}' into one class per variant "
                f"and extract a shared interface with only the methods each "
                f"variant actually needs."
            ),
        })

    def _find_bool_flag_branches(self, func_node, bool_attrs):
        """
        Returns the set of bool attrs that drive if/else branching in func_node.
        """
        hits = set()
        for node in ast.walk(func_node):
            if not isinstance(node, ast.If):
                continue
            # The test is directly `self.<bool_attr>` or `not self.<bool_attr>`
            test = node.test
            # Handle: `not self.attr`
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                test = test.operand
            if (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "self"
                and test.attr in bool_attrs
            ):
                hits.add(test.attr)
        return hits

    # ── Rule 13: God Class ────────────────────────────────────────
    # NEW: A standalone class (no interface) with too many public methods
    # forces every client to take the entire surface area, even if they
    # need only one or two methods. This is the class-level ISP smell.
    GOD_CLASS_THRESHOLD = 10

    def detect_god_class(self, node):
        # Only for standalone classes not already covered by interface rules
        if self._all_interface_bases(node.name):
            return

        INCLUDE_DUNDERS = {"__str__", "__repr__", "__len__", "__contains__",
                           "__iter__", "__next__", "__getitem__", "__setitem__"}
        public_methods = [
            f for f in self.class_method_nodes.get(node.name, [])
            if not f.name.startswith("_") or f.name in INCLUDE_DUNDERS
        ]

        count = len(public_methods)
        if count <= self.GOD_CLASS_THRESHOLD:
            return

        severity = "HIGH" if count >= self.GOD_CLASS_THRESHOLD + 5 else "MEDIUM"
        method_names = ", ".join(f.name for f in public_methods)

        self.violations.append({
            "class":    node.name,
            "lineno":   node.lineno,
            "severity": severity,
            "type":     "God Class",
            "reason": (
                f"'{node.name}' exposes {count} public methods ({method_names}). "
                f"Without an interface, every client that imports this class takes "
                f"a dependency on its entire surface — a violation of ISP at the "
                f"class level."
            ),
            "suggestion": (
                f"Extract role-based interfaces (e.g. IReader, IWriter, IValidator) "
                f"so clients can depend on only the slice they need. "
                f"Consider whether '{node.name}' should be split into smaller classes."
            ),
        })

    # ── Rule 14: Coarse-Grained Parameter Dependency ─────────────
    # NEW: A function that accepts an interface as a parameter but only calls
    # 1-2 methods on it is a client with too broad a dependency.
    # The interface could be split so the function only depends on the
    # narrow subset it actually uses.
    def detect_coarse_parameter_dependency(self, node):
        for iface_hint, called_methods, lineno in self.param_method_calls.get(node.name, []):
            # We need to know the interface's total method count
            if iface_hint not in self.interfaces:
                continue

            iface_methods = self._resolve_interface_methods(iface_hint)
            if len(iface_methods) < 4:
                continue  # Too small to matter

            usage_ratio = len(called_methods) / len(iface_methods)
            if usage_ratio >= 0.5:
                continue  # Using at least half — reasonable dependency

            severity = "HIGH" if usage_ratio <= 0.2 else "MEDIUM"

            self.violations.append({
                "class":    node.name,
                "lineno":   lineno,
                "severity": severity,
                "type":     "Coarse-Grained Parameter Dependency",
                "reason": (
                    f"A method in '{node.name}' accepts '{iface_hint}' as a parameter "
                    f"but only calls {len(called_methods)}/{len(iface_methods)} of its "
                    f"methods ({', '.join(sorted(called_methods))}). "
                    f"The function depends on far more interface surface than it needs."
                ),
                "suggestion": (
                    f"Extract a narrower interface (e.g. I{iface_hint.lstrip('I')}Reader) "
                    f"containing only the methods this function calls, and type the "
                    f"parameter against that instead of the full '{iface_hint}'."
                ),
            })


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════

def analyze_isp(code, method_threshold=6, unused_threshold=0.4):
    """
    Parse and analyse Python source for ISP violations.
    Returns a list of violation dicts, sorted HIGH → MEDIUM → LOW.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        print(f"Syntax Error: {e}")
        return []

    detector = ISPDetector(method_threshold, unused_threshold)
    detector.visit(tree)
    detector._post_visit()

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    detector.violations.sort(key=lambda v: order.get(v.get("severity", "LOW"), 2))
    return detector.violations


def get_isp_report(code_str: str):
    """
    Returns a structured report with ALL violations found.

    Shape:
    {
        "status":     "Pass" | "Violation" | "Error",
        "total":      int,
        "high":       int,
        "medium":     int,
        "low":        int,
        "violations": list,
        "reason":     str,
    }
    """
    try:
        violations = analyze_isp(code_str)

        if not violations:
            return {
                "status":     "Pass",
                "total":      0,
                "high":       0,
                "medium":     0,
                "low":        0,
                "violations": [],
                "reason":     "No ISP violations detected.",
            }

        high   = sum(1 for v in violations if v.get("severity") == "HIGH")
        medium = sum(1 for v in violations if v.get("severity") == "MEDIUM")
        low    = sum(1 for v in violations if v.get("severity") == "LOW")

        return {
            "status":     "Violation",
            "total":      len(violations),
            "high":       high,
            "medium":     medium,
            "low":        low,
            "violations": violations,
            "reason": (
                f"Found {len(violations)} violation(s): "
                f"{high} high, {medium} medium, {low} low."
            ),
        }

    except Exception as e:
        return {
            "status":     "Error",
            "total":      0,
            "high":       0,
            "medium":     0,
            "low":        0,
            "violations": [],
            "reason":     f"Analyzer error: {e}",
        }


