import unittest

import avi_publish as ap

B = "https://fake"


class FakeAvi(ap.Avi):
    """In-memory controller: enough of GET/POST/PUT/DELETE for the publish flow."""

    def __init__(self):
        super().__init__(B)
        self.version, self.db, self.n = "22.1.1", {}, 0

    def add(self, obj, **body):
        self.n += 1
        body.setdefault("uuid", f"{obj}-{self.n}")
        body["url"] = f"{B}/api/{obj}/{body['uuid']}"
        self.db.setdefault(obj, {})[body["url"]] = body
        return body

    def call(self, method, path, body=None, params=None):
        if path.startswith(B):
            if "/api/" not in path[len(B):]:
                raise AssertionError(path)
            obj = path.split("/api/")[1].split("/")[0]
            if method == "GET":
                return self.db[obj][path]
            if method == "PUT":
                self.db[obj][path] = body
                return body
            if method == "DELETE":
                del self.db[obj][path]
                return {}
        items = list(self.db.get(path, {}).values())
        if method == "GET":
            name = (params or {}).get("name")
            return {"results": [i for i in items if name in (None, i["name"])]}
        assert method == "POST"
        return self.add(path, **body)


def seed():
    api = FakeAvi()
    api.add("tenant", name="admin")
    api.add("cloud", name="NSXT", ipam_provider_ref=f"{B}/api/ipamdnsproviderprofile/x")
    cloud = api.db["cloud"]
    cloud_url = next(iter(cloud))
    prof = api.add("applicationprofile", name="http-secure", http_profile={"xff_enabled": False})
    pool = api.add("pool", name="app-pool")
    vsvip = api.add("vsvip", name="finance-app-vip", vip=[{
        "vip_id": "1", "ip_address": {"addr": "192.168.200.10", "type": "V4"},
        "ipam_network_subnet": {"network_ref": f"{B}/api/network/n", "subnet": {"ip_addr": {"addr": "192.168.200.0", "type": "V4"}, "mask": 24}}}])
    ban = api.add("httppolicyset", name="ban-reject")["url"]
    api.add("virtualservice", name="finance-app", cloud_ref=cloud_url, pool_ref=pool["url"], vsvip_ref=vsvip["url"],
            application_profile_ref=prof["url"], se_group_ref=f"{B}/api/serviceenginegroup/se",
            vrf_context_ref=f"{B}/api/vrfcontext/v", services=[{"port": 443, "enable_ssl": True}],
            ssl_key_and_certificate_refs=[f"{B}/api/sslkeyandcertificate/c"], http_policies=[{"http_policy_set_ref": ban, "index": 3}])
    return api, ban


ANSWERS = {"excludes": "static,healthz,search,api", "tenant": "admin", "cloud": "NSXT", "template": "finance-app", "waf": "", "xff": True, "pool": "app-pool",
           "FIN.vs": "finance-app", "FIN.host": "finance.ans.sddc.lab", "domain": "ans.sddc.lab", "HT.host": "hr.ans.sddc.lab", "ENG.host": "eng.ans.sddc.lab",
           "HT.vs": "hr-app", "ENG.vs": "eng-app", "HT.vip_mode": "static", "ENG.vip_mode": "auto", "HT.vip": "192.168.200.11"}


class PublishTest(unittest.TestCase):
    def test_full_run(self):
        api, ban = seed()
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        vs = {v["name"]: v for v in api.db["virtualservice"].values()}
        self.assertEqual(set(vs), {"finance-app", "hr-app", "eng-app"})
        # one shared pool, original pool untouched on finance-app
        self.assertEqual(len({v["pool_ref"] for v in vs.values()}), 1)
        # ban policy stays first, new policy appended after it
        fin = vs["finance-app"]["http_policies"]
        self.assertEqual(fin[0], {"http_policy_set_ref": ban, "index": 3})
        self.assertEqual(fin[1]["index"], 4)
        # new VSs inherit the template's ban policy first, then their own rewrite policy
        hr = vs["hr-app"]["http_policies"]
        self.assertEqual(hr[0], {"http_policy_set_ref": ban, "index": 3})
        self.assertEqual(hr[1]["index"], 4)
        # cloned profile with XFF
        prof = api.call("GET", vs["hr-app"]["application_profile_ref"])
        self.assertTrue(prof["http_profile"]["xff_enabled"])
        self.assertEqual(vs["hr-app"]["services"], [{"port": 443, "enable_ssl": True}])
        # VIPs: finance keeps .10, hr static .11, eng auto-allocated
        vips = {v["name"]: v["vip"][0] for v in api.db["vsvip"].values()}
        self.assertEqual(vips["hr-app-vip"]["ip_address"]["addr"], "192.168.200.11")
        self.assertTrue(vips["eng-app-vip"]["auto_allocate_ip"])
        self.assertNotIn("ip_address", vips["eng-app-vip"])
        # policy rule
        pol = {p["name"]: p for p in api.db["httppolicyset"].values()}["Route_HT"]
        rule = pol["http_request_policy"]["rules"][0]
        self.assertEqual(rule["match"]["host_hdr"]["value"], ["hr.ans.sddc.lab"])
        self.assertEqual(rule["match"]["path"]["match_str"], ["HT", "static", "healthz", "search", "api"])
        self.assertEqual(rule["rewrite_url_action"]["path"]["tokens"][0]["str_value"], "HT")

    def test_rerun_is_idempotent_and_delete_undoes(self):
        api, ban = seed()
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        counts = {k: len(v) for k, v in api.db.items()}
        ap.run(api, dict(ANSWERS))
        self.assertEqual(counts, {k: len(v) for k, v in api.db.items()})
        fin = next(v for v in api.db["virtualservice"].values() if v["name"] == "finance-app")
        self.assertEqual(len(fin["http_policies"]), 2)
        import builtins
        builtins.input = lambda *_: "yes"
        ap.delete(api, cfg)
        self.assertEqual([v["name"] for v in api.db["virtualservice"].values()], ["finance-app"])
        fin = next(iter(api.db["virtualservice"].values()))
        self.assertEqual([p["http_policy_set_ref"] for p in fin["http_policies"]], [ban])
        self.assertEqual(len(api.db["pool"]), 1)

    def test_bare_ip_controller_gets_https(self):
        self.assertEqual(ap.Avi("10.6.248.47/").base, "https://10.6.248.47")
        self.assertEqual(ap.Avi("https://w01-alb.ans.sddc.lab").base, "https://w01-alb.ans.sddc.lab")

    def test_vip_conflict_aborts(self):
        api, _ = seed()
        cfg = {**ANSWERS, "HT.vip": "192.168.200.10"}
        with self.assertRaises(SystemExit):
            ap.run(api, cfg)


if __name__ == "__main__":
    unittest.main()
