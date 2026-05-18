import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "digest.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid TEXT UNIQUE,
            doi TEXT,
            title TEXT,
            journal TEXT,
            pub_date TEXT,
            fetched_at DATETIME,
            sent INTEGER DEFAULT 0
        )
    ''')
    
    # Migrations for new columns
    cursor.execute("PRAGMA table_info(articles)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'abstract' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN abstract TEXT")
    if 'authors' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN authors TEXT")
    if 'article_type' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN article_type TEXT")
    if 'journal_pool' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN journal_pool TEXT")
    if 'summary' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN summary TEXT")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            articles_found INTEGER,
            articles_sent INTEGER,
            status TEXT,
            created_at DATETIME
        )
    ''')
    
    conn.commit()
    conn.close()

def article_exists(pmid: str, doi: str = "") -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    if doi:
        cursor.execute("SELECT 1 FROM articles WHERE pmid = ? OR doi = ?", (pmid, doi))
    else:
        cursor.execute("SELECT 1 FROM articles WHERE pmid = ?", (pmid,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def save_article(pmid: str, doi: str, title: str, journal: str, pub_date: str, abstract: str = "", authors: str = "", article_type: str = "", journal_pool: str = "Q1 Allergy"):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        cursor.execute('''
            INSERT INTO articles (pmid, doi, title, journal, pub_date, abstract, authors, article_type, journal_pool, fetched_at, sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ''', (pmid, doi, title, journal, pub_date, abstract, authors, article_type, journal_pool, now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    finally:
        conn.close()

def mark_article_sent(pmid: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE articles SET sent = 1 WHERE pmid = ?", (pmid,))
    conn.commit()
    conn.close()

def log_run(articles_found: int, articles_sent: int, status: str):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    cursor.execute('''
        INSERT INTO run_logs (run_date, articles_found, articles_sent, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (run_date, articles_found, articles_sent, status, now))
    conn.commit()
    conn.close()

def get_unsent_articles(limit: int):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles WHERE sent = 0 AND summary IS NOT NULL AND summary != '' ORDER BY pub_date ASC, id ASC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_unsummarized_articles(limit: int):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles WHERE sent = 0 AND (summary IS NULL OR summary = '') ORDER BY pub_date ASC, id ASC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_summary(pmid: str, summary: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE articles SET summary = ? WHERE pmid = ?", (summary, pmid))
    conn.commit()
    conn.close()

def update_article_type(pmid: str, article_type: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE articles SET article_type = ? WHERE pmid = ?", (article_type, pmid))
    conn.commit()
    conn.close()
