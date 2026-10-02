"""List your tenant's chunks so evaluation labels reference actual persistent IDs."""

import argparse
import json

from sqlalchemy import text

from app.config import Settings
from app.storage import Store

parser = argparse.ArgumentParser()
parser.add_argument("--tenant", required=True)
args = parser.parse_args()
store = Store(Settings())
with store.engine.connect() as conn:
    for row in conn.execute(
        text("SELECT metadata FROM chunks WHERE tenant=:t"), {"t": args.tenant}
    ).scalars():
        print(json.dumps(json.loads(row), ensure_ascii=False))
store.engine.dispose()
