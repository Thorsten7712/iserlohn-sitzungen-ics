#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build-Skript: Holt den Gesamt-ICS der Stadt Iserlohn und erzeugt je Gremium
einen eigenen abonnierbaren Kalender (ICS). Ausschluss: "ENTFÄLLT" im SUMMARY
oder STATUS:CANCELLED. RRULE/Serien bleiben erhalten, da VEVENT-Blöcke
unverändert kopiert werden.

Designziele:
- Keine externen Dependencies (nur Standardbibliothek)
- RFC5545-konformes "line unfolding"
- Robust gegen Encoding/Continuation-Lines
- Idempotent: wiederholte Läufe sind ok
"""

import os
import re
import sys
import html
import unicodedata
from datetime import datetime, timezone
from urllib.request import urlopen, Request

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
OUT_DIR = os.path.join(DOCS_DIR, "calendars")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "committees.txt")

SOURCE_URL = "https://www.iserlohn.sitzung-online.de/public/ics/SiKalAbo.ics"
USER_AGENT = "Mozilla/5.0 (compatible; Iserlohn-ICS-Split/1.0; +https://github.com/)"

def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)

def read_committees(path):
    committees = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            committees.append(s)
    return committees

def slugify(name):
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_str = re.sub(r"[^A-Za-z0-9]+", "-", ascii_str)
    ascii_str = re.sub(r"-{2,}", "-", ascii_str).strip("-").lower()
    return ascii_str or "kalender"

def fetch_ics(url):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    # Versuche UTF-8, fallback latin1
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin1")
    return text

def unfold_lines(text):
    """
    ICS "line folding": Fortsetzungszeilen beginnen mit SPACE/TAB.
    Wir verbinden sie mit der vorherigen Zeile.
    """
    raw_lines = text.splitlines()
    if not raw_lines:
        return []
    out = [raw_lines[0]]
    for line in raw_lines[1:]:
        if line.startswith(" ") or line.startswith("\t"):
            out[-1] += line[1:]  # ohne führendes Leerzeichen
        else:
            out.append(line)
    return out

def split_header_and_events(lines):
    """
    Trenne Kalender-Header (bis vor dem ersten BEGIN:VEVENT) und
    alle VEVENT-Blöcke (inkl. BEGIN/END).
    """
    header = []
    events = []
    in_event = False
    current = []
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            in_event = True
            current = [ln]
            continue
        if in_event:
            current.append(ln)
            if ln.startswith("END:VEVENT"):
                events.append(current)
                in_event = False
                current = []
        else:
            header.append(ln)
    return header, events

def read_prop(block, key):
    """
    Extrahiere Property-Wert aus einem VEVENT-Block, z.B. SUMMARY, STATUS.
    Achtung: Parameter wie SUMMARY;LANGUAGE=de:... -> wir finden die Zeile mit key:
    """
    key_up = key.upper()
    for ln in block:
        # Property beginnt mit z.B. "SUMMARY" oder "SUMMARY;"
        if ln.upper().startswith(key_up + ":") or ln.upper().startswith(key_up + ";"):
            # Split am ersten ":" (Parameter können mit Semikolons hängen)
            parts = ln.split(":", 1)
            if len(parts) == 2:
                return parts[1]
    return ""

def contains_cancel_marker(summary, status):
    if status.strip().upper() == "CANCELLED":
        return True
    if "ENTFÄLLT" in summary.upper() or "ENTFAELLT" in summary.upper():
        return True
    # optional: weitere Marker
    return False

def event_matches_committee(block, committee):
    summary = read_prop(block, "SUMMARY")
    if not summary:
        return False
    return committee.lower() in summary.lower()

def build_calendar_text(header_lines, event_blocks, calname):
    """
    Erzeuge vollständige VCALENDAR mit angepasstem X-WR-CALNAME.
    Wir übernehmen weitgehend den Original-Header, ersetzen/ergänzen aber CALNAME/PRODID.
    """
    # Finde Anfang und Ende des VCALENDAR
    # Wir setzen konservativ neu zusammen:
    out = []
    out.append("BEGIN:VCALENDAR")
    # PRODID
    out.append("PRODID:-//Iserlohn ICS Split//github.com//EN")
    # VERSION (falls im Header nicht vorhanden)
    out.append("VERSION:2.0")
    # CALSCALE
    out.append("CALSCALE:GREGORIAN")
    # CALNAME
    out.append(f"X-WR-CALNAME:{calname}")
    # Zeitzone(n) aus dem Originalheader übernehmen
    tz_lines = [ln for ln in header_lines if ln.startswith("BEGIN:VTIMEZONE") or ln.startswith("END:VTIMEZONE") or ln.startswith("TZID:") or ln.startswith("TZOFFSET") or ln.startswith("STANDARD") or ln.startswith("DAYLIGHT")]
    out.extend(tz_lines)
    # Events
    for ev in event_blocks:
        out.extend(ev)
    out.append("END:VCALENDAR")
    # Sorge für CRLF gemäß iCalendar
    return "\r\n".join(out) + "\r\n"

def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def generate_index(committees, files_by_committee):
    lines = []
    lines.append("<!doctype html>")
    lines.append("<html lang='de'><head><meta charset='utf-8'>")
    lines.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    lines.append("<title>Iserlohn – Gefilterte Sitzungs-Kalender</title>")
    lines.append("<style>body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:2rem;max-width:900px}code{background:#f6f6f6;padding:.1rem .3rem;border-radius:.25rem}li{margin:.4rem 0}</style>")
    lines.append("</head><body>")
    lines.append("<h1>Gefilterte Kalender nach Gremien</h1>")
    lines.append("<p>Quelle: öffentlicher Gesamt-Kalender der Stadt Iserlohn. Aktualisierung täglich 05:00 Uhr (Europe/Berlin).</p>")
    lines.append("<ul>")
    for c in committees:
        fpath = files_by_committee.get(c)
        if fpath:
            rel = os.path.relpath(fpath, DOCS_DIR).replace(os.sep, "/")
            lines.append(f"<li><strong>{html.escape(c)}</strong><br><a href='{rel}'>ICS abonnieren</a> <small>(Rechtsklick &raquo; Link kopieren)</small></li>")
    lines.append("</ul>")
    lines.append("<hr>")
    lines.append("<p><em>Stand:</em> " + datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds") + "</p>")
    lines.append("</body></html>")
    return "\n".join(lines)

def main():
    ensure_dirs()
    committees = read_committees(CONFIG_FILE)
    # 1) ICS holen
    try:
        ics_text = fetch_ics(SOURCE_URL)
    except Exception as e:
        print(f"[ERROR] Konnte ICS nicht laden: {e}", file=sys.stderr)
        sys.exit(1)

    # 2) Unfold + split
    lines = unfold_lines(ics_text)
    header, events = split_header_and_events(lines)

    # 3) Filtere cancel/ENTFÄLLT
    usable_events = []
    for ev in events:
        summary = read_prop(ev, "SUMMARY")
        status = read_prop(ev, "STATUS")
        if contains_cancel_marker(summary, status):
            continue
        usable_events.append(ev)

    # 4) Für jedes Gremium: matching Events sammeln
    files_by_committee = {}
    for committee in committees:
        matched = [ev for ev in usable_events if event_matches_committee(ev, committee)]
        if not matched:
            # Wenn kein Event passt, erzeugen wir (vorerst) keinen leeren Kalender
            continue
        calname = f"Sitzungen – {committee}"
        out_text = build_calendar_text(header, matched, calname)
        slug = slugify(committee)
        out_path = os.path.join(OUT_DIR, f"{slug}.ics")
        write_text(out_path, out_text)
        files_by_committee[committee] = out_path

    # 5) Master-Kopie ALLER nicht-cancelled Events (optional, nützlich zum Debuggen)
    if usable_events:
        all_text = build_calendar_text(header, usable_events, "Sitzungen – Alle (ohne ENTFÄLLT)")
        write_text(os.path.join(OUT_DIR, "alle-ohne-entfaellt.ics"), all_text)

    # 6) Index-Seite
    index_html = generate_index(committees, files_by_committee)
    write_text(os.path.join(DOCS_DIR, "index.html"), index_html)

    print(f"[OK] Erzeugt {len(files_by_committee)} Gremien-Kalender. Gesamt-Events (ohne ENTFÄLLT/CANCELLED): {len(usable_events)}")

if __name__ == "__main__":
    main()
