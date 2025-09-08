import asyncio
from datetime import datetime, timedelta
import re
import requests
from collections import defaultdict

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
    date_line_idx = None
    for idx, line in enumerate(normalized_lines):
        if re.search(r"\d{2}/\d{2}", line):
            date_line_idx = idx
            break
    if date_line_idx is None:
        raise Exception("Geen datumregel gevonden")
    header_cols = normalized_lines[date_line_idx].split('|')[1:-1]
    date_cols = header_cols[1:1+NUM_DAYS]
    appointments = []
    current_hour = None
    current_quarter = 0
    i = date_line_idx + 1
    year = datetime.now().year  # Jaartal toegevoegd
    
    while i < len(normalized_lines):
        line = normalized_lines[i]
        cols = line.split('|')[1:-1]
        
        left = cols[0].strip() if len(cols) > 0 else ""
        right = cols[-1].strip() if len(cols) > 0 else ""
        
        # Check voor hoofdtijd (HH:MM) in linker of rechter kolom
        m_time_left = re.match(r"^(\d{2}:\d{2})$", left)
        m_time_right = re.match(r"^(\d{2}:\d{2})$", right)
        
        if m_time_left:
            current_hour = m_time_left.group(1)
            current_quarter = 0
            log.debug(f"Tijd gevonden links: {current_hour}")
        elif m_time_right:
            current_hour = m_time_right.group(1)
            current_quarter = 0
            log.debug(f"Tijd gevonden rechts: {current_hour}")
        
        # Check voor kwartier (15, 30, 45) in linker of rechter kolom
        m_quarter_left = re.match(r"^(15|30|45)$", left)
        m_quarter_right = re.match(r"^(15|30|45)$", right)
        
        if m_quarter_left and current_hour:
            current_quarter = int(m_quarter_left.group(1))
            log.debug(f"Kwartier gevonden links: {current_quarter}")
        elif m_quarter_right and current_hour:
            current_quarter = int(m_quarter_right.group(1))
            log.debug(f"Kwartier gevonden rechts: {current_quarter}")
        
        # Verwerk afspraken als we een current_hour hebben
        if current_hour:
            # Controleer of er daadwerkelijk afspraken op deze regel staan
            has_appointments = False
            for col in range(NUM_DAYS):
                if col + 1 >= len(cols):
                    continue
                text = cols[col+1].strip()
                if (text and text != SPACER and 
                    not re.match(r"^\d+$", text) and 
                    not re.match(r"^\d{2}:\d{2}$", text) and
                    not re.match(r"^(15|30|45)$", text)):
                    has_appointments = True
                    break
            
            if has_appointments:
                # Intelligente tijdbepaling gebaseerd op patroonherkenning
                appointment_quarter = current_quarter
                
                # Heuristiek: als current_quarter 15 of 45 is, probeer te bepalen
                # of dit echt kwartier-afspraken zijn of gewoon positionering
                if current_quarter == 15 or current_quarter == 45:
                    # Check de volgende regels om te zien of er een patroon is
                    next_appointments_at_30 = False
                    if i + 1 < len(normalized_lines):
                        next_line = normalized_lines[i + 1]
                        next_cols = next_line.split('|')[1:-1]
                        next_left = next_cols[0].strip() if len(next_cols) > 0 else ""
                        next_right = next_cols[-1].strip() if len(next_cols) > 0 else ""
                        
                        # Check of de volgende regel 30 is met afspraken
                        if (next_left == "30" or next_right == "30"):
                            for col in range(NUM_DAYS):
                                if col + 1 >= len(next_cols):
                                    continue
                                next_text = next_cols[col+1].strip()
                                if (next_text and next_text != SPACER and 
                                    not re.match(r"^\d+$", next_text) and 
                                    not re.match(r"^\d{2}:\d{2}$", next_text) and
                                    not re.match(r"^(15|30|45)$", next_text)):
                                    next_appointments_at_30 = True
                                    break
                    
                    # Als er geen afspraken op 30 zijn, zijn de 15/45 afspraken waarschijnlijk op het hele uur
                    if not next_appointments_at_30 and current_quarter == 15:
                        log.debug(f"Heuristiek: afspraken op regel 15 zonder 30-afspraken -> waarschijnlijk hele uur")
                        appointment_quarter = 0
                    elif not next_appointments_at_30 and current_quarter == 45:
                        log.debug(f"Heuristiek: afspraken op regel 45 zonder 30-afspraken -> waarschijnlijk halve uur")
                        appointment_quarter = 30
                
                # Verwerk afspraken in de dagkolommen (kolom 1 tot NUM_DAYS)
                for col in range(NUM_DAYS):
                    if col + 1 >= len(cols):  # Voorkom index out of bounds
                        continue
                        
                    text = cols[col+1].strip()
                    # Accepteer alle tekst die niet een tijd, kwartier, spacer of puur nummer is
                    if (text and text != SPACER and 
                        not re.match(r"^\d+$", text) and 
                        not re.match(r"^\d{2}:\d{2}$", text) and
                        not re.match(r"^(15|30|45)$", text)):
                        
                        date_str = date_cols[col]
                        if date_str == "-":
                            continue
                        try:
                            # Jaartal toegevoegd aan de datum-string
                            dt_start = datetime.strptime(f"{date_str}/{year} {current_hour}", "%d/%m/%Y %H:%M")
                        except Exception as e:
                            log.error(f"Fout bij datum/tijd: {e} (kolom {col}, waarde '{text}')")
                            continue
                        dt_start += timedelta(minutes=appointment_quarter)
                        dt_end = dt_start + timedelta(minutes=30)
                        
                        log.debug(f"Afspraak toegevoegd: {text} op {dt_start} (regel kwartier: {current_quarter} -> afspraaktijd: {appointment_quarter})")
                        appointments.append({
                            "date": date_str,
                            "start_time": dt_start.strftime("%H:%M"),
                            "end_time": dt_end.strftime("%H:%M"),
                            "name": text
                        })
        
        i += 1
    return appointments

