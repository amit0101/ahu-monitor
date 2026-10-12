#!/usr/bin/env python3
"""
E2E Test — Aqueduct Predictive Maintenance Dashboard
=====================================================
Runs entirely from the CLI using playwright-python (no browser subagent needed).
Usage:
    python3 e2e_test.py

Outputs:
  - Screenshots: e2e_screenshots/  (shot_01_initial.png, shot_02_15s.png, shot_03_30s.png)
  - Report:      E2E_REPORT.md
"""

import asyncio
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── dependency guard ──────────────────────────────────────────────────────────
try:
    from playwright.async_api import async_playwright, ConsoleMessage, Page
except ImportError:
    print("ERROR: playwright not installed. Run: pip3 install playwright && python3 -m playwright install chromium")
    sys.exit(1)

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL  = "http://localhost:8000"
SCREENSHOT_DIR = Path(__file__).parent / "e2e_screenshots"
REPORT_PATH    = Path(__file__).parent / "E2E_REPORT.md"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> tuple:
    """Simple blocking HTTP GET that returns (ok, data)."""
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return True, json.loads(r.read())
    except Exception as e:
        return False, str(e)

def check_backend_endpoints() -> dict:
    """Directly hit every REST endpoint and record status."""
    endpoints = [
        "/api/simulation/status",
        "/api/health",
        "/api/alerts",
        "/api/predictions",
        "/api/maintenance",
        "/api/twin",
    ]
    results = {}
    for ep in endpoints:
        ok, data = fetch_json(BACKEND_URL + ep)
        results[ep] = {"ok": ok, "data": data if ok else str(data)[:120]}
    return results

# ─────────────────────────────────────────────────────────────────────────────
# Main E2E test
# ─────────────────────────────────────────────────────────────────────────────

