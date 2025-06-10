# kinequick-calendar-pdf-parser
Easily add kinequick calendar events to google calendar with python and Home Assistant

Prerequisites:

1. You have HomeAssistant installed.
2. You have installed Pyscript via HACS. 
   In the configuration.yaml you have to add
```
pyscript:
  allow_all_imports: true
  allow_paths:
    - /config/www/
```
3. Have Google Calendar set up in Home assistant.

For the script to work your "agenda.txt" file has to be in the "www" folder reachable via Samba.
I added this shell command to do an automation to get it there before I call my script so I don't have to give access to the www folder to anyone.

```
shell_command:
  kopieer_agenda: cp /media/YourAgenda/agenda.txt /config/www/agenda.txt
```

The /media/YourAgenda is a networkshare I added to Home Assistant via config/storage and mount it there.

4. First add a script in /config/script/dashboard

```
alias: Voeg agenda-item toe
mode: queued
max: 100
sequence:
  - data:
      entity_id: "{{ entity_id }}"
      summary: "{{ summary }}"
      description: "{{ description }}"
      start_date_time: "{{ start_date_time }}"
      end_date_time: "{{ end_date_time }}"
    action: calendar.create_event
```

Second, copy both files "pdf_agenda_sync_via_txt.py" and "requirements.txt" to the pyscript folder, and change your calendar name.
Reboot (For the Shell command to be able to run)

5. Now you can make an automation to run automatically every week or sooner or via a button.
   In my case the shell command has to run first, but this is not necessary if you save the file straight to the "www" folder. (Not recommended)

	To make the file you need, you have to open the KineQuick calendar and click print.
	(I use "Foxit PDF Reader" but any pdf reader that can save as "txt" format will do I think, but that's not tested).
	Your pdf reader will open a pdf. Then select the "Save as" option and save as "agenda.txt" in the desired location.



Warning: Removal of appointments via this script is not (yet) possible due to the Google Calendar integration not having this action available to call. 
So this has to happen manually in Google Calender itself or via the UI in the calendar in Home Assistant.

ToDo:
-Prevent double entries when the script is run twice for the same week.


 