"""Shared HR domain: tables with PK/FK constraints, an ontology, and a mapping spec."""
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, RelationMapping
from ontoforge.ontology import DatatypeProperty, ObjectProperty, OntoClass, Ontology, XSD
from ontoforge.registry import Registry
from ontoforge.store import TripleStore

EX, BASE = "http://d/hr#", "http://d/hr/"


def seed_tables(db):
    with db.transaction() as cur:
        cur.execute("CREATE TABLE departments (deptno int PRIMARY KEY, dname text NOT NULL)")
        cur.execute("CREATE TABLE employees (empno int PRIMARY KEY, ename text NOT NULL, sal numeric, "
                    "deptno int, manager int REFERENCES employees(empno), hired date)")
        cur.execute("CREATE TABLE employee_skills (empno int REFERENCES employees(empno), skill text, PRIMARY KEY (empno, skill))")
        cur.execute("CREATE TABLE collaborations (a int REFERENCES employees(empno), b int REFERENCES employees(empno), PRIMARY KEY (a, b))")
        cur.executemany("INSERT INTO departments VALUES (%s,%s)", [(10, "SALES"), (20, "RESEARCH")])
        cur.executemany("INSERT INTO employees VALUES (%s,%s,%s,%s,%s,%s)", [
            (1, "SMITH", 800, 10, None, "2020-01-15"), (2, "ALLEN", None, 20, 1, "2021-03-01"),
            (3, "WARD", 1250, None, 1, "2022-07-30"), (4, "GHOST", 500, 99, None, None)])
        # GHOST points at a missing department: declare the FK but don't validate existing rows.
        cur.execute("ALTER TABLE employees ADD CONSTRAINT employees_deptno_fkey FOREIGN KEY (deptno) REFERENCES departments(deptno) NOT VALID")
        cur.executemany("INSERT INTO employee_skills VALUES (%s,%s)", [(1, "sql"), (1, "python"), (2, "sql")])
        cur.executemany("INSERT INTO collaborations VALUES (%s,%s)", [(1, 2), (2, 3)])


def ontology() -> Ontology:
    o = Ontology(iri="http://d/hr", label="HR")
    o.add_class(OntoClass(EX + "Person", "Person"))
    o.add_class(OntoClass(EX + "Employee", "Employee", parents=(EX + "Person",)))
    o.add_class(OntoClass(EX + "Department", "Department"))
    o.add_object_property(ObjectProperty(EX + "worksIn", "works in", domain=EX + "Employee", range=EX + "Department"))
    o.add_object_property(ObjectProperty(EX + "reportsTo", "reports to", domain=EX + "Employee", range=EX + "Employee",
                                         inverse_of=EX + "manages"))
    o.add_object_property(ObjectProperty(EX + "manages", "manages", domain=EX + "Employee", range=EX + "Employee"))
    o.add_object_property(ObjectProperty(EX + "collaboratesWith", "collaborates with", domain=EX + "Employee", range=EX + "Employee"))
    o.add_datatype_property(DatatypeProperty(EX + "name", "name", range=XSD + "string"))  # global: any class
    o.add_datatype_property(DatatypeProperty(EX + "salary", "salary", domain=EX + "Employee", range=XSD + "decimal"))
    o.add_datatype_property(DatatypeProperty(EX + "hired", "hired", domain=EX + "Employee", range=XSD + "date"))
    o.add_datatype_property(DatatypeProperty(EX + "skill", "skill", domain=EX + "Employee", range=XSD + "string"))
    return o


def mapping() -> MappingSpec:
    return MappingSpec(base_iri=BASE, classes=(
        ClassMapping(EX + "Employee", table="employees", key_columns=("empno",), attributes=(
            AttributeBinding(EX + "name", "ename"), AttributeBinding(EX + "salary", "sal"), AttributeBinding(EX + "hired", "hired"))),
        ClassMapping(EX + "Department", table="departments", key_columns=("deptno",), attributes=(AttributeBinding(EX + "name", "dname"),)),
    ), relations=(
        RelationMapping(EX + "worksIn", EX + "Employee", EX + "Department", target_key=("deptno",)),
        RelationMapping(EX + "reportsTo", EX + "Employee", EX + "Employee", target_key=("manager",)),
        RelationMapping(EX + "collaboratesWith", EX + "Employee", EX + "Employee", table="collaborations", source_key=("a",), target_key=("b",)),
    ))


def built_domain(db, actor="alice"):
    """Seed, register, build. Returns (registry, store, version)."""
    seed_tables(db)
    reg = Registry(db)
    d = reg.create_domain("hr", base_iri=BASE)
    v = reg.create_version(d.id, actor=actor)
    reg.update_content(v.id, actor=actor, ontology_ttl=ontology().to_turtle(), mapping=mapping().to_dict())
    store = TripleStore(db)
    run = BuildPipeline(reg, store, PostgresSource(db)).run(v.id, actor=actor)
    assert run.status == "succeeded", run.error
    return reg, store, reg.get_version(v.id)
