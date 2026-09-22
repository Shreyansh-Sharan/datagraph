"""Data-quality rules on source tables: compiled to one pass per table, scored, kept as history."""
from ontoforge.build import PostgresSource
from ontoforge.dialects import DatabricksDialect
from ontoforge.llm import FakeProvider
from ontoforge.metadata import MetadataService
from ontoforge.profiling import ProfileService
from ontoforge.registry import Registry
from ontoforge.tabledq import TableQuality, rule_sql
from tests.hr_fixture import seed_tables, BASE


def _setup(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="alice")
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db)
    meta.import_tables(v.id, ["employees", "departments"], actor="alice")
    return reg, meta, src, v


def test_rules_run_in_one_pass_and_are_scored(db):
    reg, meta, src, v = _setup(db)
    dq = TableQuality(reg, meta, src, db)
    add = lambda **kw: dq.add_rule(v.id, "employees", actor="alice", **kw)
    r_null = add(name="Salary present", column="sal", kind="not_null")                       # 3 of 4 -> 75%
    r_uniq = add(name="Primary key unique", column="empno", kind="unique")                    # 100%
    r_set = add(name="Known department", column="deptno", kind="in_set", params={"values": [10, 20]})   # GHOST's 99 fails, null passes -> 75%
    r_range = add(name="Salary in range", column="sal", kind="range", params={"min": 600, "max": 2000})  # 500 fails -> 75%
    r_regex = add(name="Upper-case name", column="ename", kind="regex", params={"pattern": "^[A-Z]+$"})  # 100%
    r_ref = add(name="Department exists", column="deptno", kind="referential", params={"ref_table": "departments", "ref_column": "deptno"}, threshold=0.9)  # 75%
    r_rows = add(name="Row count within range", kind="row_count", params={"min": 1, "max": 10})           # 100%
    r_fresh = add(name="Hired recently", column="hired", kind="freshness", params={"hours": 24})         # 0%
    assert r_null.dimension == "completeness" and r_uniq.dimension == "uniqueness" and r_ref.dimension == "consistency" and r_fresh.dimension == "timeliness"
    st = dq.status(v.id, "employees")
    assert st["score"] is None and st["last_run"] is None and len(st["rules"]) == 8 and st["rules"][0]["last"] is None

    run = dq.run(v.id, "employees", actor="alice")
    assert run.status == "succeeded" and run.error is None
    st = dq.status(v.id, "employees")
    last = {r["name"]: r["last"] for r in st["rules"]}
    assert last["Salary present"]["pass_rate"] == 0.75 and last["Salary present"]["failed"] == 1 and last["Salary present"]["status"] == "failing"
    assert last["Primary key unique"]["pass_rate"] == 1 and last["Primary key unique"]["status"] == "passing"
    assert last["Known department"]["pass_rate"] == 0.75 and last["Salary in range"]["pass_rate"] == 0.75
    assert last["Upper-case name"]["pass_rate"] == 1 and last["Row count within range"]["pass_rate"] == 1
    assert last["Department exists"]["pass_rate"] == 0.75 and last["Department exists"]["status"] == "warning"    # threshold .9, warns down to .8
    assert last["Hired recently"]["pass_rate"] == 0 and last["Hired recently"]["status"] == "failing"
    assert st["score"] == round((0.75 + 1 + 0.75 + 0.75 + 1 + 0.75 + 1 + 0) / 8, 4)
    assert st["summary"] == {"passing": 3, "warning": 1, "failing": 4}
    assert st["history"][-1]["score"] == st["score"] and st["last_run"]["id"] == str(run.id)
    cols = {c["name"]: c for c in st["columns"]}
    assert cols["sal"]["score"] == 0.75 and cols["sal"]["source"] == "rules"          # mean of its two rules
    assert cols["ename"]["score"] == 1 and cols["manager"]["score"] is None           # no rule, no profile


