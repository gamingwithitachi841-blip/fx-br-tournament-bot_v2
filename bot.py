import os, sqlite3, asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip(); ADMIN_ID=int(os.getenv('ADMIN_ID','8628267774')); ENTRY_FEE=30; MAX_SLOTS=48
QR_PATH=os.path.join(os.path.dirname(__file__),'payment_qr.png')
if not BOT_TOKEN: raise RuntimeError('BOT_TOKEN is missing')
bot=Bot(BOT_TOKEN); dp=Dispatcher(); conn=sqlite3.connect('fxbr.db',check_same_thread=False); conn.row_factory=sqlite3.Row

def col(table,name,definition):
    if name not in [x['name'] for x in conn.execute(f'PRAGMA table_info({table})')]: conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
conn.execute('''CREATE TABLE IF NOT EXISTS registrations(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,username TEXT,name TEXT NOT NULL,uid TEXT NOT NULL,ign TEXT NOT NULL,payment_file_id TEXT,status TEXT NOT NULL DEFAULT 'pending',slot INTEGER,match_no INTEGER DEFAULT 1,round_id INTEGER,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
col('registrations','match_no','INTEGER DEFAULT 1'); col('registrations','round_id','INTEGER')
conn.execute('''CREATE TABLE IF NOT EXISTS match_rounds(id INTEGER PRIMARY KEY AUTOINCREMENT,match_no INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'active',room_id TEXT DEFAULT '',room_pass TEXT DEFAULT '',results TEXT DEFAULT '',created_at DATETIME DEFAULT CURRENT_TIMESTAMP,completed_at DATETIME)''')
conn.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)'''); conn.commit()

def setting(k,d=''):
    r=conn.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone(); return r['value'] if r else d
def set_setting(k,v):
    conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v))); conn.commit()
def active(): return conn.execute("SELECT * FROM match_rounds WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
if not active():
    conn.execute("INSERT INTO match_rounds(match_no,status) VALUES(1,'active')"); conn.commit()
def approved(rid): return conn.execute("SELECT COUNT(*) c FROM registrations WHERE round_id=? AND status='approved'",(rid,)).fetchone()['c']
def reserved(rid): return conn.execute("SELECT COUNT(*) c FROM registrations WHERE round_id=? AND status IN ('pending','approved')",(rid,)).fetchone()['c']
def free_slot(rid):
    used={r['slot'] for r in conn.execute("SELECT slot FROM registrations WHERE round_id=? AND status='approved' AND slot IS NOT NULL",(rid,))}
    return next((n for n in range(1,49) if n not in used),None)
def menu(uid=None):
    keys={'book':'📖 Book','my':'🎟️ My Booking','room':'🔐 Room ID & Password','rules':'📜 Rules','results':'🏆 Results'}; rows=[[KeyboardButton(text=v)] for k,v in keys.items() if setting('menu_'+k,'1')=='1']
    if uid==ADMIN_ID: rows.append([KeyboardButton(text='👑 Admin Panel')])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)
def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='🔐 Set Room ID & Password'),KeyboardButton(text='🏆 Set Results')],[KeyboardButton(text='👥 Manage Registrations')],[KeyboardButton(text='🪑 Slot List')],[KeyboardButton(text='🔄 Switch / Allow New Booking')],[KeyboardButton(text='🎛️ Manage Public Menu'),KeyboardButton(text='📊 Registration Stats')],[KeyboardButton(text='⬅️ Main Menu')]],resize_keyboard=True)

class Reg(StatesGroup): name=State(); uid=State(); ign=State(); payment=State()
class Admin(StatesGroup): room=State(); results=State()

@dp.message(CommandStart())
@dp.message(Command('menu'))
async def start(m:Message):
    r=active(); b=approved(r['id']) if r else 0; mn=r['match_no'] if r else 1
    await m.answer(f'🎮 FX BR SOLO TOURNAMENT 🇮🇳\n\n🎯 Current Match: Match {mn}\n🪑 Slots: {b}/48 booked\n🟢 Available: {48-b}\n\nMenu se option choose karo.',reply_markup=menu(m.from_user.id))