async def run_e2e() -> dict:
    """Execute the full test suite; return structured findings dict."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    findings = {
        "timestamp": datetime.now().isoformat(),
        "backend_api": {},
        "points": {},
        "console_errors": [],
        "console_warnings": [],
        "failed_requests": [],
        "screenshots": [],
        "notes": [],
    }

    # ── 0. Backend API checks (pure HTTP, no browser needed) ─────────────────
    print("  -> Checking backend REST API endpoints...")
    findings["backend_api"] = check_backend_endpoints()
    for ep, res in findings["backend_api"].items():
        status = "OK" if res["ok"] else "FAIL"
        print(f"      [{status}] {ep}")

    # ── 1. Launch headless Chromium ───────────────────────────────────────────
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        console_msgs = []
        failed_reqs  = []
        ws_connected = False

        def on_console(msg):
            text = f"[{msg.type.upper()}] {msg.text}"
            console_msgs.append(text)
            if msg.type == "error":
                findings["console_errors"].append(text)
            elif msg.type == "warning":
                findings["console_warnings"].append(text)

        def on_request_failed(req):
            entry = f"{req.method} {req.url} — {req.failure}"
            failed_reqs.append(entry)
            findings["failed_requests"].append(entry)

        def on_websocket(ws):
            nonlocal ws_connected
            ws_connected = True
            print(f"      [OK] WebSocket opened: {ws.url}")

        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)
        page.on("websocket", on_websocket)

        # Silence external font requests — headless Chromium hangs on font-load wait.
        # Use fulfill (empty 200) instead of abort: abort() emits a generic ERR_FAILED
        # console error with no URL in the message, making it impossible to filter out.
        async def block_fonts(route):
            url = route.request.url
            if "fonts.googleapis.com" in url or "fonts.gstatic.com" in url:
                await route.fulfill(status=200, content_type="text/css", body="")
            else:
                await route.continue_()
        await page.route("**/*", block_fonts)

        # ── Navigate ──────────────────────────────────────────────────────────
        print("  -> Navigating to", FRONTEND_URL)
        try:
            await page.goto(FRONTEND_URL, wait_until="networkidle", timeout=20000)
        except Exception as e:
            findings["notes"].append(f"Navigation timeout (non-fatal): {e}")
            try:
                await page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=15000)
            except Exception as e2:
                findings["notes"].append(f"domcontentloaded also timed out: {e2}")

        await asyncio.sleep(3)  # let React hydrate + WS connect

        # Screenshot #1
        shot1 = str(SCREENSHOT_DIR / "shot_01_initial.png")
        try:
            await page.screenshot(path=shot1, full_page=False, timeout=8000)
            findings["screenshots"].append(shot1)
            print("  -> Screenshot #1 saved:", shot1)
        except Exception as e:
            findings["notes"].append(f"Screenshot #1 failed (non-fatal): {e}")
            print("  -> Screenshot #1 SKIPPED (timeout):", e)

        # ── Collect page content for analysis ────────────────────────────────
        page_text = await page.inner_text("body")
        page_html = await page.content()

        # ── Point 1: Initial Load ─────────────────────────────────────────────
        has_root_content = len(page_text.strip()) > 100
        has_error_screen  = "Something went wrong" in page_text or "Cannot GET" in page_text
        findings["points"]["1_initial_load"] = {
            "pass": has_root_content and not has_error_screen,
            "detail": f"Page text length: {len(page_text)} chars. Error screen: {has_error_screen}",
        }
        p1 = findings["points"]["1_initial_load"]
        print(f"  -> Point 1 (Initial Load):       {'PASS' if p1['pass'] else 'FAIL'}")

        # ── Point 2: WebSocket ────────────────────────────────────────────────
        ws_text_found = any(kw in page_text.lower() for kw in ["connected", "ws", "websocket", "live"])
        findings["points"]["2_websocket"] = {
            "pass": ws_connected,
            "ws_opened": ws_connected,
            "indicator_text_found": ws_text_found,
            "detail": f"WS event fired: {ws_connected}. Page mentions connection: {ws_text_found}",
        }
        p2 = findings["points"]["2_websocket"]
        print(f"  -> Point 2 (WebSocket):          {'PASS' if p2['pass'] else 'FAIL'} (opened={ws_connected})")

        # ── Point 3: Sensor Cards ─────────────────────────────────────────────
        sensor_keywords = ["mm/s", "dba", " a", " pa", "vibration", "temperature", "current", "pressure", "rpm"]
        sensor_hits = [kw for kw in sensor_keywords if kw in page_text.lower()]
        has_sensor_cards = len(sensor_hits) >= 3
        findings["points"]["3_sensor_cards"] = {
            "pass": has_sensor_cards,
            "keywords_found": sensor_hits,
            "detail": f"Found sensor keywords: {sensor_hits}",
        }
        p3 = findings["points"]["3_sensor_cards"]
        print(f"  -> Point 3 (Sensor Cards):       {'PASS' if p3['pass'] else 'FAIL'} keywords={sensor_hits}")

        # ── Point 4: Health Panel ─────────────────────────────────────────────
        health_keywords = ["health", "supply fan", "filter", "coil", "ahu"]
        health_hits = [kw for kw in health_keywords if kw in page_text.lower()]
        pct_numbers = re.findall(r'\b\d{1,3}%', page_text)
        has_health_panel = len(health_hits) >= 3 and len(pct_numbers) >= 2
        findings["points"]["4_health_panel"] = {
            "pass": has_health_panel,
            "keywords_found": health_hits,
            "percentages_found": pct_numbers[:10],
            "detail": f"Health keywords: {health_hits}. Percentages: {pct_numbers[:10]}",
        }
        p4 = findings["points"]["4_health_panel"]
        print(f"  -> Point 4 (Health Panel):       {'PASS' if p4['pass'] else 'FAIL'} pcts={pct_numbers[:6]}")

        # ── Point 5: 3D AHU Model ─────────────────────────────────────────────
        canvas_count = await page.locator("canvas").count()
        has_3d = canvas_count >= 1
        findings["points"]["5_3d_model"] = {
            "pass": has_3d,
            "canvas_elements": canvas_count,
            "detail": f"<canvas> elements found: {canvas_count}",
        }
        p5 = findings["points"]["5_3d_model"]
        print(f"  -> Point 5 (3D Model):           {'PASS' if p5['pass'] else 'FAIL'} canvas_count={canvas_count}")

        # ── Point 6: Time Series Charts ───────────────────────────────────────
        svg_count = await page.locator("svg").count()
        has_charts = svg_count >= 2
        findings["points"]["6_time_series_charts"] = {
            "pass": has_charts,
            "svg_count": svg_count,
            "detail": f"SVG elements (Recharts renders SVG): {svg_count}",
        }
        p6 = findings["points"]["6_time_series_charts"]
        print(f"  -> Point 6 (Charts):             {'PASS' if p6['pass'] else 'FAIL'} svg_count={svg_count}")

        # ── Point 7: Alerts Panel ─────────────────────────────────────────────
        alert_keywords = ["alert", "warning", "critical", "fault", "anomaly", "detected"]
        alert_hits = [kw for kw in alert_keywords if kw in page_text.lower()]
        has_alerts_panel = len(alert_hits) >= 2
        findings["points"]["7_alerts_panel"] = {
            "pass": has_alerts_panel,
            "keywords_found": alert_hits,
            "detail": f"Alert keywords: {alert_hits}",
        }
        p7 = findings["points"]["7_alerts_panel"]
        print(f"  -> Point 7 (Alerts):             {'PASS' if p7['pass'] else 'FAIL'} keywords={alert_hits}")

        # ── Point 8: Maintenance Panel (checked after 15s wait — may be empty at day 1) ──
        # Will be re-evaluated at T=15s snapshot; placeholder for now
        findings["points"]["8_maintenance_panel"] = {"pass": False, "keywords_found": [], "detail": "Pending 15s snapshot"}

        # ── Point 9: aQ Assistant ─────────────────────────────────────────────
        aq_keywords = ["aq assistant", "assistant", "chat", "ask", "message"]
        aq_hits = [kw for kw in aq_keywords if kw in page_text.lower()]
        input_count = await page.locator("input[type=text], textarea").count()
        has_aq = len(aq_hits) >= 1 or input_count >= 1
        findings["points"]["9_aq_assistant"] = {
            "pass": has_aq,
            "keywords_found": aq_hits,
            "input_fields": input_count,
            "detail": f"AQ keywords: {aq_hits}. Input fields: {input_count}",
        }
        p9 = findings["points"]["9_aq_assistant"]
        print(f"  -> Point 9 (aQ Assistant):       {'PASS' if p9['pass'] else 'FAIL'} inputs={input_count}")

        # ── Point 10: Header Controls ─────────────────────────────────────────
        header_keywords = ["day", "speed", "start", "pause", "resume", "1x", "10x", "50x", "100x"]
        header_hits = [kw for kw in header_keywords if kw in page_text.lower()]
        sim_day_match = re.search(r'day\s*\d+', page_text, re.IGNORECASE)
        has_header = len(header_hits) >= 3
        findings["points"]["10_header_controls"] = {
            "pass": has_header,
            "keywords_found": header_hits,
            "sim_day_visible": bool(sim_day_match),
            "sim_day_text": sim_day_match.group() if sim_day_match else None,
            "detail": f"Header keywords: {header_hits}. Sim day: {sim_day_match.group() if sim_day_match else 'not found'}",
        }
        p10 = findings["points"]["10_header_controls"]
        print(f"  -> Point 10 (Header Controls):   {'PASS' if p10['pass'] else 'FAIL'} keywords={header_hits}")

        # ── Wait 15 seconds + Screenshot #2 ──────────────────────────────────
        print("  -> Waiting 15s for simulation progress...")
        await asyncio.sleep(15)

        shot2 = str(SCREENSHOT_DIR / "shot_02_15s.png")
        try:
            await page.screenshot(path=shot2, full_page=False, timeout=8000)
            findings["screenshots"].append(shot2)
            print("  -> Screenshot #2 saved:", shot2)
        except Exception as e:
            findings["notes"].append(f"Screenshot #2 failed (non-fatal): {e}")
            print("  -> Screenshot #2 SKIPPED (timeout):", e)

        page_text_15s = await page.inner_text("body")
        pct_numbers_15s = re.findall(r'\b\d{1,3}%', page_text_15s)
        # Sim day may be formatted across lines, match digits after DAY
        sim_day_15s = re.search(r'DAY\D*(\d+)', page_text_15s) or re.search(r'day\s*(\d+)', page_text_15s, re.IGNORECASE)
        findings["notes"].append(
            f"At T=15s: sim_day={sim_day_15s.group() if sim_day_15s else 'not found'}, pcts={pct_numbers_15s[:8]}"
        )
        print(f"      Sim day at T=15s: {sim_day_15s.group() if sim_day_15s else '?'}")

        # ── Point 8 (re-evaluated at T=15s when recommendations populate) ────
        maint_keywords = ["maintenance", "rul", "remaining", "schedule", "priority", "recommended", "clean", "replace", "inspect"]
        maint_hits_15s = [kw for kw in maint_keywords if kw in page_text_15s.lower()]
        # Panel exists if we see either a recommendation OR "no actions required"
        panel_present = "recommended actions" in page_text_15s.lower() or "no actions required" in page_text_15s.lower()
        has_maint = panel_present or len(maint_hits_15s) >= 2
        findings["points"]["8_maintenance_panel"] = {
            "pass": has_maint,
            "keywords_found": maint_hits_15s,
            "panel_present": panel_present,
            "detail": f"Panel present: {panel_present}. Keywords at T=15s: {maint_hits_15s}",
        }
        p8 = findings["points"]["8_maintenance_panel"]
        print(f"  -> Point 8 (Maintenance):        {'PASS' if p8['pass'] else 'FAIL'} panel={panel_present} keywords={maint_hits_15s[:4]}")

        # ── Try clicking a 3D component ───────────────────────────────────────
        try:
            canvas = page.locator("canvas").first
            box = await canvas.bounding_box()
            if box:
                await page.mouse.click(box["x"] + box["width"] * 0.35, box["y"] + box["height"] * 0.5)
                await asyncio.sleep(1)
                findings["notes"].append("Clicked 3D canvas (35% x, 50% y) — no error thrown")
                print("      Clicked 3D canvas — no crash")
        except Exception as e:
            findings["notes"].append(f"3D click attempt: {e}")

        # ── Wait 15 more seconds + Screenshot #3 ─────────────────────────────
        print("  -> Waiting another 15s...")
        await asyncio.sleep(15)

        shot3 = str(SCREENSHOT_DIR / "shot_03_30s.png")
        try:
            await page.screenshot(path=shot3, full_page=False, timeout=8000)
            findings["screenshots"].append(shot3)
            print("  -> Screenshot #3 saved:", shot3)
        except Exception as e:
            findings["notes"].append(f"Screenshot #3 failed (non-fatal): {e}")
            print("  -> Screenshot #3 SKIPPED (timeout):", e)

        page_text_30s = await page.inner_text("body")
        sim_day_30s = re.search(r'day\s*(\d+)', page_text_30s, re.IGNORECASE)
        findings["notes"].append(
            f"At T=30s: sim_day={sim_day_30s.group() if sim_day_30s else 'not found'}"
        )
        print(f"      Sim day at T=30s: {sim_day_30s.group() if sim_day_30s else '?'}")

        # ── Point 11: Console & Network Errors ───────────────────────────────
        # Exclude errors caused by our own font-blocking route (self-inflicted)
        SELF_CAUSED = ["fonts.googleapis.com", "fonts.gstatic.com"]
        real_js_errors = [
            m for m in console_msgs
            if "[ERROR]" in m and not any(sc in m for sc in SELF_CAUSED)
        ]
        real_failed_reqs = [
            r for r in failed_reqs
            if not any(sc in r for sc in SELF_CAUSED)
        ]
        has_no_critical_errors = len(real_js_errors) == 0 and len(real_failed_reqs) == 0
        findings["points"]["11_console_errors"] = {
            "pass": has_no_critical_errors,
            "js_errors": real_js_errors,
            "js_errors_self_caused": [m for m in console_msgs if "[ERROR]" in m and any(sc in m for sc in SELF_CAUSED)],
            "failed_requests": real_failed_reqs,
            "warnings_count": len(findings["console_warnings"]),
            "detail": f"Real JS errors: {len(real_js_errors)}. Real failed reqs: {len(real_failed_reqs)}. (Font errors from test routing excluded.)",
        }
        p11 = findings["points"]["11_console_errors"]
        print(f"  -> Point 11 (Console/Network):   {'PASS' if p11['pass'] else 'FAIL'} "
              f"real_errors={len(real_js_errors)} real_failed_reqs={len(real_failed_reqs)}")
        for e in real_js_errors[:5]:
            print(f"      [ERROR] {e[:140]}")
        for r in real_failed_reqs[:5]:
            print(f"      [FAIL REQ] {r[:140]}")

        await browser.close()

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(findings: dict) -> str:
    ts = findings["timestamp"]
    pts = findings["points"]
    api = findings["backend_api"]

    pass_count = sum(1 for p in pts.values() if p.get("pass"))
    total = len(pts)

    lines = [
        "# E2E Test Report — Aqueduct PdM Dashboard",
        f"\n**Run at:** {ts}  ",
        f"**Score:** {pass_count}/{total} points passing\n",
        "---\n",
        "## Backend API Health\n",
        "| Endpoint | Status | Data Sample |",
        "|---|---|---|",
    ]
    for ep, res in api.items():
        status = "OK" if res["ok"] else "FAIL"
        sample = str(res["data"])[:80] if res["ok"] else res["data"]
        lines.append(f"| `{ep}` | {status} | `{sample}` |")

    lines += [
        "\n---\n",
        "## E2E Dashboard Evaluation (11 Points)\n",
        "| # | Check | Verdict | Detail |",
        "|---|---|---|---|",
    ]

    checks = [
        ("1",  "Initial Load",                   "1_initial_load"),
        ("2",  "WebSocket Connection",            "2_websocket"),
        ("3",  "Sensor Cards Live Updates",       "3_sensor_cards"),
        ("4",  "Health Panel (component %)",      "4_health_panel"),
        ("5",  "3D AHU Model Rendering",          "5_3d_model"),
        ("6",  "Time Series Charts",              "6_time_series_charts"),
        ("7",  "Alerts Panel",                    "7_alerts_panel"),
        ("8",  "Maintenance Panel / RUL",         "8_maintenance_panel"),
        ("9",  "aQ Assistant Chat",               "9_aq_assistant"),
        ("10", "Header: Sim Day & Speed Controls","10_header_controls"),
        ("11", "Console & Network Errors",        "11_console_errors"),
    ]
    for num, name, key in checks:
        p = pts.get(key, {})
        v = "PASS" if p.get("pass") else "FAIL"
        detail = p.get("detail", "—")[:120]
        lines.append(f"| {num} | {name} | **{v}** | {detail} |")

    lines += ["\n---\n", "## Console Errors\n"]
    if findings["console_errors"]:
        for e in findings["console_errors"]:
            lines.append(f"- `{e[:200]}`")
    else:
        lines.append("_No JS errors detected_")

    lines += ["\n## Failed Network Requests\n"]
    if findings["failed_requests"]:
        for r in findings["failed_requests"]:
            lines.append(f"- `{r[:200]}`")
    else:
        lines.append("_No failed requests_")

    lines += ["\n## Console Warnings\n"]
    warns = findings.get("console_warnings", [])
    if warns:
        for w in warns[:10]:
            lines.append(f"- `{w[:200]}`")
    else:
        lines.append("_No warnings_")

    lines += ["\n## Notes & Simulation Progress\n"]
    for n in findings.get("notes", []):
        lines.append(f"- {n}")

    lines += ["\n## Screenshots\n"]
    for s in findings.get("screenshots", []):
        lines.append(f"- [{Path(s).name}](file://{s})")

    lines += [
        "\n---\n",
        "## Overall Assessment\n",
        f"**{pass_count}/{total} checks passed.**",
    ]
    if pass_count == total:
        lines.append("\nDashboard is fully functional and submission-ready.")
    elif pass_count >= 9:
        lines.append("\nDashboard is mostly functional. Minor issues noted above.")
    elif pass_count >= 7:
        lines.append("\nDashboard has some gaps — review FAILs before submission.")
    else:
        lines.append("\nSignificant issues found — fix before submission.")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Aqueduct PdM E2E Test — playwright-python ===\n")

    print("(1) Checking servers are up...")
    ok_be, status = fetch_json(BACKEND_URL + "/api/simulation/status")
    print(f"    Backend  {BACKEND_URL}: {'OK' if ok_be else 'FAIL'}")
    if ok_be:
        print(f"    Sim status: {status}")
    else:
        print("    ERROR: Backend is not running! Start it first:")
        print("      cd backend && python3 -m uvicorn main:app --port 8000")
        sys.exit(1)

    print("\n(2) Running browser-based E2E checks...")
    findings = asyncio.run(run_e2e())

    print("\n(3) Generating report...")
    report = generate_report(findings)
    REPORT_PATH.write_text(report)
    print(f"    Report saved -> {REPORT_PATH}")

    print("\n(4) Summary:")
    pts = findings["points"]
    pass_count = sum(1 for p in pts.values() if p.get("pass"))
    print(f"    {pass_count}/{len(pts)} points PASS")
    print(f"    Console errors: {len(findings['console_errors'])}")
    print(f"    Failed requests: {len(findings['failed_requests'])}")
    print(f"\n    Screenshots in: {SCREENSHOT_DIR}/")
    print(f"    Full report:    {REPORT_PATH}\n")
