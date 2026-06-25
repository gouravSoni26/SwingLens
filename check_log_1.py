import sqlite3
c = sqlite3.connect('data/analyses.db')
rows = c.execute('SELECT run_at, status, tickers_success FROM fetch_log ORDER BY run_at DESC LIMIT 3').fetchall()
for r in rows:
    print(r)