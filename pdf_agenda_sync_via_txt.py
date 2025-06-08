import asyncio
from datetime import datetime, timedelta
import re
import requests

def split_columns(line, col_width=27, num_cols=7):
    # Verwijder tijd rechts
    line = re.sub(r"\s+\d{2}:\d{2}\s*$", "", line)
    # Vul de regel aan tot de juiste lengte
    if len(line) < col_width * num_cols:
        line = line.ljust(col_width * num_cols)
    # Knip de regel in stukken van col_width
    return [line[i*col_width:(i+1)*col_width].strip() for i in range(num_cols)]

def clean_time_lines(lines, skip_hour=198, skip_quarter=194):
    cleaned = []
    for line in lines:
        # Controleer op uurregel (bv. 09:00)
        m_hour = re.match(r"^(\d{2}:\d{2})", line.strip())
        if m_hour:
            uur_einde = line.find(m_hour.group(1)) + 5  # positie direct na het uur
            new_line = line[:uur_einde] + line[uur_einde+skip_hour:]
            cleaned.append(new_line)
            continue
        # Controleer op kwartierregel (15, 30, 45)
        m_quarter = re.match(r"^(15|30|45)", line.strip())
        if m_quarter:
            kwart_einde = line.find(m_quarter.group(1)) + len(m_quarter.group(1))
            new_line = line[:kwart_einde] + line[kwart_einde+skip_quarter:]
            cleaned.append(new_line)
            continue
        # Anders: laat de regel ongemoeid
        cleaned.append(line)
    return cleaned

def parse_agenda(lines):
    # Zoek de regel met de datums
    date_line_idx = None
    for idx, line in enumerate(lines):
        if re.search(r"\d{2}/\d{2}", line):
            date_line_idx = idx
            break
    if date_line_idx is None:
        raise ValueError("Geen datums gevonden in tekst")

    # Haal de datums uit de kopregel
    date_line = lines[date_line_idx]
    date_cols = split_columns(date_line)
    num_cols = len(date_cols)

    appointments = []
    current_hour = None
    current_quarter = 0
    i = date_line_idx + 1
    year = datetime.now().year

    while i < len(lines):
        line = lines[i]
        line_strip = line.strip()

        # Debug: print de huidige regel
        print(f"Regel {i}: '{line_strip}'")

        # Check of het een uurregel is (bv. '09:00')
        m_time = re.match(r"^(\d{2}:\d{2})$", line_strip)
        if m_time:
            current_hour = m_time.group(1)
            current_quarter = 0
            print(f"  Nieuw uur gevonden: {current_hour}")
            i += 1
            continue

        # Check of het een kwartierregel is (15,30,45)
        m_quarter = re.match(r"^(15|30|45)$", line_strip)
        if m_quarter and current_hour:
            current_quarter = int(m_quarter.group(1))
            print(f"  Kwartier gevonden: {current_quarter} minuten")
            i += 1
            continue

        if not current_hour:
            print("  Geen huidig uur actief, overslaan.")
            i += 1
            continue

        # Splits de namenregel in kolommen van vaste breedte
        name_cols = split_columns(line, col_width=27, num_cols=num_cols)
        while len(name_cols) < num_cols:
            name_cols.append("")
        for col in range(num_cols):
            text = name_cols[col]
            if text and not re.match(r"^\d+$", text):  # geen alleen cijfers
                date_str = date_cols[col]
                dt_start = datetime.strptime(f"{date_str} {current_hour}", "%d/%m %H:%M")
                dt_start += timedelta(minutes=current_quarter)
                dt_end = dt_start + timedelta(minutes=30)
                print(f"  Afspraak: {text} op {date_str} om {dt_start.strftime('%H:%M')}")
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
    calendar_entity="calendar.your_agenda"
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

        # Split de tekst in regels
        lines = text.splitlines()
        # Verwijder na elk heel uur de eerste 198 tekens, na elke kwartierregel (15/30/45) de eerste 194 tekens
        lines = clean_time_lines(lines, skip_hour=198, skip_quarter=194)

    except Exception as e:
        log.error(f"Fout bij downloaden van TXT: {e}")
        return

    # Parse afspraken uit het TXT-bestand
    try:
        appointments = parse_agenda(lines)
    except Exception as e:
        log.error(f"Fout bij parsen van TXT: {e}")
        return

    log.info(f"Gevonden afspraken: {appointments}")

    year = datetime.now().year

    # Voeg nieuwe afspraken toe via HA-script, met vertraging
    for app in appointments:
        app_date = f"{year}-{app['date'][3:5]}-{app['date'][0:2]}"
        start_iso = f"{app_date}T{app['start_time']}:00+02:00"
        end_iso = f"{app_date}T{app['end_time']}:00+02:00"
        eid = calendar_entity if isinstance(calendar_entity, str) else calendar_entity[0]
        await task.executor(
            hass.services.call,
            "script",
            "voeg_agenda_item_toe",
            {
                "entity_id": eid,
                "summary": app['name'],
                "description": "Afspraak uit TXT agenda",
                "start_date_time": start_iso,
                "end_date_time": end_iso,
            }
        )
        log.info(f"Toegevoegd via script: {app}")
        await asyncio.sleep(0.5)  # Pauze om 'maximum number of runs' te voorkomen

    log.info("Agenda synchronisatie voltooid.")
