"""A deliberately small reader for the authored-data subset of KickAssembler.

THIS IS NOT A KICKASSEMBLER PARSER AND MUST NOT PRETEND TO BE ONE. It reads the
handful of declaration forms that src/wave_programs.asm and src/wave_encounters.asm
actually use to author encounter data, and it raises on anything else rather than
guessing. Read-only: it never rewrites assembly.

THE SUPPORTED SUBSET, in full:

    .const NAME = <arith>
    .var   NAME = <arith>
    .var   NAME = List()[.add(<element>, ...)]...
    .eval  NAME.add(<element>, ...)          # appends to an existing .var list

    <element> := <arith> | <nested List() expression> | <name of a .var list>
    <arith>   := integers and + - * / over decimal, $hex and %binary literals,
                 identifiers bound earlier, and parentheses.

WHAT IT DELIBERATELY DOES NOT DO:

  * control flow. `.for` and `.if` blocks are SKIPPED WHOLE, not interpreted.
    src/wave_programs.asm computes progAt/progBytes in a `.for` loop; the
    importer derives those the same way the engine's own arithmetic does
    (WM_STAGE_SIZE * stages) and checks the result, rather than this module
    pretending to execute assembler macros;
  * segments, labels, .byte emission, macros, functions, strings, .error;
  * any expression operator outside + - * / and parentheses.

Every failure carries the file and the line the declaration started on.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re


class AsmSyntaxError(ValueError):
    """Unsupported or malformed source. Never raised for a value we could guess."""


@dataclass
class AsmSource:
    """What one or more authored files declared."""
    consts: dict = field(default_factory=dict)   # name -> int
    lists: dict = field(default_factory=dict)    # name -> list (ints / nested lists)
    skipped_blocks: list = field(default_factory=list)   # (file, line, kind)
    origin: dict = field(default_factory=dict)   # name -> "file:line"

    def const(self, name):
        if name not in self.consts:
            raise AsmSyntaxError(f"constant {name!r} is not defined in the source read")
        return self.consts[name]

    def list_(self, name):
        if name not in self.lists:
            raise AsmSyntaxError(f"list {name!r} is not defined in the source read")
        return self.lists[name]


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------
_TOKEN = re.compile(r"""
      (?P<hex>\$[0-9A-Fa-f]+)
    | (?P<bin>%[01]+)
    | (?P<dec>\d+)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<punct>[().,+\-*/])
    | (?P<space>\s+)
