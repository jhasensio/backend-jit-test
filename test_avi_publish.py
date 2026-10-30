import builtins
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

    def named(self, obj):
        return {v["name"]: v for v in self.db.get(obj, {}).values()}


def seed(xff=True, ipam=False, extra_vrf=False, extra_seg=False):
    api = FakeAvi()
    api.add("tenant", name="admin")
    cloud = api.add("cloud", name="Default-Cloud", **({"ipam_provider_ref": f"{B}/api/ipamdnsproviderprofile/x"} if ipam else {}))
    api.add("vrfcontext", name="global", cloud_ref=cloud["url"])
    api.add("vrfcontext", name="management", cloud_ref=cloud["url"])
    if extra_vrf:
        api.add("vrfcontext", name="tenant-vrf", cloud_ref=cloud["url"])
    api.add("serviceenginegroup", name="Default-Group", cloud_ref=cloud["url"])
    if extra_seg:
        api.add("serviceenginegroup", name="SE-WAAP", cloud_ref=cloud["url"])
    api.add("applicationprofile", name=ap.APP_PROFILE, http_profile={"xff_enabled": xff, "x_forwarded_proto_enabled": True})
    api.add("networkprofile", name=ap.NETWORK_PROFILE)
    api.add("sslprofile", name=ap.SSL_PROFILE)
    api.add("sslkeyandcertificate", name=ap.CERTIFICATE)
    api.add("wafpolicy", name="System-WAF-Policy")
    api.add("network", name="vip-net", cloud_ref=cloud["url"],
            configured_subnets=[{"prefix": {"ip_addr": {"addr": "192.168.200.0", "type": "V4"}, "mask": 24}}])
    return api


# Everything the dialog would ask once there is more than one choice or no default.
ANSWERS = {"use_waf": False, "domain": "ans.sddc.lab", "backend_ip": "192.168.10.10",
           "FIN.vip": "192.168.200.10", "HT.vip": "192.168.200.11", "ENG.vip": "192.168.200.12"}


