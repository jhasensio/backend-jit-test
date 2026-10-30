# AcmeCorp Lab Environment

A lightweight Python Flask web server that simulates three isolated enterprise department portals. Designed for educational use: demonstrates how HTTP traffic flows through network appliances (WAF, DPI, load balancers) and provides hands-on practice with common web attack vectors in a controlled, intentionally vulnerable environment.

> ⚠ **Intentionally vulnerable. Do not deploy on a public network.**

## Features

* **Isolated Department Sites** — Three independent-looking portals (`/HT`, `/FIN`, `/ENG`), each with its own branding, color theme, and standalone navigation. No cross-links between sites — each simulates a separate web server.
* **Ethical Hacking Lab** — Every department site has an **Attack** tab with live XSS and SQL injection exercises. The XSS sink reflects on that specific target's page; the SQLi sink runs against a real in-memory SQLite database.
* **Connection Details Panel** — Every page shows a terminal-style debug window with `client_ip`, `target_ip`, HTTP method, host, path, and all request headers — demonstrating how requests appear to a backend server.
* **Lab Selector Portal** — Root landing page (`/` or `/home`) acts as a control panel listing all three target systems and centralized attack exercise cards.
* **Avi setup script** — `avi_publish.py` builds the three sites on an Avi controller (three VSs, three VIPs, one shared pool, host-based path-rewrite policies) from one dialog; see [Publishing the three sites](#publishing-the-three-sites-with-avi_publishpy).
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
├── avi_publish.py          # Avi controller setup script (see "Publishing the three sites")
├── test_avi_publish.py     # tests for the script, run against a fake controller
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

`avi_publish.py` configures an existing Avi controller so that this one backend looks like three independent websites. It talks to the Avi REST API with `requests` only (no Avi SDK, no Terraform or Ansible). One short dialog creates all three sites in a row.

### What it builds

| Object | Finance | HR | Engineering |
|---|---|---|---|
| Virtual service | `finance-app` | `hr-app` | `eng-app` |
| VIP (own `vsvip`, named `<vs>-vip`) | its own IP | its own IP | its own IP |
| HTTP request policy | `Route_FIN` | `Route_HT` | `Route_ENG` |
| Rewrites to | `/FIN` | `/HT` | `/ENG` |
| Host header matched | `finance.<domain>` | `hr.<domain>` | `eng.<domain>` |

All three VSs share **one new pool**, `lab-backend-pool` (port 8080, HTTP health monitor `lab-healthz-monitor` on `GET /healthz`), and listen on HTTPS 443. Each policy has one rule: if the Host header equals the site's hostname and the path does not contain the site name, `static`, `healthz`, `search` or `api`, rewrite the path to the site root (query string kept). Whatever path a user types, they land on their own site, while links, the SQLi box and the health check still work. See [Load balancer (Avi) policy](#load-balancer-avi-policy) for why those exclusions are needed.

### Fixed settings (never asked)

| Setting | Value |
|---|---|
| Application profile | `System-Secure-HTTP`. If it does not insert `X-Forwarded-For` (the Connection Details panel and the ban logic read it), a copy `System-Secure-HTTP-xff` with it enabled is created and used |
| Network profile | `System-TCP-Proxy` |
| SSL profile | `System-Standard` |
| Certificate | `System-Default-Cert` |
| Backend port | 8080 |
| Pool | always a new one, shared by the three VSs |
| Path exclusions | `static`, `healthz`, `search`, `api` plus the site's own name |
| VS, VIP and policy names | as in the table above |

### Prerequisites

* Python 3 and `pip install requests`.
* An Avi controller reachable over HTTPS with an account allowed to create virtual services, pools, policies and VsVips in the target tenant.
* A backend server reachable from the Service Engines, listening on port 8080.
* DNS (or `/etc/hosts`, or `curl -H Host:`) for the three hostnames pointing at the three VIPs.

### Quick start

```bash
pip install requests
export AVI_PASSWORD='...'                     # optional: otherwise you are prompted for it

python3 avi_publish.py --dry-run --insecure   # 1. look: discovers the controller, prints every write
python3 avi_publish.py --insecure             # 2. apply, answering the prompts
python3 avi_publish.py --insecure             # 3. re-run any time: it offers to reuse your last answers
```

`--insecure` skips TLS verification and is needed for the usual self-signed controller certificate; without it the script stops with a message telling you so. Run `--dry-run` first: reads (discovery) are real, every write is printed as the JSON it would send, and nothing is changed. For existing objects it prints only the fields that would change.

### Command-line options

| Option | Effect |
|---|---|
| `--dry-run` | Print every create/update instead of sending it |
| `--insecure` | Do not verify the controller's TLS certificate |
| `--config FILE` | Answers file to read and write (default `avi_answers.json` in the current directory) |
| `--delete` | Undo what the answers file says a previous run created |
| `--yes` | Update existing objects the script did not create without asking (see below) |
| `--timeout SECONDS` | How long to wait for each controller call (default 30) |
| `--ban-policy NAME` | Attach this existing HTTP policy (e.g. the ban `REJECT` rule) first on every VS |

Environment (all optional): `AVI_CONTROLLER` and `AVI_USERNAME` set the default shown at those two prompts, and `AVI_PASSWORD` skips the password prompt. The password is never written to disk.

### The dialog

Every run starts with a banner describing what the script builds. If an answers file with saved configuration is found, it is listed and you are asked **Reuse it? [Y/n]**. Enter reuses it (only questions it doesn't cover are asked); `n` starts a clean dialog but keeps the record `--delete` needs. Connection details are asked either way.

Numbered lists accept the number, the name, or Enter for the `[default]`. **A list with only one candidate is never asked**; the script prints what it picked.

1. **Controller IP or URL** (default `10.10.10.10`), **username** (default `admin`) and **password**. These are asked on every run, even when an answers file exists; the file or the environment only changes the default shown in brackets. A bare IP or hostname is fine (`https://` is added). The script logs in and reads the API version.
2. **Tenant**, **Cloud**, **VRF context** and **Service engine group**, each skipped if there is only one. The `management` VRF is never offered.
3. **Enable WAF?** (default no). If yes, pick the WAF policy (skipped if there is one). Detection or enforcement mode is a property of the WAF policy itself.
4. **Domain suffix** for the hostnames (default: the controller's domain, or `ans.sddc.lab` when you gave an IP).
5. **Backend server IP address(es)**, comma separated, e.g. `10.10.10.1, 10.10.10.2`. Each becomes a server (port 8080) in the shared pool; addresses are validated and duplicates dropped.
6. **VIP addresses**, one per site, typed in. An empty or invalid address, or one already used by another vsvip (or by an earlier site in the same run), is refused and asked again. If the cloud has IPAM you are first asked once for the VIP network (skipped if one) and whether to `auto`-allocate or type the addresses.

Then it creates the monitor, the pool and the three sites (policy, vsvip, virtual service each) and prints a table with each VS, hostname and VIP.

A typical run on a one-cloud controller therefore asks about nine things: controller, username, password, tenant, service engine group, WAF, domain, backend IP and the three VIPs.

### Replaying and automating: the answers file

Every answer is stored in `avi_answers.json` in the directory you run from (it is in `.gitignore`). A key that is present is not asked again (except controller and username, which only seed the default), so you can pre-fill the file and run without prompts, or delete a key to be asked just that question again. Empty answers are never saved, and a saved answer that is empty, invalid or no longer free (such as a VIP now in use) is ignored and asked again.

```json
{
  "controller": "10.10.10.10", "username": "admin",
  "tenant": "admin", "cloud": "Default-Cloud", "vrf": "global", "se_group": "Default-Group",
  "use_waf": false, "domain": "ans.sddc.lab", "backend_ip": "10.10.10.1, 10.10.10.2",
  "FIN.vip": "192.168.200.10", "HT.vip": "192.168.200.11", "ENG.vip": "192.168.200.12"
}
```

The file is read from the current directory, so an old `avi_answers.json` left in another folder silently answers questions; delete it or pass `--config` to start from a clean dialog. Other keys: `waf` (policy name, with `use_waf: true`), `vip_network` and `vip_mode` (`auto` or `static`, only when the cloud has IPAM), `ban_policy`. `_created` and `_attached` are written by the script and used by `--delete`. The file is also written when a run fails part-way, so `--delete` can still undo it.

```bash
python3 avi_publish.py --insecure --config avi_answers.json
```

### Ban policy

New virtual services start with only their own `Route_*` policy. If your lab uses a ban `REJECT` policy, pass its name and it is attached first (index 1) on all three, with the rewrite policy after it:

```bash
python3 avi_publish.py --insecure --ban-policy ban-reject
```

### Re-running, updating and removing

* **Objects the script created** (recorded in the answers file) are simply updated on a re-run.
* **Objects that already exist but the script did not create** (same name, created by hand or by a run whose answers file is gone) are not touched silently. Before updating one, the script asks `Update it? [y/N]`, because updating overwrites the settings it owns: a pool's servers and monitor, a virtual service's profiles, certificate, pool and ports (its other HTTP policies are kept). Answer `n` and the run stops with nothing changed. Use `--yes` for unattended runs. Objects updated this way are not recorded, so `--delete` will not remove them.
* **Safe to re-run.** Objects are looked up by name and updated, never duplicated. Change a hostname or the backend IP in the answers file and run again.
* **Remove everything the script created:** `python3 avi_publish.py --insecure --delete --config avi_answers.json`. It lists what will go and asks you to type `yes`, detaches the policies, then deletes the VSs, vsvips, policies, pool and monitor in reverse order. Objects it did not create are left alone.

### Errors and failures

* A rejected call stops the run with one line: method, URL, HTTP status and the controller's message (for example `PUT .../vsvip/... -> 400: ... invalid virtual ipv4 address`).
* Every controller call has a timeout (30 s, `--timeout`). A timeout or a network error stops the run with a clear message, not a traceback.
* There is no automatic rollback. The answers file, including what was created so far, is saved even when a run fails; fix the cause and re-run, and the objects already created are updated instead of duplicated, or run `--delete` to remove them.
* `--dry-run` cannot predict values the controller rejects, so a clean dry run is not a guarantee. Read its output, then apply.
* Bad IP addresses are re-asked, and an unknown saved tenant, cloud, VRF or SE group name stops the run before anything is created.

### Verifying

Send each hostname to its VIP and request any path; each should return its own site:

```bash
curl -k -H 'Host: hr.ans.sddc.lab'      https://192.168.200.11/            # -> HR site (/HT)
curl -k -H 'Host: hr.ans.sddc.lab'      https://192.168.200.11/anything    # -> still the HR site
curl -k -H 'Host: eng.ans.sddc.lab'     https://192.168.200.12/            # -> Engineering site
curl -k -H 'Host: finance.ans.sddc.lab' https://192.168.200.10/healthz     # -> ok (passes through)
```

In the controller UI, check Applications > Virtual Services (status green) and the Logs tab to see the rewritten path. A request that reaches the VIP without a matching Host header is not rewritten.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `TLS verification failed ... Re-run with --insecure` | Self-signed controller certificate; add `--insecure` |
| `... timed out after 30s` or `failed: ...` | Controller unreachable or too slow; check the address, or raise `--timeout`, then re-run |
| `stopped: pool 'lab-backend-pool' left untouched` | You answered `n` to updating an object the script did not create; rename or delete it, or re-run with `--yes` |
| `login failed: 401` | Wrong credentials, or the account lacks API access |
| `applicationprofile 'System-Secure-HTTP' not found` (or another system object) | The fixed profile or certificate is missing in that tenant; create it or adjust the constants at the top of the script |
| `VIP x.x.x.x is already used by vsvip ...` | Informational: the dialog refuses it and asks for another address |
| `... not found on the controller` | A name in the answers file does not exist in that tenant/cloud; fix or delete the key |
| VS stays red or in "no SE" | SE group has no capacity or the VIP network is not reachable from the SEs; this is controller setup, not the script |
| Every URL returns the landing page of one site | The Host header does not match any rule, or the hostname resolves to the wrong VIP |
| Links or the SQLi box break | A needed path is missing from the exclusion list (`EXCLUDES` in the script) |

### Tests

`python3 -m unittest test_avi_publish` runs the whole flow against an in-memory fake controller, with no network. It also fails if the dialog asks anything it should have skipped.

## Ban behaviour

`static/jit-guard.js` blocks the page with a full-screen "Access suspended" overlay as soon as the portal reports the client as banned (checked on load, every second, on bfcache restore, and right after a failed attack request), then redirects to the portal after 10 s. All responses are `Cache-Control: no-store`.
