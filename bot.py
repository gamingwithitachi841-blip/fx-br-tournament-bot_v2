import os
import sqlite3
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

conn = sqlite3.connect("fxbr.db")
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
    screenshot_file_id TEXT
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()

class Reg(StatesGroup):
    name = State()
    uid = State()
    ign = State()
    payment = State()

class Admin(StatesGroup):
    room_id = State()
    room_password = State()
    results = State()


def main_kb(user_id=None):
    rows = [
        [InlineKeyboardButton(text="📝 Register", callback_data="register")],
        [InlineKeyboardButton(text="🎟️ My Registration", callback_data="myreg")],
        [InlineKeyboardButton(text="🔐 Room ID & Password", callback_data="room")],
        [InlineKeyboardButton(text="📜 Rules", callback_data="rules")],
        [InlineKeyboardButton(text="🏆 Results", callback_data="results")],
    ]
    if user_id == ADMIN_ID:
        rows.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_kb(reg_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{reg_id}"),
         InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{reg_id}")]
    ])


def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Set Room ID & Password", callback_data="admin_room")],
        [InlineKeyboardButton(text="🏆 Set Results", callback_data="admin_results")],
        [InlineKeyboardButton(text="📊 Registration Stats", callback_data="admin_stats")],
    ])


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎮 <b>FX BR SOLO TOURNAMENT</b>\n\n"
        "💰 Entry Fee: <b>₹30</b>\n"
        "👤 Mode: <b>Solo</b>\n\n"
        "<b>Register</b> karo, payment complete karke payment screenshot bhejo.\n"
        "Admin approval ke baad tumhara slot number milega.",
        reply_markup=main_kb(message.from_user.id),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "register")
async def register(call: CallbackQuery, state: FSMContext):
    cur = conn.execute(
        "SELECT id FROM registrations WHERE telegram_id=? AND status IN ('pending','approved')",
        (call.from_user.id,)
    )
    if cur.fetchone():
        await call.answer("Tumhari registration pehle se ho chuki hai.", show_alert=True)
        return
    await state.set_state(Reg.name)
    await call.message.answer("👤 Apna Name enter karo:")
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
        "INSERT INTO registrations (telegram_id,username,name,uid,ign,screenshot_file_id) VALUES (?,?,?,?,?,?)",
        (message.from_user.id, message.from_user.username or "", data["name"], data["uid"], data["ign"], file_id)
    )
    reg_id = cur.lastrowid
    conn.commit()
    await state.clear()

    await message.answer(
        "✅ Payment screenshot mil gaya!\n"
        "⏳ Abhi admin payment verify karega. Thoda wait karo.\n"
        "Approval ke baad tumhara slot number milega.",
        reply_markup=main_kb(message.from_user.id)
    )

    admin_text = (
        f"🆕 <b>NEW REGISTRATION #{reg_id}</b>\n\n"
        f"👤 Name: {data['name']}\n"
        f"🎮 IGN: {data['ign']}\n"
        f"🆔 UID: {data['uid']}\n"
        f"📱 Username: @{message.from_user.username or 'N/A'}\n"
        f"💰 Fee: ₹30"
    )
    await bot.send_photo(
        ADMIN_ID,
        file_id,
        caption=admin_text,
        parse_mode="HTML",
        reply_markup=admin_kb(reg_id)
    )


@dp.message(Reg.payment)
async def payment_wrong(message: Message):
    await message.answer("📷 Payment screenshot/photo bhejo.")


