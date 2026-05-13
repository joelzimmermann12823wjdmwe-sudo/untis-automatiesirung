"""
Untis Stundenplan-Überwachung (Playwright + OIDC)
─────────────────────────────────────────────────
Überwacht deinen WebUntis-Stundenplan auf Änderungen.
Verwendet Playwright zur IServ-SSO-Anmeldung (OIDC)
und fängt die REST-API-Antworten während des Seitenladens ab.
"""

import datetime
import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ─── Konfiguration ────────────────────────────────────────────────────────────

load_dotenv()
CACHE_FILE = Path(os.getenv("CACHE_FILE", "timetable_cache.json"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "900"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

WEBUNTIS_SERVER = os.getenv("WEBUNTIS_SERVER", "obs-winsen.webuntis.com")
WEBUNTIS_SCHOOL = os.getenv("WEBUNTIS_SCHOOL", "obs-winsen")
WEBUNTIS_USER = os.getenv("WEBUNTIS_USER", "")
ISERV_PASSWORD = os.getenv("ISERV_PASSWORD", "")
ISERV_SERVER = os.getenv("ISERV_SERVER", "schuleimallertal.de")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

BASE_URL = f"https://{WEBUNTIS_SERVER}/WebUntis"

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("untis_monitor")

# ─── Datenabruf via Playwright (API-Interception) ──────────────────────────


def _pos_name(pos) -> str:
    """Extrahiert den anzeigbaren Namen aus einer Position (oder None)."""
    if pos is None:
        return ""
    if isinstance(pos, list) and len(pos) > 0:
        pos = pos[0]
    if isinstance(pos, dict):
        current = pos.get("current") or pos
        if isinstance(current, dict):
            return current.get("shortName") or current.get("longName") or ""
    return ""


def _pos_name_removed(pos) -> str:
    """Extrahiert den alten/entfernten Namen aus einer Position."""
    if pos is None:
        return ""
    if isinstance(pos, list) and len(pos) > 0:
        removed = pos[0].get("removed")
        if removed:
            return removed.get("shortName") or removed.get("longName") or ""
    return ""


def _parse_entries_response(data: dict) -> dict[int, dict[str, Any]]:
    """Wandelt timetable/entries JSON in Fingerprints um."""
    fingerprints: dict[int, dict[str, Any]] = {}
    for day in data.get("days", []):
        date_str = day.get("date", "")
        for entry in day.get("gridEntries", []):
            ids = entry.get("ids", [])
            pid = ids[0] if ids else hash(str(entry))
            dur = entry.get("duration", {})
            start_s = dur.get("start", "")
            end_s = dur.get("end", "")
            pos1 = entry.get("position1")
            pos2 = entry.get("position2")
            pos3 = entry.get("position3")
            fingerprints[pid] = {
                "id": pid,
                "date": date_str,
                "start": start_s[11:16] if len(start_s) > 11 else start_s,
                "end": end_s[11:16] if len(end_s) > 11 else end_s,
                "subjects": [_pos_name(pos2)] if _pos_name(pos2) else [],
                "teachers": [_pos_name(pos1)] if _pos_name(pos1) else [],
                "rooms": [_pos_name(pos3)] if _pos_name(pos3) else [],
                "old_teacher": _pos_name_removed(pos1),
                "old_subject": _pos_name_removed(pos2),
                "old_room": _pos_name_removed(pos3),
                "code": entry.get("status", ""),
                "type": entry.get("type", ""),
            }
    return fingerprints


def fetch_timetable() -> dict[int, dict[str, Any]]:
    """Playwright: Login via OIDC -> Timetable-Seite laden -> API abfangen -> Daten zurückgeben."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    friday = monday + datetime.timedelta(days=4)

    log.info(f"Hole Stundenplan {monday} bis {friday} via Playwright...")

    timetable_data: dict[int, dict[str, Any]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = ctx.new_page()

        # API-Response abfangen
        def on_response(response):
            if "timetable/entries?" in response.url and response.status == 200:
                try:
                    data = response.json()
                    timetable_data.update(_parse_entries_response(data))
                except Exception:
                    pass

        page.on("response", on_response)

        # OIDC-Login
        page.goto(f"{BASE_URL}/oidc/login?school={WEBUNTIS_SCHOOL}", wait_until="networkidle")
        log.info(f"Weitergeleitet zu: {page.url[:80]}")
        page.wait_for_timeout(1000)

        page.fill("input[name='_username']", WEBUNTIS_USER)
        page.fill("input[name='_password']", ISERV_PASSWORD)
        page.click("button:has-text('Anmelden')")

        try:
            page.wait_for_selector("form.authorization-form", timeout=10000)
            page.click("button[name='authorize_form[actions][accept]']")
        except Exception:
            pass

        try:
            page.wait_for_url(f"**/{WEBUNTIS_SERVER}/**", timeout=30000)
        except Exception:
            pass

        # SPA initialisieren und zur Timetable-Seite navigieren
        page.goto(f"{BASE_URL}/?school={WEBUNTIS_SCHOOL}", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Auf "Stundenplan" klicken (lazy-load des Timetable-Moduls)
        try:
            link = page.query_selector("text=Stundenplan")
            if link:
                link.click()
                page.wait_for_timeout(5000)
        except Exception:
            pass

        # Warten, bis die API-Daten abgefangen wurden
        page.wait_for_timeout(5000)

        # Falls kein Klick möglich, direkte Navigation
        if not timetable_data:
            log.info("Direkte Navigation zur Timetable-Seite...")
            page.goto(f"https://{WEBUNTIS_SERVER}/timetable/my-student?date={monday.isoformat()}", wait_until="networkidle")
            page.wait_for_timeout(8000)

        browser.close()

    log.info(f"  {len(timetable_data)} Perioden empfangen")
    return timetable_data


# ─── Änderungserkennung ────────────────────────────────────────────────────────


def _fmt_time(dt_str: str) -> str:
    return dt_str if dt_str else "??:??"


def _diff_sets(old: list[str], new: list[str]) -> bool:
    return bool(old) and bool(new) and set(old) != set(new)


def _detect_changes(
    old_cache: dict[int, dict[str, Any]],
    new_data: dict[int, dict[str, Any]],
) -> list[str]:
    changes: list[str] = []
    all_ids = set(old_cache.keys()) | set(new_data.keys())

    for pid in all_ids:
        old = old_cache.get(pid)
        new = new_data.get(pid)

        if old is None:
            subject = ", ".join(new.get("subjects", ["?"]))
            teacher = ", ".join(new.get("teachers", [""]))
            room = ", ".join(new.get("rooms", [""]))
            date_str = new.get("date", "?")
            time_str = f"{_fmt_time(new.get('start'))}–{_fmt_time(new.get('end'))}"
            code = new.get("code")
            if code == "cancelled":
                changes.append(f"AUSFALL: {subject} am {date_str} {time_str} (L: {teacher}, R: {room})")
            elif code == "irregular":
                changes.append(f"NEUE VERTRETUNG: {subject} am {date_str} {time_str} (L: {teacher}, R: {room})")
            else:
                changes.append(f"NEUE STUNDE: {subject} am {date_str} {time_str} (L: {teacher}, R: {room})")
            continue

        if new is None:
            subject = ", ".join(old.get("subjects", ["?"]))
            date_str = old.get("date", "?")
            time_str = f"{_fmt_time(old.get('start'))}–{_fmt_time(old.get('end'))}"
            changes.append(f"ENTFERNT: {subject} am {date_str} {time_str}")
            continue

        date_str = old.get("date", "?")
        time_str = f"{_fmt_time(old.get('start'))}–{_fmt_time(old.get('end'))}"
        subj_old = ", ".join(old.get("subjects", []))
        subj_new = ", ".join(new.get("subjects", []))
        teach_old = ", ".join(old.get("teachers", []))
        teach_new = ", ".join(new.get("teachers", []))
        room_old = ", ".join(old.get("rooms", []))
        room_new = ", ".join(new.get("rooms", []))
        code_old = old.get("code")
        code_new = new.get("code")

        if code_new.upper() == "CANCELLED" and code_old.upper() != "CANCELLED":
            changes.append(f"AUSFALL: {subj_new} am {date_str} {time_str}")
        elif code_old.upper() == "CANCELLED" and code_new.upper() != "CANCELLED":
            changes.append(f"WIEDER EINGEPLANT: {subj_new} am {date_str} {time_str}")

        if _diff_sets(old.get("teachers", []), new.get("teachers", [])):
            changes.append(f"VERTRETUNG: {subj_new} am {date_str} {time_str} – L: {teach_old} -> {teach_new}")

        if _diff_sets(old.get("rooms", []), new.get("rooms", [])):
            changes.append(f"RAUMWECHSEL: {subj_new} am {date_str} {time_str} – R: {room_old} -> {room_new}")

        if _diff_sets(old.get("subjects", []), new.get("subjects", [])):
            changes.append(f"FACHWECHSEL: {subj_old} -> {subj_new} am {date_str} {time_str}")

        if old.get("start") != new.get("start") or old.get("end") != new.get("end"):
            changes.append(
                f"ZEITAENDERUNG: {subj_new} am {date_str} – "
                f"{_fmt_time(old.get('start'))}–{_fmt_time(old.get('end'))} -> "
                f"{_fmt_time(new.get('start'))}–{_fmt_time(new.get('end'))}"
            )

    return changes


# ─── Cache ─────────────────────────────────────────────────────────────────────


def load_cache() -> dict[int, dict[str, Any]]:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            log.info("Cache geladen (%d Eintraege)", len(data))
            return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("Cache ungueltig (%s), starte neu", e)
    return {}


def save_cache(data: dict[int, dict[str, Any]]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Cache gespeichert (%d Eintraege)", len(data))


# ─── Benachrichtigungen (ntfy.sh) ──────────────────────────────────────────────


def send_ntfy(changes: list[str]) -> None:
    if not NTFY_TOPIC:
        log.debug("ntfy nicht konfiguriert (NTFY_TOPIC fehlt)")
        return
    body = "\n".join(changes)
    payload = json.dumps({
        "topic": NTFY_TOPIC,
        "title": "📚 Untis Änderungen",
        "message": body,
        "priority": 4,
        "tags": ["mega", "school"],
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://ntfy.sh",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        log.info("ntfy-Benachrichtigung gesendet")
    except Exception as e:
        log.error("ntfy-Fehler: %s", e)


def build_message(changes: list[str]) -> str:
    return "\n".join(changes)


# ─── Hauptschleife ────────────────────────────────────────────────────────────


def run():
    missing = []
    if not WEBUNTIS_SERVER: missing.append("WEBUNTIS_SERVER")
    if not WEBUNTIS_SCHOOL: missing.append("WEBUNTIS_SCHOOL")
    if not WEBUNTIS_USER: missing.append("WEBUNTIS_USER")
    if not ISERV_PASSWORD: missing.append("ISERV_PASSWORD")
    if missing:
        log.error("Fehlende Umgebungsvariablen: %s", ", ".join(missing))
        sys.exit(1)

    log.info(
        "Monitor gestartet – Server: %s, Schule: %s, Nutzer: %s, IServ: %s",
        WEBUNTIS_SERVER, WEBUNTIS_SCHOOL, WEBUNTIS_USER, ISERV_SERVER,
    )
    log.info("Pruefintervall: %d Sekunden", POLL_INTERVAL)

    if not NTFY_TOPIC:
        log.warning("NTFY_TOPIC nicht gesetzt – keine Benachrichtigungen")

    cache = load_cache()
    first_run = not cache

    while True:
        try:
            new_data = fetch_timetable()

            if not new_data:
                log.warning("Keine Daten erhalten -> wiederhole")
                continue

            if first_run:
                log.info("Erster Lauf – Stundenplan als Referenz gespeichert")
                save_cache(new_data)
                cache = new_data
                first_run = False
            else:
                changes = _detect_changes(cache, new_data)
                if changes:
                    msg = build_message(changes)
                    log.info("Aenderungen erkannt!\n%s", msg)
                    send_ntfy(changes)
                    cache = new_data
                    save_cache(cache)
                else:
                    log.info("Keine Aenderungen")

        except Exception as e:
            log.exception("Fehler: %s", e)

        log.info(
            "Naechste Pruefung um %s",
            (datetime.datetime.now() + datetime.timedelta(seconds=POLL_INTERVAL))
            .strftime("%H:%M")
        )
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
