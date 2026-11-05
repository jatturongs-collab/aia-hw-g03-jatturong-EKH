"""
xlcalc.py — tiny Excel formula evaluator for the formulas this skill generates.

Why: the Markdown companion must show exactly the numbers the workbook computes,
and openpyxl cannot calculate formulas.  LibreOffice is not always installed
(e.g. a fresh WSL box), so the builder evaluates its own formulas here.
If LibreOffice IS available, check_workbook.py cross-checks both engines.

Supported: numbers, "strings", cell refs (A1, $A$1, 'Sheet name'!A1), ranges inside
functions, + - * / ^ & unary -, % postfix, comparisons = <> < > <= >=,
functions IF IFERROR ROUND ROUNDUP ROUNDDOWN SUM SUMSQ AVERAGE MIN MAX ABS AND OR NOT
COUNT ISNUMBER TEXT(value only) .
Blank cells behave like Excel: 0 in arithmetic, "" in comparisons.
"""
import math
import re


class XLError(Exception):
    def __init__(self, code="#VALUE!"):
        self.code = code

    def __repr__(self):
        return self.code


ERR = XLError

TOK = re.compile(r"""
 (?P<ws>\s+)
|(?P<ref>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)?!?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
|(?P<num>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
|(?P<str>"(?:[^"]|"")*")
|(?P<func>[A-Z][A-Z0-9.]*\()
|(?P<op><>|>=|<=|[-+*/^&=<>(),%])
""", re.X)

REF_RE = re.compile(r"^(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?(?P<c1>[A-Z]{1,3})\$?(?P<r1>\d+)(?::\$?(?P<c2>[A-Z]{1,3})\$?(?P<r2>\d+))?$")


def col2num(c):
    n = 0
    for ch in c:
        n = n * 26 + (ord(ch) - 64)
    return n


def num2col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def tokenize(f):
    pos, out = 0, []
    while pos < len(f):
        m = TOK.match(f, pos)
        if not m:
            raise ValueError(f"cannot tokenize at {pos}: {f[pos:pos+20]!r} in {f!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group(kind)))
    return out


class Parser:
    PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek(); self.i += 1; return tok

    def parse(self, minp=0):
        left = self.unary()
        while True:
            k, v = self.peek()
            if k == "op" and v == "%":
                self.take(); left = ("pct", left); continue
            if k != "op" or v not in self.PREC or self.PREC[v] < minp:
                break
            self.take()
            p = self.PREC[v]
            right = self.parse(p + (0 if v == "^" else 1))
            left = ("bin", v, left, right)
        return left

    def unary(self):
        k, v = self.peek()
        if k == "op" and v in "+-":
            self.take()
            e = self.parse(5)
            return ("neg", e) if v == "-" else e
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v))
        if k == "str":
            return ("str", v[1:-1].replace('""', '"'))
        if k == "ref":
            return ("ref", v)
        if k == "func":
            name, args = v[:-1], []
            if self.peek() == ("op", ")"):
                self.take(); return ("fn", name, args)
            while True:
                if self.peek() in (("op", ","), ("op", ")")):
                    args.append(("blank",))
                else:
                    args.append(self.parse())
                k2, v2 = self.take()
                if v2 == ")":
                    break
                if v2 != ",":
                    raise ValueError("expected , or )")
            return ("fn", name, args)
        if k == "op" and v == "(":
            e = self.parse()
            self.take()
            return e
        raise ValueError(f"unexpected token {k} {v}")


