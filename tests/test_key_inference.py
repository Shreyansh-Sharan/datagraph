"""Key inference for warehouses without declared constraints: *_id naming conventions."""
from ontoforge.autodraft import draft_from_catalog, infer_keys
from ontoforge.catalog import CatalogAdapter


class NoKeysCatalog(CatalogAdapter):
    """A lakehouse: columns only, no PK/FK metadata."""
    TABLES = {
        "customers": {"customer_id": "bigint", "name": "string", "segment": "string"},
        "accounts": {"account_id": "bigint", "customer_id": "bigint", "balance": "decimal(18,2)"},
        "transactions": {"id": "bigint", "account_id": "bigint", "amount": "decimal(18,2)", "merchant_id": "bigint", "ts": "timestamp"},
        "merchants": {"merchant_id": "bigint", "merchant_name": "string"},
        "daily_kpis": {"date": "date", "revenue": "double"},              # no key at all
    }

    def list_tables(self, schema=None):
        return sorted(self.TABLES)

    def column_types(self, table):
        return dict(self.TABLES[table])


def test_infer_keys_from_naming():
    cat = NoKeysCatalog()
    keys = infer_keys(cat, list(cat.TABLES))
    assert keys["customers"].primary_key == ("customer_id",)
    assert keys["transactions"].primary_key == ("id",)
    assert keys["daily_kpis"].primary_key == ()
    assert keys["accounts"].foreign_keys == [(("customer_id",), "customers", ("customer_id",))]
    assert sorted(keys["transactions"].foreign_keys) == [(("account_id",), "accounts", ("account_id",)), (("merchant_id",), "merchants", ("merchant_id",))]
    assert keys["customers"].foreign_keys == []          # its own key is not a foreign key


def test_draft_uses_inferred_keys_when_catalog_has_none():
    onto, spec = draft_from_catalog(NoKeysCatalog(), ontology_iri="http://d/fin", base_iri="http://d/fin/", infer=True)
    rels = {(onto.local_name(r.property_iri), onto.local_name(r.source_class), onto.local_name(r.target_class)) for r in spec.relations}
    assert ("customer", "Account", "Customer") in rels and ("merchant", "Transaction", "Merchant") in rels
    assert next(c for c in spec.classes if c.class_iri.endswith("#Transaction")).key_columns == ("id",)
    assert next(c for c in spec.classes if c.class_iri.endswith("#DailyKpi")).key_columns == ("date", "revenue")   # fallback: all columns
    onto2, spec2 = draft_from_catalog(NoKeysCatalog(), ontology_iri="http://d/fin", base_iri="http://d/fin/", infer=False)
    assert spec2.relations == ()


class StarCatalog(CatalogAdapter):
    TABLES = {
        "gold.dim_customer": {"customer_sk": "int", "CustomerID": "int", "Age": "int"},
        "gold.dim_product_profile": {"product_profile_sk": "int", "LoanStatus": "string"},
        "gold.fact_customer_churn": {"customer_sk": "int", "product_profile_sk": "int", "Balance": "decimal", "Churned": "boolean"},
    }

    def list_tables(self, schema=None):
        return sorted(self.TABLES)

    def column_types(self, table):
        return dict(self.TABLES[table])


def test_star_schema_surrogate_keys_and_no_name_collisions():
    cat = StarCatalog()
    keys = infer_keys(cat, list(cat.TABLES))
    assert keys["gold.dim_customer"].primary_key == ("customer_sk",)
    assert keys["gold.fact_customer_churn"].primary_key == ("customer_sk", "product_profile_sk")
    onto, spec = draft_from_catalog(cat, ontology_iri="http://d/fin", base_iri="http://d/fin/")
    names = {onto.local_name(c) for c in onto.classes}
    assert names == {"Customer", "ProductProfile", "CustomerChurn"}
    rels = {onto.local_name(r.property_iri): (onto.local_name(r.source_class), onto.local_name(r.target_class)) for r in spec.relations}
    assert rels == {"customer": ("CustomerChurn", "Customer"), "productProfile": ("CustomerChurn", "ProductProfile")}
    dprops, oprops = set(onto.datatype_properties), set(onto.object_properties)
    assert not (dprops & oprops), "an object property must never reuse a datatype property IRI"
    from ontoforge.mapping import mapping_status
    assert mapping_status(onto, spec).completion == 1.0
