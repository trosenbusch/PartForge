"""Build the PartForge DbLib test database (SQLite) for the Altium live tests.

Usage: python build_db.py <live_dir>
Creates <live_dir>/partforge_test.db (overwrites).
"""
import os
import sqlite3
import sys

live = os.path.abspath(sys.argv[1])
db_path = os.path.join(live, "partforge_test.db")
libs = os.path.join(live, "libs")
schlib_abs = os.path.join(libs, "PF_Test.SchLib")
pcblib_abs = os.path.join(libs, "PF_Test.PcbLib")

if os.path.exists(db_path):
    os.remove(db_path)

con = sqlite3.connect(db_path)
cur = con.cursor()

COLS = [
    "Part Number", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path",
    "Value", "Description", "Comment", "Manufacturer", "Manufacturer Part Number",
    "Tolerance", "Power", "Package", "Datasheet",
]


def ddl(table, coltype, pk_type=None):
    parts = []
    for i, c in enumerate(COLS):
        t = pk_type or coltype if i == 0 else coltype
        parts.append(f"[{c}] {t}" + (" PRIMARY KEY" if i == 0 else ""))
    return f"CREATE TABLE [{table}] (\n  " + ",\n  ".join(parts) + "\n)"


cur.execute(ddl("Resistors", "TEXT"))
cur.execute(ddl("Capacitors", "VARCHAR(255)"))

LONG = "L" * 280 + "_END"  # 284 chars, longer than VARCHAR(255)

resistors = [
    # Part Number, LibRef, LibPath, FpRef, FpPath, Value, Description, Comment, Mfr, MPN, Tol, Power, Package, Datasheet
    ("RES-0001", "PF_RES", r"libs\PF_Test.SchLib", "PF_R0603", r"libs\PF_Test.PcbLib",
     "10 kΩ", "Chip resistor 10 kΩ ±1 % 0.1 W 0603 (relative paths)", "=Value",
     "Yageo", "RC0603FR-0710KL", "±1 %", "0.1 W", "0603", "https://example.com/rc0603.pdf"),
    ("RES-0002", "PF_RES", schlib_abs, "PF_R0603", pcblib_abs,
     "4.7 MΩ", "Thin film 4.7 MΩ ±0.1 % 25 ppm/K, −55 °C … +155 °C (absolute paths) äöüß €", "=Value",
     "Vishay", "TNPW06034M70BEEA", "±0.1 %", "0.1 W", "0603", ""),
    ("RES-0003", "PF_RES", "PF_Test.SchLib", "PF_R0603", "PF_Test.PcbLib",
     "100 mΩ", "Shunt 100 mΩ µ-test (bare filename paths)", "=Value",
     "Panasonic", "ERJ-3RSFR10V", "±1 %", "0.1 W", "0603", ""),
    ("RES-0004", "PF_RES", "", "PF_R0603", "",
     "1 Ω", "Empty path fields", "=Value",
     "Yageo", "RC0603FR-071RL", "±1 %", "0.1 W", "0603", ""),
    ("RES-0005", "PF_RES", "libs/PF_Test.SchLib", "PF_R0603", "libs/PF_Test.PcbLib",
     "2.2 kΩ", "Forward-slash relative paths", "=Value",
     "Yageo", "RC0603FR-072K2L", "±1 %", "0.1 W", "0603", ""),
    ("RES-0006", "PF_RES", r"libs\PF_Test.SchLib", "PF_R0805", r"libs\PF_Test.PcbLib",
     "47 kΩ", LONG, "=Value",
     "Yageo", "RC0805FR-0747KL", "±1 %", "0.125 W", "0805", ""),
    ("RES-0007", "PF_RES_MISSING", r"libs\PF_Test.SchLib", "PF_MISSING_FP", r"libs\PF_Test.PcbLib",
     "0 Ω", "Symbol and footprint names that do not exist", "=Value",
     "Yageo", "RC0603JR-070RL", "", "0.1 W", "0603", ""),
]
cur.executemany("INSERT INTO Resistors VALUES (" + ",".join("?" * len(COLS)) + ")", resistors)

caps = [
    ("CAP-0001", "PF_CAP", r"libs\PF_Test.SchLib", "PF_C0603", r"libs\PF_Test.PcbLib",
     "100 nF", "MLCC 100 nF ±10 % 50 V X7R 0603", "=Value",
     "Murata", "GRM188R71H104KA93D", "±10 %", "", "0603", ""),
    ("CAP-0002", "PF_CAP", r"libs\PF_Test.SchLib", "PF_C0603", r"libs\PF_Test.PcbLib",
     "4.7 µF", "MLCC 4.7 µF ±20 % 10 V X5R, −55 °C … +85 °C", "=Value",
     "Samsung", "CL10A475MP8NNNC", "±20 %", "", "0603", ""),
    ("CAP-0003", "PF_CAP", r"libs\PF_Test.SchLib", "PF_C0603", r"libs\PF_Test.PcbLib",
     "1 µF", LONG, "=Value",
     "Murata", "GRM188R61E105KA12D", "±10 %", "", "0603", ""),
]
cur.executemany("INSERT INTO Capacitors VALUES (" + ",".join("?" * len(COLS)) + ")", caps)

# Typed table: INTEGER / REAL columns (numeric rendering + locale test)
cur.execute("""
CREATE TABLE [Inductors] (
  [Part Number] VARCHAR(64) PRIMARY KEY,
  [Library Ref] VARCHAR(255),
  [Library Path] VARCHAR(255),
  [Footprint Ref] VARCHAR(255),
  [Footprint Path] VARCHAR(255),
  [Value] VARCHAR(255),
  [Description] VARCHAR(255),
  [Inductance_uH] REAL,
  [Current_mA] INTEGER,
  [Isat_A] NUMERIC,
  [Untyped]
)""")
cur.executemany("INSERT INTO Inductors VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
    ("IND-0001", "PF_RES", r"libs\PF_Test.SchLib", "PF_R0603", r"libs\PF_Test.PcbLib",
     "4.7 µH", "Typed columns test", 4.7, 1500, 2.25, "untyped ü"),
    ("IND-0002", "PF_RES", r"libs\PF_Test.SchLib", "PF_R0603", r"libs\PF_Test.PcbLib",
     "10 µH", "Typed columns test 2", 10.0, 800, 1, 42),
])

# Views: a plain filtered view and one with an expression column
cur.execute("CREATE VIEW [Resistors_0603] AS SELECT * FROM [Resistors] WHERE [Package] = '0603'")
cur.execute("""CREATE VIEW [AllPassives] AS
  SELECT [Part Number], [Library Ref], [Library Path], [Footprint Ref], [Footprint Path],
         [Value], [Description], [Value] || ' ' || [Tolerance] AS [Short Text], 'R' AS [Kind]
  FROM [Resistors]
  UNION ALL
  SELECT [Part Number], [Library Ref], [Library Path], [Footprint Ref], [Footprint Path],
         [Value], [Description], [Value] || ' ' || [Tolerance], 'C'
  FROM [Capacitors]""")

con.commit()
for row in cur.execute("SELECT type, name FROM sqlite_master ORDER BY type, name"):
    print(row)
con.close()
print("written", db_path)
