import os
import sqlite3
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_ID = int(os.getenv('ADMIN_ID', '8628267774'))
ENTRY_FEE = 30
QR_PATH = os.path.join(os.path.dirname(__file__), 'payment_qr.png')

if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN is missing')

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
conn = sqlite3.connect('fxbr.db', check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute('''CREATE TABLE IF NOT EXISTS registrations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 telegram_id INTEGER NOT NULL,
 username TEXT,
 name TEXT NOT NULL,
 uid TEXT NOT NULL,
 ign TEXT NOT NULL,
 payment_file_id TEXT,
 status TEXT NOT NULL DEFAULT 'pending',
 slot INTEGER,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)''')
conn.execute('''CREATE TABLE IF NOT EXISTS settings (
 key TEXT PRIMARY KEY,
 value TEXT
)''')
conn.commit()

MENU_KEYS = {
 'register': '📝 Register',
 'myreg': '🎟️ My Registration',
 'room': '🔐 Room ID & Password',
 'rules': '📜 Rules',
 'results': '🏆 Results'
}

def setting(key, default=''):
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default

def set_setting(key, value):
    conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    conn.commit()

def menu_kb(user_id=None):
    rows=[]
    for key, label in MENU_KEYS.items():
        if setting('menu_'+key, '1') == '1':
            rows.append([KeyboardButton(text=label)])
    if user_id == ADMIN_ID:
        rows.append([KeyboardButton(text='👑 Admin Panel')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

class Reg(StatesGroup):
    name=State(); uid=State(); ign=State(); payment=State()

class AdminState(StatesGroup):
    room=State(); results=State()

@dp.message(CommandStart())
@dp.message(Command('menu'))
async def start(message: Message):
    await message.answer('🎮 FX BR SOLO TOURNAMENT 🇮🇳\n\nMenu se option choose karo.', reply_markup=menu_kb(message.from_user.id))

@dp.message(F.text == '📝 Register')
async def register(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Reg.name)
    await message.answer(f'📝 New Match Registration\n\nEntry Fee: ₹{ENTRY_FEE}\n\nApna Name bhejo:')

@dp.message(Reg.name)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Reg.uid)
    await message.answer('🎮 Apna Free Fire UID bhejo:')

@dp.message(Reg.uid)
async def reg_uid(message: Message, state: FSMContext):
    await state.update_data(uid=message.text.strip())
    await state.set_state(Reg.ign)
    await message.answer('👤 Apna In-Game Name (IGN) bhejo:')

@dp.message(Reg.ign)
async def reg_ign(message: Message, state: FSMContext):
    await state.update_data(ign=message.text.strip())
    await state.set_state(Reg.payment)
    if os.path.exists(QR_PATH):
        qr = FSInputFile(QR_PATH)
        await message.answer_photo(
            photo=qr,
            caption=f'💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo.'
        )
    else:
        await message.answer(f'💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo.')

@dp.message(Reg.payment, F.photo)
async def reg_payment(message: Message, state: FSMContext):
    data=await state.get_data()
    cur=conn.execute('INSERT INTO registrations(telegram_id,username,name,uid,ign,payment_file_id,status) VALUES(?,?,?,?,?,?,?)',
                     (message.from_user.id, message.from_user.username or '', data['name'], data['uid'], data['ign'], message.photo[-1].file_id, 'pending'))
    reg_id=cur.lastrowid
    conn.commit()
    await state.clear()
    await message.answer(f'✅ Registration submit ho gayi!\nRegistration ID: #{reg_id}\n\nAdmin approval ka wait karo. Approval ke baad slot aur Room ID & Password milega.', reply_markup=menu_kb(message.from_user.id))
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Approve', callback_data=f'app:{reg_id}'),InlineKeyboardButton(text='❌ Reject', callback_data=f'rej:{reg_id}')],[InlineKeyboardButton(text='🗑️ Remove', callback_data=f'rem:{reg_id}')]])
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f'🆕 New Registration #{reg_id}\n\nName: {data["name"]}\nUID: {data["uid"]}\nIGN: {data["ign"]}\nUser: @{message.from_user.username or "NoUsername"}', reply_markup=kb)

@dp.message(Reg.payment)
async def reg_payment_wrong(message: Message):
    await message.answer('❗ Payment screenshot image bhejo, please.')

@dp.message(F.text == '🎟️ My Registration')
async def myreg(message: Message):
    rows=conn.execute('SELECT * FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 10',(message.from_user.id,)).fetchall()
    if not rows:
        await message.answer('❌ Abhi koi registration nahi hai.')
        return
    text='🎟️ Tumhari Registrations:\n\n'
    for r in rows:
        slot=f'#{r["slot"]}' if r['slot'] else '-'
        text += f'🆔 Registration: #{r["id"]}\n📌 Status: {r["status"].upper()}\n🎟️ Slot: {slot}\n👤 {r["ign"]}\n\n'
    await message.answer(text)

@dp.message(F.text == '🔐 Room ID & Password')
async def room(message: Message):
    approved=conn.execute('SELECT id FROM registrations WHERE telegram_id=? AND status="approved" ORDER BY id DESC LIMIT 1',(message.from_user.id,)).fetchone()
    if not approved:
        await message.answer('🔒 Pehle payment approve hona zaroori hai.')
        return
    rid=setting('room_id'); pwd=setting('room_pass')
    if not rid or not pwd:
        await message.answer('⏳ Room ID & Password abhi publish nahi hua. Wait karo.')
    else:
        await message.answer(f'🔐 ROOM DETAILS\n\n🆔 Room ID: {rid}\n🔑 Password: {pwd}\n\n⚠️ Kisi ke saath share mat karo.')

@dp.message(F.text == '📜 Rules')
async def rules(message: Message):
    await message.answer('📜 RULES\n\n1. No team up — team up karoge to no prize, no refund.\n2. No revive.\n3. E-sports mode ON.\n4. Random kill = no prize.\n5. Jisko jo slot milega, usi slot par rahega.\n6. All guns & character skills allowed.\n7. Network ya kisi bhi issue par management ka decision final hai.')

@dp.message(F.text == '🏆 Results')
async def results(message: Message):
    await message.answer(setting('results','🏆 Results abhi publish nahi hua.'))

@dp.message(F.text == '👑 Admin Panel')
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='🔐 Set Room ID & Password')],[KeyboardButton(text='🏆 Set Results')],[KeyboardButton(text='👥 Manage Registrations')],[KeyboardButton(text='🎛️ Manage Public Menu')],[KeyboardButton(text='📊 Registration Stats')],[KeyboardButton(text='⬅️ Main Menu')]],resize_keyboard=True)
    await message.answer('👑 Admin Panel',reply_markup=kb)

