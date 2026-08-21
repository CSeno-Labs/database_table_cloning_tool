from syncdb.schema import parse_foreign_keys_from_create


def test_parse_foreign_keys_from_show_create_table():
    create_sql = """
    CREATE TABLE `pessoa` (
      `idescola` int NOT NULL,
      `idresponsavel` int NOT NULL,
      CONSTRAINT `fk_pessoa_escola` FOREIGN KEY (`idescola`) REFERENCES `escola` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
      CONSTRAINT `fk_pessoa_responsavel` FOREIGN KEY (`idresponsavel`, `idescola`) REFERENCES `responsavel` (`id`, `idescola`) ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """

    assert parse_foreign_keys_from_create(create_sql) == (
        ("fk_pessoa_escola", ("idescola",), "escola", ("id",), "RESTRICT", "CASCADE"),
        ("fk_pessoa_responsavel", ("idresponsavel", "idescola"), "responsavel", ("id", "idescola"), "CASCADE", "RESTRICT"),
    )
