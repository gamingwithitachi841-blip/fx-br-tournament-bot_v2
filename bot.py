import os
import sqlite3
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8628267774"))
ENTRY_FEE = 30
MAX_SLOTS = 48
QR_PATH = os.path.join(os.path.dirname(__file__), "payment_qr.png")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Put BOT_TOKEN in Railway Variables.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

conn = sqlite3.connect("fxbr.db", check_same_thread=False)
conn.row_factory = sqlite3.Row

# ---------- DATABASE ----------
conn.execute("""
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    uid TEXT NOT NULL,
    ign TEXT NOT NULL,
    payment_file_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    slot INTEGER,
    match_no INTEGER DEFAULT 1,
    round_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

conn.execute("""
CREATE TABLE IF NOT EXISTS match_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    room_id TEXT DEFAULT '',
    room_pass TEXT DEFAULT '',
    results TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
)
""")


def ensure_column(table, column, definition):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# Migrate databases from older bot versions.
ensure_column("registrations", "payment_file_id", "TEXT")
ensure_column("registrations", "match_no", "INTEGER DEFAULT 1")
ensure_column("registrations", "round_id", "INTEGER")

conn.commit()


def get_setting(key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def active_round():
    return conn.execute(
        "SELECT * FROM match_rounds WHERE status='active' ORDER BY id DESC LIMIT 1"
    ).fetchone()


if not active_round():
    conn.execute("INSERT INTO match_rounds(match_no,status) VALUES(1,'active')")
    conn.commit()

# Attach old registrations without a round to the first active round.
# This keeps old approved/pending data visible after upgrading the bot.
r0 = active_round()
conn.execute(
    "UPDATE registrations SET round_id=?, match_no=? WHERE round_id IS NULL",
    (r0["id"], r0["match_no"]),
)
conn.commit()


def approved_count(round_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM registrations "
        "WHERE round_id=? AND status='approved'",
        (round_id,),
    ).fetchone()["c"]


def booked_count(round_id):
    # A pending payment is already a booking attempt, so duplicate booking
    # is blocked while it is pending. It does NOT consume a slot number.
    return conn.execute(
        "SELECT COUNT(*) AS c FROM registrations "
        "WHERE round_id=? AND status IN ('pending','approved')",
        (round_id,),
    ).fetchone()["c"]


def next_free_slot(round_id):
    used = {
        r["slot"]
        for r in conn.execute(
            "SELECT slot FROM registrations WHERE round_id=? "
            "AND status='approved' AND slot IS NOT NULL",
            (round_id,),
        ).fetchall()
    }
    for n in range(1, MAX_SLOTS + 1):
        if n not in used:
            return n
    return None


# ---------- MENUS ----------
def public_menu(user_id=None):
    rows = [
        [KeyboardButton(text="📖 Book")],
        [KeyboardButton(text="🎟️ My Booking")],
        [KeyboardButton(text="🔐 Room ID & Password")],
        [KeyboardButton(text="📜 Rules")],
        [KeyboardButton(text="🏆 Results")],
    ]
    if user_id == ADMIN_ID:
        rows.append([KeyboardButton(text="👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔐 Set Room ID & Password"), KeyboardButton(text="🏆 Set Results")],
            [KeyboardButton(text="👥 Manage Registrations")],
            [KeyboardButton(text="🪑 Slot List")],
            [KeyboardButton(text="🔄 Switch / Allow New Booking")],
            [KeyboardButton(text="🎛️ Manage Public Menu"), KeyboardButton(text="📊 Registration Stats")],
            [KeyboardButton(text="⬅️ Main Menu")],
        ],
        resize_keyboard=True,
    )


# ---------- STATES ----------
class Reg(StatesGroup):
    name = State()
    uid = State()
    ign = State()
    payment = State()


class Admin(StatesGroup):
    room = State()
    results = State()


# ---------- HELPERS ----------
def booking_exists(user_id, round_id):
    return conn.execute(
        "SELECT id FROM registrations WHERE telegram_id=? AND round_id=? "
        "AND status IN ('pending','approved') LIMIT 1",
        (user_id, round_id),
    ).fetchone()


def admin_only(message):
    return message.from_user.id == ADMIN_ID


async def auto_switch_after_full():
    """Switch only after all 48 slots are APPROVED."""
    r = active_round()
    if not r:
        return
    if approved_count(r["id"]) < MAX_SLOTS:
        return

    next_match = 2 if r["match_no"] == 1 else 1
    conn.execute(
        "UPDATE match_rounds SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
        (r["id"],),
    )
    conn.execute(
        "INSERT INTO match_rounds(match_no,status) VALUES(?,'active')",
        (next_match,),
    )
    conn.commit()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔄 Match {r['match_no']} ke 48 slots full ho gaye.\n"
            f"✅ Ab Match {next_match} active hai.\n\n"
            f"🪑 Slots: 0/{MAX_SLOTS}",
        )
    except Exception:
        pass


# ---------- START / MAIN MENU ----------
@dp.message(CommandStart())
@dp.message(Command("menu"))
async def start(message: Message):
    r = active_round()
    booked = approved_count(r["id"]) if r else 0
    match_no = r["match_no"] if r else 1
    await message.answer(
        "🎮 FX BR SOLO TOURNAMENT 🇮🇳\n\n"
        f"🎯 Current Match: Match {match_no}\n"
        f"🪑 Slots: {booked}/{MAX_SLOTS} booked\n"
        f"🟢 Available: {MAX_SLOTS - booked}\n\n"
        "Menu se option choose karo.",
        reply_markup=public_menu(message.from_user.id),
    )


@dp.message(F.text == "⬅️ Main Menu")
async def main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📋 Main Menu", reply_markup=public_menu(message.from_user.id))


# ---------- BOOKING ----------
@dp.message(F.text == "📖 Book")
async def book_start(message: Message, state: FSMContext):
    await state.clear()
    r = active_round()
    if not r:
        await message.answer("⏳ Abhi koi active match nahi hai.")
        return

    if booking_exists(message.from_user.id, r["id"]):
        await message.answer(
            "😊 Tum already book karliye ho. Pehle first match khelo, "
            "uske baad hi dobara book hoga. 🫶"
        )
        return

    # Pending does not get a slot number, but prevents the same user from
    # submitting the same current match more than once.
    if booked_count(r["id"]) >= MAX_SLOTS:
        await message.answer(
            "⏳ Ye match booking limit tak pahunch gaya hai. Next match activate ho raha hai."
        )
        await auto_switch_after_full()
        return

    await state.set_state(Reg.name)
    await message.answer(
        f"📖 Book - Match {r['match_no']}\n\n"
        f"💰 Entry Fee: ₹{ENTRY_FEE}\n"
        f"🪑 Approved Slots: {approved_count(r['id'])}/{MAX_SLOTS}\n\n"
        "Apna Name bhejo:"
    )


@dp.message(Reg.name)
async def reg_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❗ Apna Name text me bhejo.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(Reg.uid)
    await message.answer("🎮 Apna Free Fire UID bhejo:")


@dp.message(Reg.uid)
async def reg_uid(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❗ Free Fire UID text me bhejo.")
        return
    await state.update_data(uid=message.text.strip())
    await state.set_state(Reg.ign)
    await message.answer("👤 Apna In-Game Name (IGN) bhejo:")


@dp.message(Reg.ign)
async def reg_ign(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❗ IGN text me bhejo.")
        return
    await state.update_data(ign=message.text.strip())
    await state.set_state(Reg.payment)

    if os.path.exists(QR_PATH):
        await message.answer_photo(
            FSInputFile(QR_PATH),
            caption=f"💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo."
        )
    else:
        await message.answer(
            f"💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo."
        )


@dp.message(Reg.payment, F.photo)
async def reg_payment(message: Message, state: FSMContext):
    r = active_round()
    data = await state.get_data()

    if not r:
        await state.clear()
        await message.answer("⏳ Active match nahi mila. Dobara Book karo.")
        return

    if booking_exists(message.from_user.id, r["id"]):
        await state.clear()
        await message.answer(
            "😊 Tum already book karliye ho. Pehle first match khelo, "
            "uske baad hi dobara book hoga. 🫶"
        )
        return

    if approved_count(r["id"]) >= MAX_SLOTS:
        await state.clear()
        await auto_switch_after_full()
        await message.answer("⏳ Ye match full ho gaya. Next match ke liye dobara Book karo.")
        return

    # Hard cap on approved + pending submissions. This avoids accepting a 49th
    # payment screenshot while the admin is processing the first 48.
    if booked_count(r["id"]) >= MAX_SLOTS:
        await state.clear()
        await message.answer("⏳ Is match ki booking limit full hai. Next match ka wait karo.")
        return

    cur = conn.execute(
        "INSERT INTO registrations "
        "(telegram_id,username,name,uid,ign,payment_file_id,status,match_no,round_id) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            message.from_user.id,
            message.from_user.username or "",
            data.get("name", ""),
            data.get("uid", ""),
            data.get("ign", ""),
            message.photo[-1].file_id,
            "pending",
            r["match_no"],
            r["id"],
        ),
    )
    reg_id = cur.lastrowid
    conn.commit()
    await state.clear()

    await message.answer(
        f"✅ Booking submit ho gayi!\n"
        f"🎯 Match: {r['match_no']}\n"
        f"🆔 Registration ID: #{reg_id}\n\n"
        "Admin approval ka wait karo.",
        reply_markup=public_menu(message.from_user.id),
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{reg_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{reg_id}"),
            ],
            [InlineKeyboardButton(text="🗑️ Remove", callback_data=f"remove:{reg_id}")],
        ]
    )

    try:
        await bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=(
                f"🆕 New Booking #{reg_id}\n\n"
                f"🎯 Match: {r['match_no']}\n"
                f"👤 Name: {data.get('name','')}\n"
                f"🎮 UID: {data.get('uid','')}\n"
                f"👤 IGN: {data.get('ign','')}\n"
                f"📱 User: @{message.from_user.username or 'NoUsername'}"
            ),
            reply_markup=kb,
        )
    except Exception:
        pass


@dp.message(Reg.payment)
async def reg_payment_wrong_type(message: Message):
    await message.answer("❗ Payment screenshot image bhejo, please.")


# ---------- MY BOOKING ----------
@dp.message(F.text == "🎟️ My Booking")
async def my_booking(message: Message):
    rows = conn.execute(
        "SELECT * FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 20",
        (message.from_user.id,),
    ).fetchall()
    if not rows:
        await message.answer("❌ Abhi koi booking nahi hai.")
        return

    text = "🎟️ Tumhari Bookings:\n\n"
    for r in rows:
        text += (
            f"🆔 #{r['id']} | 🎯 Match {r['match_no']} | "
            f"{r['status'].upper()} | 🎟️ Slot {r['slot'] or '-'}\n"
            f"👤 {r['ign']}\n\n"
        )
    await message.answer(text)


# ---------- ROOM ----------
@dp.message(F.text == "🔐 Room ID & Password")
async def room_details(message: Message):
    r = active_round()
    if not r:
        await message.answer("⏳ Abhi koi active match nahi hai.")
        return

    booking = conn.execute(
        "SELECT * FROM registrations WHERE telegram_id=? AND round_id=? "
        "AND status='approved' LIMIT 1",
        (message.from_user.id, r["id"]),
    ).fetchone()

    if not booking:
        await message.answer("🔒 Pehle current match ka payment approve hona zaroori hai.")
        return

    room_id = r["room_id"] or get_setting("room_id", "")
    room_pass = r["room_pass"] or get_setting("room_pass", "")
    if room_id and room_pass:
        await message.answer(
            f"🔐 ROOM DETAILS - MATCH {r['match_no']}\n\n"
            f"🆔 Room ID: {room_id}\n"
            f"🔑 Password: {room_pass}"
        )
    else:
        await message.answer("⏳ Room ID & Password abhi publish nahi hua. Wait karo.")


# ---------- RULES / RESULTS ----------
@dp.message(F.text == "📜 Rules")
async def rules(message: Message):
    await message.answer(
        "📜 RULES\n\n"
        "1. No team up — team up karoge to no prize, no refund.\n"
        "2. No revive.\n"
        "3. E-sports mode ON.\n"
        "4. Random kill = no prize.\n"
        "5. Jisko jo slot milega, usi slot par rahega.\n"
        "6. All guns & character skills allowed.\n"
        "7. Network ya kisi bhi issue par management ka decision final hai."
    )


@dp.message(F.text == "🏆 Results")
async def results(message: Message):
    r = active_round()
    if r and r["results"]:
        await message.answer(r["results"])
    else:
        await message.answer(get_setting("results", "🏆 Results abhi publish nahi hua."))


# ---------- ADMIN PANEL ----------
@dp.message(F.text == "👑 Admin Panel")
async def admin_panel(message: Message):
    if not admin_only(message):
        return
    r = active_round()
    await message.answer(
        "👑 Admin Panel\n\n"
        f"🎯 Active Match: Match {r['match_no']}\n"
        f"🪑 Approved: {approved_count(r['id'])}/{MAX_SLOTS}\n"
        f"📌 Pending: {booked_count(r['id']) - approved_count(r['id'])}/{MAX_SLOTS}",
        reply_markup=admin_menu(),
    )


@dp.message(F.text == "🔐 Set Room ID & Password")
async def set_room_start(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    r = active_round()
    await state.set_state(Admin.room)
    await message.answer(
        f"🔐 Match {r['match_no']} ke liye Room ID aur Password ek line me bhejo.\n\n"
        "Example:\n12345678 1234"
    )


@dp.message(Admin.room)
async def set_room_save(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❗ Format: ROOMID PASSWORD")
        return

    r = active_round()
    conn.execute(
        "UPDATE match_rounds SET room_id=?,room_pass=? WHERE id=?",
        (parts[0], parts[1], r["id"]),
    )
    conn.commit()
    set_setting("room_id", parts[0])
    set_setting("room_pass", parts[1])
    await state.clear()
    await message.answer(
        f"✅ Match {r['match_no']} ka Room ID & Password save ho gaya.",
        reply_markup=admin_menu(),
    )


@dp.message(F.text == "🏆 Set Results")
async def set_results_start(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    await state.set_state(Admin.results)
    await message.answer("🏆 Results ka text bhejo:")


@dp.message(Admin.results)
async def set_results_save(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    r = active_round()
    conn.execute(
        "UPDATE match_rounds SET results=? WHERE id=?",
        (message.text or "", r["id"]),
    )
    conn.commit()
    set_setting("results", message.text or "")
    await state.clear()
    await message.answer("✅ Results save ho gaya.", reply_markup=admin_menu())


# ---------- MANAGE REGISTRATIONS ----------
@dp.message(F.text == "👥 Manage Registrations")
async def manage_registrations(message: Message):
    if not admin_only(message):
        return

    rows = conn.execute(
        "SELECT * FROM registrations ORDER BY id DESC LIMIT 50"
    ).fetchall()
    if not rows:
        await message.answer("Koi registration nahi hai.")
        return

    for r in rows:
        buttons = []
        if r["status"] == "pending":
            buttons.append([
                InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{r['id']}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{r['id']}"),
            ])
        buttons.append([
            InlineKeyboardButton(text="🗑️ Remove", callback_data=f"remove:{r['id']}")
        ])

        await message.answer(
            f"#{r['id']} | {r['status'].upper()} | Match {r['match_no']} | Slot {r['slot'] or '-'}\n"
            f"👤 {r['name']}\n"
            f"🎮 UID: {r['uid']}\n"
            f"IGN: {r['ign']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


# ---------- SLOT LIST ----------
@dp.message(F.text == "🪑 Slot List")
async def slot_list_menu(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "🪑 Slot List",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Match 1", callback_data="slots:1")],
                [InlineKeyboardButton(text="🎯 Match 2", callback_data="slots:2")],
            ]
        ),
    )


@dp.callback_query(F.data.startswith("slots:"))
async def show_slots(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    match_no = int(call.data.split(":")[1])
    r = conn.execute(
        "SELECT * FROM match_rounds WHERE match_no=? ORDER BY id DESC LIMIT 1",
        (match_no,),
    ).fetchone()

    by_slot = {}
    if r:
        rows = conn.execute(
            "SELECT * FROM registrations WHERE round_id=? AND status='approved'",
            (r["id"],),
        ).fetchall()
        by_slot = {x["slot"]: x for x in rows if x["slot"]}

    for start in range(1, MAX_SLOTS + 1, 12):
        end = min(start + 11, MAX_SLOTS)
        text = f"🎯 MATCH {match_no} — SLOTS {start}-{end}\n"
        for n in range(start, end + 1):
            if n in by_slot:
                text += f"🟩 Slot {n} — {by_slot[n]['ign']} — UID {by_slot[n]['uid']}\n"
            else:
                text += f"⬜ Slot {n} — Empty\n"
        await call.message.answer(text)

    buttons = []
    if r:
        occupied = sorted(by_slot.keys())
        for n in occupied:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🗑️ Delete Slot {n}",
                    callback_data=f"dslot:{r['id']}:{n}",
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text=f"🗑️ Clear Match {match_no}",
            callback_data=f"clearask:{match_no}",
        )
    ])

    await call.message.answer(
        f"🎯 Match {match_no} controls:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("dslot:"))
async def delete_slot(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    _, round_id, slot = call.data.split(":")
    row = conn.execute(
        "SELECT * FROM registrations WHERE round_id=? AND slot=? AND status='approved'",
        (int(round_id), int(slot)),
    ).fetchone()
    if not row:
        await call.answer("Slot already empty", show_alert=True)
        return

    conn.execute("DELETE FROM registrations WHERE id=?", (row["id"],))
    conn.commit()
    await call.answer(f"Slot {slot} deleted")
    await call.message.answer(
        f"🗑️ Slot {slot} delete ho gaya. Baaki slots renumber nahi honge."
    )


@dp.callback_query(F.data.startswith("clearask:"))
async def clear_match_ask(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return
    match_no = int(call.data.split(":")[1])
    await call.message.answer(
        f"⚠️ Match {match_no} ka poora old slot list clear karna hai?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Yes, Clear", callback_data=f"clear:{match_no}"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data="cancelclear"),
                ]
            ]
        ),
    )
    await call.answer()


@dp.callback_query(F.data == "cancelclear")
async def cancel_clear(call: CallbackQuery):
    await call.message.edit_text("❌ Clear cancel.")
    await call.answer()


@dp.callback_query(F.data.startswith("clear:"))
async def clear_match(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    match_no = int(call.data.split(":")[1])
    r = conn.execute(
        "SELECT * FROM match_rounds WHERE match_no=? ORDER BY id DESC LIMIT 1",
        (match_no,),
    ).fetchone()

    if r:
        conn.execute("DELETE FROM registrations WHERE round_id=?", (r["id"],))
        conn.commit()

    await call.message.edit_text(
        f"✅ Match {match_no} ka slot list clear ho gaya. Slot 1-{MAX_SLOTS} fresh available."
    )
    await call.answer()


# ---------- SWITCH MATCH ----------
@dp.message(F.text == "🔄 Switch / Allow New Booking")
async def switch_menu(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "🔄 Active match select karo:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Activate Match 1", callback_data="activate:1")],
                [InlineKeyboardButton(text="🎯 Activate Match 2", callback_data="activate:2")],
            ]
        ),
    )


@dp.callback_query(F.data.startswith("activate:"))
async def activate_match(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    match_no = int(call.data.split(":")[1])
    old = active_round()
    if old and old["match_no"] == match_no:
        await call.answer("Already active")
        return

    if old:
        conn.execute(
            "UPDATE match_rounds SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (old["id"],),
        )

    # A new activation is a new round, with fresh 1-48 slots.
    conn.execute(
        "INSERT INTO match_rounds(match_no,status) VALUES(?,'active')",
        (match_no,),
    )
    conn.commit()

    await call.message.answer(
        f"✅ Match {match_no} active ho gaya.\n🪑 Slots: 0/{MAX_SLOTS}"
    )
    await call.answer()


# ---------- PUBLIC MENU CONTROL ----------
@dp.message(F.text == "🎛️ Manage Public Menu")
async def public_menu_manage(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "🎛️ Public Menu\n\n"
        "Note: Requested main menu options fixed hain. Neeche status check kar sakte ho.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📖 Book — ON", callback_data="menuinfo")],
                [InlineKeyboardButton(text="🎟️ My Booking — ON", callback_data="menuinfo")],
                [InlineKeyboardButton(text="🔐 Room — ON", callback_data="menuinfo")],
                [InlineKeyboardButton(text="📜 Rules — ON", callback_data="menuinfo")],
                [InlineKeyboardButton(text="🏆 Results — ON", callback_data="menuinfo")],
            ]
        ),
    )


@dp.callback_query(F.data == "menuinfo")
async def menu_info(call: CallbackQuery):
    if call.from_user.id == ADMIN_ID:
        await call.answer("Public menu active hai.")
    else:
        await call.answer("Not allowed", show_alert=True)


# ---------- STATS ----------
@dp.message(F.text == "📊 Registration Stats")
async def registration_stats(message: Message):
    if not admin_only(message):
        return
    r = active_round()
    approved = approved_count(r["id"])
    booked = booked_count(r["id"])
    total = conn.execute("SELECT COUNT(*) AS c FROM registrations").fetchone()["c"]
    await message.answer(
        "📊 Stats\n\n"
        f"🎯 Active Match: {r['match_no']}\n"
        f"🪑 Approved: {approved}/{MAX_SLOTS}\n"
        f"📌 Pending + Approved: {booked}/{MAX_SLOTS}\n"
        f"📚 Total registrations: {total}",
        reply_markup=admin_menu(),
    )


# ---------- APPROVE / REJECT / REMOVE ----------
@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT * FROM registrations WHERE id=?", (reg_id,)).fetchone()
    current = active_round()

    if not row:
        await call.answer("Registration not found", show_alert=True)
        return
    if row["status"] != "pending":
        await call.answer("Already processed", show_alert=True)
        return

    # A pending booking from an old match cannot be approved into the new match.
    if not current or row["round_id"] != current["id"]:
        conn.execute("UPDATE registrations SET status='rejected' WHERE id=?", (reg_id,))
        conn.commit()
        await call.answer("Old match booking", show_alert=True)
        try:
            await bot.send_message(
                row["telegram_id"],
                "❌ Ye booking old match ki thi, isliye approve nahi ho saki. Dobara Book karo."
            )
        except Exception:
            pass
        return

    if approved_count(current["id"]) >= MAX_SLOTS:
        await call.answer("48 slots full", show_alert=True)
        return

    slot = next_free_slot(current["id"])
    if slot is None:
        await call.answer("No slot available", show_alert=True)
        return

    conn.execute(
        "UPDATE registrations SET status='approved', slot=? WHERE id=?",
        (slot, reg_id),
    )
    conn.commit()

    await call.answer("Approved")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await bot.send_message(
            row["telegram_id"],
            f"✅ Payment Approved!\n\n"
            f"🎯 Match: {current['match_no']}\n"
            f"🎟️ Tumhara Slot: {slot}\n\n"
            "Room ID & Password publish hone ke baad mil jayega."
        )
    except Exception:
        pass

    await auto_switch_after_full()


@dp.callback_query(F.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT * FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row:
        await call.answer("Not found", show_alert=True)
        return

    conn.execute("UPDATE registrations SET status='rejected' WHERE id=?", (reg_id,))
    conn.commit()
    await call.answer("Rejected")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(
            row["telegram_id"],
            "❌ Payment reject ho gaya. Zarurat ho to dobara Book karo."
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("remove:"))
async def remove_registration(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Not allowed", show_alert=True)
        return

    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT * FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row:
        await call.answer("Already removed", show_alert=True)
        return

    conn.execute("DELETE FROM registrations WHERE id=?", (reg_id,))
    conn.commit()
    await call.answer("Removed")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(
            row["telegram_id"],
            "🗑️ Tumhari booking admin ne remove kar di hai. Zarurat ho to dobara Book karo."
        )
    except Exception:
        pass


# ---------- SAFETY FALLBACK ----------
@dp.message()
async def fallback(message: Message):
    # This makes it obvious that the bot is alive if a keyboard message arrives
    # that is not handled by another route.
    if message.text and message.text.strip() == "📖 Book":
        await message.answer("📖 Book option active hai. Dobara Book press karo.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