@dp.message(F.text == '⬅️ Main Menu')
async def main_menu(message: Message):
    await message.answer('Main Menu',reply_markup=menu_kb(message.from_user.id))

@dp.message(F.text == '🔐 Set Room ID & Password')
async def setroom_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:return
    await state.set_state(AdminState.room); await message.answer('Room ID aur Password ek line me bhejo. Example:\n12345678 1234')

@dp.message(AdminState.room)
async def setroom_save(message: Message,state:FSMContext):
    if message.from_user.id != ADMIN_ID:return
    parts=message.text.split(maxsplit=1)
    if len(parts)<2: await message.answer('Format: ROOMID PASSWORD'); return
    set_setting('room_id',parts[0]); set_setting('room_pass',parts[1]); await state.clear(); await message.answer('✅ Room ID & Password save ho gaya.')

@dp.message(F.text == '🏆 Set Results')
async def setresults_start(message: Message,state:FSMContext):
    if message.from_user.id != ADMIN_ID:return
    await state.set_state(AdminState.results); await message.answer('Results ka text bhejo:')

@dp.message(AdminState.results)
async def setresults_save(message: Message,state:FSMContext):
    if message.from_user.id != ADMIN_ID:return
    set_setting('results',message.text); await state.clear(); await message.answer('✅ Results publish ho gaya.')

