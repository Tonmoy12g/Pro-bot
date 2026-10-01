# main.py — Gmail Sell Bot (Polling + Force Join + SQLite)
# পার্ট ১/৫ : Config + Database

import asyncio, json, logging, os, re, sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                            InlineKeyboardButton, BufferedInputFile)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

# ==========================================================
# CONFIG
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8913407701:AAERppuGL2DGi0CKJri7NOjjCgAhlgHKEBU")
PORT = int(os.getenv("PORT", "8080"))
DB_FILE = os.getenv("DB_FILE", "bot.db")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "8094164308").split(",") if x.strip().isdigit()]

DEFAULT_SETTINGS = {
    "bot_username": "gmailsells_bot",
    "refer_percent": "10",
    "min_wd_gmail": "20",
    "min_wd_refer": "50",
    "refer_charge": "10",
    "min_refers": "10",
    "warning_limit": "3",
    "support": "TrustVaultMails_Owner",
    "channel": "TrustVaultMailsOfficial",
    "recovery_email": "",
    "master_password": "",
    "maintenance": "0",
    "force_join": "0",
    "welcome": "🎉 বটে স্বাগতম!",
    "method_charges": "{}",
}

# ==========================================================
# DATABASE
# ==========================================================
class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self._migrate()
        self._seed()

    def _migrate(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT, first_name TEXT,
            gmail_wallet REAL DEFAULT 0,
            refer_wallet REAL DEFAULT 0,
            referred_by INTEGER,
            total_refers INTEGER DEFAULT 0,
            refer_income REAL DEFAULT 0,
            fake_warnings INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            is_new INTEGER DEFAULT 1,
            created_at TEXT);

        CREATE TABLE IF NOT EXISTS states (
            user_id INTEGER PRIMARY KEY,
            state TEXT);

        CREATE TABLE IF NOT EXISTS categories (
            key TEXT PRIMARY KEY,
            label TEXT,
            rate INTEGER DEFAULT 0,
            created_at TEXT);

        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail TEXT UNIQUE,
            password TEXT,
            category TEXT,
            added_at TEXT);

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            gmail TEXT,
            password TEXT,
            recovery TEXT,
            category TEXT,
            status TEXT,
            admin_msgs TEXT,
            created_at TEXT);

        CREATE TABLE IF NOT EXISTS used (
            gmail TEXT PRIMARY KEY,
            used_at TEXT);

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            user_id INTEGER,
            username TEXT,
            gmail TEXT,
            password TEXT,
            category TEXT,
            status TEXT,
            amount REAL,
            admin TEXT,
            timestamp TEXT);

        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            method TEXT,
            wallet TEXT,
            status TEXT,
            admin TEXT,
            timestamp TEXT);

        CREATE TABLE IF NOT EXISTS active_wd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            gross REAL,
            charge REAL,
            method TEXT,
            wallet TEXT,
            admin_msgs TEXT,
            created_at TEXT);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT);

        CREATE TABLE IF NOT EXISTS extra_admins (
            user_id INTEGER PRIMARY KEY);

        CREATE TABLE IF NOT EXISTS force_channels (
            channel TEXT PRIMARY KEY,
            added_at TEXT);
        """)
        self.conn.commit()

    def _seed(self):
        for k, v in DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)",
                (k, v))
        self.conn.commit()

    # ---------- settings ----------
    def get(self, key, default=""):
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self.conn.commit()

    def geti(self, key, default=0):
        try:
            return int(float(self.get(key, str(default))))
        except Exception:
            return default

    # ---------- force channels ----------
    def add_channel(self, ch):
        ch = ch.lower().lstrip("@").strip()
        if not ch:
            return False
        self.conn.execute(
            "INSERT OR IGNORE INTO force_channels (channel,added_at) VALUES (?,?)",
            (ch, datetime.now().isoformat()))
        self.conn.commit()
        return True

    def del_channel(self, ch):
        self.conn.execute(
            "DELETE FROM force_channels WHERE channel=?",
            (ch.lower().lstrip("@").strip(),))
        self.conn.commit()

    def channels(self):
        return [r["channel"] for r in
                self.conn.execute("SELECT channel FROM force_channels ORDER BY added_at").fetchall()]

    def force_join_on(self):
        return self.get("force_join", "0") == "1"

    # ---------- users ----------
    def user(self, uid):
        return self.conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

    def create_user(self, uid, uname, fname):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id,username,first_name,created_at) "
            "VALUES (?,?,?,?)",
            (uid, uname, fname, datetime.now().isoformat()))
        self.conn.commit()

    def upd_profile(self, uid, uname, fname):
        self.conn.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (uname, fname, uid))
        self.conn.commit()

    def is_banned(self, uid):
        r = self.conn.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
        return bool(r and r["banned"])

    def ban(self, uid, b):
        self.conn.execute(
            "UPDATE users SET banned=? WHERE user_id=?",
            (1 if b else 0, uid))
        self.conn.commit()

    def is_admin(self, uid):
        if uid in ADMIN_IDS:
            return True
        return self.conn.execute(
            "SELECT 1 FROM extra_admins WHERE user_id=?", (uid,)).fetchone() is not None

    def admins(self):
        ids = set(ADMIN_IDS)
        for r in self.conn.execute("SELECT user_id FROM extra_admins").fetchall():
            ids.add(r["user_id"])
        return list(ids)

    def add_admin(self, uid):
        self.conn.execute("INSERT OR IGNORE INTO extra_admins (user_id) VALUES (?)", (uid,))
        self.conn.commit()

    def del_admin(self, uid):
        self.conn.execute("DELETE FROM extra_admins WHERE user_id=?", (uid,))
        self.conn.commit()

    def extra_admins(self):
        return [r["user_id"] for r in
                self.conn.execute("SELECT user_id FROM extra_admins").fetchall()]

    # ---------- states ----------
    def state(self, uid):
        r = self.conn.execute("SELECT state FROM states WHERE user_id=?", (uid,)).fetchone()
        return r["state"] if r else ""

    def set_state(self, uid, s):
        self.conn.execute(
            "INSERT INTO states (user_id,state) VALUES (?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state",
            (uid, s))
        self.conn.commit()

    # ---------- categories ----------
    def cats(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM categories ORDER BY created_at").fetchall()]

    def cat(self, key):
        return self.conn.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()

    def add_cat(self, key, label, rate):
        self.conn.execute(
            "INSERT OR REPLACE INTO categories (key,label,rate,created_at) "
            "VALUES (?,?,?,?)",
            (key, label, rate, datetime.now().isoformat()))
        self.conn.commit()

    def del_cat(self, key):
        self.conn.execute("DELETE FROM categories WHERE key=?", (key,))
        self.conn.commit()

    def set_cat_rate(self, key, rate):
        self.conn.execute("UPDATE categories SET rate=? WHERE key=?", (rate, key))
        self.conn.commit()

    # ---------- stock ----------
    def add_stock(self, gmail, pwd, cat="old"):
        try:
            self.conn.execute(
                "INSERT INTO stock (gmail,password,category,added_at) VALUES (?,?,?,?)",
                (gmail, pwd, cat, datetime.now().isoformat()))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def stock_count(self):
        return self.conn.execute("SELECT COUNT(*) c FROM stock").fetchone()["c"]

    def stock_list(self, limit=500):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM stock LIMIT ?", (limit,)).fetchall()]

    def del_stock(self, gmail):
        c = self.conn.execute(
            "DELETE FROM stock WHERE LOWER(gmail)=?",
            (gmail.lower().strip(),))
        self.conn.commit()
        return c.rowcount

    def clear_stock(self):
        c = self.stock_count()
        self.conn.execute("DELETE FROM stock")
        self.conn.commit()
        return c

    # ---------- duplicate check ----------
    def used(self, gmail):
        g = gmail.lower().strip()
        if self.conn.execute("SELECT 1 FROM used WHERE gmail=?", (g,)).fetchone():
            return True
        if self.conn.execute("SELECT 1 FROM tasks WHERE LOWER(gmail)=?", (g,)).fetchone():
            return True
        return False

    def mark_used(self, gmail):
        self.conn.execute(
            "INSERT OR IGNORE INTO used (gmail,used_at) VALUES (?,?)",
            (gmail.lower().strip(), datetime.now().isoformat()))
        self.conn.commit()

    # ---------- tasks ----------
    def new_task(self, uid, gmail, pwd, rec, cat):
        c = self.conn.execute(
            "INSERT INTO tasks (user_id,gmail,password,recovery,category,status,created_at) "
            "VALUES (?,?,?,?,?,'submitted',?)",
            (uid, gmail, pwd, rec, cat, datetime.now().isoformat()))
        self.conn.commit()
        return c.lastrowid

    def task(self, tid):
        return self.conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

    def task_msgs(self, tid, msgs):
        self.conn.execute(
            "UPDATE tasks SET admin_msgs=? WHERE id=?",
            (json.dumps(msgs), tid))
        self.conn.commit()

    def del_task(self, tid):
        self.conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.conn.commit()

    # ---------- history ----------
    def add_history(self, tid, uid, uname, gmail, pwd, cat, status, amount, admin):
        self.conn.execute(
            "INSERT INTO history (task_id,user_id,username,gmail,password,category,"
            "status,amount,admin,timestamp) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, uid, uname, gmail, pwd, cat, status, amount, admin,
             datetime.now().isoformat()))
        self.conn.commit()

    def history(self, limit=200):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?",
                                  (limit,)).fetchall()]

    def user_history(self, uid, limit=30):
        return [dict(r) for r in
                self.conn.execute(
                    "SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                    (uid, limit)).fetchall()]

    # ---------- wallets ----------
    def add_wallet(self, uid, field, amt):
        if field not in ("gmail_wallet", "refer_wallet"):
            return
        self.conn.execute(
            f"UPDATE users SET {field}={field}+? WHERE user_id=?",
            (amt, uid))
        self.conn.commit()

    def set_wallet(self, uid, field, val):
        if field not in ("gmail_wallet", "refer_wallet"):
            return
        self.conn.execute(
            f"UPDATE users SET {field}=? WHERE user_id=?",
            (val, uid))
        self.conn.commit()

    def add_refer_income(self, uid, amt):
        self.conn.execute(
            "UPDATE users SET refer_wallet=refer_wallet+?, "
            "refer_income=refer_income+? WHERE user_id=?",
            (amt, amt, uid))
        self.conn.commit()

    def add_referral(self, ref_id, new_uid):
        self.conn.execute(
            "UPDATE users SET total_refers=total_refers+1 WHERE user_id=?",
            (ref_id,))
        self.conn.execute(
            "UPDATE users SET referred_by=?, is_new=0 WHERE user_id=?",
            (ref_id, new_uid))
        self.conn.commit()

    def set_not_new(self, uid):
        self.conn.execute("UPDATE users SET is_new=0 WHERE user_id=?", (uid,))
        self.conn.commit()

    def inc_warning(self, uid):
        self.conn.execute(
            "UPDATE users SET fake_warnings=fake_warnings+1 WHERE user_id=?",
            (uid,))
        self.conn.commit()
        r = self.conn.execute(
            "SELECT fake_warnings FROM users WHERE user_id=?", (uid,)).fetchone()
        return r["fake_warnings"] if r else 0

    # ---------- withdrawals ----------
    def new_wd(self, uid, amt, gross, chg, method, wallet):
        c = self.conn.execute(
            "INSERT INTO active_wd (user_id,amount,gross,charge,method,wallet,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, amt, gross, chg, method, wallet, datetime.now().isoformat()))
        self.conn.commit()
        return c.lastrowid

    def wd(self, wid):
        return self.conn.execute("SELECT * FROM active_wd WHERE id=?", (wid,)).fetchone()

    def wd_msgs(self, wid, msgs):
        self.conn.execute(
            "UPDATE active_wd SET admin_msgs=? WHERE id=?",
            (json.dumps(msgs), wid))
        self.conn.commit()

    def del_wd(self, wid):
        self.conn.execute("DELETE FROM active_wd WHERE id=?", (wid,))
        self.conn.commit()

    def add_wd_history(self, uid, uname, amt, method, wallet, status, admin):
        self.conn.execute(
            "INSERT INTO withdrawals (user_id,amount,method,wallet,status,admin,timestamp) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, amt, method, wallet, status, admin, datetime.now().isoformat()))
        self.conn.commit()

    def wd_history(self, limit=200):
        return [dict(r) for r in
                self.conn.execute(
                    "SELECT * FROM withdrawals ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()]

    # ---------- misc ----------
    def total_users(self):
        return self.conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    def all_uids(self):
        return [r["user_id"] for r in
                self.conn.execute("SELECT user_id FROM users").fetchall()]

    def find_uname(self, uname):
        r = self.conn.execute(
            "SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)",
            (uname.lstrip("@").strip(),)).fetchone()
        return r["user_id"] if r else None

    def top_refs(self, limit=20):
        return [dict(r) for r in
                self.conn.execute(
                    "SELECT user_id,username,first_name,total_refers,refer_income "
                    "FROM users WHERE total_refers>0 "
                    "ORDER BY total_refers DESC LIMIT ?",
                    (limit,)).fetchall()]

    def zero_all_wallets(self):
        self.conn.execute("UPDATE users SET gmail_wallet=0, refer_wallet=0")
        self.conn.commit()


db = DB(DB_FILE)
# ==========================================================
# পার্ট ২/৫ : Helpers + Keyboards + Telegram Utilities
# ==========================================================

GMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@gmail\.com$", re.IGNORECASE)


def valid_gmail(s):
    return bool(GMAIL_RE.match((s or "").strip()))


def esc(t):
    if t is None:
        return ""
    s = str(t)
    for c in ("\\", "_", "*", "`", "["):
        s = s.replace(c, "\\" + c)
    return s


def udisplay(uid, row=None):
    if row is None:
        row = db.user(int(uid))
    if row:
        if row["username"]:
            return "@" + row["username"]
        if row["first_name"]:
            return f"{row['first_name']} (ID: {uid})"
    return f"ID: {uid}"


def bot_username():
    return db.get("bot_username", "gmailsells_bot")


def refer_pct(): return db.geti("refer_percent", 10)
def min_wd_g(): return db.geti("min_wd_gmail", 20)
def min_wd_r(): return db.geti("min_wd_refer", 50)
def ref_charge(): return db.geti("refer_charge", 10)
def min_refs(): return db.geti("min_refers", 10)
def warn_limit(): return db.geti("warning_limit", 3)
def support_u(): return db.get("support", "TrustVaultMails_Owner")
def channel_u(): return db.get("channel", "TrustVaultMailsOfficial")
def recovery_email(): return db.get("recovery_email", "")
def master_password(): return db.get("master_password", "")
def maintenance(): return db.get("maintenance", "0") == "1"
def force_join_on(): return db.force_join_on()
def welcome(): return db.get("welcome", "🎉 বটে স্বাগতম!")


def method_charge(m):
    try:
        return int(json.loads(db.get("method_charges", "{}")).get(m, 0))
    except Exception:
        return 0


def set_method_charge(m, v):
    try:
        c = json.loads(db.get("method_charges", "{}"))
    except Exception:
        c = {}
    c[m] = v
    db.set("method_charges", json.dumps(c))


# ---------- Bot / Dispatcher ----------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)) if BOT_TOKEN else None
dp = Dispatcher()
router = Router()


# ==========================================================
# KEYBOARDS
# ==========================================================

def kb_main(is_admin):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👤 প্রোফাইল", callback_data="profile"),
        InlineKeyboardButton(text="🔗 রেফার", callback_data="refer"),
    )
    b.row(InlineKeyboardButton(text="♻️ Old Gmail জমা দিন", callback_data="submit"))
    b.row(
        InlineKeyboardButton(text="💳 উইথড্র", callback_data="withdraw"),
        InlineKeyboardButton(text="📊 স্ট্যাটস", callback_data="stats"),
    )
    b.row(InlineKeyboardButton(text="🆘 সাপোর্ট", callback_data="support"))
    if is_admin:
        b.row(InlineKeyboardButton(text="⚙️ অ্যাডমিন প্যানেল", callback_data="admin"))
    return b.as_markup()


def kb_back(target="main_menu", text="🔙 মেইন মেন্যু"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=text, callback_data=target))
    return b.as_markup()


def kb_cancel(target="main_menu"):
    return kb_back(target, "❌ বাতিল")


def kb_support():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🧑‍💻 অ্যাডমিন", url=f"https://t.me/{support_u()}"))
    b.row(InlineKeyboardButton(text="📢 চ্যানেল", url=f"https://t.me/{channel_u()}"))
    b.row(InlineKeyboardButton(text="🔙 মেইন মেন্যু", callback_data="main_menu"))
    return b.as_markup()


# ---------- FORCE JOIN KEYBOARD ----------
def kb_force_join(missing_channels):
    """
    missing_channels: লিস্ট — যেসব চ্যানেলে ইউজার এখনো join করেনি।
    """
    b = InlineKeyboardBuilder()
    for ch in missing_channels:
        b.row(InlineKeyboardButton(
            text=f"📢 @{ch} — যোগ দিন",
            url=f"https://t.me/{ch.lstrip('@')}",
        ))
    b.row(InlineKeyboardButton(
        text="✅ যোগ দিয়েছি, চেক করুন",
        callback_data="check_join",
    ))
    return b.as_markup()


def kb_categories_for_submit():
    """'Old Gmail জমা দিন' এ ক্লিক করার পর ক্যাটাগরি লিস্ট।"""
    cats = db.cats()
    b = InlineKeyboardBuilder()
    if not cats:
        b.row(InlineKeyboardButton(
            text="⚠️ এখনো কোনো ক্যাটাগরি নেই",
            callback_data="noop"))
    else:
        for c in cats:
            b.row(InlineKeyboardButton(
                text=f"{c['label']} — {c['rate']}৳",
                callback_data=f"sub_cat_{c['key']}",
            ))
    b.row(InlineKeyboardButton(text="❌ বাতিল", callback_data="main_menu"))
    return b.as_markup()


def kb_admin_panel():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📦 স্টক যোগ", callback_data="a_stock_add"))
    b.row(InlineKeyboardButton(text="🗑️ স্টক ম্যানেজ", callback_data="a_stock_mg"))
    b.row(InlineKeyboardButton(text="🗂️ ক্যাটাগরি ম্যানেজ", callback_data="a_cat_menu"))
    b.row(InlineKeyboardButton(text="🤖 বট Username সেট", callback_data="a_bot_uname"))
    b.row(InlineKeyboardButton(text="📢 Force Join চ্যানেল ম্যানেজ", callback_data="a_force_menu"))
    b.row(InlineKeyboardButton(text="🔐 মাস্টার পাসওয়ার্ড সেট", callback_data="a_master_pw"))
    b.row(InlineKeyboardButton(text="💌 রিকভারি ইমেইল সেট", callback_data="a_recovery"))
    b.row(InlineKeyboardButton(text="💵 উইথড্র লিমিট", callback_data="a_limits"))
    b.row(InlineKeyboardButton(text="💳 মেথড চার্জ", callback_data="a_mcharges"))
    b.row(InlineKeyboardButton(text="⚠️ ওয়ার্নিং লিমিট", callback_data="a_warn"))
    b.row(InlineKeyboardButton(text="🚫 ইউজার ব্যান", callback_data="a_ban"))
    b.row(InlineKeyboardButton(text="🔍 ইউজার লুকআপ", callback_data="a_lookup"))
    b.row(InlineKeyboardButton(text="💰 ব্যালেন্স ম্যানেজ", callback_data="a_bal_menu"))
    b.row(InlineKeyboardButton(text="👑 অ্যাডমিন ম্যানেজ", callback_data="a_admins"))
    b.row(InlineKeyboardButton(text="🔗 রেফার কমিশন", callback_data="a_comm"))
    b.row(InlineKeyboardButton(text="📞 সাপোর্ট/চ্যানেল", callback_data="a_contact"))
    b.row(InlineKeyboardButton(text="🚧 মেইনটেন্যান্স", callback_data="a_maint"))
    b.row(InlineKeyboardButton(text="💾 ব্যাকআপ", callback_data="a_backup"))
    b.row(InlineKeyboardButton(text="📜 জিমেইল হিস্টোরি", callback_data="a_ghist"))
    b.row(InlineKeyboardButton(text="💳 পেমেন্ট হিস্টোরি", callback_data="a_whist"))
    b.row(InlineKeyboardButton(text="🏆 টপ রেফারার", callback_data="a_top"))
    b.row(InlineKeyboardButton(text="📢 ব্রডকাস্ট", callback_data="a_bc"))
    b.row(InlineKeyboardButton(text="🔙 মেইন মেন্যু", callback_data="main_menu"))
    return b.as_markup()


def kb_admin_stock():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📃 স্টক লিস্ট", callback_data="a_stock_view"))
    b.row(InlineKeyboardButton(text="🗑️ ডিলিট", callback_data="a_stock_del"))
    b.row(InlineKeyboardButton(text="🧹 সব ক্লিয়ার", callback_data="a_stock_clear"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_stock_clear_ok():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ হ্যাঁ", callback_data="a_stock_clear_ok"),
        InlineKeyboardButton(text="❌ না", callback_data="a_stock_mg"),
    )
    return b.as_markup()


def kb_admin_cat_menu():
    b = InlineKeyboardBuilder()
    for c in db.cats():
        b.row(InlineKeyboardButton(
            text=f"🗑️ {c['label']} ({c['rate']}৳)",
            callback_data=f"a_cat_del_{c['key']}",
        ))
    b.row(InlineKeyboardButton(text="➕ নতুন ক্যাটাগরি", callback_data="a_cat_add"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_cat_del_confirm(key):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ হ্যাঁ, মুছুন", callback_data=f"a_cat_delok_{key}"),
        InlineKeyboardButton(text="❌ না", callback_data="a_cat_menu"),
    )
    return b.as_markup()


# ---------- FORCE JOIN CHANNEL MANAGEMENT ----------
def kb_admin_force_menu():
    b = InlineKeyboardBuilder()
    chs = db.channels()
    for ch in chs:
        b.row(InlineKeyboardButton(
            text=f"➖ @{ch} — বাদ দিন",
            callback_data=f"a_force_del_{ch}",
        ))
    b.row(InlineKeyboardButton(text="➕ নতুন চ্যানেল যোগ", callback_data="a_force_add"))
    status = "✅ চালু আছে" if force_join_on() else "❌ বন্ধ আছে"
    b.row(InlineKeyboardButton(
        text=f"⏯️ Force Join: {status} (টগল)",
        callback_data="a_force_toggle",
    ))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_force_del_confirm(ch):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ হ্যাঁ, বাদ দিন", callback_data=f"a_force_delok_{ch}"),
        InlineKeyboardButton(text="❌ না", callback_data="a_force_menu"),
    )
    return b.as_markup()


def kb_admin_limits():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=f"📧 জিমেইল মিন: {min_wd_g()}৳",
        callback_data="a_setlim_gmail"))
    b.row(InlineKeyboardButton(
        text=f"🔗 রেফার মিন: {min_wd_r()}৳",
        callback_data="a_setlim_refer"))
    b.row(InlineKeyboardButton(
        text=f"🔗 রেফার চার্জ: {ref_charge()}৳",
        callback_data="a_setlim_charge"))
    b.row(InlineKeyboardButton(
        text=f"🔗 ন্যূনতম রেফার: {min_refs()} জন",
        callback_data="a_setlim_minrefs"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_mcharges():
    b = InlineKeyboardBuilder()
    for m, label in (("bkash", "বিকাশ"), ("nagad", "নগদ"), ("rocket", "রকেট")):
        b.row(InlineKeyboardButton(
            text=f"{label}: {method_charge(m)}৳",
            callback_data=f"a_setmc_{m}"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_contact():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🧑‍💻 সাপোর্ট পরিবর্তন", callback_data="a_setsup"))
    b.row(InlineKeyboardButton(text="📢 চ্যানেল পরিবর্তন", callback_data="a_setch"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_admins():
    b = InlineKeyboardBuilder()
    for aid in db.extra_admins():
        b.row(InlineKeyboardButton(
            text=f"➖ {aid} — বাদ দিন",
            callback_data=f"a_deladmin_{aid}"))
    b.row(InlineKeyboardButton(text="➕ নতুন অ্যাডমিন", callback_data="a_addadmin"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_warn():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏️ পরিবর্তন", callback_data="a_setwarn"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_bal_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 ইউজার আইডি দিয়ে সার্চ", callback_data="a_bal_search"))
    b.row(InlineKeyboardButton(text="🧹 সব ইউজারের ব্যালেন্স ০ করুন", callback_data="a_bal_zero"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_bal_zero_ok():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ হ্যাঁ, সব ০ করুন", callback_data="a_bal_zero_ok"),
        InlineKeyboardButton(text="❌ না", callback_data="a_bal_menu"),
    )
    return b.as_markup()


def kb_admin_editbal(uid):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📧 জিমেইল ওয়ালেট",
        callback_data=f"a_ebal_g_{uid}"))
    b.row(InlineKeyboardButton(
        text="🔗 রেফার ওয়ালেট",
        callback_data=f"a_ebal_r_{uid}"))
    b.row(InlineKeyboardButton(text="🔙 অ্যাডমিন", callback_data="admin"))
    return b.as_markup()


def kb_admin_job(tid):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Accept", callback_data=f"aj_{tid}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"rj_{tid}"),
    )
    return b.as_markup()


def kb_admin_wd(wid):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Paid", callback_data=f"aw_{wid}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"rw_{wid}"),
    )
    return b.as_markup()


def kb_wallet_choice(g_bal, r_bal):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=f"📧 জিমেইল ({g_bal:g}৳)",
        callback_data="w_g"))
    b.row(InlineKeyboardButton(
        text=f"🔗 রেফার ({r_bal:g}৳)",
        callback_data="w_r"))
    b.row(InlineKeyboardButton(text="❌ বাতিল", callback_data="main_menu"))
    return b.as_markup()


def kb_payment(kind):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="বিকাশ", callback_data=f"pm_bkash_{kind}"),
        InlineKeyboardButton(text="নগদ", callback_data=f"pm_nagad_{kind}"),
    )
    b.row(InlineKeyboardButton(text="রকেট", callback_data=f"pm_rocket_{kind}"))
    b.row(InlineKeyboardButton(text="❌ বাতিল", callback_data="main_menu"))
    return b.as_markup()


# ==========================================================
# TELEGRAM HELPERS
# ==========================================================

async def send(chat, text, **kw):
    try:
        return await bot.send_message(chat, text, **kw)
    except Exception as e:
        log.warning(f"send fail {chat}: {e}")
        return None


async def edit(cb, text, **kw):
    try:
        return await cb.message.edit_text(text, **kw)
    except Exception:
        try:
            return await cb.message.answer(text, **kw)
        except Exception as e:
            log.warning(f"edit fail: {e}")
            return None


async def answer(cb, text="", alert=False):
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:
        pass


async def send_chunked(chat, header, lines, markup=None):
    chunks = []
    cur = header
    for ln in lines:
        cand = ln if cur == "" else cur + "\n\n" + ln
        if len(cand) > 3500:
            chunks.append(cur)
            cur = ln
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    if not chunks:
        chunks = [header]
    last = len(chunks) - 1
    for i, ch in enumerate(chunks):
        payload = {"chat_id": chat, "text": ch, "parse_mode": ParseMode.MARKDOWN}
        if i == last and markup:
            payload["reply_markup"] = markup
        try:
            await bot.send_message(**payload)
        except Exception as e:
            log.warning(f"chunked fail: {e}")


# ==========================================================
# FORCE JOIN CHECK
# ==========================================================

async def user_in_channel(uid: int, channel: str) -> bool:
    try:
        member = await bot.get_chat_member(
            chat_id=f"@{channel.lstrip('@')}", user_id=uid)
        return member.status not in ("left", "kicked")
    except Exception as e:
        log.warning(f"channel check failed @{channel}: {e}")
        # চেক করতে ব্যর্থ হলে ব্লক না করে পার হওয়াই ভালো
        return True


async def check_all_channels(uid: int):
    """সব চ্যানেল চেক করে যেগুলোতে নেই সেগুলোর লিস্ট দেয়।"""
    missing = []
    for ch in db.channels():
        if not await user_in_channel(uid, ch):
            missing.append(ch)
    return missing
# ==========================================================
# পার্ট ৩/৫ : User Handlers + Force Join
# ==========================================================

@router.message(CommandStart())
async def cmd_start(m: Message):
    uid = m.from_user.id
    row = db.user(uid)
    if row is None:
        db.create_user(uid, m.from_user.username, m.from_user.first_name)
    else:
        db.upd_profile(uid, m.from_user.username, m.from_user.first_name)

    # Ban চেক
    if db.is_banned(uid) and not db.is_admin(uid):
        await m.answer("🚫 আপনাকে ব্যান করা হয়েছে। সাপোর্টে যোগাযোগ করুন।")
        return

    # Maintenance চেক
    if maintenance() and not db.is_admin(uid):
        await m.answer("🚧 বট রক্ষণাবেক্ষণে আছে। পরে চেষ্টা করুন।")
        return

    # ---------- FORCE JOIN CHECK ----------
    if force_join_on() and not db.is_admin(uid):
        missing = await check_all_channels(uid)
        if missing:
            ch_list = "\n".join(f"• @{ch}" for ch in missing)
            await m.answer(
                f"📢 **প্রথমে আমাদের চ্যানেলে যোগ দিন!**\n\n"
                f"বট ব্যবহার করতে হলে নিচের চ্যানেলগুলোতে join করতে হবে:\n\n"
                f"{ch_list}\n\n"
                f"যোগ দেওয়ার পর ✅ বাটনে ক্লিক করুন 👇",
                reply_markup=kb_force_join(missing))
            return

    # ---------- REFERRAL ----------
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip().isdigit():
        ref = int(parts[1].strip())
        row = db.user(uid)
        if row and row["is_new"] and ref != uid and db.user(ref):
            db.add_referral(ref, uid)
            try:
                await bot.send_message(
                    ref,
                    f"🎉 আপনার রেফার লিংক দিয়ে কেউ জয়েন করেছে!\n"
                    f"সে কাজ সম্পন্ন করলে আপনি {refer_pct()}% কমিশন পাবেন।")
            except Exception:
                pass
        else:
            db.set_not_new(uid)

    # ---------- WELCOME ----------
    await m.answer(
        f"{welcome()}\n\n"
        f"♻️ Old Gmail জমা দিয়ে আয় করুন\n"
        f"🔗 রেফার করে {refer_pct()}% কমিশন নিন\n"
        f"💳 বিকাশ/নগদ/রকেটে উইথড্র করুন\n\n"
        f"👇 শুরু করুন:",
        reply_markup=kb_main(db.is_admin(uid)))


# ---------- FORCE JOIN "যোগ দিয়েছি" বাটন ----------
@router.callback_query(F.data == "check_join")
async def cb_check_join(cb: CallbackQuery):
    uid = cb.from_user.id

    if not force_join_on():
        await answer(cb, "✅ Force Join বন্ধ আছে", alert=True)
        return

    missing = await check_all_channels(uid)
    if missing:
        ch_list = "\n".join(f"• @{ch}" for ch in missing)
        await answer(cb, f"❌ আপনি এখনো যোগ দেননি:\n{ch_list}", alert=True)
        return

    await answer(cb, "✅ ধন্যবাদ! এখন বট ব্যবহার করতে পারবেন।", alert=True)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.message.answer(
        f"{welcome()}\n\n👇 শুরু করুন:",
        reply_markup=kb_main(db.is_admin(uid)))


# ---------- MAIN MENU ----------
@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery):
    uid = cb.from_user.id
    if db.is_banned(uid) and not db.is_admin(uid):
        await answer(cb, "🚫 আপনি ব্যান হয়েছেন।", alert=True)
        return
    db.set_state(uid, "")
    await answer(cb)
    await edit(cb,
               "✨ **মেইন মেন্যু** ✨\n\nএকটা অপশন বেছে নিন 👇",
               reply_markup=kb_main(db.is_admin(uid)))


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await answer(cb)


# ---------- PROFILE ----------
@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    uid = cb.from_user.id
    await answer(cb)
    r = db.user(uid)
    if not r:
        await edit(cb, "❌ /start দিন।")
        return
    g = r["gmail_wallet"] or 0
    rw = r["refer_wallet"] or 0
    total = g + rw
    await edit(cb,
        f"👤 **আপনার প্রোফাইল**\n\n"
        f"📧 জিমেইল সেল ওয়ালেট: `{g:g}` টাকা\n"
        f"🔗 রেফারেল ওয়ালেট: `{rw:g}` টাকা\n"
        f"💰 মোট ব্যালেন্স: `{total:g}` টাকা\n"
        f"👥 মোট রেফার: `{r['total_refers']}` জন\n"
        f"⚠️ ওয়ার্নিং: `{r['fake_warnings']}/{warn_limit()}`\n"
        f"🆔 ইউজার আইডি: `{uid}`",
        reply_markup=kb_back())


# ---------- REFER ----------
@router.callback_query(F.data == "refer")
async def cb_refer(cb: CallbackQuery):
    uid = cb.from_user.id
    await answer(cb)
    r = db.user(uid)
    link = f"https://t.me/{bot_username()}?start={uid}"
    await edit(cb,
        f"🎁 **My Referrals**\n\n"
        f"👤 Total Refer: `{r['total_refers']}`\n"
        f"💵 Total Refer Income: `{r['refer_income']:g}` টাকা\n"
        f"🔗 রেফারেল ওয়ালেট: `{r['refer_wallet']:g}` টাকা\n\n"
        f"🔗 **আপনার রেফার লিংক:**\n`{link}`\n\n"
        f"ℹ️ আপনার প্রতিটা রেফারের সম্পূর্ণ করা কাজ থেকে আয়ের "
        f"**{refer_pct()}%** কমিশন পাবেন।",
        reply_markup=kb_back())


# ---------- SUPPORT ----------
@router.callback_query(F.data == "support")
async def cb_support(cb: CallbackQuery):
    await answer(cb)
    await edit(cb,
               "🆘 **সাপোর্ট সেন্টার**\n\nনিচের বাটন থেকে যোগাযোগ করুন 👇",
               reply_markup=kb_support())


# ---------- STATS ----------
@router.callback_query(F.data == "stats")
async def cb_stats(cb: CallbackQuery):
    await answer(cb)
    await edit(cb,
        f"📊 **বট স্ট্যাটিস্টিকস**\n\n"
        f"👥 মোট মেম্বার: `{db.total_users()}` জন\n"
        f"📦 স্টকে জিমেইল: `{db.stock_count()}` টি\n"
        f"🗂️ ক্যাটাগরি: `{len(db.cats())}` টি",
        reply_markup=kb_back())


# ==========================================================
# SUBMIT — ক্যাটাগরি → মাস্টার পাসওয়ার্ড + রিকভারি → Gmail
# ==========================================================

@router.callback_query(F.data == "submit")
async def cb_submit(cb: CallbackQuery):
    uid = cb.from_user.id
    if db.is_banned(uid) and not db.is_admin(uid):
        await answer(cb, "🚫 আপনি ব্যান হয়েছেন।", alert=True)
        return

    cats = db.cats()
    if not cats:
        await answer(cb, "⚠️ অ্যাডমিন এখনো কোনো ক্যাটাগরি যোগ করেননি।", alert=True)
        return

    if not recovery_email():
        await answer(cb, "⚠️ অ্যাডমিন রিকভারি ইমেইল সেট করেননি।", alert=True)
        return
    if not master_password():
        await answer(cb, "⚠️ অ্যাডমিন মাস্টার পাসওয়ার্ড সেট করেননি।", alert=True)
        return

    await answer(cb)
    await edit(cb,
               "♻️ **Old Gmail জমা দিন**\n\n"
               "কোন ধরনের Gmail জমা দিতে চান? নিচে থেকে বেছে নিন 👇",
               reply_markup=kb_categories_for_submit())


@router.callback_query(F.data.startswith("sub_cat_"))
async def cb_submit_category(cb: CallbackQuery):
    uid = cb.from_user.id
    key = cb.data.replace("sub_cat_", "", 1)
    c = db.cat(key)
    if not c:
        await answer(cb, "❌ ক্যাটাগরি পাওয়া যায়নি", alert=True)
        return

    rec = recovery_email()
    mp = master_password()
    db.set_state(uid, f"w_gmail_{key}")

    await answer(cb)
    await edit(cb,
        f"♻️ **{esc(c['label'])}** — জমা দিন\n\n"
        f"⚠️ **গুরুত্বপূর্ণ:** জমা দেওয়ার আগে আপনার Gmail-এ "
        f"নিচের দুটো জিনিস সেট করুন:\n\n"
        f"💌 **রিকভারি ইমেইল:** `{esc(rec)}`\n"
        f"🔐 **Gmail পাসওয়ার্ড:** `{esc(mp)}`\n\n"
        f"📝 **এরপর শুধু আপনার Gmail এড্রেসটি লিখে পাঠান।**\n\n"
        f"উদাহরণ:\n`myemail@gmail.com`\n\n"
        f"💵 রেট: **{c['rate']} টাকা**",
        reply_markup=kb_cancel())


@router.message(F.text, lambda m: db.state(m.from_user.id).startswith("w_gmail_"))
async def handle_gmail_submit(m: Message):
    uid = m.from_user.id
    state = db.state(uid)
    text = (m.text or "").strip()
    db.set_state(uid, "")

    if db.is_banned(uid) and not db.is_admin(uid):
        await m.answer("🚫 আপনি ব্যান হয়েছেন।")
        return

    cat_key = state.replace("w_gmail_", "", 1)
    c = db.cat(cat_key)
    if not c:
        await m.answer("❌ ক্যাটাগরি পাওয়া যায়নি। আবার শুরু করুন।",
                       reply_markup=kb_back())
        return

    if not valid_gmail(text):
        await m.answer(
            "⚠️ এটা বৈধ Gmail (`@gmail.com`) নয়।\n\n"
            "শুধু Gmail এড্রেস পাঠান, যেমন:\n`myemail@gmail.com`",
            reply_markup=kb_cancel())
        return

    if db.used(text):
        await m.answer(
            f"❌ **এই Gmail অ্যাকাউন্টটি ইতিমধ্যে জমা দেওয়া হয়েছে!**\n\n"
            f"`{esc(text)}` — এটা আগে Accept হয়েছে বা এখনো রিভিউতে আছে।\n"
            f"একই অ্যাকাউন্ট বারবার জমা দেওয়া যাবে না।",
            reply_markup=kb_back())
        return

    rec = recovery_email()
    mp = master_password()
    tid = db.new_task(uid, text, mp, rec, cat_key)
    dn = udisplay(uid)

    admin_text = (
        f"♻️ **{esc(c['label'])} — ইউজার জমা দিয়েছেন!** (টাস্ক #{tid})\n\n"
        f"👤 ইউজার: **{esc(dn)}**\n"
        f"📨 জিমেইল: `{esc(text)}`\n"
        f"🔐 পাসওয়ার্ড: `{esc(mp)}`\n"
        f"💌 রিকভারি: `{esc(rec)}`\n"
        f"💵 রেট: `{c['rate']}` টাকা\n\n"
        f"(মেইলটি লগইন করে চেক করে বাটনে অ্যাকশন নিন)"
    )

    msgs = []
    for a in db.admins():
        s = await send(a, admin_text, reply_markup=kb_admin_job(tid))
        if s:
            msgs.append({"c": str(a), "m": str(s.message_id)})
    db.task_msgs(tid, msgs)

    await m.answer(
        "✅ আপনার কাজটি সফলভাবে জমা হয়েছে।\n\n"
        "এটি বর্তমানে অ্যাডমিন রিভিউতে আছে। অনুমোদিত হলে "
        "২৪ ঘণ্টার মধ্যে আপনার ব্যালেন্সে টাকা যোগ হবে।",
        reply_markup=kb_back())


# ==========================================================
# WITHDRAW
# ==========================================================

@router.callback_query(F.data == "withdraw")
async def cb_withdraw(cb: CallbackQuery):
    uid = cb.from_user.id
    await answer(cb)
    r = db.user(uid)
    if not r:
        await edit(cb, "❌ /start দিন।")
        return
    g = r["gmail_wallet"] or 0
    rw = r["refer_wallet"] or 0
    await edit(cb,
        f"💳 **কোন ওয়ালেট থেকে উইথড্র করবেন?**\n\n"
        f"📧 জিমেইল সেল: `{g:g}` টাকা (মিন: `{min_wd_g()}`)\n"
        f"🔗 রেফারেল: `{rw:g}` টাকা (মিন: `{min_wd_r()}`, "
        f"চার্জ: `{ref_charge()}`, ন্যূনতম রেফার: `{min_refs()}`)",
        reply_markup=kb_wallet_choice(g, rw))


@router.callback_query(F.data.in_({"w_g", "w_r"}))
async def cb_wallet_choice(cb: CallbackQuery):
    uid = cb.from_user.id
    kind = "gmail" if cb.data == "w_g" else "refer"
    r = db.user(uid)
    field = "gmail_wallet" if kind == "gmail" else "refer_wallet"
    bal = r[field] or 0
    mn = min_wd_g() if kind == "gmail" else min_wd_r()
    label = "জিমেইল সেল" if kind == "gmail" else "রেফারেল"

    if kind == "refer":
        if (r["total_refers"] or 0) < min_refs():
            await answer(cb,
                f"❌ রেফারেল উইথড্রর জন্য কমপক্ষে {min_refs()} জন রেফার লাগবে। "
                f"আপনার আছে {r['total_refers']} জন।", alert=True)
            return

    if bal < mn:
        await answer(cb,
            f"❌ {label} ওয়ালেটে পর্যাপ্ত ব্যালেন্স নেই! কমপক্ষে {mn} টাকা লাগবে।",
            alert=True)
        return

    await answer(cb)
    await edit(cb,
               f"💳 **পেমেন্ট মেথড বেছে নিন** ({label})",
               reply_markup=kb_payment(kind))


@router.callback_query(F.data.startswith("pm_"))
async def cb_payment_method(cb: CallbackQuery):
    uid = cb.from_user.id
    rest = cb.data[3:]
    parts = rest.split("_", 1)
    method, kind = parts[0], parts[1]
    db.set_state(uid, f"w_wallet_{method}_{kind}")
    await answer(cb)
    label = {"bkash": "বিকাশ", "nagad": "নগদ", "rocket": "রকেট"}[method]
    await edit(cb,
               f"📥 আপনার **{label}** পার্সোনাল নম্বরটি লিখে পাঠান:",
               reply_markup=kb_cancel())


@router.message(F.text, lambda m: db.state(m.from_user.id).startswith("w_wallet_"))
async def handle_wallet_number(m: Message):
    uid = m.from_user.id
    state = db.state(uid)
    text = (m.text or "").strip()
    db.set_state(uid, "")

    rest = state.replace("w_wallet_", "", 1)
    parts = rest.split("_", 1)
    method, kind = parts[0], parts[1]
    field = "gmail_wallet" if kind == "gmail" else "refer_wallet"
    label = "📧 জিমেইল সেল" if kind == "gmail" else "🔗 রেফারেল"

    r = db.user(uid)
    bal = r[field] or 0
    base_charge = ref_charge() if kind == "refer" else 0
    total_charge = base_charge + method_charge(method)
    net_amount = max(0, bal - total_charge)

    wid = db.new_wd(uid, net_amount, bal, total_charge, method, text)
    db.set_wallet(uid, field, 0)
    dn = udisplay(uid)

    method_label = {"bkash": "বিকাশ", "nagad": "নগদ", "rocket": "রকেট"}[method]
    charge_note = (
        f"\n💸 চার্জ: `{total_charge:g}` টাকা\n"
        f"💵 প্রদেয় (নেট): **{net_amount:g} টাকা**"
        if total_charge > 0 else "")

    admin_text = (
        f"🚨 **নতুন উইথড্র রিকোয়েস্ট!** (আইডি #{wid})\n\n"
        f"👤 ইউজার: **{esc(dn)}**\n"
        f"🗂️ ওয়ালেট: {label}\n"
        f"💳 মেথড: **{method_label}**\n"
        f"📞 নম্বর: `{esc(text)}`\n"
        f"💰 মোট ব্যালেন্স: **{bal:g} টাকা**{charge_note}"
    )

    msgs = []
    for a in db.admins():
        s = await send(a, admin_text, reply_markup=kb_admin_wd(wid))
        if s:
            msgs.append({"c": str(a), "m": str(s.message_id)})
    db.wd_msgs(wid, msgs)

    await m.answer(
        f"✅ **রিকোয়েস্ট পাঠানো হয়েছে!**{charge_note}\n\n"
        f"অ্যাডমিন টাকা পাঠানোর পর আপনাকে জানানো হবে।",
        reply_markup=kb_back())
# ==========================================================
# পার্ট ৪-ক : Admin Panel + Bot Username + Stock
# ==========================================================

def is_admin_cb(cb) -> bool:
    return db.is_admin(cb.from_user.id)


@router.callback_query(F.data == "admin")
async def cb_admin(cb: CallbackQuery):
    if not is_admin_cb(cb):
        await answer(cb, "❌ আপনি অ্যাডমিন নন।", alert=True)
        return
    await answer(cb)
    fj_status = "✅ চালু" if force_join_on() else "❌ বন্ধ"
    await edit(
        cb,
        f"👑 **অ্যাডমিন কন্ট্রোল প্যানেল**\n\n"
        f"📦 স্টক: `{db.stock_count()}` টি\n"
        f"🗂️ ক্যাটাগরি: `{len(db.cats())}` টি\n"
        f"🤖 বট Username: `@{esc(bot_username())}`\n"
        f"📢 Force Join: {fj_status} — `{len(db.channels())}` চ্যানেল\n"
        f"💌 রিকভারি: `{esc(recovery_email() or '(সেট হয়নি)')}`\n"
        f"🔐 মাস্টার পাসওয়ার্ড: `{esc(master_password() or '(সেট হয়নি)')}`\n\n"
        f"একটা অপশন বেছে নিন 👇",
        reply_markup=kb_admin_panel())


@router.callback_query(F.data == "a_bot_uname")
async def cb_bot_uname(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_bot_uname")
    await answer(cb)
    await edit(
        cb,
        f"🤖 **বট Username সেট করুন**\n\n"
        f"বর্তমান: `@{esc(bot_username())}`\n\n"
        f"ℹ️ এটা referral লিংকের জন্য দরকার।\n"
        f"নতুন username লিখে পাঠান (@ ছাড়া)।\n\n"
        f"উদাহরণ: `TrustVaultMailsBot`",
        reply_markup=kb_cancel("admin"))


@router.callback_query(F.data == "a_stock_add")
async def cb_stock_add(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_stock")
    await answer(cb)
    await edit(
        cb,
        "📝 **জিমেইল স্টকে যোগ করুন**\n\n"
        "ফরম্যাট:\n`ইমেইল:পাসওয়ার্ড`\n\n"
        "একাধিক হলে প্রতি লাইনে একটা:\n"
        "`a@gmail.com:pass1\nb@gmail.com:pass2`",
        reply_markup=kb_cancel("admin"))


@router.callback_query(F.data == "a_stock_mg")
async def cb_stock_mg(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        f"🗑️ **স্টক ম্যানেজমেন্ট**\n\nবর্তমানে: `{db.stock_count()}` টি জিমেইল",
        reply_markup=kb_admin_stock())


@router.callback_query(F.data == "a_stock_view")
async def cb_stock_view(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    items = db.stock_list(limit=500)
    if not items:
        await edit(cb, "📃 স্টক খালি।",
                   reply_markup=kb_back("a_stock_mg", "🔙 স্টক ম্যানেজ"))
        return
    lines = [f"{i}. `{esc(it['gmail'])}`" for i, it in enumerate(items, 1)]
    await edit(cb, f"📃 পাঠানো হচ্ছে... (মোট {len(items)} টি)",
               reply_markup=kb_back("a_stock_mg", "🔙 স্টক ম্যানেজ"))
    await send_chunked(cb.from_user.id,
                       f"📃 **স্টক লিস্ট** (মোট {len(items)} টি)", lines)


@router.callback_query(F.data == "a_stock_del")
async def cb_stock_del(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_stockdel")
    await answer(cb)
    await edit(
        cb,
        "🗑️ **ডিলিট করুন**\n\nএকাধিক হলে প্রতি লাইনে একটা:\n"
        "`a@gmail.com\nb@gmail.com`",
        reply_markup=kb_cancel("a_stock_mg"))


@router.callback_query(F.data == "a_stock_clear")
async def cb_stock_clear(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        f"⚠️ সম্পূর্ণ স্টক (`{db.stock_count()}` টি) ক্লিয়ার করবেন?\n\n"
        f"ফিরিয়ে আনা যাবে না।",
        reply_markup=kb_admin_stock_clear_ok())


@router.callback_query(F.data == "a_stock_clear_ok")
async def cb_stock_clear_ok(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    n = db.clear_stock()
    await answer(cb, "🧹 ক্লিয়ার হয়েছে")
    await edit(cb,
               f"🧹 সম্পূর্ণ স্টক ক্লিয়ার! (`{n}` টি মুছে ফেলা হয়েছে)",
               reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
# ==========================================================
# পার্ট ৪-খ : Category + Force Join + Password + Balance
# ==========================================================

# ==========================================================
# CATEGORY MANAGEMENT
# ==========================================================

@router.callback_query(F.data == "a_cat_menu")
async def cb_cat_menu(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        "🗂️ **ক্যাটাগরি ম্যানেজমেন্ট**\n\n"
        "ইউজাররা 'Old Gmail জমা দিন' বাটনে ক্লিক করলে এই ক্যাটাগরিগুলো দেখবে।\n"
        "মুছতে চাইলে সেটাতে ট্যাপ করুন।",
        reply_markup=kb_admin_cat_menu())


@router.callback_query(F.data == "a_cat_add")
async def cb_cat_add(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_cat_add")
    await answer(cb)
    await edit(
        cb,
        "➕ **নতুন ক্যাটাগরি যোগ করুন**\n\n"
        "ফরম্যাট:\n`নাম | রেট`\n\n"
        "উদাহরণ:\n"
        "`1 Month Old | 25`\n"
        "`2 Month Old | 30`",
        reply_markup=kb_cancel("a_cat_menu"))


@router.callback_query(F.data.startswith("a_cat_delok_"))
async def cb_cat_delok(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    key = cb.data.replace("a_cat_delok_", "", 1)
    db.del_cat(key)
    await answer(cb, "✅ মুছে ফেলা হয়েছে")
    await edit(cb,
               "🗑️ ক্যাটাগরি মুছে ফেলা হয়েছে।",
               reply_markup=kb_back("a_cat_menu", "🔙 ক্যাটাগরি মেনু"))


@router.callback_query(F.data.startswith("a_cat_del_"))
async def cb_cat_del(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    key = cb.data.replace("a_cat_del_", "", 1)
    c = db.cat(key)
    if not c:
        await answer(cb, "❌ পাওয়া যায়নি", alert=True)
        return
    await answer(cb)
    await edit(
        cb,
        f"⚠️ **{esc(c['label'])}** ক্যাটাগরি মুছবেন?",
        reply_markup=kb_admin_cat_del_confirm(key))


# ==========================================================
# FORCE JOIN MANAGEMENT
# ==========================================================

@router.callback_query(F.data == "a_force_menu")
async def cb_force_menu(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    chs = db.channels()
    if chs:
        ch_list = "\n".join(f"• @{ch}" for ch in chs)
    else:
        ch_list = "(এখনো কোনো চ্যানেল নেই)"
    status = "✅ **চালু আছে**" if force_join_on() else "❌ **বন্ধ আছে**"

    await edit(
        cb,
        f"📢 **Force Join চ্যানেল ম্যানেজ**\n\n"
        f"অবস্থা: {status}\n\n"
        f"**চ্যানেল তালিকা:**\n{ch_list}\n\n"
        f"ℹ️ চ্যানেল Public হতে হবে, এবং বটকে Admin বানাতে হবে।",
        reply_markup=kb_admin_force_menu())


@router.callback_query(F.data == "a_force_add")
async def cb_force_add(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_force_add")
    await answer(cb)
    await edit(
        cb,
        "➕ **নতুন Force Join চ্যানেল যোগ**\n\n"
        "চ্যানেলের username লিখে পাঠান (@ ছাড়া)।\n\n"
        "উদাহরণ:\n`TrustVaultMailsOfficial`\n\n"
        "⚠️ চ্যানেল অবশ্যই Public হতে হবে।",
        reply_markup=kb_cancel("a_force_menu"))


@router.callback_query(F.data == "a_force_toggle")
async def cb_force_toggle(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    new_state = not force_join_on()
    db.set("force_join", "1" if new_state else "0")
    await answer(cb, "✅ টগল হয়েছে")
    status = "✅ চালু" if new_state else "❌ বন্ধ"
    await edit(cb,
               f"Force Join এখন **{status}**।",
               reply_markup=kb_back("a_force_menu", "🔙 Force Join মেনু"))


@router.callback_query(F.data.startswith("a_force_delok_"))
async def cb_force_delok(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    ch = cb.data.replace("a_force_delok_", "", 1)
    db.del_channel(ch)
    await answer(cb, "✅ বাদ দেওয়া হয়েছে")
    await edit(cb,
               f"🗑️ @{esc(ch)} বাদ দেওয়া হয়েছে।",
               reply_markup=kb_back("a_force_menu", "🔙 Force Join মেনু"))


@router.callback_query(F.data.startswith("a_force_del_"))
async def cb_force_del(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    ch = cb.data.replace("a_force_del_", "", 1)
    if ch not in db.channels():
        await answer(cb, "❌ পাওয়া যায়নি", alert=True)
        return
    await answer(cb)
    await edit(
        cb,
        f"⚠️ @{esc(ch)} বাদ দেবেন?",
        reply_markup=kb_admin_force_del_confirm(ch))


# ==========================================================
# MASTER PASSWORD + RECOVERY EMAIL
# ==========================================================

@router.callback_query(F.data == "a_master_pw")
async def cb_master_pw(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_master_pw")
    await answer(cb)
    await edit(
        cb,
        f"🔐 **মাস্টার পাসওয়ার্ড সেট**\n\n"
        f"বর্তমান: `{esc(master_password() or '(সেট হয়নি)')}`\n\n"
        f"নতুন পাসওয়ার্ড লিখে পাঠান।\n\n"
        f"ℹ️ ইউজাররা এই পাসওয়ার্ডটি নিজের Gmail-এ সেট করবে এবং "
        f"শুধু Gmail এড্রেস জমা দেবে।",
        reply_markup=kb_cancel("admin"))


@router.callback_query(F.data == "a_recovery")
async def cb_set_recovery(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_recovery")
    await answer(cb)
    await edit(
        cb,
        f"💌 **ডিফল্ট রিকভারি ইমেইল**\n\n"
        f"বর্তমান: `{esc(recovery_email() or '(সেট হয়নি)')}`\n\n"
        f"নতুন রিকভারি ইমেইল লিখে পাঠান।",
        reply_markup=kb_cancel("admin"))


# ==========================================================
# LIMITS / METHOD CHARGES / WARNING
# ==========================================================

@router.callback_query(F.data == "a_limits")
async def cb_limits(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(cb,
               "💵 **উইথড্র লিমিট**\n\nপরিবর্তন করতে ট্যাপ করুন:",
               reply_markup=kb_admin_limits())


@router.callback_query(F.data.startswith("a_setlim_"))
async def cb_setlim(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    key = cb.data.replace("a_setlim_", "", 1)
    if key not in ("gmail", "refer", "charge", "minrefs"):
        await answer(cb, "❌ ভুল", alert=True)
        return
    db.set_state(cb.from_user.id, f"a_w_lim_{key}")
    await answer(cb)
    labels = {
        "gmail": "জিমেইল মিনিমাম",
        "refer": "রেফার মিনিমাম",
        "charge": "রেফার চার্জ",
        "minrefs": "ন্যূনতম রেফার",
    }
    await edit(cb,
               f"💵 **{labels[key]}**\n\nনতুন মান (শুধু সংখ্যা):",
               reply_markup=kb_cancel("a_limits"))


@router.callback_query(F.data == "a_mcharges")
async def cb_mcharges(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(cb,
               "💳 **মেথড চার্জ (টাকা)**\n\nপ্রতিটা মেথডে বাড়তি চার্জ কাটা হবে।",
               reply_markup=kb_admin_mcharges())


@router.callback_query(F.data.startswith("a_setmc_"))
async def cb_setmc(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    m = cb.data.replace("a_setmc_", "", 1)
    if m not in ("bkash", "nagad", "rocket"):
        await answer(cb, "❌ ভুল", alert=True)
        return
    db.set_state(cb.from_user.id, f"a_w_mc_{m}")
    await answer(cb)
    await edit(cb,
               f"💳 **{m} চার্জ**\n\nনতুন চার্জ (০ দিলে চার্জ নেই):",
               reply_markup=kb_cancel("a_mcharges"))


@router.callback_query(F.data == "a_warn")
async def cb_warn(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        f"⚠️ **ওয়ার্নিং লিমিট**\n\nবর্তমান: `{warn_limit()}` বার\n\n"
        f"ℹ️ এতবার Reject হলে ইউজার অটো ব্যান হবে।",
        reply_markup=kb_admin_warn())


@router.callback_query(F.data == "a_setwarn")
async def cb_setwarn(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_warn")
    await answer(cb)
    await edit(cb,
               "⚠️ নতুন ওয়ার্নিং লিমিট (কমপক্ষে ১):",
               reply_markup=kb_cancel("a_warn"))


# ==========================================================
# BAN / LOOKUP
# ==========================================================

@router.callback_query(F.data == "a_ban")
async def cb_ban(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_ban")
    await answer(cb)
    await edit(
        cb,
        "🚫 **ইউজার ব্যান/আনব্যান**\n\nইউজার **আইডি** পাঠান।\n"
        "ℹ️ ব্যান থাকলে আনব্যান হবে, না থাকলে ব্যান হবে।",
        reply_markup=kb_cancel("admin"))


@router.callback_query(F.data == "a_lookup")
async def cb_lookup(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_lookup")
    await answer(cb)
    await edit(cb,
               "🔍 **ইউজার লুকআপ**\n\nইউজার **আইডি** পাঠান।",
               reply_markup=kb_cancel("admin"))


# ==========================================================
# BALANCE MANAGEMENT
# ==========================================================

@router.callback_query(F.data == "a_bal_menu")
async def cb_bal_menu(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        "💰 **ব্যালেন্স ম্যানেজমেন্ট**\n\n"
        "ℹ️ এখান থেকে যেকোনো ইউজারের ব্যালেন্স যোগ/কাট করতে পারবেন "
        "এবং সব ইউজারের ব্যালেন্স ০ করতে পারবেন।",
        reply_markup=kb_admin_bal_menu())


@router.callback_query(F.data == "a_bal_search")
async def cb_bal_search(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_bal_search")
    await answer(cb)
    await edit(cb,
               "🔍 যার ব্যালেন্স পরিবর্তন করবেন তার **ইউজার আইডি** পাঠান:",
               reply_markup=kb_cancel("a_bal_menu"))


@router.callback_query(F.data == "a_bal_zero")
async def cb_bal_zero(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        f"⚠️ **সব ইউজারের ব্যালেন্স ০ করতে চান?**\n\n"
        f"মোট ইউজার: `{db.total_users()}` জন\n\n"
        f"এই কাজটি ফিরিয়ে আনা যাবে না!",
        reply_markup=kb_admin_bal_zero_ok())


@router.callback_query(F.data == "a_bal_zero_ok")
async def cb_bal_zero_ok(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.zero_all_wallets()
    await answer(cb, "✅ সব ব্যালেন্স ০ করা হয়েছে")
    await edit(cb,
               f"🧹 সব ইউজারের ব্যালেন্স ০ করা হয়েছে।",
               reply_markup=kb_back("a_bal_menu", "🔙 ব্যালেন্স মেনু"))


@router.callback_query(F.data.startswith("a_ebal_g_"))
async def cb_editbal_g(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    uid = cb.data.replace("a_ebal_g_", "", 1)
    db.set_state(cb.from_user.id, f"a_w_ebal_g_{uid}")
    await answer(cb)
    await edit(cb,
               "✍️ কত টাকা? (কমাতে চাইলে সামনে - দিন):",
               reply_markup=kb_cancel("admin"))


@router.callback_query(F.data.startswith("a_ebal_r_"))
async def cb_editbal_r(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    uid = cb.data.replace("a_ebal_r_", "", 1)
    db.set_state(cb.from_user.id, f"a_w_ebal_r_{uid}")
    await answer(cb)
    await edit(cb,
               "✍️ কত টাকা? (কমাতে চাইলে সামনে - দিন):",
               reply_markup=kb_cancel("admin"))


# ==========================================================
# ADMINS / COMMISSION / CONTACT / MAINTENANCE
# ==========================================================

@router.callback_query(F.data == "a_admins")
async def cb_admins(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    core = "\n".join(f"👑 `{a}` (মূল)" for a in ADMIN_IDS if a)
    await edit(
        cb,
        f"👑 **অ্যাডমিন ম্যানেজমেন্ট**\n\n{core}\n\n"
        f"ℹ️ মূল অ্যাডমিন বাদ দেওয়া যাবে না।",
        reply_markup=kb_admin_admins())


@router.callback_query(F.data == "a_addadmin")
async def cb_addadmin(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_addadmin")
    await answer(cb)
    await edit(cb,
               "➕ নতুন অ্যাডমিনের **টেলিগ্রাম আইডি** পাঠান:",
               reply_markup=kb_cancel("a_admins"))


@router.callback_query(F.data.startswith("a_deladmin_"))
async def cb_deladmin(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    try:
        target = int(cb.data.replace("a_deladmin_", "", 1))
    except ValueError:
        await answer(cb, "❌ ভুল", alert=True)
        return
    db.del_admin(target)
    await answer(cb, "✅ বাদ দেওয়া হয়েছে")
    await edit(cb,
               f"✅ `{target}`-কে বাদ দেওয়া হয়েছে।",
               reply_markup=kb_back("a_admins", "🔙 অ্যাডমিন ম্যানেজ"))


@router.callback_query(F.data == "a_comm")
async def cb_comm(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_comm")
    await answer(cb)
    await edit(cb,
               f"🔗 **রেফার কমিশন**\n\nবর্তমান: `{refer_pct()}%`\n\n"
               f"নতুন % (০-১০০):",
               reply_markup=kb_cancel("admin"))


@router.callback_query(F.data == "a_contact")
async def cb_contact(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    await edit(
        cb,
        f"📞 **সাপোর্ট/চ্যানেল**\n\n"
        f"🧑‍💻 সাপোর্ট: @{esc(support_u())}\n"
        f"📢 চ্যানেল: @{esc(channel_u())}",
        reply_markup=kb_admin_contact())


@router.callback_query(F.data == "a_setsup")
async def cb_setsup(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_sup")
    await answer(cb)
    await edit(cb,
               "✍️ নতুন সাপোর্ট ইউজারনেম (@ ছাড়া):",
               reply_markup=kb_cancel("a_contact"))


@router.callback_query(F.data == "a_setch")
async def cb_setch(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_ch")
    await answer(cb)
    await edit(cb,
               "✍️ নতুন চ্যানেল ইউজারনেম (@ ছাড়া):",
               reply_markup=kb_cancel("a_contact"))


@router.callback_query(F.data == "a_maint")
async def cb_maint(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    new_state = not maintenance()
    db.set("maintenance", "1" if new_state else "0")
    await answer(cb, "✅ টগল হয়েছে")
    status = "🚧 চালু" if new_state else "✅ বন্ধ"
    await edit(cb,
               f"মেইনটেন্যান্স মোড এখন **{status}**।",
               reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
# ==========================================================
# পার্ট ৪-গ : Backup + History + Top + Broadcast
# ==========================================================

@router.callback_query(F.data == "a_backup")
async def cb_backup(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb, "💾 ব্যাকআপ পাঠানো হচ্ছে...")
    try:
        with open(DB_FILE, "rb") as f:
            data = f.read()
        fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        await bot.send_document(
            cb.from_user.id,
            BufferedInputFile(data, filename=fname),
            caption=f"💾 ডাটাবেস ব্যাকআপ — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        )
    except Exception as e:
        await bot.send_message(cb.from_user.id, f"❌ ব্যাকআপ ব্যর্থ: {e}")


@router.callback_query(F.data == "a_ghist")
async def cb_ghist(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    h = db.history(limit=100)
    if not h:
        await edit(cb, "📜 এখনো কোনো জিমেইল Accept/Reject হয়নি।",
                   reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return
    lines = []
    for x in h:
        icon = "🟢" if x["status"] == "accepted" else "🔴"
        lines.append(
            f"{icon} #{x['task_id']} — {x['status'].capitalize()}\n"
            f"👤 {esc(x['username'])}\n"
            f"?? `{esc(x['gmail'])}`\n"
            f"🗂️ {esc(x.get('category', '') or 'old')}\n"
            f"👑 {esc(x['admin'])}\n"
            f"🕐 {x['timestamp'][:19]}")
    await edit(cb, f"📜 জিমেইল হিস্টোরি (মোট {len(h)}টি) পাঠানো হচ্ছে...",
               reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
    await send_chunked(cb.from_user.id,
                       f"📜 **জিমেইল হিস্টোরি** (মোট {len(h)}টি)", lines)


@router.callback_query(F.data == "a_whist")
async def cb_whist(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    h = db.wd_history(limit=100)
    if not h:
        await edit(cb, "💳 এখনো কোনো উইথড্র হয়নি।",
                   reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return
    lines = []
    for x in h:
        icon = "🟢" if x["status"] == "approved" else "🔴"
        lines.append(
            f"{icon} #{x['id']} — {x['status'].capitalize()}\n"
            f"👤 ID: `{x['user_id']}`\n"
            f"💰 `{x['amount']:g}` টাকা — {x['method']}\n"
            f"📞 `{esc(x['wallet'])}`\n"
            f"👑 {esc(x['admin'])}\n"
            f"🕐 {x['timestamp'][:19]}")
    await edit(cb, f"💳 পেমেন্ট হিস্টোরি (মোট {len(h)}টি) পাঠানো হচ্ছে...",
               reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
    await send_chunked(cb.from_user.id,
                       f"💳 **পেমেন্ট হিস্টোরি** (মোট {len(h)}টি)", lines)


@router.callback_query(F.data == "a_top")
async def cb_top(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    await answer(cb)
    tops = db.top_refs(limit=20)
    if not tops:
        await edit(cb, "🏆 এখনো কোনো রেফারার নেই।",
                   reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return
    lines = []
    for i, t in enumerate(tops, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        name = udisplay(t["user_id"], t)
        lines.append(f"{medal} {esc(name)}\n   👥 {t['total_refers']} | 💰 {t['refer_income']:g}৳")
    await edit(cb, "🏆 **টপ রেফারার**",
               reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
    await send_chunked(cb.from_user.id,
                       "🏆 **টপ রেফারার র‍্যাঙ্কিং**", lines)


@router.callback_query(F.data == "a_bc")
async def cb_bc(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    db.set_state(cb.from_user.id, "a_w_bc")
    await answer(cb)
    await edit(
        cb,
        "📢 **ব্রডকাস্ট নোটিশ**\n\n"
        "যে মেসেজটি সব ইউজারের কাছে পাঠাতে চান সেটি পাঠান।\n"
        "টেক্সট, ছবি, ভিডিও — যেকোনো কিছু পাঠাতে পারেন।",
        reply_markup=kb_cancel("admin"))
# ==========================================================
# পার্ট ৫A/৫ : Job Accept/Reject + Withdraw Paid/Reject
# ==========================================================

@router.callback_query(F.data.startswith("aj_"))
async def cb_accept_job(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    try:
        tid = int(cb.data.replace("aj_", "", 1))
    except ValueError:
        await answer(cb, "❌ ভুল", alert=True); return

    task = db.task(tid)
    if not task:
        await answer(cb, "⚠️ এই টাস্ক ইতিমধ্যে প্রসেস হয়েছে।", alert=True)
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    target_uid = task["user_id"]
    gmail = task["gmail"]
    pwd = task["password"]
    cat_key = task["category"] or "old"
    c = db.cat(cat_key)
    rate = c["rate"] if c else 0

    db.add_wallet(target_uid, "gmail_wallet", rate)
    db.mark_used(gmail)
    db.del_task(tid)

    u = db.user(target_uid)
    referrer_id = u["referred_by"] if u else None
    if referrer_id and db.user(referrer_id):
        comm = round(rate * refer_pct() / 100, 2)
        db.add_refer_income(referrer_id, comm)
        try:
            await bot.send_message(
                referrer_id,
                f"💰 আপনার রেফারের কাজ অনুমোদিত!\nকমিশন: **{comm:g} টাকা**")
        except Exception:
            pass

    dn = udisplay(target_uid, u)
    admin_name = udisplay(cb.from_user.id, None)
    db.add_history(tid, target_uid, dn, gmail, pwd, cat_key, "accepted", rate, admin_name)

    try:
        await bot.send_message(
            target_uid,
            f"✅ **অভিনন্দন!** আপনার Gmail অনুমোদিত হয়েছে।\n"
            f"💰 **{rate} টাকা** জিমেইল সেল ওয়ালেটে যোগ হয়েছে।")
    except Exception:
        pass

    await answer(cb, "✅ Accept হয়েছে")
    await cb.message.edit_text(
        f"🟢 **জিমেইল Accept!** (টাস্ক #{tid})\n\n"
        f"ইউজার: {esc(dn)}\n💰 {rate} টাকা দেওয়া হয়েছে।",
        reply_markup=None)

    try:
        msgs = json.loads(task["admin_msgs"] or "[]")
    except Exception:
        msgs = []
    for mm in msgs:
        if str(mm.get("c")) == str(cb.from_user.id): continue
        try:
            await bot.edit_message_text(
                chat_id=int(mm["c"]),
                message_id=int(mm["m"]),
                text=f"🟢 **Accept হয়ে গেছে** (টাস্ক #{tid})\n{esc(admin_name)} এক্সেপ্ট করেছেন।",
                reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("rj_"))
async def cb_reject_job(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    try:
        tid = int(cb.data.replace("rj_", "", 1))
    except ValueError:
        await answer(cb, "❌ ভুল", alert=True); return

    task = db.task(tid)
    if not task:
        await answer(cb, "⚠️ ইতিমধ্যে প্রসেস হয়েছে।", alert=True)
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    target_uid = task["user_id"]
    gmail = task["gmail"]
    pwd = task["password"]
    cat_key = task["category"] or "old"
    db.del_task(tid)

    warn = db.inc_warning(target_uid)
    lim = warn_limit()
    auto_ban = False
    if warn >= lim:
        db.ban(target_uid, True)
        auto_ban = True

    u = db.user(target_uid)
    dn = udisplay(target_uid, u)
    admin_name = udisplay(cb.from_user.id, None)
    db.add_history(tid, target_uid, dn, gmail, pwd, cat_key, "rejected", 0, admin_name)

    if auto_ban:
        try:
            await bot.send_message(
                target_uid,
                f"🚫 **আপনাকে অটো-ব্যান করা হয়েছে!**\n"
                f"বারবার ({lim} বার) ভুয়া/অচল জিমেইল জমা দিয়েছেন।")
        except Exception:
            pass
        note = f"\n\n🚫 ইউজার অটো-ব্যান হয়েছে (ওয়ার্নিং {warn}/{lim})।"
    else:
        try:
            await bot.send_message(
                target_uid,
                f"❌ **দুঃখিত!** আপনার জিমেইল বাতিল হয়েছে।\n"
                f"⚠️ ওয়ার্নিং: {warn}/{lim}")
        except Exception:
            pass
        note = f"\n⚠️ ওয়ার্নিং: {warn}/{lim}"

    await answer(cb, "❌ Reject হয়েছে")
    await cb.message.edit_text(
        f"🔴 **জিমেইল Reject!** (টাস্ক #{tid})\n\n"
        f"ইউজার: {esc(dn)}{note}",
        reply_markup=None)

    try:
        msgs = json.loads(task["admin_msgs"] or "[]")
    except Exception:
        msgs = []
    for mm in msgs:
        if str(mm.get("c")) == str(cb.from_user.id): continue
        try:
            await bot.edit_message_text(
                chat_id=int(mm["c"]),
                message_id=int(mm["m"]),
                text=f"🔴 **Reject হয়ে গেছে** (টাস্ক #{tid})\n{esc(admin_name)} রিজেক্ট করেছেন।{note}",
                reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("aw_"))
async def cb_paid_wd(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    try:
        wid = int(cb.data.replace("aw_", "", 1))
    except ValueError:
        await answer(cb, "❌ ভুল", alert=True); return

    wd = db.wd(wid)
    if not wd:
        await answer(cb, "⚠️ ইতিমধ্যে প্রসেস হয়েছে।", alert=True)
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    target_uid = wd["user_id"]
    amount = wd["amount"]
    method = wd["method"]
    db.del_wd(wid)

    u = db.user(target_uid)
    dn = udisplay(target_uid, u)
    admin_name = udisplay(cb.from_user.id, None)
    db.add_wd_history(target_uid, dn, amount, method, wd["wallet"], "approved", admin_name)

    try:
        await bot.send_message(
            target_uid,
            f"✅ **অভিনন্দন!**\n\nআপনার **{amount:g} টাকা**-এর উইথড্র পেমেন্ট সম্পন্ন হয়েছে। 🎉")
    except Exception:
        pass

    await answer(cb, "✅ Paid")
    await cb.message.edit_text(
        f"🟢 **পেমেন্ট কমপ্লিট!** (আইডি #{wid})\n\n"
        f"ইউজার: {esc(dn)} — {amount:g} টাকা পেমেন্ট দেওয়া হয়েছে।",
        reply_markup=None)

    try:
        msgs = json.loads(wd["admin_msgs"] or "[]")
    except Exception:
        msgs = []
    for mm in msgs:
        if str(mm.get("c")) == str(cb.from_user.id): continue
        try:
            await bot.edit_message_text(
                chat_id=int(mm["c"]),
                message_id=int(mm["m"]),
                text=f"🟢 **পেমেন্ট কমপ্লিট** (আইডি #{wid})\n{esc(admin_name)} পেমেন্ট করেছেন।",
                reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("rw_"))
async def cb_reject_wd(cb: CallbackQuery):
    if not is_admin_cb(cb): return
    try:
        wid = int(cb.data.replace("rw_", "", 1))
    except ValueError:
        await answer(cb, "❌ ভুল", alert=True); return

    wd = db.wd(wid)
    if not wd:
        await answer(cb, "⚠️ ইতিমধ্যে প্রসেস হয়েছে।", alert=True)
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        return

    target_uid = wd["user_id"]
    refund = wd["gross"]
    method = wd["method"]
    db.del_wd(wid)

    u = db.user(target_uid)
    dn = udisplay(target_uid, u)
    admin_name = udisplay(cb.from_user.id, None)

    db.add_wallet(target_uid, "gmail_wallet", refund)
    db.add_wd_history(target_uid, dn, refund, method, wd["wallet"], "rejected", admin_name)

    try:
        await bot.send_message(
            target_uid,
            f"❌ **দুঃখিত!** আপনার `{refund:g}` টাকার উইথড্র বাতিল হয়েছে।\n"
            f"টাকা ফেরত দেওয়া হয়েছে।")
    except Exception:
        pass

    await answer(cb, "❌ Reject")
    await cb.message.edit_text(
        f"🔴 **উইথড্র Reject!** (আইডি #{wid})\n\n"
        f"ইউজার: {esc(dn)} — {refund:g} টাকা ফেরত দেওয়া হয়েছে।",
        reply_markup=None)

    try:
        msgs = json.loads(wd["admin_msgs"] or "[]")
    except Exception:
        msgs = []
    for mm in msgs:
        if str(mm.get("c")) == str(cb.from_user.id): continue
        try:
            await bot.edit_message_text(
                chat_id=int(mm["c"]),
                message_id=int(mm["m"]),
                text=f"🔴 **উইথড্র Reject** (আইডি #{wid})\n{esc(admin_name)} রিজেক্ট করেছেন।",
                reply_markup=None)
        except Exception:
            pass
# ==========================================================
# পার্ট ৫B/৫ : Admin Text Input + Fallback + main()
# ==========================================================

@router.message(F.text, lambda m: db.is_admin(m.from_user.id) and db.state(m.from_user.id).startswith("a_w_"))
async def dispatch_admin_input(m: Message):
    uid = m.from_user.id
    state = db.state(uid)
    text = (m.text or "").strip()

    # ---------- 1. BOT USERNAME ----------
    if state == "a_w_bot_uname":
        db.set_state(uid, "")
        clean = text.lstrip("@").strip()
        if not clean:
            await m.answer("⚠️ সঠিক username দিন।")
            return
        db.set("bot_username", clean)
        await m.answer(
            f"✅ বট username সেট হয়েছে: `@{esc(clean)}`\n\n"
            f"referral লিংক এখন:\n`https://t.me/{esc(clean)}?start=<your_id>`",
            reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 2. STOCK ADD ----------
    if state == "a_w_stock":
        db.set_state(uid, "")
        existing = {it["gmail"].lower() for it in db.stock_list(limit=10000)}
        added = dups = invalid = 0
        for line in text.split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            parts = line.split(":", 1)
            g = parts[0].strip()
            p = parts[1].strip()
            if not valid_gmail(g):
                invalid += 1
                continue
            if g.lower() in existing:
                dups += 1
                continue
            if db.add_stock(g, p):
                existing.add(g.lower())
                added += 1
            else:
                dups += 1
        n1 = f"\n⚠️ `{dups}` ডুপ্লিকেট বাদ।" if dups else ""
        n2 = f"\n⚠️ `{invalid}` ভুল ফরম্যাট বাদ।" if invalid else ""
        await m.answer(f"✅ **{added} টি** স্টকে যোগ হয়েছে।{n1}{n2}",
                       reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 3. STOCK DELETE ----------
    if state == "a_w_stockdel":
        db.set_state(uid, "")
        targets = [t.strip() for t in text.split("\n") if t.strip()]
        removed = sum(db.del_stock(t) for t in targets)
        await m.answer(f"✅ `{removed}` টি ডিলিট হয়েছে।",
                       reply_markup=kb_back("a_stock_mg", "🔙 স্টক ম্যানেজ"))
        return

    # ---------- 4. CATEGORY ADD ----------
    if state == "a_w_cat_add":
        if "|" not in text:
            await m.answer("⚠️ ফরম্যাট: `নাম | রেট`", parse_mode=ParseMode.MARKDOWN)
            return
        db.set_state(uid, "")
        parts = text.split("|", 1)
        label = parts[0].strip()
        try:
            rate = int(parts[1].strip())
            if rate <= 0:
                raise ValueError
        except ValueError:
            await m.answer("⚠️ রেট পজিটিভ সংখ্যা দিন।")
            return
        if not label:
            await m.answer("⚠️ নাম খালি রাখা যাবে না।")
            return
        existing = {c["key"] for c in db.cats()}
        i = 1
        while f"cat{i}" in existing:
            i += 1
        key = f"cat{i}"
        db.add_cat(key, label, rate)
        await m.answer(
            f"✅ নতুন ক্যাটাগরি যোগ হয়েছে!\n\n"
            f"**{esc(label)}** — `{rate}` টাকা",
            reply_markup=kb_back("a_cat_menu", "🔙 ক্যাটাগরি মেনু"))
        return

    # ---------- 5. FORCE JOIN CHANNEL ADD ----------
    if state == "a_w_force_add":
        db.set_state(uid, "")
        clean = text.lstrip("@").strip().lower()
        if not clean:
            await m.answer("⚠️ সঠিক username দিন।")
            return
        ok = db.add_channel(clean)
        if not ok:
            await m.answer("⚠️ এই চ্যানেল ইতিমধ্যে যোগ করা আছে বা ভুল ফরম্যাট।",
                           reply_markup=kb_back("a_force_menu", "🔙 Force Join"))
            return
        try:
            chat = await bot.get_chat(f"@{clean}")
            chat_title = chat.title or clean
        except Exception:
            chat_title = clean
            await m.answer(
                f"⚠️ @{esc(clean)} যোগ করা হয়েছে, কিন্তু চেক করতে পারিনি।\n"
                f"নিশ্চিত করুন — চ্যানেল Public এবং বট Admin আছে কি না।",
                reply_markup=kb_back("a_force_menu", "🔙 Force Join"))
            return
        await m.answer(
            f"✅ নতুন চ্যানেল যোগ হয়েছে!\n\n"
            f"📢 **{esc(chat_title)}** (@{esc(clean)})",
            reply_markup=kb_back("a_force_menu", "🔙 Force Join"))
        return

    # ---------- 6. MASTER PASSWORD ----------
    if state == "a_w_master_pw":
        db.set_state(uid, "")
        if not text or len(text) < 3:
            await m.answer("⚠️ কমপক্ষে ৩ অক্ষরের পাসওয়ার্ড দিন।")
            return
        db.set("master_password", text)
        await m.answer(
            f"✅ মাস্টার পাসওয়ার্ড সেট হয়েছে:\n`{esc(text)}`",
            reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 7. RECOVERY EMAIL ----------
    if state == "a_w_recovery":
        db.set_state(uid, "")
        if not valid_gmail(text):
            await m.answer("⚠️ বৈধ Gmail দিন।",
                           reply_markup=kb_cancel("admin"))
            return
        db.set("recovery_email", text)
        await m.answer(
            f"✅ ডিফল্ট রিকভারি: `{esc(text)}`",
            reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 8. LIMITS ----------
    if state.startswith("a_w_lim_"):
        key = state.replace("a_w_lim_", "", 1)
        try:
            val = int(text)
            if val < 0:
                raise ValueError
        except ValueError:
            await m.answer("⚠️ সঠিক সংখ্যা দিন।")
            return
        db.set_state(uid, "")
        smap = {
            "gmail": "min_wd_gmail",
            "refer": "min_wd_refer",
            "charge": "refer_charge",
            "minrefs": "min_refers",
        }
        labels = {
            "gmail": "জিমেইল মিনিমাম",
            "refer": "রেফার মিনিমাম",
            "charge": "রেফার চার্জ",
            "minrefs": "ন্যূনতম রেফার",
        }
        if key not in smap:
            return
        db.set(smap[key], val)
        await m.answer(
            f"✅ {labels[key]} **{val}** সেট হয়েছে।",
            reply_markup=kb_back("a_limits", "🔙 লিমিট"))
        return

    # ---------- 9. METHOD CHARGE ----------
    if state.startswith("a_w_mc_"):
        m_key = state.replace("a_w_mc_", "", 1)
        try:
            val = int(text)
            if val < 0:
                raise ValueError
        except ValueError:
            await m.answer("⚠️ সঠিক সংখ্যা দিন।")
            return
        db.set_state(uid, "")
        set_method_charge(m_key, val)
        await m.answer(
            f"✅ {m_key} চার্জ **{val} টাকা** সেট।",
            reply_markup=kb_back("a_mcharges", "🔙 চার্জ মেনু"))
        return

    # ---------- 10. WARNING LIMIT ----------
    if state == "a_w_warn":
        try:
            val = int(text)
            if val <= 0:
                raise ValueError
        except ValueError:
            await m.answer("⚠️ পজিটিভ সংখ্যা দিন।")
            return
        db.set_state(uid, "")
        db.set("warning_limit", val)
        await m.answer(
            f"✅ ওয়ার্নিং লিমিট: **{val}**",
            reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 11. BAN ----------
    if state == "a_w_ban":
        db.set_state(uid, "")
        if not text.isdigit():
            await m.answer("⚠️ সঠিক আইডি দিন।")
            return
        target = int(text)
        r = db.user(target)
        if not r:
            await m.answer("❌ এই আইডির ইউজার নেই।",
                           reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
            return
        was_banned = bool(r["banned"])
        db.ban(target, not was_banned)
        if was_banned:
            await m.answer(f"✅ `{target}` আনব্যান হয়েছে।",
                           reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        else:
            await m.answer(f"🚫 `{target}` ব্যান হয়েছে।",
                           reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
            try:
                await bot.send_message(target,
                    "🚫 আপনাকে এই বট ব্যবহার থেকে বিরত রাখা হয়েছে।")
            except Exception:
                pass
        return

    # ---------- 12. LOOKUP ----------
    if state == "a_w_lookup":
        db.set_state(uid, "")
        if not text.isdigit():
            await m.answer("⚠️ সঠিক আইডি দিন।")
            return
        target = int(text)
        r = db.user(target)
        if not r:
            await m.answer("❌ এই আইডির ইউজার নেই।",
                           reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
            return
        h = db.user_history(target, limit=30)
        acc = sum(1 for x in h if x["status"] == "accepted")
        rej = sum(1 for x in h if x["status"] == "rejected")
        status = "🚫 ব্যানড" if r["banned"] else "✅ সচল"
        total = (r["gmail_wallet"] or 0) + (r["refer_wallet"] or 0)
        out = (
            f"🔍 **ইউজার প্রোফাইল — {esc(udisplay(target, r))}**\n"
            f"আইডি: `{target}` | স্ট্যাটাস: {status}\n\n"
            f"💰 জিমেইল: `{r['gmail_wallet']:g}` টাকা\n"
            f"🔗 রেফার: `{r['refer_wallet']:g}` টাকা\n"
            f"💵 মোট: `{total:g}` টাকা\n\n"
            f"👥 রেফার: `{r['total_refers']}` জন\n"
            f"🎁 কমিশন: `{r['refer_income']:g}` টাকা\n"
            f"⚠️ ওয়ার্নিং: `{r['fake_warnings']}/{warn_limit()}`\n\n"
            f"📧 সাবমিশন (মোট {len(h)} — 🟢 {acc} | 🔴 {rej})"
        )
        await m.answer(out, reply_markup=kb_admin_editbal(target))
        return

    # ---------- 13. BALANCE SEARCH ----------
    if state == "a_w_bal_search":
        db.set_state(uid, "")
        if not text.isdigit():
            await m.answer("⚠️ সঠিক আইডি দিন।")
            return
        target = int(text)
        r = db.user(target)
        if not r:
            await m.answer("❌ এই আইডির ইউজার নেই।",
                           reply_markup=kb_back("a_bal_menu", "🔙 ব্যালেন্স"))
            return
        out = (
            f"💰 **ইউজার:** {esc(udisplay(target, r))}\n"
            f"আইডি: `{target}`\n\n"
            f"📧 জিমেইল: `{r['gmail_wallet']:g}` টাকা\n"
            f"🔗 রেফার: `{r['refer_wallet']:g}` টাকা"
        )
        await m.answer(out, reply_markup=kb_admin_editbal(target))
        return

    # ---------- 14. EDIT BALANCE ----------
    if state.startswith("a_w_ebal_g_") or state.startswith("a_w_ebal_r_"):
        if state.startswith("a_w_ebal_g_"):
            field = "gmail_wallet"
            target = state.replace("a_w_ebal_g_", "", 1)
            label = "জিমেইল"
        else:
            field = "refer_wallet"
            target = state.replace("a_w_ebal_r_", "", 1)
            label = "রেফার"
        clean = text.replace(",", "")
        try:
            amount = float(clean)
        except ValueError:
            await m.answer("⚠️ সঠিক সংখ্যা দিন (যেমন: 50 বা -50)।")
            return
        db.set_state(uid, "")
        tid_int = int(target)
        r = db.user(tid_int)
        if not r:
            await m.answer("❌ ইউজার নেই।")
            return
        old = r[field] or 0
        new = max(0, old + amount)
        db.set_wallet(tid_int, field, new)
        await m.answer(
            f"✅ {esc(udisplay(tid_int, r))}-এর {label}: "
            f"`{old:g}` → `{new:g}` টাকা",
            reply_markup=kb_back("a_bal_menu", "🔙 ব্যালেন্স"))
        try:
            await bot.send_message(
                tid_int,
                f"{'🎉 যোগ' if amount >= 0 else 'ℹ️ কর্তন'} `{abs(amount):g}` টাকা।\n"
                f"নতুন ব্যালেন্স: `{new:g}` টাকা")
        except Exception:
            pass
        return

    # ---------- 15. ADD ADMIN ----------
    if state == "a_w_addadmin":
        db.set_state(uid, "")
        if not text.isdigit():
            await m.answer("⚠️ সঠিক আইডি দিন।")
            return
        target = int(text)
        if target in ADMIN_IDS or target in db.extra_admins():
            await m.answer(f"ℹ️ `{target}` ইতিমধ্যে অ্যাডমিন।",
                           reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
            return
        db.add_admin(target)
        await m.answer(f"✅ `{target}` অ্যাডমিন হয়েছে।",
                       reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        try:
            await bot.send_message(target,
                "🎉 আপনাকে অ্যাডমিন করা হয়েছে! /start দিন।")
        except Exception:
            pass
        return

    # ---------- 16. COMMISSION ----------
    if state == "a_w_comm":
        try:
            val = int(text)
            if val < 0 or val > 100:
                raise ValueError
        except ValueError:
            await m.answer("⚠️ ০-১০০ এর মধ্যে দিন।")
            return
        db.set_state(uid, "")
        db.set("refer_percent", val)
        await m.answer(f"✅ কমিশন **{val}%** সেট।",
                       reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 17. CONTACT ----------
    if state == "a_w_sup":
        db.set_state(uid, "")
        clean = text.lstrip("@").strip()
        if not clean:
            await m.answer("⚠️ সঠিক ইউজারনেম দিন।")
            return
        db.set("support", clean)
        await m.answer(f"✅ সাপোর্ট: @{clean}",
                       reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    if state == "a_w_ch":
        db.set_state(uid, "")
        clean = text.lstrip("@").strip()
        if not clean:
            await m.answer("⚠️ সঠিক ইউজারনেম দিন।")
            return
        db.set("channel", clean)
        await m.answer(f"✅ চ্যানেল: @{clean}",
                       reply_markup=kb_back("admin", "🔙 অ্যাডমিন"))
        return

    # ---------- 18. BROADCAST ----------
    if state == "a_w_bc":
        db.set_state(uid, "")
        await m.answer("📢 ব্রডকাস্ট পাঠানো হচ্ছে...")
        ok = 0
        for u in db.all_uids():
            try:
                await bot.copy_message(
                    chat_id=u,
                    from_chat_id=uid,
                    message_id=m.message_id)
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await m.answer(f"✅ ব্রডকাস্ট সম্পন্ন! ({ok} জন পেয়েছেন)")
        return


# ==========================================================
# FALLBACK
# ==========================================================

@router.callback_query()
async def cb_fallback(cb: CallbackQuery):
    await answer(cb, "ℹ️ এই বাটন কাজ করছে না।")


@router.message(Command("backup"))
async def cmd_backup(m: Message):
    if not db.is_admin(m.from_user.id):
        return
    try:
        with open(DB_FILE, "rb") as f:
            data = f.read()
        fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        await m.answer_document(
            BufferedInputFile(data, filename=fname),
            caption=f"💾 ডাটাবেস ব্যাকআপ")
    except Exception as e:
        await m.answer(f"❌ ব্যর্থ: {e}")


@router.message(F.text)
async def msg_fallback(m: Message):
    if db.is_admin(m.from_user.id) and db.state(m.from_user.id).startswith("a_w_"):
        return
    db.set_state(m.from_user.id, "")
    await m.answer(
        "ℹ️ বোঝা যায়নি। /start দিয়ে মেইন মেনুতে যান।",
        reply_markup=kb_back())


# ==========================================================
# MAIN — Polling + Health + Self-ping
# ==========================================================

async def self_ping_loop():
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        log.warning("RENDER_EXTERNAL_URL নেই — self-ping বন্ধ")
        return
    url = url.rstrip("/") + "/health"
    await asyncio.sleep(60)
    while True:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=10) as resp:
                    log.info(f"Self-ping {url} → {resp.status}")
        except Exception as e:
            log.warning(f"Self-ping failed: {e}")
        await asyncio.sleep(600)


async def health(request):
    return web.Response(text="OK")


async def run_polling():
    log.info("Starting bot in POLLING mode...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    asyncio.create_task(self_ping_loop())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"Health server started on port {PORT}")


async def main_async():
    dp.include_router(router)
    await asyncio.gather(
        run_health_server(),
        run_polling(),
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN env var সেট করুন!")
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()