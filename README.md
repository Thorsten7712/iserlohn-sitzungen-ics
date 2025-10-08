# Iserlohn – Gefilterte Sitzungs-Kalender (ICS)

Dieses Repository spaltet den **öffentlichen Sammel-Kalender** der Stadt Iserlohn in **einzelne abonnierbare Kalender** pro Gremium auf.  
Quelle: `https://www.iserlohn.sitzung-online.de/public/ics/SiKalAbo.ics`

- **Ausschlüsse:**  
  - `STATUS:CANCELLED`  
  - `SUMMARY` enthält „ENTFÄLLT“ (bzw. „ENTFAELLT“)  
- **Serien/Terminreihen bleiben erhalten**, da die VEVENT-Blöcke unverändert kopiert werden.
- **Aktualisierung:** Täglich 05:00 Europe/Berlin (cron in UTC gesetzt, siehe Workflow).

## Wie funktioniert der Filter?

1. Der Gesamt-ICS wird geladen.
2. ICS-Zeilen werden RFC-konform „entfaltet“ (Continuation-Lines werden angehängt).
3. VEVENT-Blöcke mit `STATUS:CANCELLED` oder „ENTFÄLLT“ im `SUMMARY` werden verworfen.
4. Für jedes Gremium in [`config/committees.txt`](config/committees.txt) werden alle Events ausgewählt, deren `SUMMARY` den Gremien-Namen **als Substring** (case-insensitive) enthält.
5. Für jedes Gremium wird eine eigene `.ics` in `docs/calendars/` erzeugt.
6. `docs/index.html` enthält Links auf alle erzeugten Kalender.

> **Hinweis:** Die Filterung basiert standardmäßig auf einem Substring-Match im `SUMMARY`.  
> Falls der Quell-ICS andere Felder (z. B. `CATEGORIES`) konsistent nutzt, lässt sich die Matching-Logik in `scripts/build.py:event_matches_committee()` leicht anpassen.

## GitHub Pages: Abo-Links

Aktiviere in den **Repository Settings → Pages** die Auslieferung aus dem `docs/`-Ordner (Branch `main`, Ordner `/docs`).  
Danach sind die ICS-Dateien unter `https://<dein-user>.github.io/<repo>/calendars/<slug>.ics` abrufbar, z. B.:

```
docs/calendars/rat-der-stadt-iserlohn.ics
docs/calendars/verkehrsausschuss.ics
...
```

## Zeitsteuerung / Cron

GitHub Actions verwendet **UTC**. Die Datei [`build.yml`](.github/workflows/build.yml) nutzt `03:30 UTC`, wodurch die Aktualisierung **ganzjährig vor 05:00 in Berlin** liegt (Sommer/Winterzeit beachten).

Falls du **exakt** 05:00 lokaler Zeit möchtest, brauchst du 2 Cron-Einträge (Sommer/Winter) oder eine Zeitzonen-Logik.

## Konfiguration anpassen

- **Gremien pflegen:** `config/committees.txt` (eine Zeile pro Gremium; Substring-Match im `SUMMARY`)
- **Quelle ändern:** `SOURCE_URL` in `scripts/build.py`
- **Ausschluss-Logik erweitern:** `contains_cancel_marker()` (z. B. weitere Ausfall-Marker)

## Lokaler Lauf

```bash
python3 scripts/build.py
# Ergebnisse in docs/calendars/
```

## Architektur-Entscheidungen

- **Keine externen Abhängigkeiten** (nur Standardbibliothek); reduziert Ausfallpunkte in CI.
- **VEVENT-Blöcke unverändert kopiert** → maximale Kompatibilität mit RRULE/Alarm/UID etc.
- **Line-Unfolding** gemäß RFC 5545 → robust bei langen Properties.
- **Substrings im SUMMARY**: pragmatisch und transparent. Wenn sich die Stadt-Namenskonvention ändert, nur `committees.txt` anpassen.

## Mögliche Erweiterungen

- Per-Person-Kalender (z. B. `thko`) durch eine `config/persons/*.txt` Mapping-Datei (Sammlung von Gremiennamen pro Person) und zusätzliches Zusammenführen.
- Explizites Matching gegen `CATEGORIES:` oder eine `(Gremium: ...)`-Konvention im `SUMMARY`.
- Generierung einer `.well-known/ical`-Struktur oder CalDAV-Gateway (separater Dienst).
