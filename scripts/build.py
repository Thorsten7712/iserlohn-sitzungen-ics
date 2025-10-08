#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build-Skript: Holt den Gesamt-ICS der Stadt Iserlohn und erzeugt je Gremium
einen eigenen abonnierbaren Kalender (ICS).

Änderungen ggü. vorher:
- ENTFÄLLT-Einträge bleiben erhalten (werden NICHT mehr gefiltert).
- STATUS:CANCELLED bleibt ausgeschlossen.
- Automatisches Aufräumen: nicht mehr konfigurierte Gremien-ICS werden gelöscht.

Designziele:
- Keine externen Dependencies (nur Standardbibliothek)
- RFC5545-konformes "line unfolding"
- VEVENT-Blöcke unverändert kopieren (RRULE etc. bleiben intakt)
- Idempotent
"""

import os
import re
import sys
import html
import unicodedata
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from typing import List, Dict

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
OUT_DIR = os.path.join(DOCS_DIR, "calendars")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "committees.txt")

SOURCE_URL = "https://www.iserlohn.sitzung-online.de/public/ics/SiKalAbo.ics"
USER_AGENT = "Mozilla/5.0 (compatible; Iserlohn-ICS-Split/1.1; +https://github.com/)"

def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)

def read_committees(path: str) -> List[str]:
    committees = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            committees.append(s)
    return committees

def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_str = re.sub(r"[^A-Za-z0-9]+", "-", ascii_str)
    ascii_str = re.sub(r"-{2,}", "-", ascii_str).strip("-").lower()
    return ascii_str or "kalender"

def fetch_ics(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin1")
    return text

def unfold_lines(text: str) -> List[str]:
    raw_lines = text.splitlines()
    if not raw_lines:
        return []
    out = [raw_lines[0]]
    for line in raw_lines[1:]:
        if line.startswith(" ") or line.startswith("\t"):
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def split_header_and_events(lines: List[str]):
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

def read_prop(block: List[str], key: str) -> str:
    key_up = key.upper()
    for ln in block:
        if ln.upper().startswith(key_up + ":") or ln.upper().startswith(key_up + ";"):
            parts = ln.split(":", 1)
            if len(parts) == 2:
                return parts[1]
    return ""

def is_cancelled(summary: str, status: str) -> bool:
    # NEU: ENTFÄLLT wird NICHT mehr als Storno behandelt.
    # Nur echte Cancel-Status fliegen raus.
    return status.strip().upper() == "CANCELLED"

def event_matches_committee(block: List[str], committee: str) -> bool:
    summary = read_prop(block, "SUMMARY")
    if not summary:
        return False
    return committee.lower() in summary.lower()

def build_calendar_text(header_lines: List[str], event_blocks: List[List[str]], calname: str) -> str:
    out = []
    out.append("BEGIN:VCALENDAR")
    out.append("PRODID:-//Iserlohn ICS Split//github.com//EN")
    out.append("VERSION:2.0")
    out.append("CALSCALE:GREGORIAN")
    out.append(f"X-WR-CALNAME:{calname}")
    # Zeitzonen-Blöcke aus dem Original übernehmen (einfach/redundant, aber sicher)
    keep_prefixes = ("BEGIN:VTIMEZONE", "END:VTIMEZONE", "TZID:", "TZOFFSET", "STANDARD", "DAYLIGHT")
    tz_lines = [ln for ln in header_lines if ln.startswith(keep_prefixes)]
    out.extend(tz_lines)
    for ev in event_blocks:
        out.extend(ev)
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"

def write_text(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def generate_index(committees: List[str], files_by_committee: Dict[str, str]) -> str:
    lines = []
    lines.append("<!doctype html>")
    lines.append("<html lang='de'><head><meta charset='utf-8'>")
    lines.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    lines.append("<title>Iserlohn – Gefilterte Sitzungs-Kalender</title>")
    lines.append("<style>body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:2rem;max-width:900px}code{background:#f6f6f6;padding:.1rem .3rem;border-radius:.25rem}li{margin:.4rem 0}</style>")
    lines.append("</head><body>")
    lines.append("<h1>Gefilterte Kalender nach Gremien</h1>")
    lines.append("<p>Quelle: öffentlicher Gesamt-Kalender der Stadt Iserlohn. Aktualisierung täglich 06:00 Uhr (Europe/Berlin).</p>")
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

def cleanup_orphans(expected_files: List[str]):
    """
    Löscht .ics-Dateien in OUT_DIR, die NICHT in expected_files stehen.
    Schutzgeländer:
      - löscht nur innerhalb von OUT_DIR
      - löscht nur .ics
    """
    expected_basenames = {os.path.basename(p) for p in expected_files}
    for root, _, files in os.walk(OUT_DIR):
        for fn in files:
            if not fn.lower().endswith(".ics"):
                continue
            if fn not in expected_basenames:
                full = os.path.join(root, fn)
                try:
                    os.remove(full)
                    print(f"[CLEANUP] Entfernt: {os.path.relpath(full, OUT_DIR)}")
                except Exception as e:
                    print(f"[WARN] Konnte {full} nicht löschen: {e}", file=sys.stderr)

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

    # 3) Filter: nur echte Cancellations raus
    usable_events = []
    for ev in events:
        summary = read_prop(ev, "SUMMARY")
        status  = read_prop(ev, "STATUS")
        if is_cancelled(summary, status):
            continue
        usable_events.append(ev)

    # 4) Gremien erzeugen
    files_by_committee: Dict[str, str] = {}
    expected_files: List[str] = []
    for committee in committees:
        matched = [ev for ev in usable_events if event_matches_committee(ev, committee)]
        if not matched:
            # Keine Datei erzeugen, wenn es gar keine Treffer gibt
            continue
        calname = f"Sitzungen – {committee}"
        out_text = build_calendar_text(header, matched, calname)
        slug = slugify(committee)
        out_path = os.path.join(OUT_DIR, f"{slug}.ics")
        write_text(out_path, out_text)
        files_by_committee[committee] = out_path
        expected_files.append(out_path)

    # 5) (Optional) Master-Kalender aller NICHT-CANCELLED Events – ENTFÄLLT ist enthalten
    if usable_events:
        all_text = build_calendar_text(header, usable_events, "Sitzungen – Alle (inkl. ENTFÄLLT, exkl. CANCELLED)")
        master_path = os.path.join(OUT_DIR, "alle.ics")
        write_text(master_path, all_text)
        expected_files.append(master_path)

    # 6) Index-Seite
    index_html = generate_index(committees, files_by_committee)
    write_text(os.path.join(DOCS_DIR, "index.html"), index_html)

    # 7) Aufräumen: alles entfernen, was nicht erwartet ist
    cleanup_orphans(expected_files)

    print(f"[OK] Erzeugt {len(files_by_committee)} Gremien-Kalender. Gesamt-Events (inkl. ENTFÄLLT, exkl. CANCELLED): {len(usable_events)}")

if __name__ == "__main__":
    main()
