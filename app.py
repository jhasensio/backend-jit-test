from flask import Flask, render_template

app = Flask(__name__)

# Default Route
@app.route('/')
@app.route('/portale/it.html')
def index():
    return render_template('index.html', 
                           dept_name="Portale Principale", 
                           theme_color="#004d99", # Standard INAIL Blue
                           services=["Denuncia infortunio", "Durc On Line", "Autoliquidazione premi"])

# HR Route
@app.route('/HR')
def hr_view():
    return render_template('index.html', 
                           dept_name="Dipartimento HR (Risorse Umane)", 
                           theme_color="#800020", # Burgundy
                           services=["Gestione presenze", "Cedolini paga", "Welfare aziendale", "Assunzioni"])

# Finance Route
@app.route('/FIN')
def fin_view():
    return render_template('index.html', 
                           dept_name="Dipartimento Finanza", 
                           theme_color="#228B22", # Green
                           services=["Fatturazione elettronica", "Bilanci", "Rendicontazione spese", "Audit interno"])

# Engineering Route
@app.route('/ENG')
def eng_view():
    return render_template('index.html', 
                           dept_name="Dipartimento Ingegneria e Sicurezza", 
                           theme_color="#FF8C00", # Orange
                           services=["Monitoraggio SOC", "Gestione firewall e WAF", "Infrastruttura di rete", "Gestione incidenti"])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
