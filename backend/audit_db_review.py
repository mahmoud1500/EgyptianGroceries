import json
import sqlite3
from pathlib import Path

path = Path(__file__).with_name('app.db')
conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
report = {'database_bytes': path.stat().st_size, 'table_row_counts': {t: conn.execute('SELECT COUNT(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}}
if 'users' in tables:
    report['user_counts'] = {'total': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 'demo_emails': conn.execute("SELECT COUNT(*) FROM users WHERE lower(email) LIKE '%@demo.com'").fetchone()[0], 'non_demo_emails': conn.execute("SELECT COUNT(*) FROM users WHERE email IS NOT NULL AND lower(email) NOT LIKE '%@demo.com'").fetchone()[0]}
print(json.dumps(report, indent=2, sort_keys=True))
conn.close()
