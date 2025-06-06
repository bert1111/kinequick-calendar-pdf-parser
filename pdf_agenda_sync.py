from datetime import datetime, timedelta
import re
import requests
import PyPDF2
from io import BytesIO

@service
async def agenda_sync(
    url="http://homeassistant:8123/local/agenda.pdf",  # <-- Vervang door jouw PDF-link
    calendar_entity="calendar.your_calendar"  # <-- Vervang door jouw agenda entity_id als string
):
    log.info(f"Downloaden van: {url}")

    try:
        response = await task.executor(requests.get, url)
        if response.status_code != 200:
            log.error(f"Kon PDF niet downloaden, status code: {response.status_code}")
            return
    except Exception as e:
        log.error(f"Fout bij downloaden van PDF: {e}")
        return

    if not response.headers.get("content-type", "").startswith("application/pdf"):
        log.error("Het gedownloade bestand is GEEN PDF! Content-type: " + response.headers.get("content-type", ""))
        log.error("Eerste 500 tekens van response:\n" + response.text[:500])
        return

    try:
        pdf_file = BytesIO(response.content)
        reader = await task.executor(PyPDF2.PdfReader, pdf_file)
    except Exception as e:
        log.error(f"Fout bij openen van PDF: {e}")
        return

    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text.replace("\n", " ")

    log.info(f"Eerste 500 tekens uit PDF: {text[:500]}")

    dates = re.findall(r"\d{2}/\d{2}", text)
    times = re.findall(r"\d{2}:\d{2}", text)
    names = re.findall(r"[A-Z][a-z]+ [A-Z][a-z]+", text)

    log.info(f"Gevonden data: {dates}")
    log.info(f"Gevonden tijden: {times}")
    log.info(f"Gevonden namen: {names}")

    if not dates or not times or not names:
        log.error("Geen data/tijden/namen gevonden in de PDF.")
        return

    appointments = []
    index = 0
    for date in dates:
        for time in times:
            if index < len(names):
                name = names[index]
                appointments.append({
                    "date": date,
                    "time": time,
                    "name": name
                })
                index += 1

    now = datetime.now()
    start = now.strftime("%Y-%m-%dT00:00:00+02:00")
    end = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59+02:00")

    # ---------- EVENTS OPHALEN VIA eval() ----------
    try:
        entity = eval(calendar_entity)
        events = entity.events if hasattr(entity, "events") else []
    except Exception as e:
        log.error(f"Kan agenda-events niet ophalen: {e}")
        events = []
    # ------------------------------------------------

    def make_key(app):
        return f"{app['date']}_{app['time']}_{app['name']}"

    # Geen generator expressions: maak set via for-loop
    pdf_keys = set()
    for app in appointments:
        pdf_keys.add(make_key(app))

    for app in appointments:
        key = make_key(app)
        found = False  # <-- Gebruik expliciete for-loop i.p.v. any()
        for ev in events:
            if key in f"{ev.get('start_time','')}_{ev.get('message','')}":
                found = True
                break
        if not found:
            app_date = f"{now.year}-{app['date'][3:5]}-{app['date'][0:2]}"
            start_dt = datetime.strptime(f"{app_date} {app['time']}", "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=30)
            start_iso = start_dt.isoformat() + "+02:00"
            end_iso = end_dt.isoformat() + "+02:00"
            await task.executor(
                hass.services.call,
                "calendar",
                "create_event",
                {
                    "entity_id": calendar_entity,
                    "summary": app['name'],
                    "description": "Afspraak uit PDF agenda",
                    "start_date_time": start_iso,
                    "end_date_time": end_iso,
                }
            )
            log.info(f"Toegevoegd: {app}")

    for ev in events:
        ev_date = ev.get("start_time", "")[:10]
        ev_time = ev.get("start_time", "")[11:16]
        ev_name = ev.get("message", "")
        ev_key = f"{ev_date[8:10]}/{ev_date[5:7]}_{ev_time}_{ev_name}"
        found = False  # <-- Gebruik expliciete for-loop i.p.v. 'if ev_key not in pdf_keys'
        for app in appointments:
            if ev_key == make_key(app):
                found = True
                break
        if not found:
            event_id = ev.get("uid", "")
            if event_id:
                await task.executor(
                    hass.services.call,
                    "calendar",
                    "delete_event",
                    {
                        "entity_id": calendar_entity,
                        "event_id": event_id,
                    }
                )
                log.info(f"Verwijderd: {ev_name} op {ev_date} {ev_time}")

    log.info("Agenda synchronisatie voltooid.")