def event_to_key(event):
    """Maak een unieke sleutel van een event, ongeacht structuur."""
    if isinstance(event, dict):
        summary = event.get("summary") or event.get("message") or ""
        description = event.get("description") or ""
        start = event.get("start")
        if isinstance(start, dict):
            start_time = start.get("dateTime") or start.get("date") or ""
        elif isinstance(start, str):
            start_time = start
        else:
            start_time = ""
        return (summary.strip(), start_time[:16], description.strip())
    elif isinstance(event, str):
        return (event.strip(), "", "")
    return ("", "", "")

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
        lines = text.splitlines()
    except Exception as e:
        log.error(f"Fout bij downloaden van TXT: {e}")
        return

    try:
        normalized = normalize_fixed_width(lines)
        for idx, l in enumerate(normalized):
            log.debug(f"GENORMALISEERDE REGEL {idx}: {l}")
    except Exception as e:
        log.error(f"Fout bij normaliseren van TXT: {e}")
        return

    try:
        appointments = parse_agenda(normalized)
    except Exception as e:
        log.error(f"Fout bij parsen van TXT: {e}")
        return

    log.info(f"Gevonden afspraken: {len(appointments)}")

    if not appointments:
        log.warning("Geen afspraken gevonden! Controleer het TXT-bestand en parsing.")
        return

    year = datetime.now().year

    # Verzamel alle datums waarop afspraken zijn
    alle_datums = set()
    for app in appointments:
        app_date = f"{year}-{app['date'][3:5]}-{app['date'][0:2]}"
        alle_datums.add(app_date)

    # Haal per dag de bestaande events op
    bestaande_events_per_dag = dict()
    for datum in alle_datums:
        start_iso = f"{datum}T00:00:00+02:00"
        end_iso = f"{datum}T23:59:59+02:00"
        events = await task.executor(
            hass.services.call,
            "calendar",
            "get_events",
            {
                "entity_id": calendar_entity,
                "start_date_time": start_iso,
                "end_date_time": end_iso,
            },
            blocking=True,
            return_response=True
        )
        log.warning(f"DEBUG: Events van {datum}: {repr(events)}")
        # Pak de juiste lijst uit de geneste structuur
        event_list = []
        if isinstance(events, dict):
            for cal_key in events:
                cal_val = events[cal_key]
                if isinstance(cal_val, dict) and "events" in cal_val:
                    event_list = cal_val["events"]
                else:
                    event_list = []
                break
        elif isinstance(events, list):
            event_list = events
        elif events is None:
            event_list = []
        else:
            event_list = [events]
        bestaande_events_per_dag[datum] = event_list

    # Voeg nieuwe afspraken toe, alleen als ze nog niet bestaan
    for app in appointments:
        app_date = f"{year}-{app['date'][3:5]}-{app['date'][0:2]}"
        start_iso = f"{app_date}T{app['start_time']}:00+02:00"
        end_iso = f"{app_date}T{app['end_time']}:00+02:00"

        # Log alle bestaande events voor debug
        log.warning(f"DEBUG: Events per dag {app_date}: {repr(bestaande_events_per_dag[app_date])}")

        # Maak een set met bestaande event keys zonder generator-expressie
        bestaande_keys = set()
        for ev in bestaande_events_per_dag[app_date]:
            bestaande_keys.add(event_to_key(ev))

        nieuwe_key = (app['name'].strip(), start_iso[:16], "Afspraak uit TXT agenda")
        if nieuwe_key in bestaande_keys:
            log.info(f"Afspraak '{app['name']}' op {start_iso} bestaat al (key match), overslaan.")
            continue

        log.info(f"Toevoegen aan agenda: {app['name']} op {start_iso} - {end_iso}")
        await task.executor(
            hass.services.call,
            "script",
            "voeg_agenda_item_toe",
            {
                "entity_id": calendar_entity,
                "summary": app['name'],
                "description": "Afspraak uit TXT agenda",
                "start_date_time": start_iso,
                "end_date_time": end_iso,
            }
        )
        await asyncio.sleep(3.0)

    log.info("Agenda synchronisatie voltooid.")