class PublishTest(unittest.TestCase):
    def setUp(self):
        self._input = builtins.input
        # any prompt the dialog should have skipped fails the test
        builtins.input = lambda *a: self.fail(f"unexpected prompt: {a}")

    def tearDown(self):
        builtins.input = self._input

    def test_one_run_builds_all_three_without_prompts(self):
        api = seed()
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        vs = api.named("virtualservice")
        self.assertEqual(set(vs), {"finance-app", "hr-app", "eng-app"})
        pools = api.named("pool")
        self.assertEqual(list(pools), ["lab-backend-pool"])
        self.assertEqual(pools["lab-backend-pool"]["servers"][0]["port"], 8080)
        self.assertEqual({v["pool_ref"] for v in vs.values()}, {pools["lab-backend-pool"]["url"]})
        # fixed system objects, management VRF filtered out, single tenant/cloud/SE group not asked
        self.assertEqual(cfg["vrf"], "global")
        self.assertEqual((cfg["tenant"], cfg["cloud"], cfg["se_group"]), ("admin", "Default-Cloud", "Default-Group"))
        for v in vs.values():
            self.assertEqual(v["services"], [{"port": 443, "enable_ssl": True}])
            self.assertEqual(len(v["ssl_key_and_certificate_refs"]), 1)
            self.assertNotIn("waf_policy_ref", v)
        vips = {n: v["vip"][0]["ip_address"]["addr"] for n, v in api.named("vsvip").items()}
        self.assertEqual(vips, {"finance-app-vip": "192.168.200.10", "hr-app-vip": "192.168.200.11", "eng-app-vip": "192.168.200.12"})
        # policy rule: host + path, fixed exclusions, rewrite to the site root
        rule = api.named("httppolicyset")["Route_HT"]["http_request_policy"]["rules"][0]
        self.assertEqual(rule["match"]["host_hdr"]["value"], ["hr.ans.sddc.lab"])
        self.assertEqual(rule["match"]["path"]["match_str"], ["HT", "static", "healthz", "search", "api"])
        self.assertEqual(rule["rewrite_url_action"]["path"]["tokens"][0]["str_value"], "HT")
        self.assertEqual(vs["hr-app"]["http_policies"][0]["index"], 11)

    def test_several_backend_ips_become_pool_servers(self):
        api = seed()
        ap.run(api, {**ANSWERS, "backend_ip": "10.10.10.1, 10.10.10.2,10.10.10.1"})
        servers = api.named("pool")["lab-backend-pool"]["servers"]
        self.assertEqual([(s["ip"]["addr"], s["port"]) for s in servers], [("10.10.10.1", 8080), ("10.10.10.2", 8080)])

    def test_bad_or_empty_backend_is_refused(self):
        for bad in ("10.10.10.1, nope", " , ", "10.10.10.999", ""):
            with self.assertRaises(ValueError):
                ap.parse_ips(bad)
        self.assertEqual(ap.parse_ips(["10.0.0.5"]), ["10.0.0.5"])

    def test_rerun_is_idempotent_and_delete_undoes(self):
        api = seed()
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        counts = {k: len(v) for k, v in api.db.items()}
        ap.run(api, cfg)    # same answers file, so the objects are recognised as created by the script
        self.assertEqual(counts, {k: len(v) for k, v in api.db.items()})
        self.assertEqual(len(api.named("virtualservice")["hr-app"]["http_policies"]), 1)
        builtins.input = lambda *_: "yes"
        ap.delete(api, cfg)
        for obj in ("virtualservice", "vsvip", "httppolicyset", "pool", "healthmonitor"):
            self.assertEqual(api.db.get(obj, {}), {}, obj)

    def test_xff_copy_when_the_profile_does_not_insert_it(self):
        api = seed(xff=False)
        ap.run(api, dict(ANSWERS))
        self.assertIn("System-Secure-HTTP-xff", api.named("applicationprofile"))
        vs = api.named("virtualservice")["hr-app"]
        self.assertEqual(vs["application_profile_ref"], api.named("applicationprofile")["System-Secure-HTTP-xff"]["url"])
        self.assertTrue(api.named("applicationprofile")["System-Secure-HTTP-xff"]["http_profile"]["xff_enabled"])

    def test_waf_policy_is_attached_when_enabled(self):
        api = seed()
        ap.run(api, {**ANSWERS, "use_waf": True})   # single WAF policy: picked silently
        for v in api.named("virtualservice").values():
            self.assertEqual(v["waf_policy_ref"], api.named("wafpolicy")["System-WAF-Policy"]["url"])

    def test_ban_policy_stays_first(self):
        api = seed()
        ban = api.add("httppolicyset", name="ban-reject")
        ap.run(api, dict(ANSWERS), ban_policy="ban-reject")
        for v in api.named("virtualservice").values():
            self.assertEqual(v["http_policies"][0], {"http_policy_set_ref": ban["url"], "index": 1})
            self.assertEqual(v["http_policies"][1]["index"], 2)   # right after the ban rule

    def test_several_vrfs_or_se_groups_are_asked(self):
        api = seed(extra_vrf=True, extra_seg=True)
        with self.assertRaises(AssertionError):   # a prompt appears (input is blocked in setUp)
            ap.run(api, dict(ANSWERS))
        cfg = {**ANSWERS, "vrf": "tenant-vrf", "se_group": "SE-WAAP"}
        ap.run(api, cfg)
        self.assertEqual(api.named("pool")["lab-backend-pool"]["vrf_ref"], api.named("vrfcontext")["tenant-vrf"]["url"])

    def test_ipam_auto_allocates_all_three(self):
        api = seed(ipam=True)
        ap.run(api, {**{k: v for k, v in ANSWERS.items() if not k.endswith(".vip")}, "vip_mode": "auto"})
        for v in api.named("vsvip").values():
            self.assertTrue(v["vip"][0]["auto_allocate_ip"])
            self.assertNotIn("ip_address", v["vip"][0])
            self.assertEqual(v["vip"][0]["ipam_network_subnet"]["subnet"]["mask"], 24)

    def test_vip_used_by_another_vsvip_is_asked_again(self):
        api = seed()
        api.add("vsvip", name="other-vip", vip=[{"ip_address": {"addr": "192.168.200.11", "type": "V4"}}])
        builtins.input = lambda *_: "192.168.200.60"      # saved HT.vip clashes, so the dialog asks again
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        self.assertEqual(cfg["HT.vip"], "192.168.200.60")

    def test_connection_details_are_always_asked_even_with_a_saved_answers_file(self):
        import json, os, sys, tempfile
        seen = {}

        class Stub:
            def __init__(self, base, **kw):
                seen["base"] = base

            def login(self, user, password):
                seen["user"], seen["password"] = user, password
            version = "1"

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            json.dump({"controller": "10.6.248.47", "username": "saved"}, open(path, "w"))
            old = (ap.Avi, ap.run, sys.argv, dict(os.environ))
            ap.Avi, ap.run = Stub, lambda *a, **k: None
            os.environ.update(AVI_PASSWORD="pw")
            for k in ("AVI_CONTROLLER", "AVI_USERNAME"):
                os.environ.pop(k, None)
            try:
                for answers, want in ((["", ""], ("10.6.248.47", "saved")), (["ctl.example", "bob"], ("ctl.example", "bob"))):
                    builtins.input = lambda *_a, it=iter(answers): next(it)
                    sys.argv = ["x", "--config", path]
                    ap.main()
                    self.assertEqual((seen["base"], seen["user"]), want)
                os.remove(path)    # no saved file and nothing typed: the seeded defaults
                builtins.input = lambda *_a, it=iter(["", ""]): next(it)
                ap.main()
                self.assertEqual((seen["base"], seen["user"]), ("10.10.10.10", "admin"))
            finally:
                ap.Avi, ap.run, sys.argv = old[:3]
                os.environ.clear()
                os.environ.update(old[3])

    def test_banner_is_a_clean_box(self):
        self.assertEqual({len(l) for l in ap.BANNER.splitlines()}, {78})
        self.assertIn("finance-app", ap.BANNER)

    def _main_with(self, saved, typed):
        """Run main() against a stub controller; returns the cfg that run() received."""
        import json, os, sys, tempfile
        got = {}

        class Stub:
            def __init__(self, base, **kw):
                pass

            def login(self, user, password):
                pass
            version = "1"

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            json.dump(saved, open(path, "w"))
            old = (ap.Avi, ap.run, sys.argv, dict(os.environ))
            ap.Avi, ap.run = Stub, lambda api, cfg, ban=None: got.update(cfg)
            os.environ["AVI_PASSWORD"] = "pw"
            sys.argv = ["x", "--config", path]
            builtins.input = lambda *_a, it=iter(typed): next(it)
            try:
                ap.main()
            finally:
                ap.Avi, ap.run, sys.argv = old[:3]
                os.environ.clear()
                os.environ.update(old[3])
        return got

    def test_saved_configuration_is_offered_and_can_be_reused(self):
        saved = {"controller": "c", "username": "u", "domain": "x.lab", "backend_ip": "10.0.0.1", "_created": [{"obj": "pool"}]}
        got = self._main_with(saved, ["", "", ""])          # Enter = reuse, then controller, username
        self.assertEqual((got["domain"], got["backend_ip"]), ("x.lab", "10.0.0.1"))

    def test_declining_reuse_clears_answers_but_keeps_the_delete_record(self):
        saved = {"controller": "c", "username": "u", "domain": "x.lab", "backend_ip": "10.0.0.1", "_created": [{"obj": "pool"}]}
        got = self._main_with(saved, ["n", "", ""])
        self.assertNotIn("domain", got)
        self.assertNotIn("backend_ip", got)
        self.assertEqual(got["_created"], [{"obj": "pool"}])
        self.assertEqual(got["controller"], "c")

    def test_no_question_when_only_connection_details_are_saved(self):
        got = self._main_with({"controller": "c", "username": "u"}, ["", ""])   # a 3rd prompt would StopIteration
        self.assertEqual(got["controller"], "c")

    def test_existing_foreign_object_needs_confirmation(self):
        api = seed()
        api.add("pool", name="lab-backend-pool", servers=[{"ip": {"addr": "1.1.1.1", "type": "V4"}, "port": 80}])
        builtins.input = lambda *_: "n"
        with self.assertRaises(SystemExit):
            ap.run(api, dict(ANSWERS))
        self.assertEqual(api.named("pool")["lab-backend-pool"]["servers"][0]["ip"]["addr"], "1.1.1.1")   # untouched
        builtins.input = lambda *_: "y"
        ap.run(api, dict(ANSWERS))
        self.assertEqual(api.named("pool")["lab-backend-pool"]["servers"][0]["ip"]["addr"], "192.168.10.10")

    def test_yes_flag_updates_foreign_objects_without_asking(self):
        api = seed()
        api.assume_yes = True
        api.add("pool", name="lab-backend-pool", servers=[])
        ap.run(api, dict(ANSWERS))          # setUp blocks input(): a prompt would fail the test
        self.assertEqual(len(api.named("pool")["lab-backend-pool"]["servers"]), 1)

    def test_objects_this_script_created_are_updated_without_asking(self):
        api = seed()
        cfg = dict(ANSWERS)
        ap.run(api, cfg)
        ap.run(api, {**ANSWERS, "_created": cfg["_created"]})

    def test_timeout_and_network_errors_exit_cleanly(self):
        import requests
        api = ap.Avi("10.0.0.1", timeout=7)
        api.version = "1"
        seen = {}

        def boom(exc):
            def request(method, url, **kw):
                seen["timeout"] = kw["timeout"]
                raise exc
            return request
        for exc, text in ((requests.exceptions.ReadTimeout("slow"), "timed out after 7s"),
                          (requests.exceptions.ConnectionError("reset"), "failed")):
            api.s.request = boom(exc)
            with self.assertRaises(SystemExit) as cm:
                api.call("GET", "pool")
            self.assertIn(text, str(cm.exception))
            self.assertEqual(seen["timeout"], 7)

    def test_empty_or_invalid_vip_is_asked_again_and_never_saved_empty(self):
        api = seed()
        replies = iter(["", "not-an-ip", "192.168.200.99"])
        cfg = {**ANSWERS, "FIN.vip": ""}                 # an empty answer left by an earlier run is ignored
        builtins.input = lambda *_: next(replies)
        ap.run(api, cfg)
        self.assertEqual(cfg["FIN.vip"], "192.168.200.99")
        self.assertEqual(api.named("vsvip")["finance-app-vip"]["vip"][0]["ip_address"]["addr"], "192.168.200.99")

    def test_same_vip_twice_is_refused(self):
        api = seed()
        replies = iter(["192.168.200.10", "192.168.200.77"])   # HR typed the finance address, then a free one
        cfg = {**ANSWERS, "HT.vip": ""}
        builtins.input = lambda *_: next(replies)
        ap.run(api, cfg)
        self.assertEqual(cfg["HT.vip"], "192.168.200.77")

    def test_bare_ip_controller_gets_https(self):
        self.assertEqual(ap.Avi("10.6.248.47/").base, "https://10.6.248.47")
        self.assertEqual(ap.Avi("https://w01-alb.ans.sddc.lab").base, "https://w01-alb.ans.sddc.lab")

    def test_object_name_starting_with_http_is_not_a_url(self):
        api = ap.Avi("10.0.0.1")
        api.version = "1"
        seen = []
        api.s.request = lambda m, url, **kw: seen.append(url) or type("R", (), {"ok": True, "text": "{}", "json": lambda s: {}})()
        api.call("GET", "httppolicyset")
        self.assertEqual(seen, ["https://10.0.0.1/api/httppolicyset"])


if __name__ == "__main__":
    unittest.main()
