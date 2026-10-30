#!/usr/bin/env python3
"""Publish the three lab sites (FIN / HT / ENG) as three virtual services on one shared pool.

Talks to the Avi REST API directly (requests only, no Avi SDK). Each VS gets its own VIP and an
HTTP request policy that rewrites every path to the site root, except the paths the pages need
(site path, static, healthz, search, api).

    python3 avi_publish.py                      # one dialog, creates all three
    python3 avi_publish.py --dry-run            # show every write instead of sending it
    python3 avi_publish.py --config avi_answers.json   # replay saved answers
    python3 avi_publish.py --delete             # undo what a previous run created

The controller and username are always asked (AVI_CONTROLLER / AVI_USERNAME or the saved answers
only set the default); the password comes from AVI_PASSWORD or a prompt and is never saved.
"""
import argparse
import getpass
import ipaddress
import json
import os
import sys

import requests
import urllib3

# Fixed on purpose: these never change between the three sites.
EXCLUDES = ["static", "healthz", "search", "api"]
BACKEND_PORT = 8080
POOL_NAME = "lab-backend-pool"
MONITOR_NAME = "lab-healthz-monitor"
FIRST_POLICY_INDEX = 11
REQUEST_TIMEOUT = 30   # seconds, per request
DEFAULT_CONTROLLER = "10.10.10.10"
DEFAULT_USER = "admin"
APP_PROFILE = "System-Secure-HTTP"
NETWORK_PROFILE = "System-TCP-Proxy"
SSL_PROFILE = "System-Standard"
CERTIFICATE = "System-Default-Cert"

SITES = [
    {"key": "FIN", "vs": "finance-app", "host": "finance", "policy": "Route_FIN", "path": "FIN"},
    {"key": "HT", "vs": "hr-app", "host": "hr", "policy": "Route_HT", "path": "HT"},
    {"key": "ENG", "vs": "eng-app", "host": "eng", "policy": "Route_ENG", "path": "ENG"},
]


