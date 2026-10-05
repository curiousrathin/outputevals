import pytest

from app.core.sqltool import MAX_RESULT_ROWS, DataQuery, QueryError


@pytest.fixture
def query(tmp_path):
    path = tmp_path / "sales.csv"
    rows = "\n".join(f"{i},Customer {i % 3},{i * 10}" for i in range(500))
    path.write_text(f"id,Customer Name,amount\n{rows}\n")
    q = DataQuery(path)
    yield q
    q.close()


def test_aggregates_over_every_row(query):
    result = query.run(
        'SELECT "Customer Name", SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 1'
    )
    assert result["row_count"] == 3
    assert result["csv"].splitlines()[0] == "Customer Name,total"
    assert not result["truncated"]
    assert query.run("SELECT COUNT(*) AS n FROM data")["csv"].splitlines()[1] == "500"


def test_truncates_large_results(query):
    result = query.run("SELECT * FROM data")
    assert result["truncated"] and result["row_count"] == MAX_RESULT_ROWS
    assert "aggregate" in result["csv"]


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE data",
        "INSERT INTO data VALUES (1, 'x', 1)",
        "SELECT 1; DROP TABLE data",
        "COPY data TO '/tmp/out.csv'",
        "SET enable_external_access = true",
    ],
)
def test_rejects_writes_and_multiple_statements(query, sql):
    with pytest.raises(QueryError):
        query.run(sql)


def test_cannot_read_other_files(query):
    with pytest.raises(QueryError):
        query.run("SELECT * FROM read_csv_auto('/etc/passwd')")


def test_sql_errors_are_reported(query):
    with pytest.raises(QueryError, match="(?i)column"):
        query.run("SELECT nope FROM data")