@dp.message(F.text=='📖 Book')
async def book(m:Message,s:FSMContext):
    await s.clear(); r=active()
    if not r: return await m.answer('⏳ Abhi koi active match nahi hai.')
    old=conn.execute("SELECT id FROM registrations WHERE telegram_id=? AND round_id=? AND status IN ('pending','approved') LIMIT 1",(m.from_user.id,r['id'])).fetchone()
    if old: return await m.answer('😊 Tum already book karliye ho. Pehle first match khelo, uske baad hi dobara book hoga. 🫶')
    if reserved(r['id'])>=48: return await m.answer('⏳ Ye match full ho gaya. Next match activate ho raha hai.')
    await s.set_state(Reg.name); await m.answer(f'📖 Book - Match {r["match_no"]}\n\nEntry Fee: ₹{ENTRY_FEE}\n🪑 Slots: {approved(r["id"])}/48\n\nApna Name bhejo:')
@dp.message(Reg.name)
async def rn(m,s): await s.update_data(name=m.text.strip()); await s.set_state(Reg.uid); await m.answer('🎮 Apna Free Fire UID bhejo:')
@dp.message(Reg.uid)
async def ru(m,s): await s.update_data(uid=m.text.strip()); await s.set_state(Reg.ign); await m.answer('👤 Apna In-Game Name (IGN) bhejo:')
@dp.message(Reg.ign)
async def ri(m,s):
    await s.update_data(ign=m.text.strip()); await s.set_state(Reg.payment)
    if os.path.exists(QR_PATH): await m.answer_photo(FSInputFile(QR_PATH),caption=f'💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo.')
    else: await m.answer(f'💰 Payment ₹{ENTRY_FEE} karo.\n\nPayment ke baad screenshot bhejo.')
@dp.message(Reg.payment,F.photo)
async def rp(m,s):
    d=await s.get_data(); r=active()
    if not r or reserved(r['id'])>=48: await s.clear(); return await m.answer('⏳ Match full/change ho gaya. Please dobara Book karo.')
    if conn.execute("SELECT id FROM registrations WHERE telegram_id=? AND round_id=? AND status IN ('pending','approved')",(m.from_user.id,r['id'])).fetchone(): await s.clear(); return await m.answer('😊 Tum already book karliye ho. Pehle first match khelo, uske baad hi dobara book hoga. 🫶')
    cur=conn.execute("INSERT INTO registrations(telegram_id,username,name,uid,ign,payment_file_id,status,match_no,round_id) VALUES(?,?,?,?,?,?,?,?,?)",(m.from_user.id,m.from_user.username or '',d['name'],d['uid'],d['ign'],m.photo[-1].file_id,'pending',r['match_no'],r['id'])); rid=cur.lastrowid; conn.commit(); await s.clear()
    await m.answer(f'✅ Booking submit ho gayi!\n🎯 Match: {r["match_no"]}\n🆔 Registration ID: #{rid}\n\nAdmin approval ka wait karo.',reply_markup=menu(m.from_user.id))
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Approve',callback_data=f'app:{rid}'),InlineKeyboardButton(text='❌ Reject',callback_data=f'rej:{rid}')],[InlineKeyboardButton(text='🗑️ Remove',callback_data=f'rem:{rid}')]])
    await bot.send_photo(ADMIN_ID,m.photo[-1].file_id,caption=f'🆕 New Booking #{rid}\n\n🎯 Match: {r["match_no"]}\nName: {d["name"]}\nUID: {d["uid"]}\nIGN: {d["ign"]}\nUser: @{m.from_user.username or "NoUsername"}',reply_markup=kb)
@dp.message(Reg.payment)
async def rpw(m): await m.answer('❗ Payment screenshot image bhejo, please.')

@dp.message(F.text=='🎟️ My Booking')
async def my(m):
    rows=conn.execute('SELECT * FROM registrations WHERE telegram_id=? ORDER BY id DESC LIMIT 10',(m.from_user.id,)).fetchall()
    if not rows:return await m.answer('❌ Abhi koi booking nahi hai.')
    await m.answer('🎟️ Tumhari Bookings:\n\n'+'\n'.join(f'🆔 #{r["id"]} | 🎯 Match {r["match_no"]} | {r["status"].upper()} | 🎟️ Slot {r["slot"] or "-"}\n👤 {r["ign"]}' for r in rows))