@dp.message(F.text == '👥 Manage Registrations')
async def manage(message: Message):
    if message.from_user.id != ADMIN_ID:return
    rows=conn.execute('SELECT * FROM registrations ORDER BY id DESC LIMIT 20').fetchall()
    if not rows: await message.answer('Koi registration nahi hai.'); return
    for r in rows:
        text=f'#{r["id"]} | {r["status"].upper()} | Slot: {r["slot"] or "-"}\n👤 {r["name"]}\n🎮 UID: {r["uid"]}\nIGN: {r["ign"]}'
        buttons=[]
        if r['status']=='pending': buttons.append([InlineKeyboardButton(text='✅ Approve',callback_data=f'app:{r["id"]}'),InlineKeyboardButton(text='❌ Reject',callback_data=f'rej:{r["id"]}')])
        buttons.append([InlineKeyboardButton(text='🗑️ Remove',callback_data=f'rem:{r["id"]}')])
        await message.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(F.text == '🎛️ Manage Public Menu')
async def manage_menu(message: Message):
    if message.from_user.id != ADMIN_ID:return
    kb=[]
    for key,label in MENU_KEYS.items():
        on=setting('menu_'+key,'1')=='1'; kb.append([InlineKeyboardButton(text=f'{label} — {"ON" if on else "OFF"}',callback_data=f'toggle:{key}')])
    await message.answer('🎛️ Public Menu ON/OFF',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(F.text == '📊 Registration Stats')
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:return
    total=conn.execute('SELECT COUNT(*) c FROM registrations').fetchone()['c']; pending=conn.execute('SELECT COUNT(*) c FROM registrations WHERE status="pending"').fetchone()['c']; approved=conn.execute('SELECT COUNT(*) c FROM registrations WHERE status="approved"').fetchone()['c']
    await message.answer(f'📊 Stats\n\nTotal: {total}\nPending: {pending}\nApproved: {approved}')

@dp.callback_query(F.data.startswith('app:'))
async def approve(call: CallbackQuery):
    if call.from_user.id!=ADMIN_ID:return await call.answer('Not allowed')
    rid=int(call.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone()
    if not row:return await call.answer('Registration not found')
    slot=conn.execute('SELECT COALESCE(MAX(slot),0)+1 s FROM registrations').fetchone()['s']
    conn.execute('UPDATE registrations SET status="approved", slot=? WHERE id=?',(slot,rid)); conn.commit()
    await call.answer('Approved'); await call.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(row['telegram_id'],f'✅ Payment Approved!\n\n🎟️ Tumhara Slot: {slot}\n\nRoom ID & Password publish hone ke baad tumhe mil jayega.')

@dp.callback_query(F.data.startswith('rej:'))
async def reject(call: CallbackQuery):
    if call.from_user.id!=ADMIN_ID:return await call.answer('Not allowed')
    rid=int(call.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone()
    if not row:return await call.answer('Not found')
    conn.execute('UPDATE registrations SET status="rejected" WHERE id=?',(rid,)); conn.commit(); await call.answer('Rejected'); await call.message.edit_reply_markup(reply_markup=None); await bot.send_message(row['telegram_id'],'❌ Payment reject ho gaya. Zarurat ho to dobara Register karo.')

@dp.callback_query(F.data.startswith('rem:'))
async def remove(call: CallbackQuery):
    if call.from_user.id!=ADMIN_ID:return await call.answer('Not allowed')
    rid=int(call.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone()
    if not row:return await call.answer('Already removed')
    conn.execute('DELETE FROM registrations WHERE id=?',(rid,)); conn.commit(); await call.answer('Removed'); await call.message.edit_reply_markup(reply_markup=None); await bot.send_message(row['telegram_id'],'🗑️ Tumhari registration admin ne remove kar di hai. Zarurat ho to dobara Register karo.')

@dp.callback_query(F.data.startswith('toggle:'))
async def toggle(call: CallbackQuery):
    if call.from_user.id!=ADMIN_ID:return await call.answer('Not allowed')
    key=call.data.split(':',1)[1]; new='0' if setting('menu_'+key,'1')=='1' else '1'; set_setting('menu_'+key,new); await call.answer('Updated')
    kb=[]
    for k,label in MENU_KEYS.items(): kb.append([InlineKeyboardButton(text=f'{label} — {"ON" if setting("menu_"+k,"1")=="1" else "OFF"}',callback_data=f'toggle:{k}')])
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

async def main():
    await dp.start_polling(bot)

if __name__=='__main__':
    import asyncio
    asyncio.run(main())
