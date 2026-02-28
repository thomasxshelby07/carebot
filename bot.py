import os
import logging
import time
import re
from dotenv import load_dotenv
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton

# Load environment variables
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN and ADMIN_ID must be set in the .env file")

ADMIN_ID = int(ADMIN_ID)

# Initialize bot
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Temporary memory to store user states and pending tickets
user_states = {}
pending_requests = {} # {user_id: {"username": "@name", "category": "cat", "time": timestamp}}

# Constants for categories
CAT_ID = "🆔 ID Issue"
CAT_WITHDRAWAL = "💰 Withdrawal Issue"
CAT_OTHER = "❓ Other Issue"
CATEGORIES = [CAT_ID, CAT_WITHDRAWAL, CAT_OTHER]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        
        if user_id == ADMIN_ID:
            # Admin Keyboard
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(KeyboardButton('📋 View Pending Tickets'))
            bot.send_message(
                ADMIN_ID, 
                "👋 <b>Welcome Admin to dafaxbet.com Care Support!</b>\n\nUse the menu below to manage user requests.",
                reply_markup=markup
            )
            return

        # User Keyboard
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(KeyboardButton(CAT_ID), KeyboardButton(CAT_WITHDRAWAL))
        markup.add(KeyboardButton(CAT_OTHER))
        
        bot.send_message(
            message.chat.id,
            "👋 <b>Welcome to dafaxbet.com Care Support!</b>\n\nHow can we assist you today?\nPlease select an issue category from the menu below:",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")

@bot.message_handler(func=lambda message: message.text in CATEGORIES)
def handle_category_selection(message):
    try:
        user_id = message.from_user.id
        category = message.text
        
        # Store state
        user_states[user_id] = category
        
        bot.send_message(
            message.chat.id,
            f"📌 <b>Category Selected:</b> {category}\n\nPlease describe your problem in detail. You can send text or a screenshot so our team can help you faster.",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error handling category: {e}")

@bot.message_handler(func=lambda message: message.text == '📋 View Pending Tickets' and message.chat.id == ADMIN_ID)
def show_pending_tickets(message):
    try:
        if not pending_requests:
            bot.send_message(ADMIN_ID, "🎉 No pending requests right now!")
            return
            
        text = "📝 <b>Pending Requests:</b>\n\n"
        count = 1
        for uid, data in pending_requests.items():
            text += f"{count}. <b>{data['username']}</b> (<code>{uid}</code>)\n"
            text += f"   📁 Category: {data['category']}\n\n"
            count += 1
            
        text += "<i>Reply to their original message to answer, or click 'Mark as Resolved' on it.</i>"
        bot.send_message(ADMIN_ID, text)
    except Exception as e:
        logger.error(f"Error showing pending tickets: {e}")

@bot.message_handler(content_types=['text', 'photo'], func=lambda message: message.chat.id != ADMIN_ID or not message.reply_to_message)
def handle_user_message(message):
    try:
        user_id = message.from_user.id
        
        if user_id == ADMIN_ID and message.reply_to_message:
            return
            
        if user_id not in user_states:
            bot.send_message(message.chat.id, "Please use /start to select a category first.")
            return

        category = user_states[user_id]
        username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        
        # Add to pending requests memory queue
        pending_requests[user_id] = {
            "username": username,
            "category": category,
            "time": time.time()
        }
        
        # Format the header
        header = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📩 <b>New Support Request</b>\n\n"
            f"📌 <b>Category:</b> {category}\n"
            f"👤 <b>User:</b> {username}\n"
            f"🆔 <b>UserID:</b> <code>{user_id}</code>\n\n"
            "📝 <b>Message:</b>\n"
        )
        
        # Inline button to resolve
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Mark as Resolved", callback_data=f"resolve_{user_id}"))
        
        if message.content_type == 'text':
            full_message = f"{header}{message.text}\n━━━━━━━━━━━━━━━━━━━━"
            bot.send_message(ADMIN_ID, full_message, reply_markup=markup)
            
        elif message.content_type == 'photo':
            caption = message.caption if message.caption else ""
            full_caption = f"{header}{caption}\n━━━━━━━━━━━━━━━━━━━━"
            if len(full_caption) > 1024:
                full_caption = full_caption[:1020] + "..."
                
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=full_caption, reply_markup=markup)
            
        # Clear user state after sending the message
        del user_states[user_id]
        
        bot.send_message(message.chat.id, "✅ <b>Message Sent!</b>\n\nOur dafaxbet.com support team has received your request and will reply shortly. Please be patient.")

    except Exception as e:
        logger.error(f"Error handling user message: {e}")
        bot.send_message(message.chat.id, "⚠️ <b>Error:</b> We couldn't process your request right now. Please try again later.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('resolve_'))
def handle_resolve_ticket(call):
    try:
        if call.message.chat.id != ADMIN_ID:
            return
            
        user_id = int(call.data.split('_')[1])
        
        if user_id in pending_requests:
            del pending_requests[user_id]
            bot.answer_callback_query(call.id, "✅ Ticket marked as resolved!")
            try:
                bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(ADMIN_ID, f"✅ Ticket for UserID: <code>{user_id}</code> closed.")
        else:
            bot.answer_callback_query(call.id, "⚠️ Already resolved or not found.", show_alert=True)
            try:
                bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            except Exception:
                pass
            
    except Exception as e:
        logger.error(f"Error resolving ticket: {e}")

@bot.message_handler(content_types=['text', 'photo'], func=lambda message: message.chat.id == ADMIN_ID and message.reply_to_message is not None)
def handle_admin_reply(message):
    try:
        reply_to = message.reply_to_message
        
        text_to_parse = ""
        if reply_to.content_type == 'text':
            text_to_parse = reply_to.text
        elif reply_to.content_type == 'photo':
            text_to_parse = reply_to.caption if reply_to.caption else ""
            
        if "UserID:" not in text_to_parse:
            bot.send_message(ADMIN_ID, "❌ Could not find UserID in the message you replied to.")
            return
            
        # Extract UserID
        parts = text_to_parse.split('UserID:')
        if len(parts) > 1:
            target_user_id_str = parts[1].split('\n')[0].strip()
            # Clean if it contains html tags
            target_user_id_str = re.sub(r'<[^>]+>', '', target_user_id_str).strip()
            
            if not target_user_id_str.isdigit():
                bot.send_message(ADMIN_ID, f"❌ Invalid UserID format in original message (parsed: {target_user_id_str}).")
                return
                
            target_user_id = int(target_user_id_str)
            
            header = (
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🎧 <b>dafaxbet.com Support Reply:</b>\n\n"
            )
            footer = "\n━━━━━━━━━━━━━━━━━━━━"
            
            if message.content_type == 'text':
                reply_text = f"{header}{message.text}{footer}"
                bot.send_message(target_user_id, reply_text)
                
            elif message.content_type == 'photo':
                caption = message.caption if message.caption else ""
                reply_caption = f"{header}{caption}{footer}"
                if len(reply_caption) > 1024:
                    reply_caption = reply_caption[:1020] + "..."
                    
                bot.send_photo(target_user_id, message.photo[-1].file_id, caption=reply_caption)
                
            # Auto-resolve from pending requests
            if target_user_id in pending_requests:
                del pending_requests[target_user_id]
                try:
                    bot.edit_message_reply_markup(chat_id=ADMIN_ID, message_id=reply_to.message_id, reply_markup=None)
                except Exception:
                    pass
                
            bot.send_message(ADMIN_ID, f"✅ Reply sent successfully to <code>{target_user_id}</code>. Ticket marked as resolved.")
            
    except Exception as e:
        logger.error(f"Error handling admin reply: {e}")
        bot.send_message(ADMIN_ID, "❌ Failed to send reply. Please check logs.")

if __name__ == "__main__":
    logger.info("Starting bot...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
