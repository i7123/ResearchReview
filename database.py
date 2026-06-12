import sqlite3
import os

DB_PATH = "data/research_review.db"

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create categories table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    )
    """)
    
    # Create papers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY,
        title TEXT,
        authors TEXT,
        abstract TEXT,
        arxiv_id TEXT,
        file_path TEXT,
        category_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (category_id) REFERENCES categories (id)
    )
    """)
    
    # Create reviews table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        paper_id TEXT PRIMARY KEY,
        strengths TEXT,
        weaknesses TEXT,
        novelty TEXT,
        technical_correctness TEXT,
        overall_score INTEGER,
        feasibility_report TEXT,
        status TEXT DEFAULT 'pending',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
    )
    """)
    
    # Create feedback_logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id TEXT,
        user_feedback TEXT,
        agent_reflection TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
    )
    """)
    
    # Create agent_traces table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id TEXT,
        step_name TEXT,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        duration REAL,
        input_data TEXT,
        output_data TEXT,
        status TEXT,
        error_message TEXT,
        FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
    )
    """)
    
    # Insert default categories if table is empty
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ("Hardware Reliability Engineering", "Hardware failure analysis, electromigration, thermal modeling, and physical reliability simulation.")
        ]
        cursor.executemany("INSERT INTO categories (name, description) VALUES (?, ?)", default_categories)
        conn.commit()
        
    conn.commit()
    conn.close()

# Category Helpers
def list_categories():
    conn = get_db_connection()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return [dict(cat) for cat in categories]

def add_category(name, description=""):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
        cat_id = cursor.lastrowid
        conn.close()
        return cat_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

# Paper Helpers
def add_paper(paper_id, title, authors, abstract, arxiv_id=None, file_path=None, category_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO papers (id, title, authors, abstract, arxiv_id, file_path, category_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (paper_id, title, authors, abstract, arxiv_id, file_path, category_id))
    conn.commit()
    conn.close()

def update_paper_category(paper_id, category_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE papers SET category_id = ? WHERE id = ?", (category_id, paper_id))
    conn.commit()
    conn.close()

def get_paper(paper_id):
    conn = get_db_connection()
    paper = conn.execute("""
    SELECT p.*, c.name as category_name 
    FROM papers p 
    LEFT JOIN categories c ON p.category_id = c.id
    WHERE p.id = ?
    """, (paper_id,)).fetchone()
    conn.close()
    return dict(paper) if paper else None

def list_papers():
    conn = get_db_connection()
    papers = conn.execute("""
    SELECT p.*, c.name as category_name, r.overall_score, r.status as review_status
    FROM papers p
    LEFT JOIN categories c ON p.category_id = c.id
    LEFT JOIN reviews r ON p.id = r.paper_id
    ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(p) for p in papers]

# Review Helpers
def save_review(paper_id, strengths, weaknesses, novelty, technical_correctness, overall_score, feasibility_report, status='completed'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO reviews (paper_id, strengths, weaknesses, novelty, technical_correctness, overall_score, feasibility_report, status, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (paper_id, strengths, weaknesses, novelty, technical_correctness, overall_score, feasibility_report, status))
    conn.commit()
    conn.close()

def update_review_status(paper_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO reviews (paper_id, status) VALUES (?, ?) ON CONFLICT(paper_id) DO UPDATE SET status=excluded.status", (paper_id, status))
    conn.commit()
    conn.close()

def get_review(paper_id):
    conn = get_db_connection()
    review = conn.execute("SELECT * FROM reviews WHERE paper_id = ?", (paper_id,)).fetchone()
    conn.close()
    return dict(review) if review else None

# Feedback Log Helpers
def add_feedback_log(paper_id, user_feedback, agent_reflection):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO feedback_logs (paper_id, user_feedback, agent_reflection)
    VALUES (?, ?, ?)
    """, (paper_id, user_feedback, agent_reflection))
    conn.commit()
    conn.close()

def get_feedback_logs(paper_id):
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM feedback_logs WHERE paper_id = ? ORDER BY created_at ASC", (paper_id,)).fetchall()
    conn.close()
    return [dict(log) for log in logs]

# Agent Tracing Helpers
def add_agent_trace(paper_id, step_name, start_time, end_time, duration, input_data, output_data, status, error_message=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO agent_traces (paper_id, step_name, start_time, end_time, duration, input_data, output_data, status, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (paper_id, step_name, start_time, end_time, duration, input_data, output_data, status, error_message))
    conn.commit()
    conn.close()

def get_agent_traces(paper_id):
    conn = get_db_connection()
    traces = conn.execute("SELECT * FROM agent_traces WHERE paper_id = ? ORDER BY start_time ASC", (paper_id,)).fetchall()
    conn.close()
    return [dict(t) for t in traces]

def delete_paper(paper_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()
    conn.close()
