# Unity Roster - Server Deployment Checklist

Run these ON THE OD SERVER (Windows) unless noted. The server is PULL-ONLY -
never hand-edit code here except the 3 provider IDs in staff.yaml (Step 6).

App location on server: C:\roster-app\dental-roster

------------------------------------------------------------

## 1. Open a new Command Prompt
Start menu -> type cmd -> Enter. Then:
    cd C:\roster-app\dental-roster

## 2. Pull the latest code from GitHub
    git pull
If it reports a conflict, STOP and note the file.

## 3. Install the new Gemini SDK
    pip install google-genai

## 4. Create the API key file (.env)
Generate a key ON THE SERVER so it never crosses machines:
  1. Server's Chrome -> https://aistudio.google.com/apikey
  2. Create API key -> copy it
  3. notepad .env
     type this line (paste the key after the = sign):
       GEMINI_API_KEY=PASTE_KEY_HERE
     Save, close. (.env is git-ignored, stays only on the server.)

## 5. See the real provider IDs
    mysql -u roster_readonly -p opendental < list_providers.sql
Password: RosterRead2026
Note the ProvNum for Dr Singh, Erica Scott, Jinwei.

## 6. Set the 3 real provider IDs in staff.yaml
    notepad config\staff.yaml
Replace placeholders with real ProvNums:
  - D_SINGH   provider_id: 90  -> Dr Singh
  - H_ERICA   provider_id: 91  -> Erica Scott
  - H_JINWEI  provider_id: 92  -> Jinwei
Save. (Only hand-edit allowed on server. Future pull conflict on staff.yaml
-> keep the server's provider_id numbers.)

## 7. Fix clinic name (if still Lighthouse)
    notepad config\clinic.yaml
Set name to: Unity Dental & Implant Centre

## 8. Restart the app
    taskkill /F /IM pythonw.exe
    start-roster.bat
Returns to prompt immediately (runs hidden). Wait ~3 seconds.

## 9. Test
Server's Chrome -> http://localhost:8000/
Pick a real Monday with appointments -> Build roster.
On error: type C:\roster-app\roster.log

## 10. Manager's desktop shortcut
Desktop -> right-click -> New -> Text Document -> rename to: Unity Roster.url
(enable File name extensions in Explorer View if needed)
Open with Notepad, paste these two lines:
    [InternetShortcut]
    URL=http://localhost:8000/
Save. Manager double-clicks "Unity Roster" -> roster opens.

------------------------------------------------------------

## Day-to-day
  Stop:  taskkill /F /IM pythonw.exe
  Start: start-roster.bat
  Log:   type C:\roster-app\roster.log
  Update from Mac: git pull (then restart)

## Troubleshooting
  - Won't load: app running? re-run start-roster.bat, check roster.log
  - 401/auth: .env key wrong/missing (Step 4)
  - Key loaded NONE: .env must be in C:\roster-app\dental-roster
  - Providers missing: provider_id doesn't match a ProvNum with appointments
