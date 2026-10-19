from flask import Flask, abort, render_template, request
import os
import socket
import sqlite3

app = Flask(__name__)

# Auth portal used by static/jit-guard.js to tell a ban from an outage (empty disables the guard).
PORTAL_URL = os.environ.get("PORTAL_URL", "").rstrip("/")


@app.context_processor
def inject_portal():
    return {"portal_url": PORTAL_URL}


@app.route('/healthz')
def healthz():
    return 'ok', 200, {'Cache-Control': 'no-store'}

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

# Stub service modules behind the "Access" tiles: one generic page per (site, service) with fake rows.
SITES = {
    'HT':  {'name': 'ACME People & Talent',      'accent': '#8b2942', 'dark': '#3a1220'},
    'FIN': {'name': 'ACME Financial Services',   'accent': '#228B22', 'dark': '#0d2e0d'},
    'ENG': {'name': 'ACME Engineering Systems',  'accent': '#c76a10', 'dark': '#3a2408'},
}
SERVICES = {
    'FIN': {
        'invoicing': ('Electronic Invoicing', ['Invoice', 'Customer', 'Amount', 'Status'], [
            ('INV-2026-0141', 'Northwind Ltd', '12,400.00', 'Paid'),
            ('INV-2026-0142', 'Contoso SpA', '3,980.50', 'Sent'),
            ('INV-2026-0143', 'Fabrikam Inc', '27,150.00', 'Overdue'),
            ('INV-2026-0144', 'Globex Corp', '810.00', 'Draft')]),
        'statements': ('Financial Statements', ['Report', 'Period', 'Prepared by', 'Status'], [
            ('Profit & Loss', 'Q1 2026', 'B. Smith', 'Final'),
            ('Balance Sheet', 'Q1 2026', 'B. Smith', 'In review'),
            ('Cash Flow', 'Q1 2026', 'E. Davis', 'Draft')]),
        'expenses': ('Expense Reporting', ['Claim', 'Employee', 'Amount', 'Status'], [
            ('EXP-9021', 'A. Johnson', '412.30', 'Approved'),
            ('EXP-9022', 'D. Brown', '96.00', 'Pending'),
            ('EXP-9023', 'F. Miller', '1,240.75', 'Rejected')]),
        'audit': ('Internal Audit', ['Check', 'Scope', 'Findings', 'Status'], [
            ('GL reconciliation', 'Accounts payable', '2', 'Open'),
            ('Variance analysis', 'Opex Q1', '0', 'Closed'),
            ('Policy compliance', 'Procurement', '1', 'Open')]),
    },
    'HT': {
        'attendance': ('Attendance Management', ['Employee', 'Team', 'Days present', 'Absences'], [
            ('A. Johnson', 'Engineering', '19', '1'), ('B. Smith', 'Finance', '20', '0'),
            ('C. White', 'Human Talent', '18', '2')]),
        'payroll': ('Payroll Processing', ['Cycle', 'Employees', 'Gross', 'Status'], [
            ('2026-03', '6', '590,000', 'Paid'), ('2026-04', '6', '590,000', 'Processing')]),
        'benefits': ('Employee Benefits', ['Program', 'Enrolled', 'Provider', 'Status'], [
            ('Health', '6', 'MediCare Plus', 'Active'), ('Dental', '4', 'SmileCo', 'Active'),
            ('Retirement', '5', 'FutureFund', 'Open enrollment')]),
        'recruitment': ('Recruitment & Onboarding', ['Requisition', 'Role', 'Candidates', 'Stage'], [
            ('REQ-311', 'SRE', '14', 'Interviews'), ('REQ-312', 'Financial Analyst', '9', 'Screening'),
            ('REQ-313', 'HR Partner', '3', 'Offer')]),
    },
    'ENG': {
        'soc': ('SOC Monitoring', ['Alert', 'Source', 'Severity', 'Status'], [
            ('Port scan', '10.20.4.17', 'Medium', 'Triaged'), ('Brute force', '10.20.9.3', 'High', 'Open'),
            ('Malware beacon', '10.20.2.88', 'Critical', 'Escalated')]),
        'firewall': ('Firewall & WAF', ['Rule', 'Action', 'Hits (24h)', 'State'], [
            ('Block SQLi patterns', 'Deny', '312', 'Enabled'), ('Allow web egress', 'Allow', '48,201', 'Enabled'),
            ('Geo block', 'Deny', '77', 'Disabled')]),
        'network': ('Network Infrastructure', ['Device', 'Role', 'Uptime', 'Status'], [
            ('core-sw-01', 'Core switch', '212 d', 'Up'), ('edge-rtr-01', 'BGP uplink', '98 d', 'Up'),
            ('dhcp-01', 'DHCP', '41 d', 'Degraded')]),
        'incidents': ('Incident Response', ['Ticket', 'Title', 'Owner', 'SLA'], [
            ('IR-502', 'Credential stuffing', 'F. Miller', 'On track'),
            ('IR-503', 'Phishing campaign', 'A. Johnson', 'At risk'),
            ('IR-498', 'Lost laptop', 'D. Brown', 'Closed')]),
    },
}


@app.route('/<site>/<service>')
def module_view(site, service):
    site = site.upper()
    spec = SERVICES.get(site, {}).get(service)
    if not spec:
        abort(404)
    title, cols, rows = spec
    return render_template('module.html', site_key=site, site=SITES[site], title=title,
                           cols=cols, rows=rows, conn=get_connection_info())


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
