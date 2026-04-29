# Enterprise Mock Web Server

A lightweight, Dockerized Python Flask web server designed to simulate a multi-departmental enterprise portal. This environment is built to generate localized, predictable HTTP traffic for testing network appliances, Web Application Firewalls (WAF), Deep Packet Inspection (DPI) rules, and load-balancing configurations without relying on external internet connectivity.

## Features

* **Complete Isolation:** Serves all static assets locally, preventing unwanted external CDN requests during packet capture and network inspection.
* **Dynamic Routing:** Separate landing pages for each department (`/ENG`, `/HT`, `/FIN`), each with its own Jinja2 template and color theme.
* **Visual Theming:** Dynamically injects CSS variables to change UI colors and content based on the requested HTTP path, making it easy to visually verify routing rules.
* **Connection Details Panel:** Every page includes an educational debug panel displaying `client_ip`, `target_ip`, HTTP method, host, path, and all request headers — useful for demonstrating how HTTP traffic flows through network appliances.
* **Lightweight:** Built on `python:3.11-slim` for rapid container deployment and teardown.

## Routes

| Path      | Description               | Theme Color |
|-----------|---------------------------|-------------|
| `/`       | Landing Page              | Blue        |
| `/HT`     | Human Talent Department   | Burgundy    |
| `/FIN`    | Finance Department        | Green       |
| `/ENG`    | Engineering Department    | Orange      |
| `/search` | Employee Search (SQLi lab)| Purple      |

## Ethical Hacking Lab

> ⚠ **This server is intentionally vulnerable. Do not deploy it on a public network.**

Two attack sinks are built in for hands-on practice:

### Exercise 1 — Reflected XSS

The `q` query parameter on `/` is reflected into the page using Jinja2's `| safe` filter, bypassing auto-escaping. Any HTML or JavaScript in the input is interpreted by the browser.

| | |
|---|---|
| **Sink** | `/?q=` |
| **Basic payload** | `<script>alert('XSS from AcmeCorp')</script>` |
| **HTML payload** | `<b style='color:red'>Injected!</b>` |
| **Attack URL** | `/?q=<script>alert('XSS from AcmeCorp')</script>` |

**Expected result:** browser alert fires; the text inside `<b>` renders as bold red HTML.

### Exercise 2 — SQL Injection

The `/search` endpoint builds its SQLite query via string concatenation instead of parameterized queries. Injected SQL is executed directly against a live in-memory SQLite database seeded with 6 fake employee rows.

| | |
|---|---|
| **Sink** | `/search?q=` |
| **Dump all rows** | `' OR '1'='1` |
| **UNION extraction** | `' UNION SELECT id,name,role,salary,department FROM employees-- ` |

**Expected result:** all rows returned; the raw SQL string is always displayed above the results table so students can see exactly what was injected.

The `/search` page also accepts normal input (e.g. `q=Alice`) to show the baseline query before injecting.

## Project Structure

```text
mock-server/
├── app.py                      # Core Flask backend and routing logic
├── Dockerfile                  # Container build instructions
├── requirements.txt            # Python dependencies (Flask, Werkzeug)
├── .gitignore                  # Standard ignore file for Python and macOS
├── static/
│   └── logo-inail.svg          # Local static asset for isolated testing
└── templates/
    ├── landing.html            # Root landing page with department cards + attack lab
    ├── department.html         # Shared department template with connection panel
    └── search.html             # SQL injection demo page
```

## Connection Details Panel

Each page renders a terminal-style debug window at the bottom of the page showing live request metadata:

* **client_ip** — source IP of the incoming request (respects `X-Forwarded-For`)
* **target_ip** — resolved IP of the server host
* **http_method** — HTTP verb used (`GET`, `POST`, etc.)
* **host / path** — request host header and URL path
* **Request Headers** — full list of all headers sent by the client

This panel is intended for educational use to demonstrate how HTTP requests are structured and how they appear to a backend server.

## Usage

```bash
pip install -r requirements.txt
python app.py
```

The server listens on `0.0.0.0:8080` by default.
