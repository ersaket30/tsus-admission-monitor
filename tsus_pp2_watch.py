#!/usr/bin/env python3
"""
TSUS Hyderabad 2027-28 PP2 admissions watcher.

Checks every 5 minutes:
  1) https://tsushyderabad.com for a 2027-28 admissions banner/link
  2) The linked ShriPortal form for Academic Year 2027-28 and
     Board option "Badhte Kadam (PP2)" (or a close text variation).

Sends one Gmail alert when BOTH conditions are verified. It will not submit
an application or enter personal information.

Gmail setup:
  - Use a Google App Password (requires 2-Step Verification), NOT your
    normal Gmail password or a session/token copied from your browser.
  - Put it in the GMAIL_APP_PASSWORD environment variable.
  - Set GMAIL_SENDER and GMAIL_RECIPIENT to your Gmail address(es).

Install:
  python3 -m venv .venv
  source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
  pip install playwright
  playwright install chromium

Run:
  export GMAIL_SENDER="you@gmail.com"
  export GMAIL_RECIPIENT="you@gmail.com"
  export GMAIL_APP_PASSWORD="your-16-character-app-password"
  python tsus_pp2_watch.py

Optional:
  CHECK_INTERVAL_SECONDS=300 python tsus_pp2_watch.py
  HEADLESS=1 python tsus_pp2_watch.py   # default; use 0 to watch browser
"""

import os
import re
import ssl
import time
import smtplib
import logging
from email.message import EmailMessage
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

