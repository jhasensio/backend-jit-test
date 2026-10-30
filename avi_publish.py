#!/usr/bin/env python3
"""Publish the three lab sites (FIN / HT / ENG) as three virtual services on one shared pool.

Talks to the Avi REST API directly (requests only, no Avi SDK). Each VS gets its own VIP and an
HTTP request policy that rewrites every path to the site root, except the paths the pages need
(site path, static, healthz, search, api).

    python3 avi_publish.py                      # interactive dialog
    python3 avi_publish.py --dry-run            # show every write instead of sending it
    python3 avi_publish.py --config avi_answers.json   # replay saved answers
    python3 avi_publish.py --delete             # undo what a previous run created

Credentials come from AVI_USERNAME / AVI_PASSWORD or a prompt and are never saved.
"""
import argparse
import copy
import getpass
import json
import os
import sys

import requests

DEFAULT_EXCLUDES = "static,healthz,search,api"
DEFAULT_FIRST_INDEX = 11

# vs / policy names follow the finance-app / Route_FIN reference; "path" is the Flask route.
SITES = [
    {"key": "FIN", "vs": "finance-app", "host": "finance", "policy": "Route_FIN", "path": "FIN", "vip": "192.168.200.10"},
    {"key": "HT", "vs": "hr-app", "host": "hr", "policy": "Route_HT", "path": "HT", "vip": "192.168.200.11"},
    {"key": "ENG", "vs": "eng-app", "host": "eng", "policy": "Route_ENG", "path": "ENG", "vip": "192.168.200.12"},
]

# VS fields cloned from the template VS (runtime and per-VS fields are deliberately left out).
CLONED = [
    "application_profile_ref", "network_profile_ref", "analytics_profile_ref", "analytics_policy",
    "error_page_profile_ref", "network_security_policy_ref", "se_group_ref", "vrf_context_ref",
    "ssl_key_and_certificate_refs", "ssl_profile_ref", "services", "waf_policy_ref", "scaleout_ecmp",
]
# Required refs asked for one by one when no template VS is used: (field, object, label).
FROM_SCRATCH = [
    ("vrf_context_ref", "vrfcontext", "VRF context"),
    ("se_group_ref", "serviceenginegroup", "Service engine group"),
    ("application_profile_ref", "applicationprofile", "Application profile"),
    ("network_profile_ref", "networkprofile", "Network profile"),
    ("ssl_profile_ref", "sslprofile", "SSL profile"),
    ("ssl_cert", "sslkeyandcertificate", "SSL certificate"),
]
VIP_DROP = ["ip_address", "auto_allocate_ip", "auto_allocate_ip_type", "avi_allocated_vip", "avi_allocated_fip"]


class Avi:
    def __init__(self, base, verify=True, dry_run=False):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.verify = verify
        self.dry_run = dry_run
        self.version = None
        self.tenant = "admin"

    def login(self, user, password):
        r = self.s.get(f"{self.base}/api/initial-data")
        r.raise_for_status()
        self.version = r.json()["version"]["Version"]
        r = self.s.post(f"{self.base}/login", json={"username": user, "password": password})
        r.raise_for_status()

    def call(self, method, path, body=None, params=None):
        url = path if path.startswith("http") else f"{self.base}/api/{path}"
        if method != "GET" and self.dry_run:
            print(f"\n--- DRY RUN {method} {url}\n{json.dumps(body, indent=2)}")
            name = (body or {}).get("name", "x")
            return {**(body or {}), "url": url if method != "POST" else f"{url}/{name}"}
        headers = {
            "X-Avi-Version": self.version,
            "X-Avi-Tenant": self.tenant,
            "X-CSRFToken": self.s.cookies.get("csrftoken", ""),
            "Referer": self.base,
        }
        r = self.s.request(method, url, json=body, params=params, headers=headers)
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

    def ref(self, obj, name):
        return f"{self.base}/api/{obj}/{name}"


# ---- dialog helpers: a saved answer wins, otherwise prompt and remember ----------------------

def ask(cfg, key, prompt, default=None):
    if key in cfg:
        return cfg[key]
    shown = f" [{default}]" if default not in (None, "") else ""
    cfg[key] = input(f"{prompt}{shown}: ").strip() or default or ""
    return cfg[key]