class Workbook:
    """cells: {sheet: {"B6": value_or_formula}}"""

    def __init__(self, cells):
        self.cells = cells
        self.cache = {}
        self.ast = {}
        self.stack = set()

    def get(self, sheet, addr):
        key = (sheet, addr)
        if key in self.cache:
            return self.cache[key]
        raw = self.cells.get(sheet, {}).get(addr)
        if isinstance(raw, str) and raw.startswith("="):
            if key in self.stack:
                raise XLError("#CIRC!")
            self.stack.add(key)
            try:
                if raw not in self.ast:
                    self.ast[raw] = Parser(tokenize(raw[1:])).parse()
                val = self.ev(self.ast[raw], sheet)
                if isinstance(val, list):
                    val = val[0][0] if val and val[0] else None
            except XLError as e:
                val = e
            except ZeroDivisionError:
                val = XLError("#DIV/0!")
            finally:
                self.stack.discard(key)
        else:
            val = raw
        self.cache[key] = val
        return val

    # ----------------------------------------------------------------
    def resolve(self, ref, sheet):
        m = REF_RE.match(ref)
        if not m:
            raise XLError("#REF!")
        sh = m.group("sheet")
        if sh:
            sh = sh[1:-1].replace("''", "'") if sh.startswith("'") else sh
        else:
            sh = sheet
        if sh not in self.cells:
            raise XLError("#REF!")
        c1, r1 = col2num(m.group("c1")), int(m.group("r1"))
        if m.group("c2"):
            c2, r2 = col2num(m.group("c2")), int(m.group("r2"))
            return [[self.get(sh, f"{num2col(c)}{r}") for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
        return self.get(sh, f"{num2col(c1)}{r1}")

    @staticmethod
    def num(v):
        if isinstance(v, XLError):
            raise v
        if v is None or v == "":
            if v == "":
                raise XLError("#VALUE!")
            return 0.0
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            raise XLError("#VALUE!")

    @staticmethod
    def flat(vals):
        out = []
        for v in vals:
            if isinstance(v, list):
                for row in v:
                    out.extend(row)
            else:
                out.append(v)
        return out

    def ev(self, n, sheet):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "str":
            return n[1]
        if t == "blank":
            return None
        if t == "ref":
            return self.resolve(n[1], sheet)
        if t == "neg":
            return -self.num(self.ev(n[1], sheet))
        if t == "pct":
            return self.num(self.ev(n[1], sheet)) / 100
        if t == "bin":
            op = n[1]
            a, b = self.ev(n[2], sheet), self.ev(n[3], sheet)
            for x in (a, b):
                if isinstance(x, XLError):
                    raise x
            if op in ("=", "<>", "<", ">", "<=", ">="):
                a2 = "" if a is None and isinstance(b, str) else (0.0 if a is None else a)
                b2 = "" if b is None and isinstance(a, str) else (0.0 if b is None else b)
                if isinstance(a2, str) != isinstance(b2, str):
                    res = {"=": False, "<>": True}.get(op)
                    if res is None:
                        res = isinstance(a2, str) if op in (">", ">=") else not isinstance(a2, str)
                    return res
                if isinstance(a2, str):
                    a2, b2 = a2.lower(), b2.lower()
                return {"=": a2 == b2, "<>": a2 != b2, "<": a2 < b2, ">": a2 > b2, "<=": a2 <= b2, ">=": a2 >= b2}[op]
            if op == "&":
                s = lambda x: "" if x is None else (fmt_general(x) if isinstance(x, float) else str(x))
                return s(a) + s(b)
            x, y = self.num(a), self.num(b)
            if op == "+": return x + y
            if op == "-": return x - y
            if op == "*": return x * y
            if op == "/":
                if y == 0:
                    raise XLError("#DIV/0!")
                return x / y
            if op == "^":
                return x ** y
        if t == "fn":
            return self.fn(n[1], n[2], sheet)
        raise XLError("#NAME?")

    def fn(self, name, args, sheet):
        E = lambda a: self.ev(a, sheet)
        if name == "IF":
            c = E(args[0])
            if isinstance(c, XLError):
                raise c
            cond = bool(self.num(c)) if not isinstance(c, str) else (c != "")
            if cond:
                return E(args[1]) if len(args) > 1 else True
            return E(args[2]) if len(args) > 2 else False
        if name == "IFERROR":
            try:
                v = E(args[0])
                if isinstance(v, XLError):
                    raise v
                return v
            except (XLError, ZeroDivisionError, OverflowError, ValueError):
                return E(args[1])
        vals = [E(a) for a in args]
        if name in ("SUM", "SUMSQ", "AVERAGE", "MIN", "MAX", "COUNT"):
            fl = self.flat(vals)
            for x in fl:
                if isinstance(x, XLError):
                    raise x
            nums = [float(x) for x in fl if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if name == "SUM": return sum(nums)
            if name == "SUMSQ": return sum(x * x for x in nums)
            if name == "COUNT": return float(len(nums))
            if name == "AVERAGE":
                if not nums:
                    raise XLError("#DIV/0!")
                return sum(nums) / len(nums)
            if name == "MIN": return min(nums) if nums else 0.0
            if name == "MAX": return max(nums) if nums else 0.0
        if name == "N":
            x = vals[0]
            if isinstance(x, XLError):
                raise x
            return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else (1.0 if x is True else 0.0)
        if name == "ABS":
            return abs(self.num(vals[0]))
        if name in ("ROUND", "ROUNDUP", "ROUNDDOWN"):
            x, d = self.num(vals[0]), int(self.num(vals[1])) if len(vals) > 1 else 0
            f = 10 ** d
            if name == "ROUND":
                return math.floor(abs(x) * f + 0.5) / f * (1 if x >= 0 else -1)
            if name == "ROUNDUP":
                return math.ceil(abs(x) * f) / f * (1 if x >= 0 else -1)
            return math.floor(abs(x) * f) / f * (1 if x >= 0 else -1)
        if name == "AND":
            return all(bool(self.num(v)) for v in self.flat(vals))
        if name == "OR":
            return any(bool(self.num(v)) for v in self.flat(vals))
        if name == "NOT":
            return not bool(self.num(vals[0]))
        if name == "ISNUMBER":
            return isinstance(vals[0], (int, float)) and not isinstance(vals[0], bool)
        if name == "TEXT":
            return fmt_general(self.num(vals[0]))
        raise XLError("#NAME?")


def fmt_general(x):
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.10g}"