def test_a_broken_rule_does_not_sink_the_others_and_profile_fills_column_scores(db):
    reg, meta, src, v = _setup(db)
    dq = TableQuality(reg, meta, src, db)
    good = dq.add_rule(v.id, "employees", actor="alice", name="Name present", column="ename", kind="not_null")
    bad = dq.add_rule(v.id, "employees", actor="alice", name="Nonsense", kind="custom", params={"predicate": "no_such_column > 1"})
    dq.run(v.id, "employees", actor="alice")
    st = dq.status(v.id, "employees")
    last = {r["id"]: r["last"] for r in st["rules"]}
    assert last[str(good.id)]["pass_rate"] == 1 and last[str(good.id)]["status"] == "passing"
    assert last[str(bad.id)]["pass_rate"] is None and last[str(bad.id)]["status"] == "error" and "no_such_column" in last[str(bad.id)]["error"]
    assert st["score"] == 1                                                        # the errored rule is left out of the score
    ProfileService(reg, meta, src, db).run(v.id, "employees", actor="alice")
    cols = {c["name"]: c for c in dq.status(v.id, "employees")["columns"]}
    assert cols["sal"]["score"] == 0.75 and cols["sal"]["source"] == "profile"    # completeness from the profile when no rule touches it
    dq.update_rule(bad.id, actor="alice", enabled=False)
    dq.delete_rule(good.id, actor="alice")
    assert [r["name"] for r in dq.status(v.id, "employees")["rules"]] == ["Nonsense"]


def test_ai_suggests_rules_from_the_columns(db):
    reg, meta, src, v = _setup(db)
    llm = FakeProvider([{"rules": [
        {"name": "Employee number unique", "column": "empno", "kind": "unique", "params": {}, "threshold": 1.0, "rationale": "key"},
        {"name": "Salary positive", "column": "sal", "kind": "range", "params": {"min": 0, "max": 1000000}, "threshold": 0.95, "rationale": "pay"},
        {"name": "Bogus", "column": "no_such", "kind": "not_null", "params": {}, "threshold": 0.9, "rationale": "x"},
        {"name": "Weird", "column": "sal", "kind": "teleport", "params": {}, "threshold": 0.9, "rationale": "x"}]}])
    dq = TableQuality(reg, meta, src, db)
    report = dq.suggest(v.id, "employees", llm, actor="alice")
    assert report["added"] == 2 and sorted(report["skipped"]) == ["Bogus (unknown column no_such)", "Weird (unknown kind teleport)"]
    rules = dq.status(v.id, "employees")["rules"]
    assert [r["origin"] for r in rules] == ["ai", "ai"] and rules[0]["dimension"] == "uniqueness"


def test_rule_sql_in_databricks_flavour():
    d = DatabricksDialect()
    p, f = rule_sql({"kind": "regex", "column_name": "ename", "params": {"pattern": "^[A-Z]+$"}}, d)
    assert "RLIKE" in p and "count_if(" in p and f is not None
    p, _ = rule_sql({"kind": "freshness", "column_name": "ts", "params": {"hours": 24}}, d)
    assert "INTERVAL 24 HOURS" in p and "max(`ts`)" in p


def test_failing_rows_can_be_shown_for_a_rule(db):
    reg, meta, src, v = _setup(db)
    dq = TableQuality(reg, meta, src, db)
    r_null = dq.add_rule(v.id, "employees", actor="alice", name="Salary present", column="sal", kind="not_null")
    r_uniq = dq.add_rule(v.id, "employees", actor="alice", name="Dept unique", column="deptno", kind="unique")
    r_rows = dq.add_rule(v.id, "employees", actor="alice", name="Rows", kind="row_count", params={"min": 1})
    cols, rows = dq.failures(r_null.id, limit=10)
    assert "ename" in cols and [r[cols.index("ename")] for r in rows] == ["ALLEN"]          # the one row with a null salary
    cols, rows = dq.failures(r_uniq.id, limit=10)
    assert sorted(r[cols.index("ename")] for r in rows) == []                                # every department appears once
    with db.transaction() as cur:
        cur.execute("UPDATE employees SET deptno = 10 WHERE empno = 2")
    cols, rows = dq.failures(r_uniq.id, limit=10)
    assert sorted(r[cols.index("ename")] for r in rows) == ["ALLEN", "SMITH"]                # both share department 10
    try:
        dq.failures(r_rows.id)
        assert False, "a table-level rule has no failing rows"
    except ValueError as e:
        assert "row" in str(e).lower()


