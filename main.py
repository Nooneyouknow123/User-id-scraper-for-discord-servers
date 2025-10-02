# Full all-in-one tracker with persistent checkpoints (copy-paste)
import os
import sys
import time
import asyncio
import discord
import sqlite3
import logging
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

# ---------------- Config ----------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_TOKEN not found in .env")

DB_FILE = "users.db"
LOG_FILE = "logs.txt"
HEARTBEAT_SECONDS = 300  # 5 minutes when scanning is active

# ---------------- Logging ----------------
logger = logging.getLogger("user_tracker")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logger.addHandler(file_handler)

# reduce discord.py noise
logging.getLogger("discord").setLevel(logging.WARNING)

# ---------------- Database ----------------
def init_db(path=DB_FILE):
    conn = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_servers (
            user_id TEXT,
            server_id TEXT,
            PRIMARY KEY(user_id, server_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            channel_id TEXT PRIMARY KEY,
            last_message_id TEXT
        )
    """)
    conn.commit()
    return conn

conn = init_db()
cur = conn.cursor()
cur.execute("PRAGMA foreign_keys = ON")

# ---------------- Global state ----------------
scanning_active = False
heartbeat_task = None

# ---------------- Helper DB functions ----------------
def db_user_exists(user_id: str) -> bool:
    try:
        row = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
        return bool(row)
    except Exception:
        return False

def db_get_user_servers(user_id: str) -> set:
    try:
        rows = conn.execute("SELECT server_id FROM user_servers WHERE user_id=?", (user_id,)).fetchall()
        return set(r[0] for r in rows)
    except Exception:
        return set()

def db_add_server(guild):
    if guild is None:
        return
    try:
        gid = str(guild.id)
        gname = guild.name if getattr(guild, "name", None) else gid
        conn.execute("INSERT OR REPLACE INTO servers (id, name) VALUES (?, ?)", (gid, gname))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

def db_set_checkpoint(channel_id: str, message_id: str):
    try:
        conn.execute("INSERT OR REPLACE INTO checkpoints (channel_id, last_message_id) VALUES (?, ?)", (str(channel_id), str(message_id)))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

def db_get_checkpoint(channel_id: str):
    try:
        row = conn.execute("SELECT last_message_id FROM checkpoints WHERE channel_id=?", (str(channel_id),)).fetchone()
        return row[0] if row else None
    except Exception:
        return None

# ---------------- Atomic add & log logic ----------------
def atomic_add_user_and_maybe_log(user, guild, action: str):
    """
    - If user NOT in DB: insert user + server + mapping, then write a single log line.
    - If user already in DB: ensure server mapping exists silently (no log).
    This function is designed to be safe for single-process use.
    """
    if user is None:
        return

    uid = str(user.id)
    gid = str(guild.id) if guild is not None else None
    gname = guild.name if guild is not None and getattr(guild, "name", None) else (gid or "Unknown")

    try:
        # start transaction
        conn.execute("BEGIN")
        exists = conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone()
        if not exists:
            # insert user
            conn.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (uid, str(user)))
            # ensure server and mapping
            if gid is not None:
                conn.execute("INSERT OR REPLACE INTO servers (id, name) VALUES (?, ?)", (gid, gname))
                conn.execute("INSERT OR IGNORE INTO user_servers (user_id, server_id) VALUES (?, ?)", (uid, gid))
            conn.commit()
            # log AFTER commit to guarantee DB state
            logger.info(f"{user} ({uid}) discovered in {gname} --- {action}")
        else:
            # user exists: silently ensure server & mapping
            if gid is not None:
                conn.execute("INSERT OR REPLACE INTO servers (id, name) VALUES (?, ?)", (gid, gname))
                conn.execute("INSERT OR IGNORE INTO user_servers (user_id, server_id) VALUES (?, ?)", (uid, gid))
                conn.commit()
            else:
                conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # best-effort fallback (try simple inserts)
        try:
            if not db_user_exists(uid):
                conn.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (uid, str(user)))
            if gid is not None:
                conn.execute("INSERT OR REPLACE INTO servers (id, name) VALUES (?, ?)", (gid, gname))
                conn.execute("INSERT OR IGNORE INTO user_servers (user_id, server_id) VALUES (?, ?)", (uid, gid))
            conn.commit()
            if not db_user_exists(uid):
                logger.info(f"{user} ({uid}) discovered in {gname} --- {action}")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

# ---------------- Discord Bot ----------------
bot = commands.Bot(command_prefix="!", self_bot=True)

# ---------------- Heartbeat (only while scanning_active True) ----------------
async def heartbeat():
    while scanning_active:
        try:
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            print(f"[heartbeat] users in DB: {total}  time: {datetime.utcnow().isoformat()}Z")
        except Exception:
            pass
        await asyncio.sleep(HEARTBEAT_SECONDS)

# ---------------- Scanning helpers (with checkpoints) ----------------
async def paginate_reaction_users(reaction, guild):
    try:
        async for user in reaction.users(limit=None):
            if getattr(user, "bot", False):
                continue
            atomic_add_user_and_maybe_log(user, guild, f"reacted {reaction.emoji}")
    except discord.HTTPException:
        await asyncio.sleep(1)
    except Exception:
        return

async def process_message_reactions_and_author(message, guild):
    # author
    try:
        if message.author and not getattr(message.author, "bot", False):
            atomic_add_user_and_maybe_log(message.author, guild, f"sent message id={message.id}")
    except Exception:
        pass

    # reactions
    try:
        for reaction in message.reactions:
            try:
                await paginate_reaction_users(reaction, guild)
            except Exception:
                await asyncio.sleep(1)
                continue
    except Exception:
        pass

async def scan_channel_history_with_checkpoint(channel, guild, msg_limit=None):
    """
    Scans a channel history using checkpoints.
    - If checkpoint exists: scan messages AFTER that checkpoint (newer messages) oldest_first.
    - If no checkpoint: scan full history oldest_first (so we process from oldest -> newest) and set checkpoint to last processed.
    """
    channel_id = str(channel.id)
    last_msg_id = db_get_checkpoint(channel_id)

    # build the iterator parameters
    try:
        if last_msg_id:
            # resume from last checkpoint, fetch messages after that (i.e., newer messages)
            after_obj = discord.Object(id=int(last_msg_id))
            async for message in channel.history(limit=msg_limit, after=after_obj, oldest_first=True):
                await process_message_reactions_and_author(message, guild)
                # update checkpoint as we go (so partial progress is preserved)
                try:
                    db_set_checkpoint(channel_id, str(message.id))
                except Exception:
                    pass
        else:
            # no checkpoint -> full historical scan from oldest to newest
            async for message in channel.history(limit=msg_limit, oldest_first=True):
                await process_message_reactions_and_author(message, guild)
                try:
                    db_set_checkpoint(channel_id, str(message.id))
                except Exception:
                    pass
    except discord.Forbidden:
        return
    except discord.NotFound:
        return
    except Exception:
        return

async def full_scan_guild_with_checkpoints(guild, msg_limit=None):
    try:
        db_add_server(guild)
    except Exception:
        pass

    for channel in guild.text_channels:
        await scan_channel_history_with_checkpoint(channel, guild, msg_limit=msg_limit)

    try:
        boosters = getattr(guild, "premium_subscribers", None)
        if boosters:
            for member in boosters:
                if member and not getattr(member, "bot", False):
                    atomic_add_user_and_maybe_log(member, guild, "is a booster")
    except Exception:
        pass

# ---------------- Live event handlers ----------------
@bot.event
async def on_ready():
    global scanning_active, heartbeat_task
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

    # choose mode
    choice = input("Mode: 1 → Target server scan + live, 2 → All servers scan + live, s → search tools\n> ").strip().lower()
    if choice == "1":
        try:
            sid = int(input("Enter target server ID: ").strip())
        except Exception:
            print("Invalid server id")
            await bot.close()
            return
        guild = bot.get_guild(sid)
        if guild is None:
            print("Guild not found or not cached.")
            await bot.close()
            return

        scanning_active = True
        heartbeat_task = bot.loop.create_task(heartbeat())
        try:
            await full_scan_guild_with_checkpoints(guild, msg_limit=None)
        finally:
            scanning_active = False
        print("Initial scan complete for target server. Now live-tracking.")

    elif choice == "2":
        scanning_active = True
        heartbeat_task = bot.loop.create_task(heartbeat())
        try:
            for g in bot.guilds:
                await full_scan_guild_with_checkpoints(g, msg_limit=None)
        finally:
            scanning_active = False
        print("Initial scan complete for all servers. Now live-tracking.")

    elif choice == "s":
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, search_menu)
        return
    else:
        print("Invalid choice, shutting down.")
        await bot.close()
        return

@bot.event
async def on_message(message):
    try:
        if message.author.bot:
            return
    except Exception:
        return
    if message.guild is None:
        return
    try:
        atomic_add_user_and_maybe_log(message.author, message.guild, f"sent message id={message.id}")
        # checkpoint update for channel in case this is newer than stored
        try:
            db_set_checkpoint(str(message.channel.id), str(message.id))
        except Exception:
            pass
    except Exception:
        pass

@bot.event
async def on_reaction_add(reaction, user):
    try:
        if user.bot:
            return
    except Exception:
        return
    guild = None
    try:
        msg = getattr(reaction, "message", None)
        guild = msg.guild if msg is not None else None
    except Exception:
        guild = None
    if guild is None:
        return
    try:
        atomic_add_user_and_maybe_log(user, guild, f"reacted {reaction.emoji} (live)")
        # update checkpoint to message id (live)
        try:
            db_set_checkpoint(str(reaction.message.channel.id), str(reaction.message.id))
        except Exception:
            pass
    except Exception:
        pass

@bot.event
async def on_member_join(member):
    try:
        if member.bot:
            return
    except Exception:
        return
    try:
        atomic_add_user_and_maybe_log(member, member.guild, "joined (live)")
    except Exception:
        pass

@bot.event
async def on_presence_update(before, after):
    try:
        if getattr(after, "bot", False):
            return
    except Exception:
        return
    try:
        guild = getattr(after, "guild", None)
        if guild is None:
            for g in bot.guilds:
                if g.get_member(after.id):
                    guild = g
                    break
        if guild is None:
            return
        atomic_add_user_and_maybe_log(after, guild, f"presence {getattr(after, 'status', None)}")
    except Exception:
        pass

# ---------------- Search utilities (blocking) ----------------
def search_menu():
    while True:
        print("\n===== SEARCH / TOOLS =====")
        print("1) Show total unique users")
        print("2) Search user by ID or name")
        print("3) Check duplicates in DB")
        print("4) Check duplicates in logs.txt")
        print("5) Remove duplicates from DB")
        print("6) Remove duplicates from logs.txt")
        print("7) Exit menu")
        print("8) Remove user by server ID ")
        c = input("> ").strip()
        if c == "1":
            try:
                total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                print(f"Total unique users (DB): {total}")
            except Exception as e:
                print("Error:", e)
        elif c == "2":
            q = input("Enter user ID or part of username: ").strip()
            try:
                rows = conn.execute("SELECT id, username FROM users WHERE id=? OR username LIKE ?", (q, f"%{q}%")).fetchall()
                if not rows:
                    print("No match")
                for r in rows:
                    print(f"{r[1]} ({r[0]})")
                    srv = conn.execute("SELECT s.name FROM user_servers us JOIN servers s ON us.server_id=s.id WHERE us.user_id=?", (r[0],)).fetchall()
                    print("Servers:", ", ".join([s[0] for s in srv]) if srv else "None")
            except Exception as e:
                print("Error:", e)
        elif c == "3":
            try:
                ids = [r[0] for r in conn.execute("SELECT id FROM users").fetchall()]
                dupes = set([x for x in ids if ids.count(x) > 1])
                if dupes:
                    print("Duplicates found in DB:", dupes)
                else:
                    print("No duplicates in DB")
            except Exception as e:
                print("Error:", e)
        elif c == "4":
            try:
                seen = set()
                dupes = []
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        if "(" in line and ")" in line:
                            uid = line.split("(")[-1].split(")")[0]
                            if uid in seen:
                                dupes.append(uid)
                            seen.add(uid)
                print(f"Duplicate lines in logs.txt: {len(dupes)}")
            except FileNotFoundError:
                print("logs.txt not found")
        elif c == "5":
            confirm = input("Type YES to remove duplicate user rows from DB: ").strip()
            if confirm == "YES":
                try:
                    ids_rows = conn.execute("SELECT id FROM users").fetchall()
                    ids = [r[0] for r in ids_rows]
                    seen = set()
                    to_remove = []
                    for uid in ids:
                        if uid in seen:
                            to_remove.append(uid)
                        seen.add(uid)
                    for uid in to_remove:
                        conn.execute("DELETE FROM user_servers WHERE user_id=?", (uid,))
                        conn.execute("DELETE FROM users WHERE id=?", (uid,))
                    conn.commit()
                    print(f"Removed {len(to_remove)} duplicate DB rows")
                except Exception as e:
                    print("Error:", e)
        elif c == "6":
            confirm = input("Type YES to dedupe logs.txt (keep first occurrence per user): ").strip()
            if confirm == "YES":
                try:
                    seen = set()
                    out = []
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        for line in f:
                            if "(" in line and ")" in line:
                                uid = line.split("(")[-1].split(")")[0]
                                if uid in seen:
                                    continue
                                seen.add(uid)
                            out.append(line)
                    with open(LOG_FILE, "w", encoding="utf-8") as f:
                        f.writelines(out)
                    print(f"Cleaned logs.txt; entries kept: {len(out)}")
                except FileNotFoundError:
                    print("logs.txt not found")
        elif c == "7":
            break
        
        elif c == "8":
            sid = input("Enter server ID to purge: ").strip()
            try:
                # Get all users linked to this server
                users = conn.execute("SELECT user_id FROM user_servers WHERE server_id=?", (sid,)).fetchall()
                removed_count = 0
                for (uid,) in users:
                    # Check how many servers this user is in
                    servers = conn.execute("SELECT COUNT(*) FROM user_servers WHERE user_id=?", (uid,)).fetchone()[0]
                    if servers <= 1:
                        # User only belongs to this server → remove user completely
                        conn.execute("DELETE FROM user_servers WHERE user_id=?", (uid,))
                        conn.execute("DELETE FROM users WHERE id=?", (uid,))
                        removed_count += 1
                    else:
                        # User is in multiple servers → remove only this mapping
                        conn.execute("DELETE FROM user_servers WHERE user_id=? AND server_id=?", (uid, sid))
                        removed_count += 1
                conn.execute("DELETE FROM servers WHERE id=?", (sid,))
                conn.commit()
                print(f"✅ Removed {removed_count} user-server relationships for server {sid}")
            except Exception as e:
                print("Error while purging server:", e)
        else:
            print("Invalid option")

# ---------------- Run ----------------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Interrupted by user — shutting down.")
    finally:
        try:
            conn.commit()
            conn.close()
        except Exception:
            pass
