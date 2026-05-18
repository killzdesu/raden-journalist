import sqlite3
import subprocess
import sys
import os
import threading

# Path to the DB — one level up from web/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Flask, jsonify, render_template, request
from config import MAX_ARTICLES_PER_RUN

app = Flask(__name__)

DB_PATH = os.path.join(BASE_DIR, "digest.db")
MAIN_PY = os.path.join(BASE_DIR, "main.py")

# Track running job state
_job_state = {"running": False, "output": [], "returncode": None}
_job_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", max_articles_per_run=MAX_ARTICLES_PER_RUN)


# ─── API: Stats ──────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM articles")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM articles WHERE sent = 0")
    not_sent = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM articles WHERE sent = 0 AND summary IS NOT NULL AND summary != ''")
    ready_to_send = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM articles WHERE sent = 0 AND (summary IS NULL OR summary = '')")
    unsummarized = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM articles WHERE sent = 1")
    sent = cur.fetchone()[0]

    conn.close()
    return jsonify({
        "total": total,
        "not_sent": not_sent,
        "ready_to_send": ready_to_send,
        "unsummarized": unsummarized,
        "sent": sent,
    })


# ─── API: Articles ───────────────────────────────────────────────────────────

@app.route("/api/articles")
def api_articles():
    filter_by = request.args.get("filter", "all")  # all | not_sent | ready | unsummarized | sent
    sort_dir  = request.args.get("sort", "desc")    # desc = latest first, asc = oldest first
    order     = "DESC" if sort_dir != "asc" else "ASC"
    page = int(request.args.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page

    where_clause = ""
    if filter_by == "not_sent":
        where_clause = "WHERE sent = 0"
    elif filter_by == "ready":
        where_clause = "WHERE sent = 0 AND summary IS NOT NULL AND summary != ''"
    elif filter_by == "unsummarized":
        where_clause = "WHERE sent = 0 AND (summary IS NULL OR summary = '')"
    elif filter_by == "sent":
        where_clause = "WHERE sent = 1"

    conn = get_db()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM articles {where_clause}")
    total_count = cur.fetchone()[0]

    cur.execute(
        f"""SELECT id, pmid, doi, title, journal, pub_date, fetched_at,
                   authors, article_type, journal_pool,
                   sent,
                   CASE WHEN summary IS NOT NULL AND summary != '' THEN 1 ELSE 0 END AS has_summary
            FROM articles {where_clause}
            ORDER BY pub_date {order}, id {order}
            LIMIT ? OFFSET ?""",
        (per_page, offset),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({"articles": rows, "total": total_count, "page": page, "per_page": per_page})



@app.route("/api/articles/<int:article_id>")
def api_article_detail(article_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.route("/api/articles/<int:article_id>", methods=["DELETE"])
def api_article_delete(article_id):
    conn = get_db()
    cur = conn.cursor()
    # Only allow deleting unsummarized articles
    cur.execute(
        "SELECT id, summary, sent FROM articles WHERE id = ?", (article_id,)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    if row["sent"]:
        conn.close()
        return jsonify({"error": "Cannot delete a sent article"}), 400

    cur.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted", "id": article_id})


# ─── API: Run Logs ───────────────────────────────────────────────────────────

@app.route("/api/run-logs")
def api_run_logs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM run_logs ORDER BY id DESC LIMIT 30")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ─── API: Trigger summarize job ──────────────────────────────────────────────

def _run_job(mode, articles_per_run=None, resummarize_id=None, resend_id=None):
    """Runs main.py with the given flag in a background thread."""
    flag_map = {
        "summarize": "--summarize-only",
        "fetch": "",           # full run
        "send": "--send-new-only",
        "resummarize": None,
        "resend": None,
    }
    cmd = [sys.executable, MAIN_PY]
    
    if resummarize_id:
        cmd.extend(["--resummarize-id", str(resummarize_id)])
    elif resend_id:
        cmd.extend(["--resend-id", str(resend_id)])
    else:
        flag = flag_map.get(mode, "--summarize-only")
        if flag:
            cmd.append(flag)
        if articles_per_run is not None:
            cmd.extend(["--articles-per-run", str(articles_per_run)])

    with _job_lock:
        _job_state["running"] = True
        _job_state["output"] = []
        _job_state["returncode"] = None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            with _job_lock:
                _job_state["output"].append(line.rstrip())
        proc.wait()
        with _job_lock:
            _job_state["returncode"] = proc.returncode
    finally:
        with _job_lock:
            _job_state["running"] = False


@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "summarize")
    articles_per_run = data.get("articles_per_run", None)

    with _job_lock:
        if _job_state["running"]:
            return jsonify({"error": "A job is already running"}), 409

    t = threading.Thread(target=_run_job, args=(mode, articles_per_run), daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": mode, "articles_per_run": articles_per_run})

@app.route("/api/resummarize", methods=["POST"])
def api_resummarize():
    data = request.get_json(silent=True) or {}
    article_id = data.get("article_id")
    if not article_id:
        return jsonify({"error": "Missing article_id"}), 400

    with _job_lock:
        if _job_state["running"]:
            return jsonify({"error": "A job is already running"}), 409

    t = threading.Thread(target=_run_job, args=("resummarize", None, article_id, None), daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": "resummarize", "article_id": article_id})

@app.route("/api/resend", methods=["POST"])
def api_resend():
    data = request.get_json(silent=True) or {}
    article_id = data.get("article_id")
    if not article_id:
        return jsonify({"error": "Missing article_id"}), 400

    with _job_lock:
        if _job_state["running"]:
            return jsonify({"error": "A job is already running"}), 409

    t = threading.Thread(target=_run_job, args=("resend", None, None, article_id), daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": "resend", "article_id": article_id})


@app.route("/api/job-status")
def api_job_status():
    with _job_lock:
        return jsonify({
            "running": _job_state["running"],
            "output": _job_state["output"][-100:],  # last 100 lines
            "returncode": _job_state["returncode"],
        })


if __name__ == "__main__":
    # Bind to all interfaces so it's reachable on the VPS
    app.run(host="0.0.0.0", port=5055, debug=False)
