import asyncio
from datetime import datetime, timedelta
import re
import requests
from collections import defaultdict

# Kolombreedtes en instellingen
LEFT_WIDTH = 7
DAY_WIDTH = 27
NUM_DAYS = 7
RIGHT_WIDTH = 6
SPACER = "-"

def normalize_fixed_width(lines, left=LEFT_WIDTH, day=DAY_WIDTH, days=NUM_DAYS, right=RIGHT_WIDTH, spacer=SPACER):
    norm_lines = []
    for line in lines:
        needed_len = left + day*days + right
        if len(line) < needed_len:
            line = line.ljust(needed_len)
        pos = 0
        cols = []
        leftval = line[pos:pos+left].strip() or spacer
        cols.append(leftval)
        pos += left
        for i in range(days):
            dayval = line[pos:pos+day].strip() or spacer
            cols.append(dayval)
            pos += day
        rightval = line[pos:pos+right].strip() or spacer
        cols.append(rightval)
        norm_lines.append("|" + "|".join(cols) + "|")
    return norm_lines

def parse_agenda(normalized_lines):
    # Zoek de headerregel met datums
    date_line_idx = None
    for idx, line in enumerate(normalized_lines):
        if re.search(r"\d{2}/\d{2}", line):
            date_line_idx = idx
            break
    if date_line_idx is None:
        raise Exception("Geen datumregel gevonden")
    header_cols = normalized_lines[date_line_idx].split('|')[1:-1]
    date_cols = header_cols[1:1+NUM_DAYS]  # sla de eerste kolom (links) over
    appointments = []
    current_hour = None
    current_quarter = 0
    year = datetime.now().year
    i = date_line_idx + 1
    while i < len(normalized_lines):
        line = normalized_lines[i]
        cols = line.split('|')[1:-1]
        left = cols[0].strip()
        right = cols[-1].strip()
        # Herken uurregel (links/rechts)
        m_time = re.match(r"^(\d{2}:\d{2})$", left)
        m_time_r = re.match(r"^(\d{2}:\d{2})$", right)
        if m_time:
            current_hour = m_time.group(1)
            current_quarter = 0
            i += 1
            continue
        elif m_time_r:
            current_hour = m_time_r.group(1)
            current_quarter = 0
            i += 1
            continue
        # Herken kwartierregel (links/rechts)
        m_quarter = re.match(r"^(15|30|45)$", left)
        m_quarter_r = re.match(r"^(15|30|45)$", right)
        if m_quarter and current_hour:
            current_quarter = int(m_quarter.group(1))
            i += 1
            continue
        elif m_quarter_r and current_hour:
            current_quarter = int(m_quarter_r.group(1))
            i += 1
            continue
        # Alleen verwerken als er een actief uur is
        if not current_hour:
            i += 1
            continue
        # Dagkolommen zijn kolom 1 t/m 7
        for col in range(NUM_DAYS):
            text = cols[col+1].strip()
            if text and text != SPACER and not re.match(r"^\d+$", text):
                date_str = date_cols[col]
                if date_str == "-":
                    continue
                try:
                    dt_start = datetime.strptime(f"{date_str} {current_hour}", "%d/%m %H:%M")
                except Exception as e:
                    log.error(f"Fout bij datum/tijd: {e} (kolom {col}, waarde '{text}')")
                    continue
                dt_start += timedelta(minutes=current_quarter)
                dt_end = dt_start + timedelta(minutes=30)
                appointments.append({
                    "date": date_str,
                    "start_time": dt_start.strftime("%H:%M"),
                    "end_time": dt_end.strftime("%H:%M"),
                    "name": text
                })
        i += 1
    return appointments

@service
async def agenda_sync_txt(
    url="http://homeassistant:8123/local/agenda.txt",
    calendar_entity="calendar.odeyn_agenda"
):
    if isinstance(calendar_entity, list):
        calendar_entity = calendar_entity[0]

    log.info(f"Downloaden van: {url}")

    try:
        response = await task.executor(requests.get, url)
        if response.status_code != 200:
            log.error(f"Kon TXT niet downloaden, status code: {response.status_code}")
            return
        text = response.text
        lines = text.splitlines()
    except Exception as e:
        log.error(f"Fout bij downloaden van TXT: {e}")
        return

    # Normaliseer de tekst en vul lege kolommen met spacer
    try:
        normalized = normalize_fixed_width(lines)
        for idx, l in enumerate(normalized):
            log.debug(f"GENORMALISEERDE REGEL {idx}: {l}")
    except Exception as e:
        log.error(f"Fout bij normaliseren van TXT: {e}")
        return

    # Parse afspraken uit het TXT-bestand
    try:
        appointments = parse_agenda(normalized)
    except Exception as e:
        log.error(f"Fout bij parsen van TXT: {e}")
        return

    log.info(f"Gevonden afspraken: {len(appointments)}")

    # Optioneel: overzicht per dag in de log
    by_day = defaultdict(list)
    for app in appointments:
        by_day[app['date']].append(app)
    dagen = sorted(by_day.keys(), key=lambda d: datetime.strptime(d, "%d/%m"))
    for dag in dagen:
        log.info(f"Dag {dag}:")
        for app in sorted(by_day[dag], key=lambda a: a['start_time']):
            log.info(f"  {app['start_time']} - {app['end_time']}: {app['name']}")

    if not appointments:
        log.warning("Geen afspraken gevonden! Controleer het TXT-bestand en parsing.")
        return

    year = datetime.now().year

    # Voeg nieuwe afspraken toe via HA-script, met vertraging
    for app in appointments:
        try:
            app_date = f"{year}-{app['date'][3:5]}-{app['date'][0:2]}"
            start_iso = f"{app_date}T{app['start_time']}:00+02:00"
            end_iso = f"{app_date}T{app['end_time']}:00+02:00"
            eid = calendar_entity if isinstance(calendar_entity, str) else calendar_entity[0]
            log.info(f"Toevoegen aan agenda: {app['name']} op {start_iso} - {end_iso}")
            await task.executor(
                hass.services.call,
                "script",
                "voeg_agenda_item_toe",  # Pas aan naar jouw scriptnaam!
                {
                    "entity_id": eid,
                    "summary": app['name'],
                    "description": "Afspraak uit TXT agenda",
                    "start_date_time": start_iso,
                    "end_date_time": end_iso,
                }
            )
            await asyncio.sleep(3.0)  # Pauze om 'maximum number of runs' te voorkomen
        except Exception as e:
            log.error(f"Fout bij toevoegen van afspraak: {e} ({app})")

    log.info("Agenda synchronisatie voltooid.")
