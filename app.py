from flask import Flask, render_template, request
import socket
import sqlite3

app = Flask(__name__)

def get_connection_info():
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    try:
        target_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        target_ip = request.host.split(':')[0]
    return {
        'client_ip': client_ip,
        'target_ip': target_ip,
        'method': request.method,
        'host': request.host,
        'path': request.path,
        'headers': dict(request.headers),
    }

def get_demo_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE employees (
        id INTEGER PRIMARY KEY, name TEXT, department TEXT, role TEXT, salary INTEGER
    )''')
    conn.executemany('INSERT INTO employees VALUES (?,?,?,?,?)', [
        (1, 'Alice Johnson',  'Engineering',   'Senior Engineer',    95000),
        (2, 'Bob Smith',      'Finance',        'Financial Analyst',  82000),
        (3, 'Carol White',    'Human Talent',   'HR Manager',         76000),
        (4, 'David Brown',    'Engineering',    'DevOps Lead',        91000),
        (5, 'Eve Davis',      'Finance',        'CFO',               148000),
        (6, 'Frank Miller',   'Engineering',    'Security Engineer',  98000),
    ])
    conn.commit()
    return conn

@app.route('/')
@app.route('/home')
def landing():
    q = request.args.get('q', '')
    return render_template('landing.html', q=q, conn=get_connection_info())

@app.route('/HT')
def ht_view():
    return render_template('ht.html',
        q=request.args.get('q', ''),
        tab=request.args.get('tab', 'home'),
        conn=get_connection_info())

@app.route('/FIN')
def fin_view():
    return render_template('fin.html',
        q=request.args.get('q', ''),
        tab=request.args.get('tab', 'home'),
        conn=get_connection_info())

@app.route('/ENG')
def eng_view():
    return render_template('eng.html',
        q=request.args.get('q', ''),
        tab=request.args.get('tab', 'home'),
        conn=get_connection_info())

# INTENTIONALLY VULNERABLE — educational SQL injection demo
@app.route('/search')
def search():
    q = request.args.get('q', '')
    results = []
    # Unsafe string concatenation is the point — students can see and exploit this
    sql = f"SELECT id, name, department, role, salary FROM employees WHERE name LIKE '%{q}%'"
    error = None
    if q:
        try:
            db = get_demo_db()
            results = [dict(row) for row in db.execute(sql).fetchall()]
            db.close()
        except Exception as e:
            error = str(e)
    return render_template('search.html',
        query=q,
        sql=sql,
        results=results,
        error=error,
        conn=get_connection_info()
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
