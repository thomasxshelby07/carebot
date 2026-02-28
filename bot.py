import os
import logging
import time
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# State Storage
#
# user_sessions   : {user_id: {"username": str, "msg_count": int}}
# pending_requests: {user_id: {"username": str, "time": float}}
# msg_map         : {admin_msg_id: user_id}   ← KEY FIX: reliable reply routing
# ─────────────────────────────────────────────
user_sessions    = {}
pending_requests = {}
msg_map          = {}   # Maps every forwarded admin message → original user_id


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


def send_to_admin_and_map(user_id, send_fn, *args, **kwargs):
    """
    Calls send_fn(*args, **kwargs) to send a message to admin,
    then registers the resulting message_id → user_id in msg_map.
    Returns the sent Message object.
    """
    sent = send_fn(*args, **kwargs)
    if sent:
        msg_map[sent.message_id] = user_id
        logger.info(f"msg_map updated: admin_msg_id={sent.message_id} → user_id={user_id}")
    return sent


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
                "• <b>Reply</b> to any forwarded user message to respond\n"
                "• Press <b>✅ Mark as Resolved</b> to close a ticket\n"
                "• Use <b>📋 Pending Tickets</b> to see open cases",
                reply_markup=markup
            )
            return

        # Reset / init session for user
        user_sessions[user_id] = {
            "username": get_username(message.from_user),
            "msg_count": 0
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
        lines.append("<i>Reply to a forwarded message in chat to respond.</i>")
        bot.send_message(ADMIN_ID, "\n".join(lines))
    except Exception as e:
        logger.error(f"Pending tickets error: {e}")


# ─────────────────────────────────────────────
# USER → ADMIN: Forward messages
# ─────────────────────────────────────────────
@bot.message_handler(
    content_types=['text', 'photo', 'document', 'video', 'voice', 'audio', 'sticker'],
    func=lambda m: m.chat.id != ADMIN_ID
)
def handle_user_message(message):
    try:
        user_id = message.from_user.id

        # Auto-register if user messages without /start
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                "username": get_username(message.from_user),
                "msg_count": 0
            }

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

        # Build header
        if count == 1:
            header = build_first_message_header(username, user_id)
        else:
            header = build_followup_header(username, user_id, count)

        # ── Forward to admin and register in msg_map ──
        if message.content_type == 'text':
            full_msg = f"{header}{message.text}"
            send_to_admin_and_map(
                user_id,
                bot.send_message,
                ADMIN_ID, full_msg, reply_markup=markup
            )

        elif message.content_type == 'photo':
            caption_text = message.caption or ""
            full_caption = f"{header}{caption_text}"
            if len(full_caption) > 1024:
                full_caption = full_caption[:1020] + "…"
            send_to_admin_and_map(
                user_id,
                bot.send_photo,
                ADMIN_ID,
                message.photo[-1].file_id,
                caption=full_caption,
                reply_markup=markup
            )

        elif message.content_type == 'document':
            caption_text = message.caption or ""
            full_caption = f"{header}{caption_text}"[:1024]
            send_to_admin_and_map(
                user_id,
                bot.send_document,
                ADMIN_ID,
                message.document.file_id,
                caption=full_caption,
                reply_markup=markup
            )

        elif message.content_type == 'video':
            caption_text = message.caption or ""
            full_caption = f"{header}{caption_text}"[:1024]
            send_to_admin_and_map(
                user_id,
                bot.send_video,
                ADMIN_ID,
                message.video.file_id,
                caption=full_caption,
                reply_markup=markup
            )

        elif message.content_type == 'voice':
            send_to_admin_and_map(
                user_id,
                bot.send_voice,
                ADMIN_ID,
                message.voice.file_id,
                caption=header,
                reply_markup=markup
            )

        elif message.content_type == 'audio':
            send_to_admin_and_map(
                user_id,
                bot.send_audio,
                ADMIN_ID,
                message.audio.file_id,
                caption=header,
                reply_markup=markup
            )

        elif message.content_type == 'sticker':
            # Send header as text first, then sticker
            header_msg = bot.send_message(ADMIN_ID, header, reply_markup=markup)
            msg_map[header_msg.message_id] = user_id
            send_to_admin_and_map(
                user_id,
                bot.send_sticker,
                ADMIN_ID,
                message.sticker.file_id
            )

        else:
            # Unsupported type — forward generic notice
            send_to_admin_and_map(
                user_id,
                bot.send_message,
                ADMIN_ID,
                f"{header}[Unsupported message type: {message.content_type}]",
                reply_markup=markup
            )

        # ── Ack to user ──
        if count == 1:
            bot.send_message(
                message.chat.id,
                "✅ <b>Received!</b> Our team will reply shortly.\n"
                "<i>You can send more details anytime.</i>"
            )
        else:
            bot.send_message(message.chat.id, "📨 <i>Message added to your ticket.</i>")

    except Exception as e:
        logger.error(f"User message error: {e}", exc_info=True)
        try:
            bot.send_message(message.chat.id, "⚠️ Something went wrong. Please try again.")
        except Exception:
            pass