@dp.message(F.text=='🔐 Room ID & Password')
async def room(m):
    r=active()
    if not r:return await m.answer('⏳ Abhi koi active match nahi hai.')
    if not conn.execute("SELECT id FROM registrations WHERE telegram_id=? AND round_id=? AND status='approved'",(m.from_user.id,r['id'])).fetchone():return await m.answer('🔒 Pehle current match ka payment approve hona zaroori hai.')
    rid=r['room_id'] or setting('room_id'); pw=r['room_pass'] or setting('room_pass')
    await m.answer(f'🔐 ROOM DETAILS - MATCH {r["match_no"]}\n\n🆔 Room ID: {rid}\n🔑 Password: {pw}' if rid and pw else '⏳ Room ID & Password abhi publish nahi hua. Wait karo.')
@dp.message(F.text=='📜 Rules')
async def rules(m): await m.answer('📜 RULES\n\n1. No team up — team up karoge to no prize, no refund.\n2. No revive.\n3. E-sports mode ON.\n4. Random kill = no prize.\n5. Jisko jo slot milega, usi slot par rahega.\n6. All guns & character skills allowed.\n7. Network ya kisi bhi issue par management ka decision final hai.')
@dp.message(F.text=='🏆 Results')
async def results(m):
    r=active(); await m.answer((r['results'] if r and r['results'] else setting('results','🏆 Results abhi publish nahi hua.')))

async def switch_if_full():
    r=active()
    if not r or reserved(r['id'])<48:return
    nxt=2 if r['match_no']==1 else 1
    conn.execute("UPDATE match_rounds SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",(r['id'],)); conn.execute("INSERT INTO match_rounds(match_no,status) VALUES(?,'active')",(nxt,)); conn.commit()
    try: await bot.send_message(ADMIN_ID,f'🔄 Match {r["match_no"]} ke 48 slots full. ✅ Match {nxt} active hai.')
    except: pass

@dp.message(F.text=='👑 Admin Panel')
async def ap(m):
    if m.from_user.id!=ADMIN_ID:return
    r=active(); await m.answer(f'👑 Admin Panel\n\n🎯 Active Match: {r["match_no"]}\n🪑 Approved: {approved(r["id"])}/48',reply_markup=admin_menu())
@dp.message(F.text=='⬅️ Main Menu')
async def mm(m): await m.answer('Main Menu',reply_markup=menu(m.from_user.id))

@dp.message(F.text=='🔐 Set Room ID & Password')
async def sr(m,s):
    if m.from_user.id==ADMIN_ID: await s.set_state(Admin.room); await m.answer('Room ID aur Password ek line me bhejo. Example:\n12345678 1234')
@dp.message(Admin.room)
async def srs(m,s):
    if m.from_user.id!=ADMIN_ID:return
    p=m.text.split(maxsplit=1)
    if len(p)<2:return await m.answer('Format: ROOMID PASSWORD')
    r=active(); conn.execute('UPDATE match_rounds SET room_id=?,room_pass=? WHERE id=?',(p[0],p[1],r['id'])); conn.commit(); set_setting('room_id',p[0]); set_setting('room_pass',p[1]); await s.clear(); await m.answer(f'✅ Match {r["match_no"]} ka Room ID & Password save ho gaya.')
@dp.message(F.text=='🏆 Set Results')
async def srst(m,s):
    if m.from_user.id==ADMIN_ID: await s.set_state(Admin.results); await m.answer('Results ka text bhejo:')
@dp.message(Admin.results)
async def srss(m,s):
    if m.from_user.id!=ADMIN_ID:return
    r=active(); conn.execute('UPDATE match_rounds SET results=? WHERE id=?',(m.text,r['id'])); conn.commit(); set_setting('results',m.text); await s.clear(); await m.answer('✅ Results save ho gaya.')

