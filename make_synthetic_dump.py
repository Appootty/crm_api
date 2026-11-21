"""Zip the CSV folder into dump-YYYY-MM-DD.zip (stands in for your friend's nightly dump).
Usage: python make_synthetic_dump.py [csv_folder] [output_folder]"""
import sys, zipfile
from datetime import date
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "../crm_demo_csv")
out = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
out.mkdir(parents=True, exist_ok=True)
target = out / f"dump-{date.today().isoformat()}.zip"
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(src.glob("*.csv")):
        z.write(f, f.name)
print("created", target)
