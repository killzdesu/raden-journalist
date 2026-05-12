import sqlite3

conn = sqlite3.connect('digest.db')
cur = conn.cursor()
cur.execute('SELECT pmid, doi, title, journal, pub_date FROM articles')
rows = cur.fetchall()

print('papers:')
for row in rows:
    pmid, doi, title, journal, pub_date = row
    print(f'- pmid: {pmid}')
    print(f'  doi: {doi}')
    print(f'  title: {title}')
    print(f'  journal: {journal}')
    print(f'  pub_date: {pub_date}')