def test_status_carries_each_rules_recent_history(db):
    reg, meta, src, v = _setup(db)
    dq = TableQuality(reg, meta, src, db)
    r = dq.add_rule(v.id, "employees", actor="alice", name="Salary present", column="sal", kind="not_null")
    dq.run(v.id, "employees", actor="alice")
    with db.transaction() as cur:
        cur.execute("UPDATE employees SET sal = 700 WHERE sal IS NULL")
    dq.run(v.id, "employees", actor="alice")
    rule = next(x for x in dq.status(v.id, "employees")["rules"] if x["id"] == str(r.id))
    assert [h["pass_rate"] for h in rule["history"]] == [0.75, 1.0] and all("ran_at" in h for h in rule["history"])


def test_failing_predicate_in_databricks_flavour():
    from ontoforge.tabledq import failing_predicate
    d = DatabricksDialect()
    w = failing_predicate({"kind": "regex", "column_name": "ename", "params": {"pattern": "^[A-Z]+$"}}, d, "`hr`.`employees`")
    assert w == "NOT (`ename` IS NULL OR CAST(`ename` AS STRING) RLIKE '^[A-Z]+$')"
    w = failing_predicate({"kind": "in_set", "column_name": "g", "params": {"values": ["M", "F"]}}, d, "`t`")
    assert w == "NOT (`g` IS NULL OR CAST(`g` AS STRING) IN ('M', 'F'))"
    assert failing_predicate({"kind": "unique", "column_name": "id", "params": {}}, d, "`t`").startswith("`id` IN (SELECT `id` FROM `t`")


def test_rules_are_derived_from_the_profile_without_the_ai(db):
    reg, meta, src, v = _setup(db)
    dq = TableQuality(reg, meta, src, db)
    try:
        dq.auto_suggest(v.id, "employees", actor="alice")
        assert False, "no profile yet"
    except ValueError as e:
        assert "profile" in str(e).lower()
    ProfileService(reg, meta, src, db).run(v.id, "employees", actor="alice")
    report = dq.auto_suggest(v.id, "employees", actor="alice")
    rules = {(r["kind"], r["column_name"]): r for r in dq.status(v.id, "employees")["rules"]}
    assert report["added"] == len(rules) and all(r["origin"] == "auto" for r in rules.values())
    assert rules[("unique", "empno")]["threshold"] == 1.0 and rules[("not_null", "empno")]["threshold"] == 1.0   # the key
    assert rules[("not_null", "ename")]["threshold"] == 0.99                                                    # never null so far
    assert ("in_set", "ename") not in rules                                                                    # four names in four rows: not a code set
    assert rules[("range", "sal")]["params"] == {"min": 425, "max": 1325}                                       # observed 500..1250, widened by a tenth
    assert rules[("range", "deptno")]["params"] == {"min": 1.1, "max": 107.9}                                  # observed 10..99, a tenth either way
    assert rules[("row_count", None)]["params"] == {"min": 3, "max": 5}                                         # four rows, a fifth either way
    assert ("freshness", "hired") not in rules                                                                  # last hire years ago: no freshness promise
    again = dq.auto_suggest(v.id, "employees", actor="alice")
    assert again["added"] == 0 and len(again["skipped"]) == len(rules)                                         # nothing twice
