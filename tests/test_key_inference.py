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


class RgmCatalog(CatalogAdapter):
    TABLES = {
        "gold.dim_product": {"sku_id": "bigint", "sku_code": "string", "brand": "string"},
        "gold.dim_calendar": {"date": "date", "day_num": "int", "date_id": "bigint", "season": "string"},
        "gold.dim_store": {"store_id": "bigint", "store_code": "string"},
        "gold.fact_sales": {"customer_id": "bigint", "date_id": "bigint", "sku_id": "bigint", "store_id": "bigint", "net_sales_value": "double"},
        "gold.fact_target": {"id": "bigint", "date_id": "int", "sku_id": "bigint", "sales_value_target": "decimal"},
    }

    def list_tables(self, schema=None):
        return sorted(self.TABLES)

    def column_types(self, table):
        return dict(self.TABLES[table])


def test_second_pass_picks_first_id_column_that_is_not_another_tables_key():
    keys = infer_keys(RgmCatalog(), list(RgmCatalog.TABLES))
    assert keys["gold.dim_product"].primary_key == ("sku_id",)
    assert keys["gold.dim_calendar"].primary_key == ("date_id",)
    assert keys["gold.dim_store"].primary_key == ("store_id",)
    assert keys["gold.fact_target"].primary_key == ("id",)
    assert keys["gold.fact_sales"].primary_key == ("date_id", "sku_id", "store_id")   # composite of its FKs; customer_id has no target here
    assert sorted(keys["gold.fact_sales"].foreign_keys) == [
        (("date_id",), "gold.dim_calendar", ("date_id",)), (("sku_id",), "gold.dim_product", ("sku_id",)), (("store_id",), "gold.dim_store", ("store_id",))]
    assert (("sku_id",), "gold.dim_product", ("sku_id",)) in keys["gold.fact_target"].foreign_keys


class CollidingCatalog(CatalogAdapter):
    TABLES = {
        "gold.dim_promotion": {"promo_id": "bigint", "promo_code": "string", "dim_promotion_sk": "string"},
        "gold.fact_promotions": {"id": "bigint", "promo_id": "bigint", "promo_spend": "decimal"},
        "gold.dim_product": {"dim_product_sk": "string", "sku_id": "bigint", "sku_code": "string"},
        "gold.fact_sales": {"sku_id": "bigint", "promo_id": "bigint", "net": "double"},
    }

    def list_tables(self, schema=None):
        return sorted(self.TABLES)

    def column_types(self, table):
        return dict(self.TABLES[table])


def test_referenced_columns_win_as_primary_keys():
    keys = infer_keys(CollidingCatalog(), list(CollidingCatalog.TABLES))
    assert keys["gold.dim_product"].primary_key == ("sku_id",)          # referenced by fact_sales, unlike the _sk hash
    assert keys["gold.dim_promotion"].primary_key == ("promo_id",)
    assert (("sku_id",), "gold.dim_product", ("sku_id",)) in keys["gold.fact_sales"].foreign_keys


def test_class_names_never_collide():
    onto, spec = draft_from_catalog(CollidingCatalog(), ontology_iri="http://d/x", base_iri="http://d/x/")
    names = sorted(onto.local_name(c) for c in onto.classes)
    assert names == ["FactPromotion", "Product", "Promotion", "Sale"]
    keys = {onto.local_name(c.class_iri): c.key_columns for c in spec.classes}
    assert keys["Promotion"] == ("promo_id",) and keys["FactPromotion"] == ("id",)
    rels = {(onto.local_name(r.source_class), onto.local_name(r.target_class)) for r in spec.relations}
    assert ("FactPromotion", "Promotion") in rels and ("Sale", "Product") in rels


def test_shared_relations_get_union_domains_instead_of_last_writer_wins():
    class TwoFacts(CatalogAdapter):
        TABLES = {"dim_customer": {"customer_id": "int", "name": "string"},
                  "fact_sales": {"id": "int", "customer_id": "int", "net": "double"},
                  "fact_target": {"id": "int", "customer_id": "int", "target": "double"}}
        def list_tables(self, schema=None): return sorted(self.TABLES)
        def column_types(self, table): return dict(self.TABLES[table])
    onto, spec = draft_from_catalog(TwoFacts(), ontology_iri="http://d/x", base_iri="http://d/x/")
    p = onto.object_properties["http://d/x#customer"]
    assert set(p.domains) == {"http://d/x#Sale", "http://d/x#Target"} and p.range == "http://d/x#Customer"
    assert {onto.local_name(r.source_class) for r in spec.relations if r.property_iri == p.iri} == {"Sale", "Target"}
    from ontoforge.mapping import mapping_status
    assert mapping_status(onto, spec).completion == 1.0


def test_autodraft_assigns_icons_from_class_names():
    from ontoforge.autodraft import icon_for
    assert icon_for("Customer") == "👤" and icon_for("Product") == "📦" and icon_for("SalesOrgHierarchy") == "🏢"
    assert icon_for("Calendar") == "📅" and icon_for("Geography") == "🌍" and icon_for("Sale") == "🧾"
    assert icon_for("QuantumFlux") == "🔹"
    onto, spec = draft_from_catalog(RgmCatalog(), ontology_iri="http://d/fin", base_iri="http://d/fin/")
    assert onto.classes["http://d/fin#Product"].icon == "📦" and onto.classes["http://d/fin#Store"].icon == "🏬"
