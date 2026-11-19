"""The studio's mongosh subset: tokenizer, parser, literal values and planning (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bson import Decimal128, ObjectId, Regex
from bson.int64 import Int64

from nosqlde.studio import mongosh
from nosqlde.studio.mongosh import SubsetError, explain_summary, plan_all


def one(text: str) -> mongosh.Operation:
    ops = plan_all(text)
    assert len(ops) == 1, ops
    return ops[0]


def value(text: str) -> object:
    """Evaluate a literal by planning db.c.insertOne(<literal>)."""
    return one(f"db.c.insertOne({{v: {text}}})").args[0]["v"]


# ---------------------------------------------------------------- literals


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", 1),
        ("-3", -3),
        ("2.5", 2.5),
        ("14000.00", 14000.0),
        ("1e3", 1000.0),
        (".5", 0.5),
        ("0x1F", 31),
        ("'single'", "single"),
        ('"double"', "double"),
        ("'it\\'s'", "it's"),
        ('"tab\\tend"', "tab\tend"),
        ('"\\u00e9"', "é"),
        ("true", True),
        ("false", False),
        ("null", None),
        ("[]", []),
        ("[1, 'a', null,]", [1, "a", None]),
        ("{}", {}),
    ],
)
def test_scalar_and_container_literals(text: str, expected: object) -> None:
    assert value(text) == expected


def test_integers_stay_integers_and_decimals_stay_floats() -> None:
    assert isinstance(value("7"), int)
    assert isinstance(value("7.0"), float)


def test_object_keys_unquoted_quoted_dollar_and_trailing_comma() -> None:
    doc = value("{a: 1, 'b': 2, \"c.d\": 3, $gt: 4, _x$: 5, 10: 6,}")
    assert doc == {"a": 1, "b": 2, "c.d": 3, "$gt": 4, "_x$": 5, "10": 6}


def test_object_key_order_is_kept_for_sort_specs() -> None:
    op = one("db.c.find().sort({updated_at: 1, _id: -1})")
    assert list(op.cursor[0][1][0].items()) == [("updated_at", 1), ("_id", -1)]


def test_nested_documents_and_arrays() -> None:
    assert value("{a: {b: [1, {c: 'x'}]}}") == {"a": {"b": [1, {"c": "x"}]}}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('ISODate("2025-06-01")', datetime(2025, 6, 1, tzinfo=UTC)),
        ('ISODate("2025-04-30T23:01:15Z")', datetime(2025, 4, 30, 23, 1, 15, tzinfo=UTC)),
        ("ISODate('2025-04-30T23:01:15.123456Z')", datetime(2025, 4, 30, 23, 1, 15, 123000, tzinfo=UTC)),
        ('ISODate("2025-01-01T02:00:00+02:00")', datetime(2025, 1, 1, 0, 0, tzinfo=UTC)),
        ('new Date("2025-06-01T00:00:00")', datetime(2025, 6, 1, tzinfo=UTC)),
        ("new Date(0)", datetime(1970, 1, 1, tzinfo=UTC)),
    ],
)
def test_dates_are_utc_with_millisecond_precision(text: str, expected: datetime) -> None:
    assert value(text) == expected


def test_new_date_without_arguments_is_now() -> None:
    got = value("new Date()")
    assert isinstance(got, datetime) and abs((datetime.now(UTC) - got).total_seconds()) < 5


def test_bson_constructors() -> None:
    assert value("NumberDecimal('12500.00')") == Decimal128("12500.00")
    assert value("Decimal128('1.5')") == Decimal128("1.5")
    oid = "65f0a1b2c3d4e5f601234567"
    assert value(f"ObjectId('{oid}')") == ObjectId(oid)
    assert isinstance(value("ObjectId()"), ObjectId)
    assert value("NumberInt(5)") == 5
    long = value("NumberLong('9007199254740993')")
    assert isinstance(long, Int64) and long == 9007199254740993


def test_regex_literals_with_flags() -> None:
    r = value("/^A00+/i")
    assert isinstance(r, Regex) and r.pattern == "^A00+"
    assert value("/a\\/b/") == Regex("a\\/b", "")
    assert value("/[/]x/").pattern == "[/]x"


def test_comments_are_ignored() -> None:
    op = one("// a comment\ndb.c.find({a: 1}) /* inline */ // trailing")
    assert op.method == "find" and op.args == [{"a": 1}]


# ---------------------------------------------------------------- statements and plans


def test_find_with_every_cursor_modifier() -> None:
    op = one(
        "db.applications.find({status: 'declined'}, {_id: 1})"
        ".sort({submitted_at: 1}).skip(5).limit(10).project({product: 1})"
    )
    assert op.kind == "collection" and op.collection == "applications" and op.method == "find"
    assert op.args == [{"status": "declined"}, {"_id": 1}]
    assert [name for name, _ in op.cursor] == ["sort", "skip", "limit", "project"]
    assert op.explain is None


def test_chains_may_continue_on_the_next_line() -> None:
    op = one("db.c.find({})\n  .sort({a: 1})\n  .limit(2)")
    assert [n for n, _ in op.cursor] == ["sort", "limit"]


def test_explain_verbosity() -> None:
    assert one("db.c.find({}).explain('executionStats')").explain == "executionStats"
    assert one("db.c.find({}).explain()").explain == "queryPlanner"
    assert one("db.c.find({}).explain(true)").explain == "allPlansExecution"


def test_multiple_statements_by_newline_or_semicolon() -> None:
    ops = plan_all("db.a.countDocuments({})\ndb.b.countDocuments({}); db.c.drop();;")
    assert [(o.collection, o.method) for o in ops] == [
        ("a", "countDocuments"),
        ("b", "countDocuments"),
        ("c", "drop"),
    ]
    assert ops[0].text == "db.a.countDocuments({})"


def test_two_statements_on_one_line_need_a_semicolon() -> None:
    with pytest.raises(SubsetError, match="end the statement with ';'"):
        plan_all("db.a.find() db.b.find()")


def test_aggregate_pipeline_and_to_array() -> None:
    op = one('db.c.aggregate([{$match: {a: 1}}, {$group: {_id: "$b", n: {$sum: 1}}},]).toArray()')
    assert op.method == "aggregate" and len(op.args[0]) == 2
    assert op.cursor == [("toArray", [])]


@pytest.mark.parametrize(
    "text",
    [
        "db.c.findOne({_id: 'A0000006'}, {product: 1})",
        "db.c.countDocuments({status: 'funded'})",
        "db.c.estimatedDocumentCount()",
        "db.c.distinct('channel', {status: 'funded'})",
        "db.c.insertOne({_id: 1})",
        "db.c.insertMany([{_id: 1}, {_id: 2}], {ordered: false})",
        "db.c.updateOne({_id: 1}, {$set: {a: 2}}, {upsert: true})",
        "db.c.updateMany({}, [{$set: {a: 1}}])",
        "db.c.replaceOne({_id: 1}, {a: 1})",
        "db.c.deleteOne({_id: 1})",
        "db.c.deleteMany({})",
        "db.c.createIndex({status: 1, submitted_at: 1}, {name: 'ix'})",
        "db.c.getIndexes()",
        "db.c.dropIndex('ix')",
        "db.c.dropIndex({status: 1})",
        "db.c.dropIndexes()",
        "db.c.drop()",
    ],
)
def test_every_collection_method_plans(text: str) -> None:
    op = one(text)
    assert op.kind == "collection" and op.collection == "c"


def test_db_level_commands() -> None:
    assert one("show collections").kind == "show"
    assert one("show tables").method == "collections"
    assert one("db.getCollectionNames()").method == "getCollectionNames"
    op = one("db.createCollection('v', {validator: {$jsonSchema: {bsonType: 'object'}}})")
    assert op.kind == "db" and op.args[0] == "v"


def test_get_collection_and_bracket_access() -> None:
    assert one("db.getCollection('odd-name').find()").collection == "odd-name"
    assert one("db['odd-name'].countDocuments({})").collection == "odd-name"


# ---------------------------------------------------------------- errors with positions


def error(text: str) -> SubsetError:
    with pytest.raises(SubsetError) as info:
        plan_all(text)
    return info.value


def test_error_has_line_column_and_a_caret() -> None:
    err = error("db.c.find({a: 1})\nvar x")
    assert (err.line, err.col) == (2, 1)
    assert "'var' is not supported" in err.message
    assert "subset" in err.render() and "^" in err.render()


@pytest.mark.parametrize(
    ("text", "needle", "col"),
    [
        ("db.c.find({a: 1 + 2})", "arithmetic", 17),
        ("x = db.c.find()", "assignment", 3),
        ("db.c.find({a: x})", "variables are not supported", 15),
        ("db.c.find({a: `t`})", "template literals", 15),
        ("db.c.find({a: 'open})", "unterminated string", 15),
        ("db.c.find({a: /open})", "unterminated regular expression", 15),
        ("db.c.find({a: /x/g})", "unsupported regex flag", 18),
        ("db.c.find({a.b: 1})", "quote dotted field names", 13),
        ("db.c.find({a 1})", "expected ':'", 14),
        ("db.c.find({a: 1}", "expected ',' or ')'", 17),
        ("db.c.find([1)", "expected ',' or ']'", 13),
        ("db.c.find({a: (1)})", "parentheses for grouping", 15),
        ("db.c.find({a: undefined})", "use null", 15),
        ("db.c.find({a: ISODate})", "with parentheses", 15),
        ("db.c.find({a: ISODate('not a date')})", "cannot read 'not a date' as a date", 15),
        ("db.c.find({a: NumberDecimal('x')})", "not a decimal number", 15),
        ("db.c.find({a: ObjectId('123')})", "24-character hex", 15),
        ("db.c.find({a: new Map()})", "new Map", 15),
        ("use larkspur", "'use' is not supported", 1),
        ("show dbs", "'show dbs' is not supported", 1),
        ("print('hi')", "must start with db.", 1),
        ("db.c", "call a method on it", 1),
        ("db.c.find", "call it with parentheses", 6),
        ("db.c.mapReduce()", "not in the studio's mongosh subset", 6),
        ("db.c.count()", "legacy method", 6),
        ("db.c.insert({})", "legacy method", 6),
        ("db.c.explain().find()", "at the end of a find()", 6),
        ("db.find()", "collection method", 4),
        ("db.c.find().map()", ".map() is not supported after find()", 13),
        ("db.c.find().explain('x')", "explain() takes", 20),
        ("db.c.find().explain().limit(1)", "must be the last call", 23),
        ("db.c.find().limit(-1)", "non-negative whole number", 18),
        ("db.c.find().limit('a')", "non-negative whole number", 18),
        ("db.c.find().sort(1)", "takes an object", 17),
        ("db.c.aggregate({$match: {}})", "array of stages", 15),
        ("db.c.countDocuments({}).limit(1)", "does not return a cursor", 25),
        ("db.c.aggregate([]).sort({a: 1})", ".sort() is not supported after aggregate()", 20),
        ("db.c.find({}, {}, {}, {})", "takes 0 to 2 argument(s), got 4", 10),
        ("db.c.findOne(1)", "the filter must be an object", 13),
        ("db.c.distinct(1)", "field name string", 14),
        ("db.c.insertMany({})", "array of documents", 16),
        ("db.c.updateOne({}, 1)", "update document or an aggregation pipeline", 15),
        ("db.getCollectionNames().foo()", "nothing can follow", 25),
        ("db.getCollection(1).find()", "collection name string", 17),
        ("db.c.find({a: 1})x", "unexpected 'x'", 18),
        ("db.c.find({a: 1x})", "after the number", 16),
        ("db.c.find({a: -'x'})", "only supported in front of a number", 16),
        ("db.c.find(/* open", "unterminated /* comment", 11),
        ("db.c.find({a: [1,]]})", "expected ',' or '}'", 19),
    ],
)
def test_errors_point_at_the_problem(text: str, needle: str, col: int) -> None:
    err = error(text)
    assert needle in err.message, err.message
    assert err.line == 1
    assert err.col == col, (err.col, err.render())


def test_every_error_mentions_the_subset_when_it_is_about_unsupported_syntax() -> None:
    for text in ("var a = 1", "db.c.find({a: x})", "a + b", "db.c.find({a: (1)})"):
        assert "subset" in error(text).message


# ---------------------------------------------------------------- explain summary


def test_explain_summary_reads_the_8_0_nested_plan() -> None:
    explain = {
        "queryPlanner": {
            "namespace": "db.c",
            "winningPlan": {
                "queryPlan": {
                    "stage": "FETCH",
                    "inputStage": {"stage": "IXSCAN", "indexName": "status_1", "isMultiKey": False},
                }
            },
        },
        "executionStats": {
            "nReturned": 117,
            "totalKeysExamined": 117,
            "totalDocsExamined": 117,
            "executionTimeMillis": 1,
        },
    }
    s = explain_summary(explain)
    assert s["stages"] == "FETCH <- IXSCAN" and s["indexName"] == "status_1"
    assert (s["nReturned"], s["totalKeysExamined"], s["totalDocsExamined"]) == (117, 117, 117)


def test_explain_summary_without_execution_stats_and_with_input_stages() -> None:
    explain = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "SORT_MERGE",
                "inputStages": [
                    {"stage": "IXSCAN", "indexName": "a_1", "isMultiKey": True},
                    {"stage": "COLLSCAN"},
                ],
            }
        }
    }
    s = explain_summary(explain)
    assert s["stages"] == "SORT_MERGE <- IXSCAN <- COLLSCAN"
    assert s["isMultiKey"] is True and "nReturned" not in s
