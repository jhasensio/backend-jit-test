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
| `/<site>/<service>` | Stub service pages (e.g. `/FIN/invoicing`) behind the Access tiles | Site colour |
| `/api/search`     | JSON twin of `/search` (verdict, SQL, rows) used by the Attack tab | — |

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

The `/search` endpoint builds its SQLite query via string concatenation. Injected SQL runs against a live in-memory SQLite database seeded with 6 fake employee rows. The raw SQL string is always shown above the results, with a verdict (injection succeeded / SQL error leaked / no effect). On the Attack tab the result appears inline in the exercise card.

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

## Load balancer (Avi) policy

This backend hosts the three sites as paths of one server, which is a lab shortcut, not a production pattern: in production each site would be its own application. Publish one hostname per site and map it to its path with an HTTP Request policy on the virtual service. The same instructions are shown on the home page.

Keep the ban `REJECT` rule first, then one rewrite rule per site:

| Match | Action |
|-------|--------|
| Host header equals `finance.example.lab` and path contains none of `/FIN`, `/static`, `/healthz`, `/search`, `/api` | Rewrite URL path to `/FIN` |
| Same with `hr.example.lab` and `/HT` in place of `/FIN` | Rewrite URL path to `/HT` |
| Same with `eng.example.lab` and `/ENG` in place of `/FIN` | Rewrite URL path to `/ENG` |

A rule without the path exclusions rewrites everything to the site root, so no link, attack result or health check gets through.

| Path | Why it must pass unchanged |
|------|----------------------------|
| `/<SITE>/...` | stub service pages |
| `/search` | SQL injection page |
| `/api/search` | inline SQLi result (a rewrite returns HTML and the box reports "Request blocked") |
| `/static/...` | `jit-guard.js`, `sqli-lab.js` |
| `/healthz` | ban heartbeat; must answer `ok` |

`/home` is left to be rewritten, so the logo returns users to their own site. Other sites stay reachable by path on every hostname; add a deny rule per host for real isolation.

## Publishing the three sites with `avi_publish.py`

Creates (or updates) three HTTPS virtual services, one VIP each, on one shared pool, with a `Route_*` HTTP request policy per site that applies the rewrite table above. It uses the Avi REST API through `requests` only (`pip install requests`; no Avi SDK).

```bash
python3 avi_publish.py --dry-run --insecure     # discover the controller, print every write
python3 avi_publish.py --insecure               # interactive: tenant, cloud, template VS, WAF, pool, VIPs
python3 avi_publish.py --config avi_answers.json   # replay the saved answers
python3 avi_publish.py --delete                 # detach policies and delete what the run created
```

* Credentials come from `AVI_USERNAME` / `AVI_PASSWORD` or a prompt and are never written to disk.
* A template VS (default `finance-app`) supplies profiles, certificate, SE group, VRF, WAF and the shared pool. If it is one of the three sites, only its policy is attached, after any policy already on it (such as the ban rule); its pool, certificate and VIP are untouched.
* VIPs: auto-allocate is offered only when the cloud has IPAM, otherwise a static address is asked for and checked against existing vsvips.
* Rules match the Host header plus path, rewrite to `/FIN`, `/HT` or `/ENG`, and pass `static`, `healthz`, `search` and `api` through. If the application profile does not insert `X-Forwarded-For`, the script offers an `-xff` copy of it.
* `python3 -m unittest test_avi_publish` runs the flow against an in-memory fake controller.

## Ban behaviour

`static/jit-guard.js` blocks the page with a full-screen "Access suspended" overlay as soon as the portal reports the client as banned (checked on load, every second, on bfcache restore, and right after a failed attack request), then redirects to the portal after 10 s. All responses are `Cache-Control: no-store`.
