import os
import sqlite3
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8628267774"))
ENTRY_FEE = 30
QR_PATH = os.path.join(os.path.dirname(__file__), "payment_qr.png")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Put your BotFather token in Railway Variables.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

conn = sqlite3.connect("fxbr.db", check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    username TEXT,
    name TEXT,
    uid TEXT,
    ign TEXT,
    status TEXT DEFAULT 'pending',
    slot INTEGER,
    screenshot_file_id TEXT,
    room_id TEXT,
    room_password TEXT
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()

# Safe migration for an older fxbr.db that does not yet have room columns.
cols = {r[1] for r in conn.execute("PRAGMA table_info(registrations)").fetchall()}
if "room_id" not in cols:
    conn.execute("ALTER TABLE registrations ADD COLUMN room_id TEXT")
if "room_password" not in cols:
    conn.execute("ALTER TABLE registrations ADD COLUMN room_password TEXT")
conn.commit()

PUBLIC_ITEMS = {
    "register": "📝 Register",
    "myreg": "🎟️ My Registration",
    "room": "🔐 Room ID & Password",
    "rules": "📜 Rules",
    "results": "🏆 Results",
}
DEFAULT_MENU = {key: "1" for key in PUBLIC_ITEMS}

class Reg(StatesGroup):
    name = State()
    uid = State()
    ign = State()
    payment = State()

class Admin(StatesGroup):
    room_match = State()
    room_id = State()
    room_password = State()
    results = State()


def setting(key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
    conn.commit()


def public_enabled(key):
    return setting(f"menu_{key}", DEFAULT_MENU.get(key, "1")) == "1"


def main_kb(user_id=None):
    rows = []
    if public_enabled("register"):
        rows.append([InlineKeyboardButton(text=PUBLIC_ITEMS["register"], callback_data="register")])
    if public_enabled("myreg"):
        rows.append([InlineKeyboardButton(text=PUBLIC_ITEMS["myreg"], callback_data="myreg")])
    if public_enabled("room"):
        rows.append([InlineKeyboardButton(text=PUBLIC_ITEMS["room"], callback_data="room")])
    if public_enabled("rules"):
        rows.append([InlineKeyboardButton(text=PUBLIC_ITEMS["rules"], callback_data="rules")])
    if public_enabled("results"):
        rows.append([InlineKeyboardButton(text=PUBLIC_ITEMS["results"], callback_data="results")])
    if user_id == ADMIN_ID:
        rows.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_kb(reg_id, status):
    rows = []
    if status == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{reg_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{reg_id}"),
            InlineKeyboardButton(text="🗑️ Remove", callback_data=f"remove:{reg_id}")
        ])
    elif status == "approved":
        rows.append([
            InlineKeyboardButton(text="🔐 Set Room", callback_data=f"setroom:{reg_id}"),
            InlineKeyboardButton(text="🗑️ Remove", callback_data=f"remove:{reg_id}")
        ])
    else:
        rows.append([InlineKeyboardButton(text="🗑️ Remove", callback_data=f"remove:{reg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Manage Registrations", callback_data="admin_regs")],
        [InlineKeyboardButton(text="🔐 Set Room for Match", callback_data="admin_room")],
        [InlineKeyboardButton(text="🏆 Set Results", callback_data="admin_results")],
        [InlineKeyboardButton(text="🎛️ Manage Public Menu", callback_data="admin_menu")],
        [InlineKeyboardButton(text="📊 Registration Stats", callback_data="admin_stats")],
    ])


