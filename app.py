from flask import Flask, render_template, request
import socket

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

@app.route('/')
def landing():
    return render_template('landing.html', conn=get_connection_info())

@app.route('/HT')
def ht_view():
    return render_template('department.html',
        dept_name="Human Talent Department",
        dept_code="HT",
        theme_color="#800020",
        services=["Attendance Management", "Payroll Processing", "Employee Benefits", "Recruitment & Onboarding"],
        conn=get_connection_info()
    )

@app.route('/FIN')
def fin_view():
    return render_template('department.html',
        dept_name="Finance Department",
        dept_code="FIN",
        theme_color="#228B22",
        services=["Electronic Invoicing", "Financial Statements", "Expense Reporting", "Internal Audit"],
        conn=get_connection_info()
    )

@app.route('/ENG')
def eng_view():
    return render_template('department.html',
        dept_name="Engineering Department",
        dept_code="ENG",
        theme_color="#FF8C00",
        services=["SOC Monitoring", "Firewall & WAF Management", "Network Infrastructure", "Incident Response"],
        conn=get_connection_info()
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
