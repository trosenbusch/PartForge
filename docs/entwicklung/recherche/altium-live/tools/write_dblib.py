"""Write Altium .DbLib files pointing at the SQLite test DB through MSDASQL + SQLite3 ODBC Driver.

Usage: python write_dblib.py <live_dir>
Writes:
  PF_Test_abs.DbLib   absolute DB path in the connection string
  PF_Test_rel.DbLib   relative DB path (Database=partforge_test.db) + DatabasePathRelative=1
"""
import os
import sys

live = os.path.abspath(sys.argv[1])
db_abs = os.path.join(live, "partforge_test.db")

TABLES = ["Resistors", "Capacitors", "Inductors", "Resistors_0603", "AllPassives"]
KEY = "Part Number"
MODEL_FIELDS = ["Library Ref", "Library Path", "Footprint Ref", "Footprint Path", "Description"]


def conn_str(db):
    # NoCreat=1: never let the ODBC driver create an empty DB when the path does not resolve
    return ('Provider=MSDASQL.1;Persist Security Info=False;'
            f'Extended Properties="DRIVER=SQLite3 ODBC Driver;Database={db};NoCreat=1;"')


def dblib(conn, db_path_field, relative):
    L = []
    L += ["[OutputDatabaseLinkFile]", "Version=1.1", "[DatabaseLinks]",
          f"ConnectionString={conn}",
          "AddMode=3", "RemoveMode=1", "UpdateMode=2", "ViewMode=0",
          "LeftQuote=[", "RightQuote=]", "QuoteTableNames=1", "UseTableSchemaName=0",
          "DefaultColumnType=VARCHAR(255)",
          "LibraryDatabaseType=",
          f"LibraryDatabasePath={db_path_field}",
          f"DatabasePathRelative={1 if relative else 0}",
          "TopPanelCollapsed=0", "LibrarySearchPath=", "OrcadMultiValueDelimiter=,",
          "SearchSubDirectories=0", "SchemaName=", f"LastFocusedTable={TABLES[0]}"]
    for i, t in enumerate(TABLES, 1):
        L += [f"[Table{i}]", "SchemaName=", f"TableName={t}", "Enabled=True",
              "UserWhere=0", "UserWhereText="]
    n = 0
    for t in TABLES:
        n += 1
        L += [f"[FieldMap{n}]",
              f"Options=FieldName={t}.{KEY}|TableNameOnly={t}|FieldNameOnly={KEY}|FieldType=0|"
              f"ParameterName={KEY}|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0"]
        for f in MODEL_FIELDS:
            n += 1
            L += [f"[FieldMap{n}]",
                  f"Options=FieldName={t}.{f}|TableNameOnly={t}|FieldNameOnly={f}|FieldType=1|"
                  f"ParameterName=[{f}]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0"]
    return "\r\n".join(L) + "\r\n"


variants = {
    "PF_Test_abs.DbLib": dblib(conn_str(db_abs), db_abs, False),
    "PF_Test_rel.DbLib": dblib(conn_str("partforge_test.db"), "partforge_test.db", True),
}
for name, text in variants.items():
    p = os.path.join(live, name)
    with open(p, "w", encoding="ascii", newline="") as fh:
        fh.write(text)
    print("written", p)
