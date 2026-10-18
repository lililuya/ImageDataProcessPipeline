"""数据库测试只操作随机schema，禁止使用业务schema。"""

import os
import uuid

import psycopg
import pytest
from psycopg import sql

from idp.catalog.postgres import Catalog


@pytest.fixture
def catalog():
    dsn = os.environ.get("IDP_TEST_DSN")
    if not dsn:
        pytest.skip("IDP_TEST_DSN not configured; PostgreSQL integration not measured")
    schema = "idp_test_" + uuid.uuid4().hex
    cat = Catalog(dsn, schema)
    try:
        yield cat
    finally:
        assert schema.startswith("idp_test_") and len(schema) == 41
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
