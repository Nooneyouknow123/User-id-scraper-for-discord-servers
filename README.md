# Discord Member Logger

> A single-file Discord user tracking script with persistent storage, checkpointed history scanning, live logging, and built-in tools for searching, deduplication, and maintenance.

---

## ⚠️ Disclaimer

- This script runs in **self-bot mode** (`self_bot=True` in `main.py`).  
- **Self-bots and user tokens are against Discord’s Terms of Service.**  
- Running this on your personal Discord account can result in **account termination**.  
- This project is provided for **educational and testing purposes only**, ideally on accounts/servers you own.  

---

## 📖 Overview

The script does the following:

- Collects **user IDs**, **usernames**, **server IDs**, and **server names**.  
- Saves data to an **SQLite database** (`users.db`).  
- Maintains **user–server mappings**.  
- Performs **full scan** (all servers) or **targeted scan** (single server).  
- Uses **persistent checkpoints** to resume channel history scanning.  
- Discovers users from:
  - Message authors  
  - Reactions on messages  
  - Server boosters (`premium_subscribers`)  
  - Member joins  
  - Presence updates  
- Writes readable log lines into **`logs.txt`**.  
- Runs **live event tracking** after initial scan.  
- Includes **search & maintenance CLI menu** for duplicates and purging.  
- Prints a **heartbeat** every 5 minutes showing total users in DB.  

---

## 🗂️ Database Structure

`users.db` is automatically created with four tables:

```sql
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT
);

CREATE TABLE IF NOT EXISTS servers (
  id TEXT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS user_servers (
  user_id TEXT,
  server_id TEXT,
  PRIMARY KEY(user_id, server_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
  channel_id TEXT PRIMARY KEY,
  last_message_id TEXT
);
```

- `users` → stores unique user IDs + usernames.  
- `servers` → stores guild IDs + names.  
- `user_servers` → links users to servers.  
- `checkpoints` → tracks last processed message per channel (so scanning can resume).  

---

## 📝 logs.txt

All **first-time user discoveries** are logged into `logs.txt`.  
Format:

```
2025-10-02 14:20:33,120 - ExampleUser#1234 (123456789012345678) discovered in ExampleServer --- sent message id=987654321
```

- Timestamp  
- Username + ID  
- Server name  
- Action (message, reaction, join, presence, booster)  

Duplicates may appear if the script restarts or re-discovers the same user.  
Use the maintenance menu to **check** or **deduplicate** logs.

---

## 🔍 Search & Maintenance Menu

At startup, choose `s` to open the CLI menu.  

Available commands:

1. **Show total unique users**  
   - Prints total count from DB.  

2. **Search user by ID or username**  
   - Search exact ID or partial name.  
   - Shows servers linked to that user.  

3. **Check duplicates in DB**  
   - Reports duplicate user IDs in `users` table.  

4. **Check duplicates in logs.txt**  
   - Reports duplicate entries in `logs.txt` by user ID.  

5. **Remove duplicates from DB**  
   - Deletes duplicate user rows.  
   - Requires typing `YES` to confirm.  

6. **Remove duplicates from logs.txt**  
   - Deduplicates log file.  
   - Keeps first occurrence per user, removes others.  
   - Requires typing `YES` to confirm.  

7. **Exit menu**  
   - Leaves the menu.  

8. **Remove user data by server ID**  
   - Purges all user–server relationships for the given server.  
   - If a user only existed in that server → removed completely.  
   - Removes the server entry as well.  

---

## 🖥️ How to Run

### 1. Install Python
Requires **Python 3.9+**.  
Check with:
```bash
python --version
```

### 2. Create Virtual Environment (optional but recommended)
```bash
python -m venv .venv
```
Activate it:
- Windows: `.venv\Scripts\activate`  
- Linux/Mac: `source .venv/bin/activate`

### 3. Install Dependencies
```bash
pip install discord.py python-dotenv
```

### 4. Create `.env`
In the same folder as `main.py`, create a file named `.env`:

```
DISCORD_TOKEN=your_discord_account_token_here
```

---

## 🔑 Getting Your Discord Account Token

⚠️ **Warning:** Using a user token is not allowed by Discord ToS.  
This is explained here only for technical completeness.  

1. Open Discord in your browser (desktop app doesn’t work).  
2. Press **F12** or **Ctrl+Shift+I** to open Developer Tools.  
3. Go to the **Application / Storage** tab.  
4. Expand **Local Storage** → select `https://discord.com`.  
5. Look for the entry called **token**.  
6. Copy its value — this is your account token.  

⚠️ Keep this secret. Anyone with your token has **full control** of your account.  

---

## 🚀 Running the Script

Run:
```bash
python main.py
```

On login, you’ll see a mode selector:

```
Mode: 1 → Target server scan + live
      2 → All servers scan + live
      s → search tools
>
```

- `1` → Scans one server (asks for server ID).  
- `2` → Scans all servers.  
- `s` → Opens search/maintenance menu.  

---

## 🔒 Anti-Duplication

### Built-in
- Uses database **unique constraints** (`PRIMARY KEY`, `INSERT OR IGNORE`) to prevent duplicate entries.  
- Logs only record **first discovery** of each user.  

### Cleanup Tools
- **DB cleanup** → Menu option 5 (removes duplicate DB rows).  
- **Logs cleanup** → Menu option 6 (deduplicates `logs.txt`).  

---

## 📂 Files Created

- **`main.py`** → the script.  
- **`users.db`** → SQLite DB (auto-created).  
- **`logs.txt`** → append-only discovery log.  
- **`.env`** → must contain your token.  

---

## 💡 Example Workflow

1. Run script → choose **Full Scan (2)**.  
2. Wait for scan to complete → live tracking starts.  
3. Stop script, then restart later → it resumes from **checkpoints**.  
4. To check total users → restart script, choose **Search Menu (s)**, then option **1**.  
5. To clean duplicate logs → option **4** then **6**.  
6. To purge a server → option **8**, enter server ID.  

---

## 🔐 Security Notes

- `users.db` and `logs.txt` contain **user IDs and usernames** → handle as sensitive data.  
- Never share your `.env` file or token.  
- Use **search menu option 8** to remove all records for a specific server if needed.  

---

## 🧾 License

MIT License

Copyright (c) 2025 Syed Wajih

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


---


