"""
End-to-end tests in a real browser (Playwright + Chromium), against a live test server.

They cover what unit tests can't: JavaScript behaviour, the stylesheet actually applying,
keyboard use, the phone layout, printing, and automated accessibility checks (axe-core).
"""

import os

# Playwright's synchronous API runs an event loop in this thread, which makes Django's
# safety check think the database is being used from async code. It isn't.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from axe_playwright_python.sync_playwright import Axe  # noqa: E402
from django.contrib.staticfiles.testing import StaticLiveServerTestCase  # noqa: E402
from django.test import override_settings  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from checker.tests_marts import add_category, make_rate  # noqa: E402

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1366, "height": 900}
PLATE_YELLOW = "rgb(244, 194, 27)"


@override_settings(DVSA_CLIENT_ID="")   # demo cars only: never call the real DVSA API
class BrowserTests(StaticLiveServerTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        # E2E_BROWSER_PATH: use a Chromium already on the machine instead of Playwright's own
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get("E2E_BROWSER_PATH") or None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def open(self, path, viewport=DESKTOP, **context_options):
        context = self.browser.new_context(viewport=viewport, **context_options)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        # JavaScript errors, and any file the page needs (CSS, fonts, scripts, images) that
        # fails to load. The page's own status is left out: a 404 page is meant to be a 404.
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: msg.type == "error"
                and not msg.text.startswith("Failed to load resource") and errors.append(msg.text))
        page.on("response", lambda r: r.status >= 400 and r.request.resource_type != "document"
                and errors.append(f"{r.status} {r.url}"))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"browser errors on {path}"))
        page.goto(self.live_server_url + path)
        return page

    # ---------- the main journey ----------

    def test_check_a_car_from_the_home_page(self):
        page = self.open("/")
        page.fill("#reg", "sample 3")                  # lower case and a space, as people type
        expect(page.locator("#reg")).to_have_value("SAMPLE 3")
        page.click("[data-check-button]")
        page.wait_for_url("**/report/SAMPLE3/")
        expect(page.locator("h1")).to_have_text("Vauxhall Corsa")
        expect(page.get_by_text("Dangerous defect recorded")).to_be_visible()

    def test_empty_plate_is_not_submitted(self):
        page = self.open("/")
        page.click("[data-check-button]")
        self.assertTrue(page.url.endswith("/"))
        expect(page.locator("#reg")).to_be_focused()

    def test_evidence_chip_jumps_to_the_mot_test(self):
        page = self.open("/report/SAMPLE3/")
        chip = page.locator(".finding .chip").first
        target = chip.get_attribute("href")
        chip.click()
        self.assertTrue(page.url.endswith(target))
        expect(page.locator(target)).to_be_in_viewport()

    def test_unknown_page_shows_the_site_404(self):
        page = self.open("/no-such-page/")
        expect(page.locator("h1")).to_have_text("This page doesn't exist")

    # ---------- the comparison section, styled ----------

    def test_comparison_chart_is_drawn_and_styled(self):
        fiesta = make_rate()                           # SAMPLE1 is a 2016 Ford Fiesta
        for i in range(6):
            make_rate(model_year_key=f"m{i}", model=f"MODEL {i}", tests=100 * (i + 1),
                      initial_fail_rate_pct=20 + i, vs_peers="within", funnel_position="inside")
        add_category(fiesta, "Brakes", 9.0, 6.0)
        page = self.open("/report/SAMPLE1/")
        # the simple scale is what people see first
        marker = page.locator(".position-this")
        expect(marker).to_be_visible()
        expect(page.locator(".position-lead")).to_contain_text("first used in 2016")
        # the bug where the chart showed up black and white: the stylesheet must apply
        self.assertEqual(marker.evaluate("el => getComputedStyle(el).backgroundColor"), PLATE_YELLOW)
        # the detailed funnel chart stays available, one click away
        dot = page.locator(".funnel-this")
        expect(dot).to_be_hidden()
        page.get_by_text("Show the detailed chart").click()
        expect(dot).to_be_visible()
        self.assertEqual(dot.evaluate("el => getComputedStyle(el).fill"), PLATE_YELLOW)
        bar = page.locator(".bar-model")
        self.assertEqual(bar.evaluate("el => getComputedStyle(el).backgroundColor"), PLATE_YELLOW)

    # ---------- phones, keyboards, printing, no JavaScript ----------

    def test_phone_menu_opens_and_closes(self):
        page = self.open("/help/", viewport=PHONE)
        button = page.locator("[data-menu-button]")
        methodology = page.locator("#site-nav").get_by_role("link", name="Methodology")
        expect(methodology).to_be_hidden()
        button.click()
        expect(button).to_have_attribute("aria-expanded", "true")
        expect(methodology).to_be_visible()
        page.keyboard.press("Escape")
        expect(button).to_have_attribute("aria-expanded", "false")
        expect(button).to_be_focused()

    def test_menu_works_without_javascript(self):
        page = self.open("/help/", viewport=PHONE, java_script_enabled=False)
        expect(page.locator("#site-nav").get_by_role("link", name="Methodology")).to_be_visible()

    def test_skip_link_is_first_and_moves_focus_to_the_content(self):
        page = self.open("/methodology/")
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate("document.activeElement.id"), "main")

    def test_copy_link_puts_the_report_address_on_the_clipboard(self):
        page = self.open("/report/SAMPLE3/", permissions=["clipboard-read", "clipboard-write"])
        page.click("[data-copy-link]")
        expect(page.locator("[data-copy-label]")).to_have_text("Link copied")
        self.assertEqual(page.evaluate("navigator.clipboard.readText()"),
                         self.live_server_url + "/report/SAMPLE3/")

    def test_printed_report_drops_navigation_and_keeps_the_summary(self):
        page = self.open("/report/SAMPLE3/")
        page.emulate_media(media="print")
        expect(page.locator(".site-header")).to_be_hidden()
        expect(page.locator(".aside-actions")).to_be_hidden()
        expect(page.locator(".aside-glance")).to_be_visible()

    # ---------- light and dark themes ----------

    def background(self, page):
        return page.evaluate("getComputedStyle(document.body).backgroundColor")

    def test_follows_the_device_setting(self):
        self.assertEqual(self.background(self.open("/", color_scheme="light")), "rgb(246, 245, 240)")
        self.assertEqual(self.background(self.open("/", color_scheme="dark")), "rgb(17, 18, 16)")

    def test_theme_switch_is_remembered_across_pages(self):
        page = self.open("/", color_scheme="dark")
        switch = page.locator("[data-theme-toggle]")
        expect(switch).to_have_attribute("aria-label", "Switch to light theme")
        switch.click()
        self.assertEqual(self.background(page), "rgb(246, 245, 240)")
        expect(switch).to_have_attribute("aria-label", "Switch to dark theme")
        page.goto(self.live_server_url + "/help/")             # a new page load
        self.assertEqual(page.evaluate("document.documentElement.dataset.theme"), "light")
        self.assertEqual(self.background(page), "rgb(246, 245, 240)")

    # ---------- explore models and the seller checklist ----------

    def seed_models(self):
        fiesta = make_rate()                                     # 2016 Ford Fiesta, as SAMPLE1
        for i, year in enumerate((2014, 2015)):
            make_rate(model_year_key=f"fiesta-{year}", first_use_year=year, vs_peers="within",
                      funnel_position="inside", estimated_initial_fail_rate_pct=33 - i)
        for i in range(55):                                      # enough models for a ranking
            make_rate(model_year_key=f"m{i}", make="VAUXHALL", make_slug="vauxhall",
                      model=f"MODEL {i}", model_slug=f"model-{i}", tests=40 + 200 * i,
                      estimated_initial_fail_rate_pct=15 + i * 0.3, vs_peers="within",
                      funnel_position="inside")
        return fiesta

    def test_explore_from_search_to_a_model_page(self):
        self.seed_models()
        page = self.open("/models/")
        page.fill("#model-q", "ford fiesta")
        page.get_by_role("button", name="Search").click()
        page.get_by_role("link", name="Ford Fiesta").first.click()
        page.wait_for_url("**/models/ford/fiesta/")
        expect(page.locator("h1")).to_have_text("Ford Fiesta")
        expect(page.locator(".yc-model")).to_be_visible()

    def test_ranking_year_can_be_changed(self):
        self.seed_models()
        page = self.open("/models/")
        expect(page.locator("#rank-h")).to_contain_text("2016")
        page.select_option("#rank-year", "2016")
        page.get_by_role("button", name="Show").click()
        expect(page.locator(".rank-table").first.locator("tbody tr")).to_have_count(10)

    def test_checklist_items_can_be_ticked(self):
        page = self.open("/report/SAMPLE3/")
        box = page.locator("#questions input[type=checkbox]").first
        box.check()
        expect(box).to_be_checked()

    # ---------- accessibility ----------

    def test_no_serious_accessibility_problems(self):
        """axe-core, the engine behind most accessibility checkers, on the main pages, in
        both themes at desktop and phone widths. Fails on any 'serious' or 'critical'
        problem, listing each one."""
        self.seed_models()
        axe = Axe()
        for path in ["/", "/report/SAMPLE3/", "/report/SAMPLE1/", "/methodology/", "/help/",
                     "/privacy/", "/contact/", "/report/NOSUCHCAR/", "/models/",
                     "/models/?q=ford", "/models/vauxhall/", "/models/ford/fiesta/"]:
            for viewport, scheme in ((DESKTOP, "dark"), (PHONE, "dark"),
                                     (DESKTOP, "light"), (PHONE, "light")):
                with self.subTest(path=path, width=viewport["width"], theme=scheme):
                    page = self.open(path, viewport=viewport, reduced_motion="reduce",
                                     color_scheme=scheme)
                    results = axe.run(page)
                    problems = [f"{v['id']} ({v['impact']}): {v['help']} - "
                                f"{[n['target'] for n in v['nodes'][:3]]}"
                                for v in results.response["violations"]
                                if v["impact"] in ("serious", "critical")]
                    self.assertEqual(problems, [])