# ─────────────────────────────────────────────
# ADMIN → USER: Reply
# ─────────────────────────────────────────────
@bot.message_handler(
    content_types=['text', 'photo', 'document', 'video', 'voice', 'audio'],
    func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message is not None
)
def handle_admin_reply(message):
    try:
        reply_to_id = message.reply_to_message.message_id

        # ── Primary: look up from msg_map ──
        target_user_id = msg_map.get(reply_to_id)

        if not target_user_id:
            bot.send_message(
                ADMIN_ID,
                "❌ <b>Can't find user for this message.</b>\n"
                "Make sure you're replying to a <i>forwarded support message</i>.\n\n"
                "<i>Tip: Only messages forwarded after the latest bot restart are mapped.</i>"
            )
            return

        # Snapshot username before deleting from pending
        username = pending_requests.get(target_user_id, {}).get("username", f"<code>{target_user_id}</code>")

        # ── Build reply ──
        reply_header = "🎧 <b>Support Team Reply:</b>\n\n"
        reply_footer  = "\n\n<i>— dafaxbet.com Support</i>"

        if message.content_type == 'text':
            bot.send_message(
                target_user_id,
                f"{reply_header}{message.text}{reply_footer}"
            )

        elif message.content_type == 'photo':
            cap = message.caption or ""
            full_cap = f"{reply_header}{cap}{reply_footer}"[:1024]
            bot.send_photo(target_user_id, message.photo[-1].file_id, caption=full_cap)

        elif message.content_type == 'document':
            cap = message.caption or ""
            full_cap = f"{reply_header}{cap}{reply_footer}"[:1024]
            bot.send_document(target_user_id, message.document.file_id, caption=full_cap)

        elif message.content_type == 'video':
            cap = message.caption or ""
            full_cap = f"{reply_header}{cap}{reply_footer}"[:1024]
            bot.send_video(target_user_id, message.video.file_id, caption=full_cap)

        elif message.content_type == 'voice':
            bot.send_voice(target_user_id, message.voice.file_id)

        elif message.content_type == 'audio':
            bot.send_audio(target_user_id, message.audio.file_id)

        # ── Clean up ticket ──
        if target_user_id in pending_requests:
            del pending_requests[target_user_id]

        # Reset msg_count for fresh thread next time
        if target_user_id in user_sessions:
            user_sessions[target_user_id]["msg_count"] = 0

        # Remove resolve button from original ticket
        try:
            bot.edit_message_reply_markup(
                chat_id=ADMIN_ID,
                message_id=reply_to_id,
                reply_markup=None
            )
        except Exception:
            pass

        bot.send_message(
            ADMIN_ID,
            f"✅ <b>Reply sent</b> to {username}.\nTicket auto-closed."
        )

    except Exception as e:
        logger.error(f"Admin reply error: {e}", exc_info=True)
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

            # Remove inline button
            try:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass

            # Mark resolved visually
            try:
                original_text = call.message.text or call.message.caption or ""
                resolved_text = original_text + "\n\n<i>✅ Resolved</i>"
                if call.message.content_type == 'text':
                    bot.edit_message_text(
                        chat_id=ADMIN_ID,
                        message_id=call.message.message_id,
                        text=resolved_text,
                        parse_mode="HTML"
                    )
            except Exception:
                pass

            # Notify user their ticket is closed
            try:
                bot.send_message(
                    user_id,
                    "✅ <b>Your support ticket has been marked as resolved.</b>\n"
                    "<i>If you need further help, feel free to message us again.</i>"
                )
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
        logger.error(f"Resolve error: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Bot starting — polling mode")
    while True:
        try:
            bot.polling(
                non_stop=True,
                interval=0,
                timeout=30,
                allowed_updates=["message", "callback_query"]
            )
        except Exception as e:
            logger.error(f"Polling crashed: {e}", exc_info=True)
            time.sleep(5)