@dp.message(F.text=='👥 Manage Registrations')
async def manage(m):
    if m.from_user.id!=ADMIN_ID:return
    rows=conn.execute('SELECT * FROM registrations ORDER BY id DESC LIMIT 30').fetchall()
    if not rows:return await m.answer('Koi registration nahi hai.')
    for r in rows:
        kb=[]
        if r['status']=='pending':kb=[[InlineKeyboardButton(text='✅ Approve',callback_data=f'app:{r["id"]}'),InlineKeyboardButton(text='❌ Reject',callback_data=f'rej:{r["id"]}')]]
        kb.append([InlineKeyboardButton(text='🗑️ Remove',callback_data=f'rem:{r["id"]}')])
        await m.answer(f'#{r["id"]} | {r["status"].upper()} | Match {r["match_no"]} | Slot {r["slot"] or "-"}\n👤 {r["name"]}\n🎮 UID: {r["uid"]}\nIGN: {r["ign"]}',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message(F.text=='🪑 Slot List')
async def sl(m):
    if m.from_user.id==ADMIN_ID: await m.answer('🪑 Slot List',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🎯 Match 1',callback_data='slots:1')],[InlineKeyboardButton(text='🎯 Match 2',callback_data='slots:2')]]))
@dp.callback_query(F.data.startswith('slots:'))
async def slots(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    mn=int(c.data.split(':')[1]); r=conn.execute('SELECT * FROM match_rounds WHERE match_no=? ORDER BY id DESC LIMIT 1',(mn,)).fetchone(); by={}
    if r:
        by={x['slot']:x for x in conn.execute("SELECT * FROM registrations WHERE round_id=? AND status='approved'",(r['id'],)).fetchall() if x['slot']}
    for st in range(1,49,12):
        txt=f'🎯 MATCH {mn} — SLOTS {st}-{min(st+11,48)}\n'+'\n'.join(f'🪑 Slot {n} — {by[n]["ign"]} — UID {by[n]["uid"]}' if n in by else f'⬜ Slot {n} — Empty' for n in range(st,min(st+11,48)+1)); await c.message.answer(txt)
    btn=[[InlineKeyboardButton(text=f'🗑️ Delete Slot {n}',callback_data=f'dslot:{r["id"]}:{n}')] for n in sorted(by)] if r else []
    btn.append([InlineKeyboardButton(text=f'🗑️ Clear Match {mn}',callback_data=f'clearask:{mn}')]); await c.message.answer(f'🎯 Match {mn} controls:',reply_markup=InlineKeyboardMarkup(inline_keyboard=btn)); await c.answer()
@dp.callback_query(F.data.startswith('dslot:'))
async def ds(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    _,rid,n=c.data.split(':'); row=conn.execute("SELECT * FROM registrations WHERE round_id=? AND slot=? AND status='approved'",(int(rid),int(n))).fetchone()
    if not row:return await c.answer('Slot already empty')
    conn.execute('DELETE FROM registrations WHERE id=?',(row['id'],)); conn.commit(); await c.answer(f'Slot {n} deleted'); await c.message.edit_reply_markup(reply_markup=None)
@dp.callback_query(F.data.startswith('clearask:'))
async def ca(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    mn=int(c.data.split(':')[1]); await c.message.answer(f'⚠️ Match {mn} ka slot list clear karna hai?',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Yes, Clear',callback_data=f'clear:{mn}'),InlineKeyboardButton(text='❌ Cancel',callback_data='cancelclear')]])); await c.answer()
@dp.callback_query(F.data=='cancelclear')
async def cc(c): await c.message.edit_text('❌ Clear cancel.'); await c.answer()
@dp.callback_query(F.data.startswith('clear:'))
async def clr(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    mn=int(c.data.split(':')[1]); r=conn.execute('SELECT * FROM match_rounds WHERE match_no=? ORDER BY id DESC LIMIT 1',(mn,)).fetchone()
    if r: conn.execute('DELETE FROM registrations WHERE round_id=?',(r['id'],)); conn.commit()
    await c.message.edit_text(f'✅ Match {mn} ka slot list clear ho gaya. Slot 1-48 fresh available.'); await c.answer()

@dp.message(F.text=='🔄 Switch / Allow New Booking')
async def sm(m):
    if m.from_user.id==ADMIN_ID: await m.answer('🔄 Active match select karo:',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🎯 Activate Match 1',callback_data='activate:1')],[InlineKeyboardButton(text='🎯 Activate Match 2',callback_data='activate:2')]]))
@dp.callback_query(F.data.startswith('activate:'))
async def act(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    mn=int(c.data.split(':')[1]); old=active()
    if old and old['match_no']==mn:return await c.answer('Already active')
    if old: conn.execute("UPDATE match_rounds SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",(old['id'],))
    conn.execute("INSERT INTO match_rounds(match_no,status) VALUES(?,'active')",(mn,)); conn.commit(); await c.message.answer(f'✅ Match {mn} active ho gaya. Slots 0/48.'); await c.answer()

@dp.message(F.text=='🎛️ Manage Public Menu')
async def mp(m):
    if m.from_user.id!=ADMIN_ID:return
    labels={'book':'📖 Book','my':'🎟️ My Booking','room':'🔐 Room ID & Password','rules':'📜 Rules','results':'🏆 Results'}
    await m.answer('🎛️ Public Menu ON/OFF',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'{v} — {"ON" if setting("menu_"+k,"1")=="1" else "OFF"}',callback_data=f'toggle:{k}')] for k,v in labels.items()]))
@dp.callback_query(F.data.startswith('toggle:'))
async def tog(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    k=c.data.split(':')[1]; set_setting('menu_'+k,'0' if setting('menu_'+k,'1')=='1' else '1'); await c.answer('Updated')
@dp.message(F.text=='📊 Registration Stats')
async def stats(m):
    if m.from_user.id!=ADMIN_ID:return
    r=active(); await m.answer(f'📊 Stats\n\n🎯 Active Match: {r["match_no"]}\n🪑 Approved: {approved(r["id"])}/48\n📌 Approved + Pending: {reserved(r["id"])}/48\n\nTotal: {conn.execute("SELECT COUNT(*) c FROM registrations").fetchone()["c"]}')

@dp.callback_query(F.data.startswith('app:'))
async def app(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    rid=int(c.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone(); r=active()
    if not row:return await c.answer('Not found')
    if row['status']!='pending':return await c.answer('Already processed')
    if not r or row['round_id']!=r['id']: conn.execute("UPDATE registrations SET status='rejected' WHERE id=?",(rid,)); conn.commit(); await c.answer('Old match'); return
    if approved(r['id'])>=48:return await c.answer('48 slots full')
    slot=free_slot(r['id']); conn.execute("UPDATE registrations SET status='approved',slot=? WHERE id=?",(slot,rid)); conn.commit(); await c.answer('Approved'); await c.message.edit_reply_markup(reply_markup=None); await bot.send_message(row['telegram_id'],f'✅ Payment Approved!\n\n🎯 Match: {r["match_no"]}\n🎟️ Tumhara Slot: {slot}\n\nRoom ID & Password publish hone ke baad tumhe mil jayega.'); await switch_if_full()
@dp.callback_query(F.data.startswith('rej:'))
async def rej(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    rid=int(c.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone()
    if not row:return await c.answer('Not found')
    conn.execute("UPDATE registrations SET status='rejected' WHERE id=?",(rid,)); conn.commit(); await c.answer('Rejected'); await c.message.edit_reply_markup(reply_markup=None); await bot.send_message(row['telegram_id'],'❌ Payment reject ho gaya. Zarurat ho to dobara Book karo.')
@dp.callback_query(F.data.startswith('rem:'))
async def rem(c):
    if c.from_user.id!=ADMIN_ID:return await c.answer('Not allowed')
    rid=int(c.data.split(':')[1]); row=conn.execute('SELECT * FROM registrations WHERE id=?',(rid,)).fetchone()
    if not row:return await c.answer('Already removed')
    conn.execute('DELETE FROM registrations WHERE id=?',(rid,)); conn.commit(); await c.answer('Removed'); await c.message.edit_reply_markup(reply_markup=None); await bot.send_message(row['telegram_id'],'🗑️ Tumhari booking admin ne remove kar di hai. Zarurat ho to dobara Book karo.')

async def main(): await dp.start_polling(bot)
if __name__=='__main__': asyncio.run(main())