def confirm(cfg, key, prompt, default=True):
    if key in cfg:
        return cfg[key]
    cfg[key] = (input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower() or ("y" if default else "n")).startswith("y")
    return cfg[key]


def pick(cfg, key, prompt, items, default=None):
    """choose() for a required answer: a name that is not on the controller stops the run."""
    item = choose(cfg, key, prompt, items, default)
    if item is None:
        sys.exit(f"{prompt}: '{cfg[key]}' not found on the controller")
    return item


def choose(cfg, key, prompt, items, default=None, optional=False):
    """Pick an item (dict with 'name') from a numbered list; returns the item, or None if optional."""
    if key in cfg:
        return next((i for i in items if i["name"] == cfg[key]), None)
    names = [i["name"] for i in items]
    print(f"\n{prompt}")
    for n, name in enumerate(names, 1):
        print(f"  {n}) {name}")
    if optional:
        print("  0) none")
    default = default if default in names else (names[0] if names and not optional else "")
    while True:
        raw = input(f"Choice [{default or '0'}]: ").strip()
        if not raw:
            pick = default
        elif raw == "0" and optional:
            pick = ""
        elif raw.isdigit() and 1 <= int(raw) <= len(names):
            pick = names[int(raw) - 1]
        else:
            pick = raw if raw in names else None
        if pick is not None:
            break
        print("  not a valid choice")
    cfg[key] = pick
    return next((i for i in items if i["name"] == pick), None)


# ---- object builders ---------------------------------------------------------------------------

