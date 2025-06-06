import appdaemon.plugins.hass.hassapi as hass
import re
from datetime import datetime, timedelta
from PyPDF2 import PdfReader
import os

class PdfAgendaSync(hass.Hass):
    def initialize(self):
        # Dagelijks om 03:00 uitvoeren
        self.run_daily(self.sync_pdf_to_calendar, "03:00:00")

        # Pad naar de PDF in de media-map
        self.pdf_path = "/media/agenda.pdf"  # <-- Zet je bestand hier neer

        # Calendar entity_id (pas aan naar jouw Google Calendar in Home Assistant)
        self.calendar_entity = "calendar.jouw_google_agenda"  # <-- PAS AAN

        # Event duur in minuten
        self.event_duration = 45

    def sync_pdf_to_calendar(self, kwargs):
        self.log("Start synchronisatie van PDF agenda...")

        # 1. PDF inlezen
        if not os.path.exists(self.pdf_path):
            self.log(f"PDF niet gevonden: {self.pdf_path}", level="WARNING")
            return

        with open(self.pdf_path, "rb") as f:
            reader = PdfReader(f)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text.replace("\n", " ")

        # 2. Data, tijden en namen extraheren (PAS REGEX AAN NAAR JOUW PDF!)
        dates = re.findall(r"\d{2}/\d{2}", text)
        times = re.findall(r"\d{2}:\d{2}", text)
        names = re.findall(r"[A-Z][a-z]+ [A-Z][a-z]+", text)

        if not dates or not times or not names:
            self.log("Kon geen data, tijden of namen vinden in de PDF", level="WARNING")
            return

        # 3. Maak een lijst van afspraken uit de PDF
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

        # 4. Ophalen van bestaande afspraken in de agenda (voor komende 7 dagen)
        now = datetime.now()
        start = now.strftime("%Y-%m-%dT00:00:00+02:00")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59+02:00")
        events = self.get_calendar_events(start, end)

        # 5. Maak een set van unieke sleutels voor afspraken (date+time+name)
        def make_key(app): return f"{app['date']}_{app['time']}_{app['name']}"
        pdf_keys = set(make_key(app) for app in appointments)
        event_keys = set()

        # 6. Voeg nieuwe afspraken toe, verwijder oude
        for app in appointments:
            key = make_key(app)
            if not any(key in ev for ev in event_keys):
                if not self.appointment_exists(events, app):
                    self.create_calendar_event(app)
                    self.log(f"Toegevoegd: {app}")

        for event in events:
            event_key = f"{event['start'][:10]}_{event['start'][11:16]}_{event['summary']}"
            if event_key not in pdf_keys:
                self.delete_calendar_event(event)
                self.log(f"Verwijderd: {event}")

        self.log("PDF agenda synchronisatie voltooid.")

    def get_calendar_events(self, start, end):
        entity = self.calendar_entity
        events = self.get_state(entity, attribute="all")["attributes"].get("events", [])
        filtered = []
        for event in events:
            if "start_time" in event:
                if start <= event["start_time"] <= end:
                    filtered.append({
                        "event_id": event.get("uid", ""),
                        "start": event["start_time"],
                        "end": event["end_time"],
                        "summary": event["message"]
                    })
        return filtered

    def appointment_exists(self, events, app):
        app_date = f"2025-{app['date'][3:5]}-{app['date'][0:2]}"
        app_time = app['time']
        app_name = app['name']
        for event in events:
            if (event["start"].startswith(app_date) and
                event["start"][11:16] == app_time and
                event["summary"] == app_name):
                return True
        return False

    def create_calendar_event(self, app):
        app_date = f"2025-{app['date'][3:5]}-{app['date'][0:2]}"
        start_dt = datetime.strptime(f"{app_date} {app['time']}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=self.event_duration)
        start_iso = start_dt.isoformat() + "+02:00"
        end_iso = end_dt.isoformat() + "+02:00"

        self.call_service("calendar/create_event", entity_id=self.calendar_entity,
                          summary=app['name'],
                          description="Afspraak uit PDF agenda",
                          start=start_iso,
                          end=end_iso)

    def delete_calendar_event(self, event):
        if "event_id" in event and event["event_id"]:
            self.call_service("calendar/delete_event", entity_id=self.calendar_entity,
                              event_id=event["event_id"])
