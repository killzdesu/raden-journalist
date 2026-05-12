import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "digest.db")

def remove_articles_without_abstract():
    print(f"Connecting to database at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check how many articles will be removed
        cursor.execute("SELECT COUNT(*) FROM articles WHERE abstract IS NULL OR TRIM(abstract) = ''")
        count = cursor.fetchone()[0]

        print(f"Found {count} articles without an abstract.")

        if count > 0:
            # Delete the articles
            cursor.execute("DELETE FROM articles WHERE abstract IS NULL OR TRIM(abstract) = ''")
            conn.commit()
            print(f"Successfully deleted {count} articles.")
        else:
            print("No action needed.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    remove_articles_without_abstract()