HOME_URL = "https://tsushyderabad.com"
KNOWN_PORTAL_URL = (
    "https://tsush.shriportal.com/OnlineReg/Admission.aspx"
    "?key=30005043C5114C4810C9"
)
INTERVAL = max(60, int(os.getenv("CHECK_INTERVAL_SECONDS", "300")))
HEADLESS = os.getenv("HEADLESS", "1").strip().lower() not in ("0", "false", "no")
STATE_FILE = os.getenv("STATE_FILE", "tsus_pp2_alert_sent.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

YEAR_RE = re.compile(r"2027\s*[-–/]\s*28", re.I)
PP2_RE = re.compile(r"badhte\s*kadam\s*\(?\s*pp\s*[- ]?2\s*\)?", re.I)


def send_gmail_alert(subject: str, body: str) -> None:
    sender = os.getenv("GMAIL_SENDER")
    recipient = os.getenv("GMAIL_RECIPIENT")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all((sender, recipient, app_password)):
        raise RuntimeError(
            "Set GMAIL_SENDER, GMAIL_RECIPIENT and GMAIL_APP_PASSWORD "
            "environment variables before running."
        )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(sender, app_password.replace(" ", ""))
        smtp.send_message(msg)


def visible_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def find_admission_link(page) -> str | None:
    """Prefer a homepage link whose visible text or URL indicates 2027-28 admissions."""
    links = page.locator("a")
    count = min(links.count(), 500)
    candidates = []

    for i in range(count):
        link = links.nth(i)
        try:
            href = link.get_attribute("href")
            if not href:
                continue
            label = (link.inner_text(timeout=700) or "").strip()
            aria = link.get_attribute("aria-label") or ""
            title = link.get_attribute("title") or ""
            combined = " ".join((label, aria, title, href))
            if "admission" in combined.lower() and YEAR_RE.search(combined):
                candidates.append(urljoin(HOME_URL, href))
        except Exception:
            continue

    # If the homepage banner is not exposed as a conventional link, the known
    # portal URL remains a fallback for checking the actual application form.
    return candidates[0] if candidates else None


def click_information_checkbox_and_continue(page) -> None:
    """
    Try to acknowledge the portal's information checkbox and proceed.
    Does not fill personal data or submit the application.
    """
    # Check any visible checkbox on the initial information page.
    checkbox = page.locator('input[type="checkbox"]:visible')
    try:
        for i in range(min(checkbox.count(), 5)):
            item = checkbox.nth(i)
            if not item.is_checked():
                item.check(timeout=2500)
    except Exception:
        pass

    # Click a likely continue/agree/next control, never a final submit button.
    patterns = re.compile(r"^(continue|proceed|next|i agree|agree)$", re.I)
    for locator in (
        page.get_by_role("button", name=patterns),
        page.get_by_role("link", name=patterns),
        page.locator('input[type="button"], input[type="submit"]'),
    ):
        try:
            n = min(locator.count(), 10)
            for i in range(n):
                item = locator.nth(i)
                label = (
                    item.get_attribute("value")
                    or item.inner_text(timeout=500)
                    or item.get_attribute("aria-label")
                    or ""
                ).strip()
                if patterns.match(label):
                    item.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    return
        except Exception:
            continue


def board_dropdown_has_pp2(page) -> bool:
    """Inspect native select elements and custom dropdown text/options."""
    # Native HTML select controls
    selects = page.locator("select")
    try:
        for i in range(min(selects.count(), 30)):
            select = selects.nth(i)
            try:
                options = select.locator("option").all_inner_texts()
                joined = " | ".join(options)
                if PP2_RE.search(joined):
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Some portals render dropdown choices in custom listboxes.
    try:
        page.get_by_text(PP2_RE, exact=False).first.wait_for(state="visible", timeout=1800)
        return True
    except Exception:
        return False


def check_once() -> tuple[bool, str]:
    evidence = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            ignore_https_errors=False,
        )
        page = context.new_page()
        try:
            logging.info("Checking school homepage: %s", HOME_URL)
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            home_text = visible_text(page)

            banner_found = bool(YEAR_RE.search(home_text) and
                                re.search(r"admission", home_text, re.I))
            banner_link = find_admission_link(page)
            if banner_found:
                evidence.append("Homepage text includes an admissions reference and 2027-28.")
            if banner_link:
                evidence.append(f"2027-28 admissions link found: {banner_link}")

            # Use the newly detected banner destination if available; otherwise
            # inspect the known portal URL supplied by the user.
            portal_url = banner_link or KNOWN_PORTAL_URL
            logging.info("Checking application portal: %s", portal_url)
            portal = context.new_page()
            portal.goto(portal_url, wait_until="domcontentloaded", timeout=45000)
            portal.wait_for_timeout(2000)
            click_information_checkbox_and_continue(portal)
            portal.wait_for_timeout(1500)

            portal_text = visible_text(portal)
            academic_year_found = bool(YEAR_RE.search(portal_text))
            pp2_found = board_dropdown_has_pp2(portal)

            if academic_year_found:
                evidence.append("Application portal shows Academic Year 2027-28.")
            if pp2_found:
                evidence.append('Board dropdown contains "Badhte Kadam (PP2)".')

            # Require both actual form conditions. Homepage banner is useful
            # corroboration, but the portal dropdown is the decisive signal.
            ready = academic_year_found and pp2_found
            if ready:
                evidence.append(f"Application portal checked: {portal.url}")
            else:
                logging.info(
                    "Not ready: academic_year=%s, PP2_option=%s, banner=%s",
                    academic_year_found, pp2_found, banner_found
                )
            return ready, "\n".join(evidence) if evidence else (
                "The portal was reachable, but the 2027-28 PP2 admission "
                "conditions could not both be verified."
            )
        finally:
            context.close()
            browser.close()


def main() -> None:
    logging.info("TSUS PP2 watcher started; interval=%s seconds", INTERVAL)
    while True:
        try:
            ready, details = check_once()
            if ready:
                if os.path.exists(STATE_FILE):
                    logging.info("PP2 condition is still met; alert already sent.")
                else:
                    body = (
                        "TSUS Hyderabad 2027-28 PP2 admissions appear to be available.\n\n"
                        "Verified conditions:\n"
                        f"{details}\n\n"
                        "Open the application portal:\n"
                        f"{KNOWN_PORTAL_URL}\n\n"
                        "Please verify the details yourself before submitting an application. "
                        "This script does not submit forms or enter personal information."
                    )
                    send_gmail_alert(
                        "TSUS Hyderabad: 2027-28 PP2 admissions may be open",
                        body,
                    )
                    with open(STATE_FILE, "w", encoding="utf-8") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
                    logging.info("Gmail alert sent.")
            else:
                logging.info("No verified PP2 opening. No email sent.")
        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            return
        except Exception:
            logging.exception("Check failed; will retry at the next interval.")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
