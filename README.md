# AcmeCorp Lab Environment

A lightweight Python Flask web server that simulates three isolated enterprise department portals. Designed for educational use: demonstrates how HTTP traffic flows through network appliances (WAF, DPI, load balancers) and provides hands-on practice with common web attack vectors in a controlled, intentionally vulnerable environment.

> ⚠ **Intentionally vulnerable. Do not deploy on a public network.**

## Features

* **Isolated Department Sites** — Three independent-looking portals (`/HT`, `/FIN`, `/ENG`), each with its own branding, color theme, and standalone navigation. No cross-links between sites — each simulates a separate web server.
* **Ethical Hacking Lab** — Every department site has an **Attack** tab with live XSS and SQL injection exercises. The XSS sink reflects on that specific target's page; the SQLi sink runs against a real in-memory SQLite database.
* **Connection Details Panel** — Every page shows a terminal-style debug window with `client_ip`, `target_ip`, HTTP method, host, path, and all request headers — demonstrating how requests appear to a backend server.
* **Lab Selector Portal** — Root landing page (`/` or `/home`) acts as a control panel listing all three target systems and centralized attack exercise cards.
* **Complete Isolation** — All assets served locally; no external CDN requests during packet capture or network inspection.

## Routes

| Path              | Description                              | Theme    |
|-------------------|------------------------------------------|----------|
| `/` or `/home`    | Lab selector — links to all targets      | Blue     |
| `/HT`             | ACME People & Talent (HR portal)         | Burgundy |
| `/FIN`            | ACME Financial Services                  | Green    |
| `/ENG`            | ACME Engineering Systems                 | Orange   |
| `/search`         | Employee directory — SQL injection sink  | Purple   |

Each department route accepts `?tab=attack` to switch to the Attack tab, and `?q=` to trigger the XSS reflection.

## Ethical Hacking Lab

Two attack sinks are available on every department page (via the **Attack** tab) and on the landing page.

### Exercise 1 — Reflected XSS

The `q` query parameter is reflected into the page using Jinja2's `| safe` filter, bypassing auto-escaping. Any HTML or JavaScript is executed by the browser.

| | |
|---|---|
| **Sink** | `/{dept}?tab=attack&q=` |
| **Alert payload** | `<script>alert('XSS on HT')</script>` |
| **HTML payload** | `<img src=x onerror=alert('img XSS')>` |
| **Example URL** | `/HT?tab=attack&q=<script>alert(1)</script>` |

Works independently on each of the three target sites.

### Exercise 2 — SQL Injection

The `/search` endpoint builds its SQLite query via string concatenation. Injected SQL runs against a live in-memory SQLite database seeded with 6 fake employee rows. The raw SQL string is always shown above the results.

| | |
|---|---|
| **Sink** | `/search?q=` |
| **Dump all rows** | `' OR '1'='1` |
| **UNION extraction** | `' UNION SELECT id,name,role,salary,department FROM employees-- ` |

## Navigation

* Every page has a **Home** link in the navigation pointing to `/home`.
* The **AcmeCorp logo** in every header is also a clickable Home link.
* Department footers include a `← Home` return link.
* Each isolated site nav contains only dept-specific items — no links to other departments.

## Connection Details Panel

Shown at the bottom of every page:

| Field | Source |
|---|---|
| `client_ip` | `X-Forwarded-For` header, fallback to `request.remote_addr` |
| `target_ip` | Resolved hostname of the server |
| `http_method` | `request.method` |
| `host / path` | `request.host` / `request.path` |
| Request Headers | Full `request.headers` dict |

## Project Structure

```text
backend-jit-test/
├── app.py                  # Flask routes and SQLite demo DB
├── requirements.txt        # Flask, Werkzeug
├── .gitignore
├── static/
│   └── logo-inail.svg
└── templates/
    ├── landing.html        # Lab selector portal (/ and /home)
    ├── ht.html             # ACME People & Talent — isolated site
    ├── fin.html            # ACME Financial Services — isolated site
    ├── eng.html            # ACME Engineering Systems — isolated site
    ├── search.html         # SQL injection demo (/search)
    └── department.html     # (legacy — unused)
```

## Usage

```bash
pip install -r requirements.txt
python app.py
```

Server listens on `0.0.0.0:8080` by default.