def policy_body(site, host, excludes, tenant_ref):
    match = {"path": {
        "match_case": "SENSITIVE",
        "match_criteria": "DOES_NOT_CONTAIN",
        "match_decoded_string": False,
        "match_str": [site["path"]] + excludes,
    }}
    if host:
        match["host_hdr"] = {"match_case": "INSENSITIVE", "match_criteria": "HDR_EQUALS", "value": [host]}
    return {
        "name": site["policy"],
        "tenant_ref": tenant_ref,
        "is_internal_policy": False,
        "http_request_policy": {"rules": [{
            "name": f"rewrite-to-{site['key'].lower()}",
            "index": 0,
            "enable": True,
            "match": match,
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
    nxt = max((p["index"] for p in vs_policies), default=DEFAULT_FIRST_INDEX - 1) + 1
    return vs_policies + [{"http_policy_set_ref": policy_ref, "index": nxt}]


def upsert(api, obj, body, created):
    cur = api.list(obj, name=body["name"])
    if cur:
        print(f"  updating {obj} {body['name']}")
        return api.call("PUT", cur[0]["url"], {**cur[0], **body})
    print(f"  creating {obj} {body['name']}")
    res = api.call("POST", obj, body)
    created.append({"obj": obj, "name": body["name"], "url": res["url"]})
    return res


def vip_entry(api, cfg, cloud, tpl_vsvip, key, ip_default, used):
    """Build the vsvip 'vip' entry: auto-allocate (only with IPAM) or a static address."""
    if tpl_vsvip:
        entry = {k: v for k, v in copy.deepcopy(tpl_vsvip["vip"][0]).items() if k not in VIP_DROP}
    else:
        net = pick(cfg, "vip_network", "VIP network", api.list("network"))
        cidr = ask(cfg, "vip_subnet", "VIP subnet (CIDR)", "192.168.200.0/24")
        addr, mask = cidr.split("/")
        entry = {"vip_id": "0", "ipam_network_subnet": {
            "network_ref": net["url"], "subnet": {"ip_addr": {"addr": addr, "type": "V4"}, "mask": int(mask)}}}
    has_ipam = bool(cloud.get("ipam_provider_ref")) or "ipam_network_subnet" in entry
    if has_ipam and ask(cfg, f"{key}.vip_mode", "VIP mode (auto/static)", "auto") == "auto":
        return {**entry, "auto_allocate_ip": True, "auto_allocate_ip_type": "V4_ONLY"}
    if not has_ipam:
        print("  no IPAM detected on this cloud: a static VIP is required")
    ip = ask(cfg, f"{key}.vip", "VIP address", ip_default)
    if ip in used:
        sys.exit(f"VIP {ip} is already used by vsvip {used[ip]}")
    return {**entry, "ip_address": {"addr": ip, "type": "V4"}}


def run(api, cfg, dry_run=False):
    created, attached = [], []
    host = api.base.split("//")[-1].split("/")[0]
    suffix = host.split(".", 1)[1] if "." in host else "lab"

    tenant = pick(cfg, "tenant", "Tenant", api.list("tenant"), "admin")
    api.tenant = tenant["name"]
    tenant_ref = tenant["url"]
    cloud = pick(cfg, "cloud", "Cloud", api.list("cloud"), "Default-Cloud")
    in_cloud = lambda items: [i for i in items if i.get("cloud_ref") in (None, cloud["url"])]

    # -- template VS: clone profiles, cert, SE group, VRF, WAF, pool from it -----------------------
    vss = api.list("virtualservice")
    tpl = choose(cfg, "template", "Template virtual service to clone settings from", vss, "finance-app", optional=True)
    common, tpl_vsvip = {}, None
    if tpl:
        common = {k: copy.deepcopy(tpl[k]) for k in CLONED if k in tpl}
        if tpl.get("vsvip_ref"):
            tpl_vsvip = api.call("GET", tpl["vsvip_ref"])
    else:
        for field, obj, label in FROM_SCRATCH:
            item = pick(cfg, field, label, in_cloud(api.list(obj)))
            if field == "ssl_cert":
                common["ssl_key_and_certificate_refs"] = [item["url"]]
            else:
                common[field] = item["url"]
        common["services"] = [{"port": 443, "enable_ssl": True}]

    # WAF
    wafs = api.list("wafpolicy")
    waf = choose(cfg, "waf", "WAF policy", wafs, next((w["name"] for w in wafs if w["url"] == common.get("waf_policy_ref")), ""), optional=True)
    common.pop("waf_policy_ref", None)
    if waf:
        common["waf_policy_ref"] = waf["url"]

    # X-Forwarded-For: the lab's client_ip and ban logic read it
    prof = api.call("GET", common["application_profile_ref"])
    if "http_profile" in prof and not prof["http_profile"].get("xff_enabled"):
        if confirm(cfg, "xff", f"Application profile {prof['name']} does not insert X-Forwarded-For. Create an XFF copy?"):
            clone = {k: v for k, v in prof.items() if k not in ("uuid", "url", "_last_modified")}
            clone.update(name=f"{prof['name']}-xff", tenant_ref=tenant_ref)
            clone["http_profile"]["xff_enabled"] = True
            common["application_profile_ref"] = upsert(api, "applicationprofile", clone, created)["url"]

    # -- shared pool -------------------------------------------------------------------------------
    pools = api.list("pool")
    tpl_pool = next((p["name"] for p in pools if p["url"] == (tpl or {}).get("pool_ref")), "")
    pool = choose(cfg, "pool", "Shared pool (empty list entry = create a new one)", pools, tpl_pool, optional=True)
    if pool:
        pool_ref = pool["url"]
    else:
        mon = upsert(api, "healthmonitor", {
            "name": "lab-healthz-monitor", "type": "HEALTH_MONITOR_HTTP", "tenant_ref": tenant_ref,
            "http_monitor": {"http_request": "GET /healthz HTTP/1.0", "http_response_code": ["HTTP_2XX"]}}, created)
        servers = ask(cfg, "pool_servers", "Backend server IPs (comma separated)").split(",")
        port = int(ask(cfg, "pool_port", "Backend port", "8080"))
        pool_ref = upsert(api, "pool", {
            "name": ask(cfg, "pool_name", "Pool name", "lab-backend-pool"), "tenant_ref": tenant_ref,
            "cloud_ref": cloud["url"], "default_server_port": port, "health_monitor_refs": [mon["url"]],
            "vrf_ref": common.get("vrf_context_ref"),
            "servers": [{"ip": {"addr": s.strip(), "type": "V4"}, "port": port} for s in servers]}, created)["url"]

    # -- sites -------------------------------------------------------------------------------------
    excludes = [e.strip() for e in ask(cfg, "excludes", "Paths passed through unchanged (comma separated)", DEFAULT_EXCLUDES).split(",") if e.strip()]
    used = {}
    for v in api.list("vsvip"):
        for e in v.get("vip", []):
            used[e.get("ip_address", {}).get("addr")] = v["name"]
    results = []
    for site in SITES:
        k = site["key"]
        print(f"\n== {k} ==")
        vs_name = ask(cfg, f"{k}.vs", "Virtual service name", site["vs"])
        hostname = ask(cfg, f"{k}.host", "Hostname to match (blank = no host match)", f"{site['host']}.{suffix}")
        if not hostname:
            print("  warning: without a host match, requests by raw IP are rewritten too")
        policy = upsert(api, "httppolicyset", policy_body(site, hostname, excludes, tenant_ref), created)
        existing = next((v for v in vss if v["name"] == vs_name), None) or (api.list("virtualservice", name=vs_name) or [None])[0]
        if existing and tpl and existing["name"] == tpl["name"]:
            # the template itself: only its policy changes, pool / cert / VIP stay as they are
            pols = attach_policy(existing.get("http_policies", []), policy["url"])
            api.call("PUT", existing["url"], {**existing, "http_policies": pols})
            attached.append({"vs": existing["url"], "policy": policy["url"]})
            results.append((vs_name, existing.get("vsvip_ref")))
            continue
        vsvip_name = f"{vs_name}-vip"
        entry = vip_entry(api, cfg, cloud, tpl_vsvip, k, site["vip"], {a: n for a, n in used.items() if n != vsvip_name})
        vsvip = upsert(api, "vsvip", {
            "name": vsvip_name, "tenant_ref": tenant_ref, "cloud_ref": cloud["url"],
            "vrf_context_ref": common.get("vrf_context_ref"), "vip": [entry]}, created)
        pols = attach_policy(existing.get("http_policies", []) if existing else [], policy["url"])
        body = {**common, "name": vs_name, "tenant_ref": tenant_ref, "cloud_ref": cloud["url"],
                "vsvip_ref": vsvip["url"], "pool_ref": pool_ref, "http_policies": pols, "enabled": True}
        upsert(api, "virtualservice", body, created)
        attached.append({"vs": body["name"], "policy": policy["url"]})
        results.append((vs_name, vsvip["url"]))

    cfg["_created"] = created
    cfg["_attached"] = attached
    if not dry_run:
        print("\nResult:")
        for vs_name, ref in results:
            vip = api.call("GET", ref)["vip"][0] if ref else {}
            print(f"  {vs_name}: {vip.get('ip_address', {}).get('addr', '(allocating)')}")
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
        vs = a["vs"] if a["vs"].startswith("http") else (api.list("virtualservice", name=a["vs"]) or [{}])[0].get("url")
        if not vs:
            continue
        cur = api.call("GET", vs)
        cur["http_policies"] = [p for p in cur.get("http_policies", []) if p["http_policy_set_ref"] != a["policy"]]
        api.call("PUT", vs, cur)
    for c in reversed(created):
        api.call("DELETE", c["url"])
    print("done")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="avi_answers.json", help="answers file (read if present, written at the end)")
    ap.add_argument("--dry-run", action="store_true", help="print every write instead of sending it")
    ap.add_argument("--delete", action="store_true", help="undo what a previous run created")
    ap.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed controller)")
    args = ap.parse_args()

    cfg = json.load(open(args.config)) if os.path.exists(args.config) else {}
    controller = ask(cfg, "controller", "Controller URL", "https://w01-alb.ans.sddc.lab")
    user = os.environ.get("AVI_USERNAME") or ask(cfg, "username", "Username", "admin")
    password = os.environ.get("AVI_PASSWORD") or getpass.getpass("Password: ")
    api = Avi(controller, verify=not args.insecure, dry_run=args.dry_run)
    api.login(user, password)
    print(f"Connected, controller API version {api.version}")

    if args.delete:
        delete(api, cfg)
    else:
        run(api, cfg, args.dry_run)
        json.dump(cfg, open(args.config, "w"), indent=2)
        print(f"\nAnswers saved to {args.config}")


if __name__ == "__main__":
    main()
