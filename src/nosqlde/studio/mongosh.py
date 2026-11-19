"""A mongosh-style subset, interpreted in Python, so learners type what they type at work.

Three stages, kept apart so the first two can be unit-tested without a database:

1. `tokenize` and `parse`: JavaScript literal syntax (unquoted keys, single or double
   quotes, trailing commas, comments, /regex/flags, ISODate, new Date, NumberDecimal,
   ObjectId, NumberInt, NumberLong) and call chains such as
   `db.applications.find({status: 'declined'}).sort({submitted_at: 1}).limit(5)`.
2. `plan`: turn one parsed statement into an `Operation` (collection, method, Python
   arguments, cursor modifiers), checking every name against the supported subset.
3. `execute`: run the `Operation` with pymongo and shape the reply like mongosh does.

Anything outside the subset raises `SubsetError` with the line and column, and says that
this is a subset (no variables, functions, arithmetic or loops).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bson import Decimal128, ObjectId, Regex
from bson.int64 import Int64

# ---------------------------------------------------------------- the subset

COLLECTION_METHODS: dict[str, tuple[int, int]] = {
    # name: (min args, max args)
    "find": (0, 2),
    "findOne": (0, 2),
    "aggregate": (1, 2),
    "countDocuments": (0, 2),
    "estimatedDocumentCount": (0, 0),
    "distinct": (1, 2),
    "insertOne": (1, 1),
    "insertMany": (1, 2),
    "updateOne": (2, 3),
    "updateMany": (2, 3),
    "replaceOne": (2, 3),
    "deleteOne": (1, 1),
    "deleteMany": (1, 1),
    "createIndex": (1, 2),
    "getIndexes": (0, 0),
    "dropIndex": (1, 1),
    "dropIndexes": (0, 0),
    "drop": (0, 0),
}
CURSOR_METHODS: dict[str, tuple[int, int]] = {
    "sort": (1, 1),
    "limit": (1, 1),
    "skip": (1, 1),
    "project": (1, 1),
    "explain": (0, 1),
    "toArray": (0, 0),
    "pretty": (0, 0),
}
#: cursor methods allowed after aggregate()
AGGREGATE_CURSOR_METHODS = {"toArray", "pretty"}
DB_METHODS: dict[str, tuple[int, int]] = {
    "getCollectionNames": (0, 0),
    "getCollection": (1, 1),
    "createCollection": (1, 2),
}
CONSTRUCTORS = {"ISODate", "Date", "NumberDecimal", "Decimal128", "ObjectId", "NumberInt", "NumberLong"}
EXPLAIN_VERBOSITY = ("queryPlanner", "executionStats", "allPlansExecution")

SUBSET_NOTE = (
    "The studio runs a subset of mongosh: db.<collection>.<method>(...) calls with literal "
    "arguments, cursor modifiers, show collections and db.getCollectionNames(). Variables, "
    "functions, arithmetic and loops are not supported."
)


class SubsetError(ValueError):
    """Input outside the supported mongosh subset, with its position."""

    def __init__(self, message: str, line: int, col: int, source: str = "") -> None:
        self.message = message
        self.line = line
        self.col = col
        self.source = source
        super().__init__(self.render())

    def render(self) -> str:
        text = f"line {self.line}, column {self.col}: {self.message}"
        lines = self.source.splitlines()
        if self.source and 0 < self.line <= len(lines):
            text += f"\n  {lines[self.line - 1]}\n  {' ' * (self.col - 1)}^"
        return text


# ---------------------------------------------------------------- tokens


@dataclass(frozen=True)
class Token:
    kind: str  # num, str, ident, regex, punct, eof
    value: Any
    pos: int
    line: int
    col: int


_IDENT_START = re.compile(r"[A-Za-z_$]")
_IDENT = re.compile(r"[A-Za-z0-9_$]*")
_NUMBER = re.compile(r"(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_PUNCT = set("{}[](),:.;")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _line_col(text: str, pos: int) -> tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    col = pos - (text.rfind("\n", 0, pos) + 1) + 1
    return line, col


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)

    def err(msg: str, at: int) -> SubsetError:
        line, col = _line_col(text, at)
        return SubsetError(msg, line, col, text)

    def add(kind: str, value: Any, at: int) -> None:
        line, col = _line_col(text, at)
        tokens.append(Token(kind, value, at, line, col))

    while i < n:
        ch = text[i]
        if ch in " \t\r\n﻿":
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise err("unterminated /* comment", i)
            i = end + 2
            continue
        if ch in "\"'":
            start, i, out = i, i + 1, []
            while True:
                if i >= n or text[i] == "\n":
                    raise err(f"unterminated string (missing closing {ch})", start)
                c = text[i]
                if c == ch:
                    i += 1
                    break
                if c == "\\":
                    if i + 1 >= n:
                        raise err("unterminated string", start)
                    nxt = text[i + 1]
                    if nxt == "u":
                        hexpart = text[i + 2 : i + 6]
                        if not re.fullmatch(r"[0-9a-fA-F]{4}", hexpart):
                            raise err("bad \\u escape", i)
                        out.append(chr(int(hexpart, 16)))
                        i += 6
                        continue
                    if nxt == "\n":  # line continuation
                        i += 2
                        continue
                    out.append(_ESCAPES.get(nxt, nxt))
                    i += 2
                    continue
                out.append(c)
                i += 1
            add("str", "".join(out), start)
            continue
        if ch == "`":
            raise err("template literals (`...`) are not supported; use '...' or \"...\"", i)
        if ch == "/":
            # No division in the subset, so a lone slash always starts a regex literal.
            start, i, in_class = i, i + 1, False
            while True:
                if i >= n or text[i] == "\n":
                    raise err("unterminated regular expression (missing closing /)", start)
                c = text[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                i += 1
            pattern = text[start + 1 : i]
            i += 1
            flags_m = re.match(r"[A-Za-z]*", text[i:])
            flags = flags_m.group(0) if flags_m else ""
            bad = set(flags) - set("imsxu")
            if bad:
                raise err(
                    f"unsupported regex flag(s) {''.join(sorted(bad))!r}; MongoDB supports i, m, s, x, u", i
                )
            i += len(flags)
            add("regex", (pattern, flags), start)
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER.match(text, i)
            assert m is not None
            raw = m.group(0)
            if raw.lower().startswith("0x"):
                value: Any = int(raw, 16)
            elif re.fullmatch(r"\d+", raw):
                value = int(raw)
            else:
                value = float(raw)
                if value.is_integer() and "e" not in raw.lower() and "." not in raw:
                    value = int(raw)
            add("num", value, i)
            i = m.end()
            if i < n and _IDENT_START.match(text[i]):
                raise err(f"unexpected {text[i]!r} after the number {raw}", i)
            continue
        if _IDENT_START.match(ch):
            m = _IDENT.match(text, i + 1)
            end = m.end() if m else i + 1
            add("ident", text[i:end], i)
            i = end
            continue
        if ch in _PUNCT:
            add("punct", ch, i)
            i += 1
            continue
        if ch == "-":
            add("punct", "-", i)
            i += 1
            continue
        what = {
            "=": "assignment and comparison operators",
            "+": "arithmetic",
            "*": "arithmetic",
            "%": "arithmetic",
            "!": "operators",
            "<": "operators",
            ">": "operators",
            "&": "operators",
            "|": "operators",
            "?": "operators",
        }.get(ch, "this character")
        raise err(f"{ch!r}: {what} are not part of the studio's mongosh subset. {SUBSET_NOTE}", i)
    add("eof", None, n)
    return tokens


# ---------------------------------------------------------------- syntax tree


@dataclass(frozen=True)
class Node:
    line: int
    col: int


@dataclass(frozen=True)
class Literal(Node):
    value: Any


@dataclass(frozen=True)
class ObjectLit(Node):
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class ArrayLit(Node):
    items: tuple[Any, ...]


@dataclass(frozen=True)
class Name(Node):
    name: str


@dataclass(frozen=True)
class New(Node):
    name: str
    args: tuple[Any, ...]


@dataclass(frozen=True)
class Member(Node):
    name: str


@dataclass(frozen=True)
class Index(Node):
    key: Any


@dataclass(frozen=True)
class Call(Node):
    args: tuple[Any, ...]


@dataclass(frozen=True)
class Chain(Node):
    base: Any
    ops: tuple[Any, ...]


@dataclass(frozen=True)
class Show(Node):
    what: str


@dataclass(frozen=True)
class Statement:
    node: Any
    text: str  # the source text of the statement


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0

    # helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.tokens[min(self.i + k, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.i]
        self.i = min(self.i + 1, len(self.tokens) - 1)
        return t

    def error(self, msg: str, tok: Token | None = None) -> SubsetError:
        t = tok or self.tok
        return SubsetError(msg, t.line, t.col, self.text)

    def is_punct(self, ch: str) -> bool:
        return self.tok.kind == "punct" and self.tok.value == ch

    def expect(self, ch: str, what: str = "") -> Token:
        if not self.is_punct(ch):
            got = "the end of the input" if self.tok.kind == "eof" else repr(self.tok.value)
            raise self.error(f"expected {ch!r}{' ' + what if what else ''}, found {got}")
        return self.advance()

    # grammar
    def program(self) -> list[Statement]:
        out: list[Statement] = []
        while True:
            while self.is_punct(";"):
                self.advance()
            if self.tok.kind == "eof":
                return out
            start = self.tok
            node = self.statement()
            end = self.tok.pos if self.tok.kind != "eof" else len(self.text)
            text = self.text[start.pos : end].strip().rstrip(";").strip()
            out.append(Statement(node, text))
            if self.is_punct(";"):
                continue
            if self.tok.kind == "eof":
                continue
            if self.tok.line == self.tokens[self.i - 1].line:
                raise self.error(
                    f"unexpected {self.tok.value!r}: end the statement with ';' or start a new line"
                )

    def statement(self) -> Any:
        t = self.tok
        if t.kind == "ident" and t.value == "show" and self.peek().kind == "ident":
            self.advance()
            what = self.advance()
            return Show(t.line, t.col, str(what.value))
        if t.kind == "ident" and t.value in (
            "var",
            "let",
            "const",
            "function",
            "for",
            "while",
            "if",
            "return",
        ):
            raise self.error(f"'{t.value}' is not supported. {SUBSET_NOTE}")
        if t.kind == "ident" and t.value == "use":
            raise self.error(
                "'use' is not supported: the studio's console always uses the chapter's database"
            )
        return self.postfix()

    def postfix(self) -> Any:
        start = self.tok
        base = self.primary()
        ops: list[Any] = []
        while True:
            t = self.tok
            if self.is_punct("."):
                self.advance()
                name = self.tok
                if name.kind != "ident":
                    raise self.error("expected a name after '.'")
                self.advance()
                ops.append(Member(name.line, name.col, str(name.value)))
            elif self.is_punct("("):
                ops.append(Call(t.line, t.col, self.arguments()))
            elif self.is_punct("["):
                self.advance()
                key = self.value()
                self.expect("]")
                ops.append(Index(t.line, t.col, key))
            else:
                break
        if not ops:
            return base
        return Chain(start.line, start.col, base, tuple(ops))

    def arguments(self) -> tuple[Any, ...]:
        self.expect("(")
        args: list[Any] = []
        while not self.is_punct(")"):
            args.append(self.value())
            if self.is_punct(","):
                self.advance()
            elif not self.is_punct(")"):
                raise self.error(f"expected ',' or ')' in the argument list, found {self._what()}")
        self.advance()
        return tuple(args)

    def _what(self) -> str:
        return "the end of the input" if self.tok.kind == "eof" else repr(self.tok.value)

    def value(self) -> Any:
        """A value expression: literal, object, array, constructor, or a chain (rejected later)."""
        return self.postfix()

    def primary(self) -> Any:
        t = self.tok
        if t.kind in ("num", "str"):
            self.advance()
            return Literal(t.line, t.col, t.value)
        if t.kind == "regex":
            self.advance()
            pattern, flags = t.value
            return Literal(t.line, t.col, Regex(pattern, flags))
        if self.is_punct("-"):
            self.advance()
            num = self.tok
            if num.kind != "num":
                raise self.error("'-' is only supported in front of a number")
            self.advance()
            return Literal(t.line, t.col, -num.value)
        if self.is_punct("{"):
            return self.object()
        if self.is_punct("["):
            return self.array()
        if self.is_punct("("):
            raise self.error(f"parentheses for grouping are not supported. {SUBSET_NOTE}")
        if t.kind == "ident":
            if t.value == "new":
                self.advance()
                name = self.tok
                if name.kind != "ident":
                    raise self.error("expected a constructor name after 'new'")
                self.advance()
                args = self.arguments() if self.is_punct("(") else ()
                return New(t.line, t.col, str(name.value), args)
            self.advance()
            return Name(t.line, t.col, str(t.value))
        if t.kind == "eof":
            raise self.error("unexpected end of the input")
        raise self.error(f"unexpected {t.value!r}")

    def object(self) -> ObjectLit:
        open_tok = self.expect("{")
        items: list[tuple[str, Any]] = []
        while not self.is_punct("}"):
            k = self.tok
            if k.kind in ("ident", "str", "num"):
                key = str(k.value)
            else:
                raise self.error(f"expected a field name, found {self._what()}")
            self.advance()
            # mongosh users often quote dotted paths; unquoted dotted keys are not JavaScript
            if self.is_punct("."):
                raise self.error(f"quote dotted field names: write '{key}.{self.peek().value}' in quotes")
            self.expect(":", f"after the field name {key!r}")
            items.append((key, self.value()))
            if self.is_punct(","):
                self.advance()
            elif not self.is_punct("}"):
                raise self.error(f"expected ',' or '}}' in the object, found {self._what()}")
        self.advance()
        return ObjectLit(open_tok.line, open_tok.col, tuple(items))

    def array(self) -> ArrayLit:
        open_tok = self.expect("[")
        items: list[Any] = []
        while not self.is_punct("]"):
            items.append(self.value())
            if self.is_punct(","):
                self.advance()
            elif not self.is_punct("]"):
                raise self.error(f"expected ',' or ']' in the array, found {self._what()}")
        self.advance()
        return ArrayLit(open_tok.line, open_tok.col, tuple(items))


def parse(text: str) -> list[Statement]:
    """Parse a whole console input into statements."""
    return _Parser(text).program()


# ---------------------------------------------------------------- literal values


def _parse_date(text: str, node: Node, source: str) -> datetime:
    s = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T00:00:00"
    s = s.replace(" ", "T", 1) if re.match(r"\d{4}-\d{2}-\d{2} \d", s) else s
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(s)
    except ValueError:
        raise SubsetError(
            f"cannot read {text!r} as a date; use ISO 8601, e.g. ISODate('2025-06-01T00:00:00Z')",
            node.line,
            node.col,
            source,
        ) from None
    if value.tzinfo is None:  # mongosh reads a date without an offset as UTC
        value = value.replace(tzinfo=UTC)
    # BSON dates have millisecond precision
    return value.astimezone(UTC).replace(microsecond=value.microsecond // 1000 * 1000)


def evaluate(node: Any, source: str = "") -> Any:
    """Turn a literal node into a Python/BSON value."""

    def err(msg: str, n: Node) -> SubsetError:
        return SubsetError(msg, n.line, n.col, source)

    if isinstance(node, Literal):
        return node.value
    if isinstance(node, ObjectLit):
        out: dict[str, Any] = {}
        for key, value in node.items:
            out[key] = evaluate(value, source)
        return out
    if isinstance(node, ArrayLit):
        return [evaluate(v, source) for v in node.items]
    if isinstance(node, Name):
        if node.name == "true":
            return True
        if node.name == "false":
            return False
        if node.name == "null":
            return None
        if node.name == "undefined":
            raise err("undefined is not supported; use null", node)
        if node.name in CONSTRUCTORS:
            raise err(f"call {node.name}(...) with parentheses", node)
        raise err(f"unknown name {node.name!r}: variables are not supported. {SUBSET_NOTE}", node)
    if isinstance(node, New):
        if node.name != "Date":
            raise err(f"'new {node.name}' is not supported; the subset has new Date(...)", node)
        return _construct("Date", node.args, node, source)
    if isinstance(node, Chain):
        if isinstance(node.base, Name) and node.base.name in CONSTRUCTORS and len(node.ops) == 1:
            call = node.ops[0]
            if isinstance(call, Call):
                return _construct(node.base.name, call.args, node, source)
        if isinstance(node.base, Name) and node.base.name == "db":
            raise err("a query cannot be used as a value here. " + SUBSET_NOTE, node)
        raise err(f"this expression is not a literal value. {SUBSET_NOTE}", node)
    raise err("unsupported value", node if isinstance(node, Node) else Node(1, 1))


def _construct(name: str, arg_nodes: tuple[Any, ...], node: Node, source: str) -> Any:
    args = [evaluate(a, source) for a in arg_nodes]

    def err(msg: str) -> SubsetError:
        return SubsetError(msg, node.line, node.col, source)

    if name in ("ISODate", "Date"):
        if not args:
            now = datetime.now(UTC)
            return now.replace(microsecond=now.microsecond // 1000 * 1000)
        if len(args) == 1 and isinstance(args[0], str):
            return _parse_date(args[0], node, source)
        if len(args) == 1 and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
            return datetime.fromtimestamp(args[0] / 1000, tz=UTC)
        raise err(f"{name}() takes one ISO date string or a number of milliseconds")
    if name in ("NumberDecimal", "Decimal128"):
        if len(args) != 1 or not isinstance(args[0], (str, int, float)) or isinstance(args[0], bool):
            raise err(f"{name}() takes one string, e.g. {name}('12500.00')")
        try:
            return Decimal128(str(args[0]))
        except Exception:
            raise err(f"{args[0]!r} is not a decimal number") from None
    if name == "ObjectId":
        if not args:
            return ObjectId()
        if len(args) == 1 and isinstance(args[0], str) and ObjectId.is_valid(args[0]):
            return ObjectId(args[0])
        raise err("ObjectId() takes a 24-character hex string")
    if name in ("NumberInt", "NumberLong"):
        if len(args) != 1:
            raise err(f"{name}() takes one number")
        try:
            number = int(str(args[0]))
        except ValueError:
            raise err(f"{args[0]!r} is not an integer") from None
        return Int64(number) if name == "NumberLong" else number
    raise err(f"unknown constructor {name}")


# ---------------------------------------------------------------- planning


@dataclass
class Operation:
    """One statement, resolved against the subset but not yet executed."""

    kind: str  # collection | db | show
    method: str
    collection: str | None = None
    args: list[Any] = field(default_factory=list)
    cursor: list[tuple[str, list[Any]]] = field(default_factory=list)
    text: str = ""
    line: int = 1
    col: int = 1

    @property
    def explain(self) -> str | None:
        for name, args in self.cursor:
            if name == "explain":
                return str(args[0]) if args else "queryPlanner"
        return None


def _check_arity(name: str, args: tuple[Any, ...], limits: tuple[int, int], node: Node, source: str) -> None:
    lo, hi = limits
    if not lo <= len(args) <= hi:
        want = f"{lo}" if lo == hi else f"{lo} to {hi}"
        raise SubsetError(f"{name}() takes {want} argument(s), got {len(args)}", node.line, node.col, source)


def plan(statement: Statement, source: str = "") -> Operation:
    node = statement.node
    src = source or statement.text

    def err(msg: str, n: Node) -> SubsetError:
        return SubsetError(msg, n.line, n.col, src)

    if isinstance(node, Show):
        if node.what in ("collections", "tables"):
            return Operation("show", "collections", text=statement.text, line=node.line, col=node.col)
        raise err(f"'show {node.what}' is not supported; the subset has 'show collections'", node)
    if not isinstance(node, Chain) or not isinstance(node.base, Name) or node.base.name != "db":
        n = node if isinstance(node, Node) else Node(1, 1)
        raise err(f"a statement must start with db. (for example db.applications.find()). {SUBSET_NOTE}", n)

    ops = list(node.ops)
    pos = 0

    def take_call(name: str, member: Member) -> Call:
        nonlocal pos
        if pos >= len(ops) or not isinstance(ops[pos], Call):
            raise err(f"{name} is a method: call it with parentheses, {name}(...)", member)
        call: Call = ops[pos]
        pos += 1
        return call

    # db.<collection> | db['<collection>'] | db.getCollection('<collection>') | db.<db method>()
    first = ops[pos]
    pos += 1
    collection: str
    if isinstance(first, Index):
        key = evaluate(first.key, src)
        if not isinstance(key, str):
            raise err("db[...] takes a collection name string", first)
        collection = key
    elif isinstance(first, Member):
        if first.name in DB_METHODS:
            call = take_call(first.name, first)
            _check_arity(first.name, call.args, DB_METHODS[first.name], call, src)
            args = [evaluate(a, src) for a in call.args]
            if first.name == "getCollection":
                if not isinstance(args[0], str):
                    raise err("getCollection() takes a collection name string", call)
                collection = args[0]
            else:
                if pos < len(ops):
                    raise err(f"nothing can follow db.{first.name}()", ops[pos])
                if first.name == "createCollection":
                    if not isinstance(args[0], str):
                        raise err("createCollection() takes a collection name string", call)
                    if len(args) > 1 and not isinstance(args[1], dict):
                        raise err("createCollection() options must be an object", call)
                return Operation(
                    "db", first.name, args=args, text=statement.text, line=node.line, col=node.col
                )
        elif first.name in COLLECTION_METHODS or first.name in CURSOR_METHODS:
            raise err(
                f"db.{first.name}() is a collection method: write db.<collection>.{first.name}(...)", first
            )
        else:
            collection = first.name
    else:
        raise err("expected a collection after db", first)

    if pos >= len(ops):
        raise err(f"db.{collection} is a collection: call a method on it, e.g. db.{collection}.find()", node)
    method_node = ops[pos]
    pos += 1
    if not isinstance(method_node, Member):
        raise err("expected a method name", method_node)
    method = method_node.name
    if method not in COLLECTION_METHODS:
        hint = ""
        if method in ("count", "insert", "update", "remove", "save"):
            hint = " (that legacy method was removed from mongosh; use countDocuments, insertOne, updateOne or deleteOne)"
        elif method == "explain":
            hint = " (put .explain('executionStats') at the end of a find(), e.g. db.c.find({...}).explain('executionStats'))"
        raise err(
            f"{method}() is not in the studio's mongosh subset{hint}. Supported collection methods: "
            + ", ".join(COLLECTION_METHODS),
            method_node,
        )
    call = take_call(method, method_node)
    _check_arity(method, call.args, COLLECTION_METHODS[method], call, src)
    args = [evaluate(a, src) for a in call.args]
    _validate_args(method, args, call, src)

    cursor: list[tuple[str, list[Any]]] = []
    while pos < len(ops):
        mod = ops[pos]
        pos += 1
        if not isinstance(mod, Member):
            raise err("expected .method(...) after the call", mod)
        name = mod.name
        allowed = (
            CURSOR_METHODS
            if method == "find"
            else ({k: CURSOR_METHODS[k] for k in AGGREGATE_CURSOR_METHODS} if method == "aggregate" else {})
        )
        if name not in allowed:
            if method in ("find", "aggregate"):
                raise err(
                    f".{name}() is not supported after {method}(); the subset has "
                    + ", ".join(f".{k}()" for k in allowed),
                    mod,
                )
            raise err(f"{method}() does not return a cursor, so .{name}() cannot follow it", mod)
        mcall = take_call(name, mod)
        _check_arity(name, mcall.args, allowed[name], mcall, src)
        margs = [evaluate(a, src) for a in mcall.args]
        if name in ("limit", "skip") and (
            not isinstance(margs[0], int) or isinstance(margs[0], bool) or margs[0] < 0
        ):
            raise err(f".{name}() takes a non-negative whole number", mcall)
        if name in ("sort", "project") and not isinstance(margs[0], dict):
            raise err(f".{name}() takes an object, e.g. .{name}({{submitted_at: 1}})", mcall)
        if name == "explain":
            if margs and margs[0] is True:
                margs = ["allPlansExecution"]
            if margs and margs[0] not in EXPLAIN_VERBOSITY:
                raise err("explain() takes 'queryPlanner', 'executionStats' or 'allPlansExecution'", mcall)
            if any(n == "explain" for n, _ in cursor):
                raise err("explain() can only be used once", mcall)
        elif any(n == "explain" for n, _ in cursor):
            raise err("explain() must be the last call in the chain", mod)
        cursor.append((name, margs))
    return Operation(
        "collection",
        method,
        collection=collection,
        args=args,
        cursor=cursor,
        text=statement.text,
        line=node.line,
        col=node.col,
    )


def _validate_args(method: str, args: list[Any], node: Node, source: str) -> None:
    def err(msg: str) -> SubsetError:
        return SubsetError(msg, node.line, node.col, source)

    def obj(i: int, what: str) -> None:
        if len(args) > i and args[i] is not None and not isinstance(args[i], dict):
            raise err(f"{method}(): the {what} must be an object {{...}}")

    if method in ("find", "findOne"):
        obj(0, "filter")
        obj(1, "projection")
    elif method == "aggregate":
        if not isinstance(args[0], list) or not all(isinstance(s, dict) for s in args[0]):
            raise err("aggregate() takes an array of stages, e.g. aggregate([{$match: {...}}])")
        obj(1, "options")
    elif method == "countDocuments":
        obj(0, "filter")
        obj(1, "options")
    elif method == "distinct":
        if not isinstance(args[0], str):
            raise err("distinct() takes a field name string first")
        obj(1, "filter")
    elif method == "insertOne":
        obj(0, "document")
    elif method == "insertMany":
        if not isinstance(args[0], list) or not all(isinstance(d, dict) for d in args[0]):
            raise err("insertMany() takes an array of documents")
        obj(1, "options")
    elif method in ("updateOne", "updateMany", "replaceOne"):
        obj(0, "filter")
        if method == "replaceOne":
            obj(1, "replacement document")
        elif not isinstance(args[1], (dict, list)):
            raise err(f"{method}() takes an update document or an aggregation pipeline")
        obj(2, "options")
    elif method in ("deleteOne", "deleteMany"):
        obj(0, "filter")
    elif method == "createIndex":
        obj(0, "index keys")
        obj(1, "options")
    elif method == "dropIndex" and not isinstance(args[0], (str, dict)):
        raise err("dropIndex() takes an index name or a key pattern")


def plan_all(text: str) -> list[Operation]:
    return [plan(s, text) for s in parse(text)]


# ---------------------------------------------------------------- explain summary


def explain_summary(explain: dict[str, Any]) -> dict[str, Any]:
    """The numbers the guide reads from explain(): stage chain, keys and docs examined."""
    planner = explain.get("queryPlanner", {})
    node = planner.get("winningPlan", {})
    node = node.get("queryPlan", node)  # 8.0 nests the plan under queryPlan (SBE engine)
    stages: list[str] = []
    index_names: list[str] = []
    multikey = False
    stack = [node]
    while stack:
        cur = stack.pop(0)
        if not isinstance(cur, dict) or "stage" not in cur:
            continue
        stages.append(str(cur["stage"]))
        if cur.get("indexName"):
            index_names.append(str(cur["indexName"]))
        multikey = multikey or bool(cur.get("isMultiKey"))
        if "inputStage" in cur:
            stack.append(cur["inputStage"])
        stack.extend(cur.get("inputStages", []))
    out: dict[str, Any] = {
        "namespace": planner.get("namespace"),
        "stages": " <- ".join(stages),
        "indexName": ", ".join(index_names) or None,
        "isMultiKey": multikey,
    }
    stats = explain.get("executionStats")
    if stats:
        out.update(
            {
                "nReturned": stats.get("nReturned"),
                "totalKeysExamined": stats.get("totalKeysExamined"),
                "totalDocsExamined": stats.get("totalDocsExamined"),
                "executionTimeMillis": stats.get("executionTimeMillis"),
            }
        )
    return out