""", re.X)


def _tokenise(text, where):
    out, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise AsmSyntaxError(f"{where}: unsupported character {text[i]!r} in "
                                 f"{text.strip()!r}")
        i = m.end()
        if m.lastgroup == "space":
            continue
        out.append((m.lastgroup, m.group()))
    return out


def _strip_comments(line):
    return line.split("//", 1)[0]


# ---------------------------------------------------------------------------
# a tiny recursive-descent reader over one declaration's right-hand side
# ---------------------------------------------------------------------------
class _Reader:
    def __init__(self, tokens, src, where):
        self.t, self.i, self.src, self.where = tokens, 0, src, where

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self, kind=None, value=None):
        g, v = self.peek()
        if g is None:
            raise AsmSyntaxError(f"{self.where}: declaration ended unexpectedly")
        if (kind and g != kind) or (value is not None and v != value):
            raise AsmSyntaxError(f"{self.where}: expected {value or kind}, got {v!r}")
        self.i += 1
        return v

    def at(self, value):
        return self.peek()[1] == value

    def done(self):
        return self.i >= len(self.t)

    # ---- values --------------------------------------------------------
    def element(self):
        """A list element: a nested List(), a named list, or an arithmetic value."""
        g, v = self.peek()
        if g == "ident" and v == "List":
            return self.list_expr()
        if g == "ident" and v in self.src.lists and self.peek(1)[1] in (",", ")"):
            self.take()
            return self.src.lists[v]
        return self.arith()

    def list_expr(self):
        self.take("ident", "List")
        self.take("punct", "(")
        self.take("punct", ")")
        out = []
        while self.at("."):
            self.take("punct", ".")
            name = self.take("ident")
            if name != "add":
                raise AsmSyntaxError(
                    f"{self.where}: only List().add(...) is supported, got .{name}()")
            self.take("punct", "(")
            if not self.at(")"):
                out.append(self.element())
                while self.at(","):
                    self.take("punct", ",")
                    out.append(self.element())
            self.take("punct", ")")
        return out

    def arith(self):
        val = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take("punct")
            rhs = self.term()
            val = val + rhs if op == "+" else val - rhs
        return val

    def term(self):
        val = self.factor()
        while self.peek()[1] in ("*", "/"):
            op = self.take("punct")
            rhs = self.factor()
            if op == "*":
                val = val * rhs
            else:
                if rhs == 0:
                    raise AsmSyntaxError(f"{self.where}: division by zero")
                val = val // rhs
        return val

    def factor(self):
        g, v = self.peek()
        if v == "-":
            self.take("punct")
            return -self.factor()
        if v == "(":
            self.take("punct")
            val = self.arith()
            self.take("punct", ")")
            return val
        if g == "hex":
            self.take(); return int(v[1:], 16)
        if g == "bin":
            self.take(); return int(v[1:], 2)
        if g == "dec":
            self.take(); return int(v)
        if g == "ident":
            self.take()
            if v in self.src.consts:
                return self.src.consts[v]
            if v in self.src.lists:
                raise AsmSyntaxError(
                    f"{self.where}: {v!r} is a list and cannot be used as a number")
            raise AsmSyntaxError(f"{self.where}: unknown identifier {v!r}")
        raise AsmSyntaxError(f"{self.where}: expected a value, got {v!r}")


# ---------------------------------------------------------------------------
# declaration gathering
# ---------------------------------------------------------------------------
def _logical_declarations(path):
    """Yield (line_number, text) for each .const/.var/.eval, joined across lines.

    A declaration continues while its parentheses are unbalanced, which is how
    the multi-line `.eval progs.add(List() ... )` blocks are read as one unit.
    `.for` and `.if` blocks are skipped by brace depth.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    i, brace = 0, 0
    while i < len(lines):
        raw = _strip_comments(lines[i])
        stripped = raw.strip()

        if brace > 0:
            brace += raw.count("{") - raw.count("}")
            i += 1
            continue
        if stripped.startswith(".for") or stripped.startswith(".if"):
            yield ("skip", i + 1, stripped.split("(")[0].strip())
            brace += raw.count("{") - raw.count("}")
            i += 1
            continue

        if re.match(r"\.(const|var|eval)\b", stripped):
            start, buf = i + 1, raw
            while buf.count("(") > buf.count(")"):
                i += 1
                if i >= len(lines):
                    raise AsmSyntaxError(
                        f"{path.name}:{start}: unbalanced parentheses in declaration")
                buf += " " + _strip_comments(lines[i])
            yield ("decl", start, " ".join(buf.split()))
        i += 1


def parse_files(paths):
    """Read the supported declarations from `paths`, in order. Returns AsmSource."""
    src = AsmSource()
    for path in paths:
        path = Path(path)
        if not path.is_file():
            raise AsmSyntaxError(f"source file not found: {path}")
        for kind, line, text in _logical_declarations(path):
            where = f"{path.name}:{line}"
            if kind == "skip":
                src.skipped_blocks.append((path.name, line, text))
                continue
            _parse_declaration(text, src, where)
    return src


def _parse_declaration(text, src, where):
    m = re.match(r"\.(const|var|eval)\s+(.*)$", text)
    directive, rest = m.group(1), m.group(2)

    # .eval NAME.add(...)  -- the only .eval form supported
    if directive == "eval":
        m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*add\s*\((.*)\)\s*$", rest)
        if not m2:
            raise AsmSyntaxError(
                f"{where}: the only supported .eval form is NAME.add(...); got "
                f"{rest!r}")
        name = m2.group(1)
        if name not in src.lists:
            raise AsmSyntaxError(f"{where}: .eval {name}.add(...) but {name!r} is not "
                                 f"a declared list")
        reader = _Reader(_tokenise(m2.group(2), where), src, where)
        src.lists[name].append(reader.element())
        while reader.at(","):
            reader.take("punct", ",")
            src.lists[name].append(reader.element())
        if not reader.done():
            raise AsmSyntaxError(f"{where}: trailing tokens after .eval")
        return

    m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", rest)
    if not m2:
        raise AsmSyntaxError(f"{where}: expected NAME = value, got {rest!r}")
    name, value = m2.group(1), m2.group(2).strip()

    if name in src.consts or name in src.lists:
        raise AsmSyntaxError(f"{where}: {name!r} is already defined "
                             f"({src.origin.get(name)})")

    reader = _Reader(_tokenise(value, where), src, where)
    if reader.peek()[1] == "List":
        result = reader.list_expr()
        if not reader.done():
            raise AsmSyntaxError(f"{where}: trailing tokens after List(...)")
        src.lists[name] = result
    else:
        result = reader.arith()
        if not reader.done():
            raise AsmSyntaxError(f"{where}: trailing tokens after value")
        if directive == "var":
            src.lists.pop(name, None)
        src.consts[name] = result
    src.origin[name] = where
