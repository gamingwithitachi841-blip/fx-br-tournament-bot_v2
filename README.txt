# FX BR Solo Tournament Telegram Bot

Standalone Telegram bot. No website required.

Configured:
- Mode: Solo
- Entry fee: ₹30
- Admin Telegram ID: 8628267774
- Payment QR: payment_qr.png
- Payment screenshot approval
- Slot assignment
- Room ID & Password locked to approved players
- Rules and results

## Run
1. Install Python 3.10+.
2. Copy `.env.example` to `.env`.
3. Put your BotFather token in `.env`.
4. Run:
   pip install -r requirements.txt
   python bot.py

## Admin commands
/admin
/setroom ROOM_ID PASSWORD
/setresults YOUR_RESULT

Never share your BotFather token publicly.
