import os
import logging
import time
import re
from dotenv import load_dotenv
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN and ADMIN_ID must be set in the .env file")

ADMIN_ID = int(ADMIN_ID)

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# State Storage
# user_sessions : {user_id: {"username": str, "msg_count": int, "open": bool}}
# pending_requests : {user_id: {"username": str, "time": float}}
# ─────────────────────────────────────────────
user_sessions = {}
pending_requests = {}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def get_username(user):
    return f"@{user.username}" if user.username else user.first_name


def make_resolve_markup(user_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Mark as Resolved", callback_data=f"resolve_{user_id}"))
    return markup


def build_first_message_header(username, user_id):
    return (
        f"┌─────────────────────\n"
        f"│ 📩 <b>New Support Ticket</b>\n"
        f"│\n"
        f"│ 👤 <b>User:</b> {username}\n"
        f"│ 🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"└─────────────────────\n"
        f"<b>Message:</b>\n"
    )


def build_followup_header(username, user_id, count):
    return (
        f"┌─ 🔁 <b>Follow-up #{count}</b>\n"
        f"│ {username} · <code>{user_id}</code>\n"
        f"└─────────────────────\n"
    )


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id

        if user_id == ADMIN_ID:
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(KeyboardButton('📋 Pending Tickets'))
            bot.send_message(
                ADMIN_ID,
                "👋 <b>Admin Panel — dafaxbet.com Support</b>\n\n"
                "• <b>Reply</b> to any user message to respond\n"
                "• Press <b>✅ Mark as Resolved</b> to close a ticket\n"
                "• Use <b>📋 Pending Tickets</b> to see open cases",
                reply_markup=markup
            )
            return

        user_sessions[user_id] = {
            "username": get_username(message.from_user),
            "msg_count": 0,
            "open": True
        }

        bot.send_message(
            message.chat.id,
            "👋 <b>Welcome to dafaxbet.com Support!</b>\n\n"
            "Describe your issue below — text or screenshot, anything works.\n"
            "<i>You can send multiple messages, our team will reply here.</i>",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"/start error: {e}")


# ─────────────────────────────────────────────
# ADMIN: View Pending Tickets
# ─────────────────────────────────────────────
@bot.message_handler(
    func=lambda m: m.text == '📋 Pending Tickets' and m.chat.id == ADMIN_ID
)
def show_pending_tickets(message):
    try:
        if not pending_requests:
            bot.send_message(ADMIN_ID, "✅ <b>No open tickets right now.</b>")
            return

        lines = ["📋 <b>Open Tickets</b>\n"]
        for i, (uid, data) in enumerate(pending_requests.items(), 1):
            mins_ago = int((time.time() - data['time']) / 60)
            lines.append(
                f"{i}. {data['username']}  ·  <code>{uid}</code>\n"
                f"   ⏱ {mins_ago} min ago\n"
            )
        lines.append("<i>Reply to their message in chat to respond.</i>")
        bot.send_message(ADMIN_ID, "\n".join(lines))
    except Exception as e:
        logger.error(f"Pending tickets error: {e}")


# ─────────────────────────────────────────────
# USER → ADMIN: Forward messages
# ─────────────────────────────────────────────
@bot.message_handler(
    content_types=['text', 'photo'],
    func=lambda m: m.chat.id != ADMIN_ID
)
def handle_user_message(message):
    try:
        user_id = message.from_user.id

        if user_id not in user_sessions:
            bot.send_message(message.chat.id, "Please send /start to begin.")
            return

        session = user_sessions[user_id]
        session["msg_count"] += 1
        count = session["msg_count"]
        username = session["username"]

        # Track in pending
        pending_requests[user_id] = {
            "username": username,
            "time": time.time()
        }

        markup = make_resolve_markup(user_id)

        # First message → full card, follow-ups → compact header
        if count == 1:
            header = build_first_message_header(username, user_id)
        else:
            header = build_followup_header(username, user_id, count)

        if message.content_type == 'text':
            full_msg = f"{header}{message.text}"
            bot.send_message(ADMIN_ID, full_msg, reply_markup=markup if count == 1 else None)

        elif message.content_type == 'photo':
            caption_text = message.caption or ""
            full_caption = f"{header}{caption_text}"
            if len(full_caption) > 1024:
                full_caption = full_caption[:1020] + "…"
            bot.send_photo(
                ADMIN_ID,
                message.photo[-1].file_id,
                caption=full_caption,
                reply_markup=markup if count == 1 else None
            )

        # Subtle ack to user (no spam)
        if count == 1:
            bot.send_message(
                message.chat.id,
                "✅ <b>Received!</b> Our team will reply shortly.\n"
                "<i>You can send more details anytime.</i>"
            )
        else:
            bot.send_message(message.chat.id, "📨 <i>Message added to your ticket.</i>")

    except Exception as e:
        logger.error(f"User message error: {e}")
        bot.send_message(message.chat.id, "⚠️ Something went wrong. Please try again.")


# ─────────────────────────────────────────────
# ADMIN → USER: Reply
# ─────────────────────────────────────────────
@bot.message_handler(
    content_types=['text', 'photo'],
    func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message is not None
)
def handle_admin_reply(message):
    try:
        reply_to = message.reply_to_message

        # Parse text from replied message
        if reply_to.content_type == 'text':
            source_text = reply_to.text or ""
        elif reply_to.content_type == 'photo':
            source_text = reply_to.caption or ""
        else:
            source_text = ""

        # Extract UserID
        if "ID:</b>" not in source_text and "ID:</b" not in source_text:
            # Try plain text fallback
            if "UserID:" in source_text:
                id_marker = "UserID:"
            else:
                bot.send_message(ADMIN_ID, "❌ <b>Can't find User ID</b> in that message.\nMake sure you're replying to a support ticket.")
                return
        else:
            id_marker = "ID:</b>"

        parts = source_text.split(id_marker)
        if len(parts) < 2:
            bot.send_message(ADMIN_ID, "❌ Could not parse User ID from that message.")
            return

        raw_id = parts[1].split('\n')[0].strip()
        clean_id = re.sub(r'<[^>]+>', '', raw_id).strip()

        if not clean_id.isdigit():
            bot.send_message(ADMIN_ID, f"❌ Invalid user ID extracted: <code>{clean_id}</code>")
            return

        target_user_id = int(clean_id)

        # Build reply to user
        reply_header = "🎧 <b>Support Team Reply:</b>\n\n"
        reply_footer = "\n\n<i>— dafaxbet.com Support</i>"

        if message.content_type == 'text':
            bot.send_message(target_user_id, f"{reply_header}{message.text}{reply_footer}")

        elif message.content_type == 'photo':
            cap = message.caption or ""
            full_cap = f"{reply_header}{cap}{reply_footer}"
            if len(full_cap) > 1024:
                full_cap = full_cap[:1020] + "…"
            bot.send_photo(target_user_id, message.photo[-1].file_id, caption=full_cap)

        # Close ticket + clean up
        if target_user_id in pending_requests:
            del pending_requests[target_user_id]

        # Reset msg_count so next user message starts fresh thread
        if target_user_id in user_sessions:
            user_sessions[target_user_id]["msg_count"] = 0

        # Remove resolve button from original ticket card
        try:
            bot.edit_message_reply_markup(
                chat_id=ADMIN_ID,
                message_id=reply_to.message_id,
                reply_markup=None
            )
        except Exception:
            pass

        bot.send_message(
            ADMIN_ID,
            f"✅ <b>Reply sent</b> to {pending_requests.get(target_user_id, {}).get('username', f'<code>{target_user_id}</code>')}.\n"
            f"Ticket auto-closed."
        )

    except Exception as e:
        logger.error(f"Admin reply error: {e}")
        bot.send_message(ADMIN_ID, "❌ Failed to send reply. Check logs.")


# ─────────────────────────────────────────────
# ADMIN: Mark as Resolved (button)
# ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data.startswith('resolve_'))
def handle_resolve_ticket(call):
    try:
        if call.message.chat.id != ADMIN_ID:
            return

        user_id = int(call.data.split('_')[1])

        if user_id in pending_requests:
            uname = pending_requests[user_id]['username']
            del pending_requests[user_id]
            if user_id in user_sessions:
                user_sessions[user_id]["msg_count"] = 0
            bot.answer_callback_query(call.id, "✅ Ticket resolved!")
            try:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass
            # Subtle inline edit to show resolved state
            try:
                original_text = call.message.text or call.message.caption or ""
                resolved_text = original_text + f"\n\n<i>✅ Resolved</i>"
                if call.message.content_type == 'text':
                    bot.edit_message_text(
                        chat_id=ADMIN_ID,
                        message_id=call.message.message_id,
                        text=resolved_text,
                        parse_mode="HTML"
                    )
                # For photos we skip text edit (caption limit)
            except Exception:
                pass
        else:
            bot.answer_callback_query(call.id, "⚠️ Already resolved.", show_alert=True)
            try:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Resolve error: {e}")


# ─────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Bot starting...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