@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    cur = conn.execute("SELECT telegram_id FROM registrations WHERE id=? AND status='pending'", (reg_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("Registration nahi mili ya pehle hi process ho chuki hai.", show_alert=True)
        return
    cur = conn.execute("SELECT COALESCE(MAX(slot),0)+1 FROM registrations WHERE status='approved'")
    slot = cur.fetchone()[0]
    conn.execute("UPDATE registrations SET status='approved',slot=? WHERE id=?", (slot, reg_id))
    conn.commit()
    await bot.send_message(
        row[0],
        f"🎉 <b>Payment Approved!</b>\n\n🎟️ Tumhara Slot: <b>{slot}</b>\n\n"
        "Match ready hone par Room ID & Password isi bot se milega. Wait karo.",
        parse_mode="HTML",
        reply_markup=main_kb(row[0])
    )
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Approved ✅")


@dp.callback_query(F.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    reg_id = int(call.data.split(":")[1])
    cur = conn.execute("SELECT telegram_id FROM registrations WHERE id=?", (reg_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("Registration nahi mili.", show_alert=True)
        return
    conn.execute("UPDATE registrations SET status='rejected' WHERE id=?", (reg_id,))
    conn.commit()
    await bot.send_message(row[0], "❌ Tumhara payment/registration reject ho gaya hai. Admin se contact karo.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Rejected ❌")


@dp.callback_query(F.data == "myreg")
async def myreg(call: CallbackQuery):
    cur = conn.execute(
        "SELECT name,uid,ign,status,slot FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 1",
        (call.from_user.id,)
    )
    r = cur.fetchone()
    if not r:
        await call.message.answer("Tumhari abhi koi registration nahi hai.", reply_markup=main_kb(call.from_user.id))
    else:
        await call.message.answer(
            f"👤 Name: {r[0]}\n🎮 IGN: {r[2]}\n🆔 UID: {r[1]}\n"
            f"📌 Status: {r[3]}\n🎟️ Slot: {r[4] or 'Not assigned'}",
            reply_markup=main_kb(call.from_user.id)
        )
    await call.answer()


@dp.callback_query(F.data == "room")
async def room(call: CallbackQuery):
    cur = conn.execute("SELECT status FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 1", (call.from_user.id,))
    r = cur.fetchone()
    if not r or r[0] != "approved":
        await call.message.answer("🔒 Pehle tumhari registration/payment approve hona zaroori hai.")
        await call.answer()
        return
    room_id = conn.execute("SELECT value FROM settings WHERE key='room_id'").fetchone()
    password = conn.execute("SELECT value FROM settings WHERE key='room_password'").fetchone()
    if not room_id or not password:
        await call.message.answer("⏳ Abhi Room ID & Password set nahi kiya gaya hai. Thoda wait karo.")
    else:
        await call.message.answer(f"🔐 <b>Room ID:</b> {room_id[0]}\n🔑 <b>Password:</b> {password[0]}", parse_mode="HTML")
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
    text = conn.execute("SELECT value FROM settings WHERE key='results'").fetchone()
    await call.message.answer(text[0] if text else "🏆 Abhi results publish nahi hue hain. Thoda wait karo.")
    await call.answer()


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    await call.message.answer("👑 <b>FX BR ADMIN PANEL</b>\n\nKya karna hai, option select karo:", reply_markup=admin_panel_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "admin_room")
async def admin_room(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Sirf admin use kar sakta hai.", show_alert=True)
        return
    await state.set_state(Admin.room_id)
    await call.message.answer("🔐 <b>Room ID</b> bhejo:", parse_mode="HTML")
    await call.answer()


@dp.message(Admin.room_id)
async def admin_room_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(room_id=message.text.strip())
    await state.set_state(Admin.room_password)
    await message.answer("🔑 Ab <b>Room Password</b> bhejo:", parse_mode="HTML")


@dp.message(Admin.room_password)
async def admin_room_password(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('room_id',?)", (data["room_id"],))
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('room_password',?)", (message.text.strip(),))
    conn.commit()
    await state.clear()
    await message.answer(
        f"✅ <b>Room details save ho gaye!</b>\n\n🔐 Room ID: <code>{data['room_id']}</code>\n🔑 Password: <code>{message.text.strip()}</code>",
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
    text = message.text.strip()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('results',?)", (text,))
    conn.commit()
    await state.clear()
    await message.answer("✅ <b>Results successfully publish ho gaye!</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")


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


# Old commands remain available as backup.
@dp.message(F.text.startswith("/setroom "))
async def setroom(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Use: /setroom ROOM_ID PASSWORD")
        return
    room_id, password = parts[1], parts[2]
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('room_id',?)", (room_id,))
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('room_password',?)", (password,))
    conn.commit()
    await message.answer("🔐 Room ID & Password save ho gaya.")


@dp.message(F.text.startswith("/setresults "))
async def setresults(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text[len("/setresults "):].strip()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('results',?)", (text,))
    conn.commit()
    await message.answer("🏆 Results update ho gaye.")


@dp.message(F.text == "/admin")
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👑 <b>FX BR ADMIN PANEL</b>\n\nKya karna hai, option select karo:", reply_markup=admin_panel_kb(), parse_mode="HTML")


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
