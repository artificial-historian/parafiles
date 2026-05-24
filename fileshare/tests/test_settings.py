from parafiles_project.settings import database_from_url


def test_database_from_url_decodes_percent_encoded_postgres_credentials():
    database = database_from_url(
        "postgres://para%40files:qzc34fhn12%21%40@127.0.0.1:5432/para%2Dfiles"
    )

    assert database["USER"] == "para@files"
    assert database["PASSWORD"] == "qzc34fhn12!@"
    assert database["NAME"] == "para-files"
