import asyncio
from datetime import datetime, timedelta
import re
import requests

def parse_agenda(lines):
    # Zoek de regel met de datums (bv. '02/06  03/06  ...')
    date_line_idx = None
    for idx, line in enumerate(lines):
        if re.search(r"\d{2}/\d{2}", line):
            date_line_idx = idx
            break
    if date_line_idx is None:
        raise ValueError("Geen datums gevonden in tekst")

    date_line = lines[date_line_idx]

    # Vind startposities van elke datum in de regel
    date_positions = []
    for match in re.finditer(r"\d{2}/\d{2}", date_line):
        date_positions.append((match.start(), match.group()))

    # Voeg eindpositie toe voor laatste kolom (einde regel)
    date_positions.append((len(date_line), None))

    def get_col_text(line, col_idx):
        start = date_positions[col_idx][0]
        end = date_positions[col_idx + 1][0]
        return line[start:end].strip()

    appointments = []
    current_hour = None
    current_quarter = 0
    i = date_line_idx + 1

    while i < len(lines):
        line = lines[i]
        line_strip = line.strip()

        # Check of het een uurregel is (bv. '09:00')
        m_time = re.match(r"^(\d{2}:\d{2})", line_strip)
        if m_time:
            current_hour = m_time.group(1)
            current_quarter = 0
            i += 1
            continue

        # Check of het een kwartierregel is (15,30,45)
        m_quarter = re.match(r"^(15|30|45)$", line_strip)
        if m_quarter and current_hour:
            current_quarter = int(m_quarter.group(1))
            i += 1
            continue

        if not current_hour:
            i += 1
            continue

        # Lees namen per kolom
        for col in range(len(date_positions) - 1):
            text = get_col_text(line, col)
            if text and not re.match(r"^\d+$", text):  # geen alleen cijfers
                date_str = date_positions[col][1]
                # Bouw starttijd
                dt_start = datetime.strptime(f"{date_str} {current_hour}", "%d/%m %H:%M")
                dt_start += timedelta(minutes=current_quarter)
                dt_end = dt_start + timedelta(minutes=30)  # vaste duur
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
    # Forceer direct string (voor de zekerheid)
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
        # Bouw ISO datums
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
        await asyncio.sleep(0.5)  # Korte pauze om 'maximum number of runs' te voorkomen

    log.info("Agenda synchronisatie voltooid.")