def admin_menu_kb():
    rows = []
    for key, label in PUBLIC_ITEMS.items():
        state = "ON" if public_enabled(key) else "OFF"
        rows.append([InlineKeyboardButton(text=f"{label} — {state}", callback_data=f"toggle_menu:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ Back to Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎮 <b>FX BR SOLO TOURNAMENT</b> 🇮🇳\n\n"
        "💰 Entry Fee: <b>₹30</b>\n"
        "👤 Mode: <b>Solo</b>\n\n"
        "Har match ke liye alag se Register kar sakte ho.\n"
        "Payment approve hone ke baad us match ka slot milega.\n"
        "Room ID & Password admin usi match ke liye set karega.\n\n"
        "👇 Neeche menu se option select karo.",
        reply_markup=main_kb(message.from_user.id), parse_mode="HTML"
    )


@dp.message(Command("menu"))
async def menu(message: Message):
    await message.answer("📋 <b>Main Menu</b>\n\nOption select karo:", reply_markup=main_kb(message.from_user.id), parse_mode="HTML")


@dp.callback_query(F.data == "register")
async def register(call: CallbackQuery, state: FSMContext):
    if not public_enabled("register"):
        await call.answer("Registration abhi available nahi hai.", show_alert=True)
        return
    # IMPORTANT: No duplicate check. Every Register tap creates a NEW match registration.
    await state.set_state(Reg.name)
    await call.message.answer("📝 <b>New Match Registration</b>\n\n👤 Apna Name enter karo:", parse_mode="HTML")
    await call.answer()


@dp.message(Reg.name)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Reg.uid)
    await message.answer("🆔 Apna Free Fire UID enter karo:")


@dp.message(Reg.uid)
async def reg_uid(message: Message, state: FSMContext):
    await state.update_data(uid=message.text.strip())
    await state.set_state(Reg.ign)
    await message.answer("🎮 Apna In-game Name (IGN) enter karo:")


@dp.message(Reg.ign)
async def reg_ign(message: Message, state: FSMContext):
    await state.update_data(ign=message.text.strip())
    await state.set_state(Reg.payment)
    if os.path.exists(QR_PATH):
        await message.answer_photo(
            FSInputFile(QR_PATH),
            caption="💰 Entry Fee: ₹30\n\nIs QR se payment karo, phir <b>payment screenshot</b> yahan bhejo.",
            parse_mode="HTML"
        )
    else:
        await message.answer("💰 Entry Fee: ₹30\nPayment karke screenshot yahan bhejo.")


@dp.message(Reg.payment, F.photo)
async def reg_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.photo[-1].file_id
    cur = conn.execute(
        "INSERT INTO registrations (telegram_id,username,name,uid,ign,screenshot_file_id,status) VALUES (?,?,?,?,?,?,?)",
        (message.from_user.id, message.from_user.username or "", data["name"], data["uid"], data["ign"], file_id, "pending")
    )
    reg_id = cur.lastrowid
    conn.commit()
    await state.clear()

    await message.answer(
        f"✅ Payment screenshot mil gaya!\n\n🆕 <b>Match Registration #{reg_id}</b>\n"
        "⏳ Abhi admin payment verify karega.\n"
        "Approval ke baad is match ka slot milega.\n"
        "Room ID & Password isi match ke liye baad mein milega.",
        reply_markup=main_kb(message.from_user.id), parse_mode="HTML"
    )

    admin_text = (
        f"🆕 <b>NEW MATCH REGISTRATION #{reg_id}</b>\n\n"
        f"👤 Name: {data['name']}\n"
        f"🎮 IGN: {data['ign']}\n"
        f"🆔 UID: {data['uid']}\n"
        f"📱 Username: @{message.from_user.username or 'N/A'}\n"
        f"💰 Fee: ₹30"
    )
    await bot.send_photo(ADMIN_ID, file_id, caption=admin_text, parse_mode="HTML", reply_markup=admin_kb(reg_id, "pending"))


@dp.message(Reg.payment)
async def payment_wrong(message: Message):
    await message.answer("📷 Payment screenshot/photo bhejo.")


@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT telegram_id,status FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row or row[1] != "pending":
        await call.answer("Registration nahi mili ya pehle hi process ho chuki hai.", show_alert=True)
        return
    # Slot numbers are assigned globally to approved registrations. A new registration gets a new slot.
    slot = conn.execute("SELECT COALESCE(MAX(slot),0)+1 FROM registrations WHERE status='approved'").fetchone()[0]
    conn.execute("UPDATE registrations SET status='approved',slot=? WHERE id=?", (slot, reg_id))
    conn.commit()
    await bot.send_message(
        row[0],
        f"🎉 <b>Payment Approved!</b>\n\n🆕 Match: <b>#{reg_id}</b>\n🎟️ Tumhara Slot: <b>{slot}</b>\n\n"
        "🔐 Is match ka Room ID & Password admin set karne ke baad isi bot mein milega.",
        parse_mode="HTML", reply_markup=main_kb(row[0])
    )
    await call.message.edit_reply_markup(reply_markup=admin_kb(reg_id, "approved"))
    await call.answer("Approved ✅")


@dp.callback_query(F.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT telegram_id,status FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row:
        await call.answer("Registration nahi mili.", show_alert=True)
        return
    conn.execute("UPDATE registrations SET status='rejected' WHERE id=?", (reg_id,))
    conn.commit()
    await bot.send_message(row[0], f"❌ Match #{reg_id} ka payment/registration reject ho gaya hai. Admin se contact karo.")
    await call.message.edit_reply_markup(reply_markup=admin_kb(reg_id, "rejected"))
    await call.answer("Rejected ❌")


@dp.callback_query(F.data.startswith("remove:"))
async def remove_registration(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT telegram_id,status,slot FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row:
        await call.answer("Registration already removed.", show_alert=True)
        return
    conn.execute("DELETE FROM registrations WHERE id=?", (reg_id,))
    conn.commit()
    try:
        await bot.send_message(
            row[0],
            f"🗑️ <b>Match #{reg_id}</b> ki tumhari registration admin ne remove kar di hai.\n\n"
            "Ab tum chaaho to <b>Register</b> karke new match join kar sakte ho.",
            reply_markup=main_kb(row[0]), parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Registration removed 🗑️")


@dp.callback_query(F.data.startswith("setroom:"))
async def set_room_for_match(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    row = conn.execute("SELECT status FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row or row[0] != "approved":
        await call.answer("Pehle registration approve karo.", show_alert=True)
        return
    await state.update_data(room_match=reg_id)
    await state.set_state(Admin.room_id)
    await call.message.answer(f"🔐 Match <b>#{reg_id}</b> ke liye Room ID bhejo:", parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "myreg")
async def myreg(call: CallbackQuery):
    rows = conn.execute(
        "SELECT id,name,uid,ign,status,slot,room_id,room_password FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,)
    ).fetchall()
    if not rows:
        await call.message.answer("Tumhari abhi koi registration nahi hai.", reply_markup=main_kb(call.from_user.id))
    else:
        lines = ["🎟️ <b>Tumhari Registrations</b>\n"]
        for r in rows:
            room_state = "Room set hai" if r[6] and r[7] else "Room pending"
            lines.append(
                f"🆕 Match <b>#{r[0]}</b>\n"
                f"👤 {r[1]} | 🎮 {r[3]}\n"
                f"📌 Status: <b>{r[4]}</b> | 🎟️ Slot: <b>{r[5] or '-'} </b>\n"
                f"🔐 {room_state}\n"
            )
        await call.message.answer("\n".join(lines), reply_markup=main_kb(call.from_user.id), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "room")
async def room(call: CallbackQuery):
    # Show the latest approved match that has its own room credentials.
    row = conn.execute(
        "SELECT id,slot,room_id,room_password FROM registrations "
        "WHERE telegram_id=? AND status='approved' AND room_id IS NOT NULL AND room_id!='' "
        "AND room_password IS NOT NULL AND room_password!='' ORDER BY id DESC LIMIT 1",
        (call.from_user.id,)
    ).fetchone()
    if not row:
        approved = conn.execute(
            "SELECT id FROM registrations WHERE telegram_id=? AND status='approved' ORDER BY id DESC LIMIT 1",
            (call.from_user.id,)
        ).fetchone()
        if approved:
            await call.message.answer(f"⏳ Match #{approved[0]} approved hai, lekin uska Room ID & Password abhi admin ne set nahi kiya hai.")
        else:
            await call.message.answer("🔒 Pehle tumhari registration/payment approve hona zaroori hai.")
        await call.answer()
        return
    await call.message.answer(
        f"🔐 <b>Match #{row[0]}</b>\n\n"
        f"🎟️ Slot: <b>{row[1]}</b>\n"
        f"🆔 Room ID: <code>{row[2]}</code>\n"
        f"🔑 Password: <code>{row[3]}</code>",
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "rules")
async def rules(call: CallbackQuery):
    await call.message.answer(
        "📜 <b>FX BR SOLO RULES</b>\n\n"
        "1. Team up mat karo — team up kiya to no prize/no refund.\n"
        "2. Revive allowed nahi hai.\n"
        "3. E-sports mode ON rahega.\n"
        "4. Random kill kiya to no prize.\n"
        "5. Jo slot milega usi slot par raho, warna kick/no refund.\n"
        "6. All guns aur all character skills allowed hain.\n"
        "7. Network ya personal issue ke liye management responsible nahi hai.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "results")
async def results(call: CallbackQuery):
    text = setting("results")
    await call.message.answer(text if text else "🏆 Abhi results publish nahi hue hain. Thoda wait karo.")
    await call.answer()


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    await call.message.answer("👑 <b>FX BR ADMIN PANEL</b>\n\nKya manage karna hai, option select karo:", reply_markup=admin_panel_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "admin_room")
async def admin_room(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    approved = conn.execute(
        "SELECT id,name,ign,slot FROM registrations WHERE status='approved' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    if not approved:
        await call.message.answer("❌ Abhi koi approved match nahi hai.", reply_markup=admin_panel_kb())
        await call.answer()
        return
    rows = []
    for r in approved:
        rows.append([InlineKeyboardButton(text=f"Match #{r[0]} | {r[1]} | Slot {r[3] or '-'}", callback_data=f"setroom:{r[0]}")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel")])
    await call.message.answer("🔐 Jis match ka Room ID & Password set karna hai, woh select karo:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.message(Admin.room_id)
async def admin_room_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    reg_id = data.get("room_match")
    if not reg_id:
        await state.clear()
        await message.answer("❌ Match select nahi hua. Admin Panel se phir try karo.")
        return
    await state.update_data(room_id=message.text.strip())
    await state.set_state(Admin.room_password)
    await message.answer(f"🔑 Match <b>#{reg_id}</b> ka Room Password bhejo:", parse_mode="HTML")


@dp.message(Admin.room_password)
async def admin_room_password(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    reg_id = data.get("room_match")
    room_id = data.get("room_id")
    password = message.text.strip()
    if not reg_id or not room_id:
        await state.clear()
        await message.answer("❌ Match details missing hain. Admin Panel se phir try karo.")
        return
    row = conn.execute("SELECT telegram_id,status FROM registrations WHERE id=?", (reg_id,)).fetchone()
    if not row or row[1] != "approved":
        await state.clear()
        await message.answer("❌ Ye match approved nahi hai ya remove ho chuka hai.")
        return
    conn.execute("UPDATE registrations SET room_id=?, room_password=? WHERE id=?", (room_id, password, reg_id))
    conn.commit()
    await state.clear()
    await bot.send_message(
        row[0],
        f"🔐 <b>Room ID & Password Ready!</b>\n\n🆕 Match: <b>#{reg_id}</b>\n"
        f"🆔 Room ID: <code>{room_id}</code>\n🔑 Password: <code>{password}</code>",
        parse_mode="HTML", reply_markup=main_kb(row[0])
    )
    await message.answer(
        f"✅ Match <b>#{reg_id}</b> ka Room ID & Password save ho gaya.\n\n"
        f"🆔 {room_id}\n🔑 {password}\n\nPlayer ko bhi send kar diya gaya hai.",
        reply_markup=admin_panel_kb(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin_results")
async def admin_results(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    await state.set_state(Admin.results)
    await call.message.answer("🏆 Jo result publish karna hai woh yahan bhejo.\n\nExample:\n<code>🥇 1st - Player A\n🥈 2nd - Player B\n🥉 3rd - Player C</code>", parse_mode="HTML")
    await call.answer()


@dp.message(Admin.results)
async def admin_results_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    set_setting("results", message.text.strip())
    await state.clear()
    await message.answer("✅ <b>Results successfully publish ho gaye!</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "admin_regs")
async def admin_regs(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    rows = conn.execute("SELECT id,name,uid,ign,status,slot,room_id FROM registrations ORDER BY id DESC LIMIT 30").fetchall()
    if not rows:
        await call.message.answer("👥 <b>Registrations</b>\n\nAbhi koi registration nahi hai.", reply_markup=admin_panel_kb(), parse_mode="HTML")
    else:
        await call.message.answer("👥 <b>All Match Registrations</b>\n\nHar Register = new match registration. Approved match ke liye Set Room bhi kar sakte ho. Remove karne par public user ki woh registration delete ho jayegi.", reply_markup=admin_panel_kb(), parse_mode="HTML")
        for r in rows:
            reg_id, name, uid, ign, status, slot, room_id = r
            room_state = "🔐 Room Set" if room_id else "⏳ Room Pending"
            await call.message.answer(
                f"🆕 <b>Match #{reg_id}</b>\n👤 {name}\n🎮 {ign}\n🆔 {uid}\n📌 {status}\n🎟️ Slot: {slot or '-'}\n{room_state}",
                reply_markup=admin_kb(reg_id, status), parse_mode="HTML"
            )
    await call.answer()


@dp.callback_query(F.data == "admin_menu")
async def admin_menu(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    await call.message.answer("🎛️ <b>Public Menu Management</b>\n\nON/OFF karke public menu control karo:", reply_markup=admin_menu_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("toggle_menu:"))
async def toggle_menu(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    key = call.data.split(":", 1)[1]
    if key not in PUBLIC_ITEMS:
        await call.answer("Invalid option.", show_alert=True)
        return
    new_value = "0" if public_enabled(key) else "1"
    set_setting(f"menu_{key}", new_value)
    await call.message.edit_reply_markup(reply_markup=admin_menu_kb())
    await call.answer(f"{PUBLIC_ITEMS[key]} {'ON' if new_value == '1' else 'OFF'}")


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    total = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM registrations WHERE status='pending'").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM registrations WHERE status='approved'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM registrations WHERE status='rejected'").fetchone()[0]
    await call.message.answer(
        f"📊 <b>Registration Stats</b>\n\nTotal: {total}\n⏳ Pending: {pending}\n✅ Approved: {approved}\n❌ Rejected: {rejected}",
        reply_markup=admin_panel_kb(), parse_mode="HTML"
    )
    await call.answer()


# Backup command: choose a match from Admin Panel for match-specific Room ID/Password.
@dp.message(F.text.startswith("/setroom "))
async def setroom(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔐 Ab Admin Panel → Set Room for Match use karo, taaki har match ka alag Room ID & Password rahe.")


@dp.message(F.text.startswith("/setresults "))
async def setresults(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    set_setting("results", message.text[len("/setresults "):].strip())
    await message.answer("🏆 Results update ho gaye.")


@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👑 <b>FX BR ADMIN PANEL</b>\n\nKya manage karna hai, option select karo:", reply_markup=admin_panel_kb(), parse_mode="HTML")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