class Avi:
    def __init__(self, base, verify=True, dry_run=False, timeout=REQUEST_TIMEOUT, assume_yes=False):
        self.timeout = timeout
        self.assume_yes = assume_yes   # update objects this script did not create without asking
        self.base = (base if "://" in base else f"https://{base}").rstrip("/")
        self.s = requests.Session()
        self.s.verify = verify
        if not verify:
            urllib3.disable_warnings()
        self.dry_run = dry_run
        self.version = None
        self.tenant = "admin"

    def login(self, user, password):
        try:
            r = self.s.post(f"{self.base}/login", json={"username": user, "password": password}, timeout=self.timeout)
        except requests.exceptions.SSLError:
            sys.exit(f"TLS verification failed for {self.base} (self-signed certificate?). Re-run with --insecure.")
        except requests.exceptions.Timeout:
            sys.exit(f"{self.base} did not answer within {self.timeout}s")
        except requests.exceptions.RequestException as e:
            sys.exit(f"cannot reach {self.base}: {e}")
        if not r.ok:
            sys.exit(f"login failed: {r.status_code} {r.text}")
        # the version is only readable after login; later calls then send it as X-Avi-Version
        self.version = self.call("GET", "cluster/version")["Version"]

    def call(self, method, path, body=None, params=None):
        url = path if "://" in path else f"{self.base}/api/{path}"
        if method != "GET" and self.dry_run:
            shown = body
            if method == "PUT":  # show only what changes, not the whole existing object
                cur = self.call("GET", url)
                shown = {k: v for k, v in body.items() if cur.get(k) != v}
            print(f"\n--- DRY RUN {method} {url}\n{json.dumps(shown, indent=2)}")
            name = (body or {}).get("name", "x")
            return {**(body or {}), "url": url if method != "POST" else f"{url}/{name}"}
        headers = {
            "X-Avi-Version": self.version,
            "X-Avi-Tenant": self.tenant,
            "X-CSRFToken": self.s.cookies.get("csrftoken", ""),
            "Referer": self.base,
        }
        try:
            r = self.s.request(method, url, json=body, params=params, headers=headers, timeout=self.timeout)
        except requests.exceptions.Timeout:
            sys.exit(f"{method} {url} timed out after {self.timeout}s. Re-run to continue: existing objects are updated, not duplicated.")
        except requests.exceptions.RequestException as e:
            sys.exit(f"{method} {url} failed: {e}. Re-run to continue: existing objects are updated, not duplicated.")
        if not r.ok:
            sys.exit(f"{method} {url} -> {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    def list(self, obj, **params):
        params.setdefault("page_size", 200)
        out, resp = [], self.call("GET", obj, params=params)
        while True:
            out += resp.get("results", [])
            if not resp.get("next"):
                return out
            resp = self.call("GET", resp["next"])

    def by_name(self, obj, name):
        found = self.list(obj, name=name)
        if not found:
            sys.exit(f"{obj} '{name}' not found on the controller")
        return found[0]


# ---- dialog helpers: a saved answer wins, a single option is taken silently --------------------

def ask(cfg, key, prompt, default=None, check=None):
    """Saved answer if it is usable, otherwise prompt until `check` (raises ValueError) accepts the input."""
    if cfg.get(key) not in (None, ""):
        try:
            if check:
                check(cfg[key])
            return cfg[key]
        except ValueError as e:
            print(f"  saved {key} ignored: {e}")
    shown = f" [{default}]" if default not in (None, "") else ""
    while True:
        value = input(f"{prompt}{shown}: ").strip() or default or ""
        try:
            (check or (lambda v: v or fail("an answer is required")))(value)
        except ValueError as e:
            print(f"  {e}")
            continue
        cfg[key] = value
        return value


def fail(message):
    raise ValueError(message)


def confirm(cfg, key, prompt, default=False):
    if key in cfg:
        return cfg[key]
    cfg[key] = (input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower() or ("y" if default else "n")).startswith("y")
    return cfg[key]


def choose(cfg, key, prompt, items, default=None):
    """Pick an item (dict with 'name'); with a single candidate nothing is asked."""
    if not items:
        sys.exit(f"{prompt}: nothing to choose from on the controller")
    names = [i["name"] for i in items]
    if key not in cfg and len(items) == 1:
        print(f"{prompt}: {names[0]}")
        cfg[key] = names[0]
    if key in cfg:
        item = next((i for i in items if i["name"] == cfg[key]), None)
        if item is None:
            sys.exit(f"{prompt}: '{cfg[key]}' not found on the controller")
        return item
    print(f"\n{prompt}")
    for n, name in enumerate(names, 1):
        print(f"  {n}) {name}")
    default = default if default in names else names[0]
    while True:
        raw = input(f"Choice [{default}]: ").strip() or default
        pick = names[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(names) else raw
        if pick in names:
            break
        print("  not a valid choice")
    cfg[key] = pick
    return items[names.index(pick)]


# ---- object builders ---------------------------------------------------------------------------

def policy_body(site, host, tenant_ref):
    return {
        "name": site["policy"],
        "tenant_ref": tenant_ref,
        "is_internal_policy": False,
        "http_request_policy": {"rules": [{
            "name": f"rewrite-to-{site['key'].lower()}",
            "index": 0,
            "enable": True,
            "match": {
                "host_hdr": {"match_case": "INSENSITIVE", "match_criteria": "HDR_EQUALS", "value": [host]},
                "path": {"match_case": "SENSITIVE", "match_criteria": "DOES_NOT_CONTAIN",
                         "match_decoded_string": False, "match_str": [site["path"]] + EXCLUDES},
            },
            "rewrite_url_action": {
                "path": {"type": "URI_PARAM_TYPE_TOKENIZED",
                         "tokens": [{"type": "URI_TOKEN_TYPE_STRING", "str_value": site["path"]}]},
                "query": {"keep_query": True},
            },
        }]},
    }


def attach_policy(vs_policies, policy_ref):
    """Append the policy after whatever is already attached (ban rules must stay first)."""
    if any(p["http_policy_set_ref"] == policy_ref for p in vs_policies):
        return vs_policies
    nxt = max((p["index"] for p in vs_policies), default=FIRST_POLICY_INDEX - 1) + 1
    return vs_policies + [{"http_policy_set_ref": policy_ref, "index": nxt}]


def upsert(api, obj, body, created):
    cur = api.list(obj, name=body["name"])
    if cur:
        ours = any(c["url"] == cur[0]["url"] for c in created)
        if not ours and not api.assume_yes:
            answer = input(f"  {obj} '{body['name']}' already exists and was not created by this script.\n"
                           "  Updating overwrites the settings the script owns on it. Update it? [y/N]: ")
            if not answer.strip().lower().startswith("y"):
                sys.exit(f"stopped: {obj} '{body['name']}' left untouched. Rename or delete it, or use --yes.")
        print(f"  updating {obj} {body['name']}")
        return api.call("PUT", cur[0]["url"], {**cur[0], **body})
    print(f"  creating {obj} {body['name']}")
    res = api.call("POST", obj, body)
    created.append({"obj": obj, "name": body["name"], "url": res["url"]})
    return res


def vip_builder(api, cfg, cloud):
    """Return f(ip) building the vsvip 'vip' entry; ip=None means auto-allocate (needs IPAM)."""
    if not cloud.get("ipam_provider_ref"):
        print("No IPAM on this cloud: VIP addresses are typed in.")
        return lambda ip: {"vip_id": "1", "enabled": True, "prefix_length": 32,
                           "ip_address": {"addr": ip, "type": "V4"}}
    net = choose(cfg, "vip_network", "VIP network",
                 [n for n in api.list("network") if n.get("cloud_ref") in (None, cloud["url"])])
    subnets = net.get("configured_subnets") or []
    if not subnets:
        sys.exit(f"network {net['name']} has no configured subnet to allocate VIPs from")

    def build(ip):
        entry = {"vip_id": "1", "enabled": True,
                 "ipam_network_subnet": {"network_ref": net["url"], "subnet": subnets[0]["prefix"]}}
        if ip:
            return {**entry, "ip_address": {"addr": ip, "type": "V4"}}
        return {**entry, "auto_allocate_ip": True, "auto_allocate_ip_type": "V4_ONLY"}
    return build


def parse_ips(raw):
    """'10.10.10.1, 10.10.10.2' (or a list) -> ['10.10.10.1', '10.10.10.2'], validated, order kept."""
    items = raw if isinstance(raw, list) else raw.split(",")
    ips = []
    for item in (i.strip() for i in items):
        if not item:
            continue
        try:
            ip = str(ipaddress.IPv4Address(item))
        except ValueError:
            raise ValueError(f"'{item}' is not an IPv4 address")
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError("at least one IPv4 address is required")
    return ips


def one_ip(raw):
    ips = parse_ips(raw)
    if len(ips) != 1:
        raise ValueError("enter exactly one IPv4 address")
    return ips[0]


def run(api, cfg, ban_policy=None):
    created = cfg.setdefault("_created", [])
    attached = cfg.setdefault("_attached", [])
    host = api.base.split("//")[-1].split("/")[0]
    guess = host.split(".", 1)[1] if "." in host and not host.replace(".", "").isdigit() else "ans.sddc.lab"

    # -- common settings, asked once (a single candidate is picked without asking) -----------------
    tenant = choose(cfg, "tenant", "Tenant", api.list("tenant"), "admin")
    api.tenant = tenant["name"]
    tenant_ref = tenant["url"]
    cloud = choose(cfg, "cloud", "Cloud", api.list("cloud"), "Default-Cloud")
    in_cloud = lambda items: [i for i in items if i.get("cloud_ref") in (None, cloud["url"])]
    vrf = choose(cfg, "vrf", "VRF context",
                 [v for v in in_cloud(api.list("vrfcontext")) if v["name"] != "management"], "global")
    seg = choose(cfg, "se_group", "Service engine group", in_cloud(api.list("serviceenginegroup")), "Default-Group")
    waf = None
    if confirm(cfg, "use_waf", "Enable WAF?"):
        waf = choose(cfg, "waf", "WAF policy", api.list("wafpolicy"))
    domain = ask(cfg, "domain", "Domain suffix for the site hostnames", guess)
    backends = parse_ips(ask(cfg, "backend_ip", "Backend server IP address(es), comma separated", check=parse_ips))

    # -- fixed system objects ----------------------------------------------------------------------
    app_profile = api.by_name("applicationprofile", APP_PROFILE)
    if not app_profile.get("http_profile", {}).get("xff_enabled"):
        # the Connection Details panel and the ban logic read X-Forwarded-For
        clone = {k: v for k, v in app_profile.items() if k not in ("uuid", "url", "_last_modified")}
        clone.update(name=f"{APP_PROFILE}-xff", tenant_ref=tenant_ref)
        clone["http_profile"] = {**clone["http_profile"], "xff_enabled": True}
        print(f"{APP_PROFILE} does not insert X-Forwarded-For: using a copy that does")
        app_profile = upsert(api, "applicationprofile", clone, created)
    net_profile = api.by_name("networkprofile", NETWORK_PROFILE)
    ssl_profile = api.by_name("sslprofile", SSL_PROFILE)
    cert = api.by_name("sslkeyandcertificate", CERTIFICATE)
    ban = api.by_name("httppolicyset", ban_policy) if ban_policy else None

    # -- shared pool -------------------------------------------------------------------------------
    print("\n== Shared pool ==")
    mon = upsert(api, "healthmonitor", {
        "name": MONITOR_NAME, "type": "HEALTH_MONITOR_HTTP", "tenant_ref": tenant_ref,
        "http_monitor": {"http_request": "GET /healthz HTTP/1.0", "http_response_code": ["HTTP_2XX"]}}, created)
    pool = upsert(api, "pool", {
        "name": POOL_NAME, "tenant_ref": tenant_ref, "cloud_ref": cloud["url"], "vrf_ref": vrf["url"],
        "default_server_port": BACKEND_PORT, "health_monitor_refs": [mon["url"]],
        "servers": [{"ip": {"addr": ip, "type": "V4"}, "port": BACKEND_PORT} for ip in backends]}, created)

    # -- the three sites, one after the other ------------------------------------------------------
    build_vip = vip_builder(api, cfg, cloud)
    auto = bool(cloud.get("ipam_provider_ref")) and ask(cfg, "vip_mode", "VIP addresses (auto/static)", "auto") == "auto"
    used = {e.get("ip_address", {}).get("addr"): v["name"] for v in api.list("vsvip") for e in v.get("vip", [])}
    results = []
    for site in SITES:
        hostname = f"{site['host']}.{domain}"
        print(f"\n== {site['vs']} ({hostname} -> /{site['path']}) ==")
        vsvip_name = f"{site['vs']}-vip"

        def free(v, name=vsvip_name):
            v = one_ip(v)
            if used.get(v) not in (None, name):
                raise ValueError(f"VIP {v} is already used by vsvip {used[v]}")
        ip = None if auto else ask(cfg, f"{site['key']}.vip", f"VIP address for {site['vs']}", check=free)
        if ip:
            ip = one_ip(ip)
            used[ip] = vsvip_name
        policy = upsert(api, "httppolicyset", policy_body(site, hostname, tenant_ref), created)
        vsvip = upsert(api, "vsvip", {
            "name": vsvip_name, "tenant_ref": tenant_ref, "cloud_ref": cloud["url"],
            "vrf_context_ref": vrf["url"], "vip": [build_vip(ip)]}, created)
        existing = (api.list("virtualservice", name=site["vs"]) or [{}])[0]
        pols = existing.get("http_policies") or []
        if ban and not any(p["http_policy_set_ref"] == ban["url"] for p in pols):
            pols = [{"http_policy_set_ref": ban["url"], "index": 1}] + pols
        body = {
            "name": site["vs"], "tenant_ref": tenant_ref, "cloud_ref": cloud["url"], "enabled": True,
            "vsvip_ref": vsvip["url"], "pool_ref": pool["url"],
            "application_profile_ref": app_profile["url"], "network_profile_ref": net_profile["url"],
            "ssl_profile_ref": ssl_profile["url"], "ssl_key_and_certificate_refs": [cert["url"]],
            "se_group_ref": seg["url"], "vrf_context_ref": vrf["url"],
            "services": [{"port": 443, "enable_ssl": True}],
            "http_policies": attach_policy(pols, policy["url"]),
        }
        if waf:
            body["waf_policy_ref"] = waf["url"]
        upsert(api, "virtualservice", body, created)
        attached.append({"vs": site["vs"], "policy": policy["url"]})
        results.append((site["vs"], hostname, vsvip["url"]))

    if api.dry_run:
        print("\nDry run only: nothing was changed. The controller validates each object when you apply,"
              "\nso a rejected value (for example a bad address) can still show up on the real run.")
    else:
        print("\nResult:")
        for vs_name, hostname, ref in results:
            vip = api.call("GET", ref)["vip"][0]
            print(f"  {vs_name:<12} {hostname:<28} {vip.get('ip_address', {}).get('addr', '(allocating)')}")
    return results


def delete(api, cfg):
    created, attached = cfg.get("_created", []), cfg.get("_attached", [])
    if not created and not attached:
        sys.exit("nothing recorded in the answers file to delete")
    api.tenant = cfg.get("tenant", "admin")
    print("This will detach the policies and delete:")
    for c in reversed(created):
        print(f"  {c['obj']} {c['name']}")
    if input("Type 'yes' to continue: ").strip() != "yes":
        sys.exit("aborted")
    for a in attached:
        vs = a["vs"] if "://" in a["vs"] else (api.list("virtualservice", name=a["vs"]) or [{}])[0].get("url")
        if not vs:
            continue
        cur = api.call("GET", vs)
        cur["http_policies"] = [p for p in (cur.get("http_policies") or []) if p["http_policy_set_ref"] != a["policy"]]
        api.call("PUT", vs, cur)
    for c in reversed(created):
        api.call("DELETE", c["url"])
    print("done")


_BANNER_LINES = [
    "avi_publish.py - AcmeCorp lab: three sites on one backend, via Avi",
    None,
    "Creates on an existing Avi controller (REST API, no SDK):",
    "  - 3 HTTPS virtual services, each with its own VIP:",
    "      finance-app -> /FIN    hr-app -> /HT    eng-app -> /ENG",
    f"  - 1 shared pool ({POOL_NAME}, port {BACKEND_PORT}) with a /healthz monitor",
    "  - 1 HTTP request policy per site that rewrites every path to the site",
    f"    root, except {', '.join(EXCLUDES)} and the site's own path",
    "",
    "--dry-run  show every change without making it",
    "--delete   remove what a previous run created",
    "--help     all options",
]
_RULE = "+" + "-" * 76 + "+"
BANNER = "\n".join([_RULE] + [_RULE if l is None else f"|  {l:<74}|" for l in _BANNER_LINES] + [_RULE]) + "\n"

LABELS = [("tenant", "Tenant"), ("cloud", "Cloud"), ("vrf", "VRF context"), ("se_group", "Service engine group"),
          ("use_waf", "WAF enabled"), ("waf", "WAF policy"), ("domain", "Domain suffix"), ("backend_ip", "Backend IP(s)"),
          ("vip_network", "VIP network"), ("vip_mode", "VIP mode"),
          ("FIN.vip", "VIP finance-app"), ("HT.vip", "VIP hr-app"), ("ENG.vip", "VIP eng-app")]


def saved_answers(cfg):
    """The saved configuration answers worth reusing (connection details are always asked)."""
    return [(label, cfg[key]) for key, label in LABELS if key in cfg and cfg[key] not in ("", None)]


def reuse_saved(cfg, path):
    """Offer the answers from a previous run; declining keeps only what --delete and the defaults need."""
    saved = saved_answers(cfg)
    if not saved:
        return cfg
    print(f"Found a saved configuration in {path}:")
    for label, value in saved:
        print(f"  {label:<22} {', '.join(value) if isinstance(value, list) else value}")
    if input("Reuse it? [Y/n]: ").strip().lower().startswith("n"):
        print("Starting with a clean dialog.\n")
        return {k: v for k, v in cfg.items() if k in ("controller", "username") or k.startswith("_")}
    print()
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="avi_answers.json", help="answers file (read if present, written at the end)")
    ap.add_argument("--dry-run", action="store_true", help="print every write instead of sending it")
    ap.add_argument("--delete", action="store_true", help="undo what a previous run created")
    ap.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed controller)")
    ap.add_argument("--yes", action="store_true", help="update existing objects this script did not create without asking")
    ap.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT, help=f"seconds to wait for each controller call (default {REQUEST_TIMEOUT})")
    ap.add_argument("--ban-policy", help="name of an existing HTTP policy (e.g. the ban REJECT rule) to attach first on every VS")
    args = ap.parse_args()

    cfg = json.load(open(args.config)) if os.path.exists(args.config) and os.path.getsize(args.config) else {}
    print(BANNER)
    if not args.delete:
        cfg = reuse_saved(cfg, args.config)
    # connection details are always asked; the environment or the saved answers only supply the default
    controller = input(f"Controller IP or URL [{os.environ.get('AVI_CONTROLLER') or cfg.get('controller') or DEFAULT_CONTROLLER}]: ").strip() \
        or os.environ.get("AVI_CONTROLLER") or cfg.get("controller") or DEFAULT_CONTROLLER
    user = input(f"Username [{os.environ.get('AVI_USERNAME') or cfg.get('username') or DEFAULT_USER}]: ").strip() \
        or os.environ.get("AVI_USERNAME") or cfg.get("username") or DEFAULT_USER
    cfg.update(controller=controller, username=user)
    password = os.environ.get("AVI_PASSWORD") or getpass.getpass("Password: ")
    api = Avi(controller, verify=not args.insecure, dry_run=args.dry_run, timeout=args.timeout, assume_yes=args.yes)
    api.login(user, password)
    print(f"Connected, controller API version {api.version}")

    if args.delete:
        delete(api, cfg)
        return
    try:
        run(api, cfg, args.ban_policy or cfg.get("ban_policy"))
    finally:  # keep the answers and the created-objects record even if a call fails midway
        json.dump(cfg, open(args.config, "w"), indent=2)
        print(f"\nAnswers saved to {args.config}")


if __name__ == "__main__":
    main()
