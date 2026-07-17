import os
import asyncio
import logging
import aiohttp
from datetime import datetime
from io import BytesIO
from threading import Thread
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

# Telethon for OTP
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, RPCError

from database import db
from utils import (
    format_price, escape_markdown,
    get_main_reply_keyboard, get_admin_reply_keyboard,
    get_admin_inline_keyboard, get_cancel_inline_keyboard, get_payment_inline_keyboard,
    get_logout_inline_keyboard,
    generate_fampay_qr, verify_fampay_payment, check_force_channel,
    verify_payment_api
)

# ---------- Flask Web Server ----------
web = Flask(__name__)

@web.route("/")
def home():
    return "✅ Bot is running!"

def run_web():
    web.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        threaded=True
    )

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MERCHANT_UPI = os.getenv("MERCHANT_UPI")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Active OTP clients: phone -> {client, user_id, account_id, first_otp_sent}
active_otp_clients = {}

# ============================================================
# START COMMAND – Persistent Reply Keyboard
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.connect()
    existing = await db.get_user(user.id)
    if not existing:
        await db.create_user(user.id, user.username, user.full_name)

    if not await check_force_channel(context, user.id):
        force_channel = os.getenv("FORCE_CHANNEL")
        try:
            chat = await context.bot.get_chat(int(force_channel))
            link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(force_channel)[4:]}"
            keyboard = [[InlineKeyboardButton("📢 Join Channel", url=link)],
                        [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]]
            await update.message.reply_text(
                f"🔒 **Please Join Our Channel First!**\n\n{link}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        except Exception as e:
            logger.error(f"Force channel error: {e}")

    welcome = f"🌟 **Welcome {escape_markdown(user.full_name)}!**\n\nWelcome to **Premium Account Store**.\nUse the buttons below."
    admins = await db.get_admins()
    if user.id in admins:
        reply_markup = get_admin_reply_keyboard()
    else:
        reply_markup = get_main_reply_keyboard()
    await update.message.reply_text(
        welcome,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# CALLBACK HANDLER (for inline buttons)
# ============================================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    await db.connect()

    if data == "cancel_operation":
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled.", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        admins = await db.get_admins()
        if user_id in admins:
            reply_markup = get_admin_reply_keyboard()
        else:
            reply_markup = get_main_reply_keyboard()
        await query.message.reply_text("Main Menu", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "check_join":
        if await check_force_channel(context, user_id):
            await query.edit_message_text("✅ Thanks for joining!", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
            admins = await db.get_admins()
            if user_id in admins:
                reply_markup = get_admin_reply_keyboard()
            else:
                reply_markup = get_main_reply_keyboard()
            await query.message.reply_text("Main Menu", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.answer("❌ Please join first!", alert=True)
        return

    if data == "start_back":
        await query.edit_message_text("🌟 Main Menu", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        admins = await db.get_admins()
        if user_id in admins:
            reply_markup = get_admin_reply_keyboard()
        else:
            reply_markup = get_main_reply_keyboard()
        await query.message.reply_text("Main Menu", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    # ---------- LOGOUT & REMOVE ----------
    if data.startswith("logout_acc_"):
        await handle_logout(query, context)
        return

    # ---------- PAYMENT CALLBACKS ----------
    if data.startswith("verify_pay_"):
        await verify_payment(query, context)
        return

    # ---------- ADMIN INLINE CALLBACKS ----------
    if data == "admin_panel":
        admins = await db.get_admins()
        if user_id not in admins:
            await query.answer("⛔ Unauthorized", alert=True)
            return
        await show_admin_panel(query, context)
        return

    if data.startswith("admin_"):
        await handle_admin_callback(query, context)
        return

    # ---------- SERVICE SELECTION ----------
    if data.startswith("acc_service_"):
        service_id = data.split("_")[2]
        await show_account_service_detail(query, context, service_id)
        return

    if data.startswith("buy_acc_"):
        service_id = data.split("_")[2]
        await handle_account_purchase(query, context, service_id)
        return

    if data.startswith("confirm_acc_"):
        service_id = data.split("_")[2]
        await confirm_account_purchase(query, context, service_id)
        return

    if data.startswith("sess_service_"):
        service_id = data.split("_")[2]
        await show_session_service_detail(query, context, service_id)
        return

    if data.startswith("buy_sess_"):
        service_id = data.split("_")[2]
        await handle_session_purchase(query, context, service_id)
        return

    if data.startswith("confirm_sess_"):
        service_id = data.split("_")[2]
        await confirm_session_purchase(query, context, service_id)
        return

    # ---------- PAGINATION ----------
    if data.startswith("acc_page_"):
        page = int(data.split("_")[2])
        context.user_data["acc_page"] = page
        platform = context.user_data.get("current_platform", "telegram")
        await show_account_services(query, context, platform=platform)
        return

    if data.startswith("sess_page_"):
        page = int(data.split("_")[2])
        context.user_data["sess_page"] = page
        await show_session_services(query, context)
        return

    # ---------- BACK TO SERVICES ----------
    if data == "back_to_acc_services":
        platform = context.user_data.get("current_platform", "telegram")
        await show_account_services(query, context, platform=platform)
        return

    if data == "back_to_sess_services":
        await show_session_services(query, context)
        return

# ============================================================
# MESSAGE HANDLER – handles text commands from reply keyboard
# ============================================================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    await db.connect()

    # ---------- BACK BUTTON (always works) ----------
    if text == "🔙 Back":
        admins = await db.get_admins()
        if user_id in admins:
            reply_markup = get_admin_reply_keyboard()
        else:
            reply_markup = get_main_reply_keyboard()
        await update.message.reply_text("🌟 Main Menu", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    # ---------- ADMIN PANEL BUTTON ----------
    if text == "⚙️ Admin Panel":
        admins = await db.get_admins()
        if user_id not in admins:
            await update.message.reply_text("⛔ You are not an admin.", parse_mode=ParseMode.MARKDOWN)
            return
        await show_admin_panel_from_message(update, context)
        return

    if text == "/cancel":
        context.user_data.clear()
        admins = await db.get_admins()
        reply_markup = get_admin_reply_keyboard() if user_id in admins else get_main_reply_keyboard()
        await update.message.reply_text("❌ Cancelled.", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    # ---------- BROADCAST COMMAND (fixed) ----------
    if text.startswith("/broadcast"):
        admins = await db.get_admins()
        if user_id not in admins:
            await update.message.reply_text("⛔ Only admins can broadcast.", parse_mode=ParseMode.MARKDOWN)
            return
        msg = text.replace("/broadcast", "").strip()
        if not msg:
            await update.message.reply_text("📢 Usage: `/broadcast Your message here`", parse_mode=ParseMode.MARKDOWN)
            return
        # Broadcast to all users
        users = await db.db.users.find({}).to_list(length=None)
        success = 0
        progress = await update.message.reply_text(f"⏳ Broadcasting to {len(users)} users...", parse_mode=ParseMode.MARKDOWN)
        for i, user in enumerate(users):
            try:
                await context.bot.send_message(user["user_id"], msg)
                success += 1
                if (i+1) % 10 == 0:
                    await progress.edit_text(f"⏳ Progress: {success}/{len(users)}", parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.warning(f"Broadcast failed for {user['user_id']}: {e}")
        await progress.edit_text(f"✅ Broadcast complete: {success}/{len(users)}", parse_mode=ParseMode.MARKDOWN)
        return

    # ---------- MAIN MENU BUTTONS ----------
    if text == "🛒 Buy Telegram":
        await show_account_services_from_message(update, context, platform="telegram")
        return

    if text == "💬 Buy WhatsApp":
        await show_account_services_from_message(update, context, platform="whatsapp")
        return

    if text == "🔐 Buy Session":
        await show_session_services_from_message(update, context)
        return

    if text == "👤 My Profile":
        user = await db.get_user(user_id)
        balance = user.get("balance", 0) if user else 0
        purchases = user.get("total_purchases", 0) if user else 0
        profile_text = (f"👤 **My Profile**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🆔 User ID: `{user_id}`\n👤 Username: @{update.effective_user.username or 'N/A'}\n"
                        f"💰 Balance: ₹{format_price(balance)}\n📦 Purchases: {purchases}")
        keyboard = ReplyKeyboardMarkup(
            [["💰 Add Balance", "🔙 Back"]],
            resize_keyboard=True, one_time_keyboard=False
        )
        await update.message.reply_text(profile_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return

    if text == "💰 Wallet":
        context.user_data["payment_state"] = "custom_amount"
        await update.message.reply_text(
            "💳 **Enter the amount you want to add**\n"
            "Minimum: ₹10 | Maximum: ₹10,000\n\n"
            "Send the amount as a number.\n"
            "Example: `100`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if text == "📞 Support":
        support_user = await db.get_settings("support_username") or "admin"
        await update.message.reply_text(
            f"📞 **Support**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Need help? Contact our support team:\n\n"
            f"• Telegram: @{support_user}\n"
            f"• Response time: Usually within 24 hours\n"
            f"• For payment issues, send your Order ID\n━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=ReplyKeyboardMarkup(
                [["📱 Contact Support", "🔙 Back"]],
                resize_keyboard=True, one_time_keyboard=False
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if text == "📱 Contact Support":
        support_user = await db.get_settings("support_username") or "admin"
        await update.message.reply_text(
            f"📱 Contact our support directly: @{support_user}",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Back"]],
                resize_keyboard=True, one_time_keyboard=False
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if text == "📜 History":
        purchases = await db.get_purchase_history(user_id)
        if not purchases:
            await update.message.reply_text(
                "📭 **No purchase history.**\n\nYou haven't bought anything yet.",
                reply_markup=ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        msg = "📜 **Your Purchase History**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        for p in purchases[:10]:
            date_str = p["sold_at"].strftime("%d-%b %H:%M") if p["sold_at"] else "Unknown"
            status_emoji = "✅" if p["status"] == "sold" else "🗑️"
            msg += f"{status_emoji} **{p['service_name']}**\n"
            msg += f"   • {p['item']} – ₹{format_price(p['price'])}\n"
            msg += f"   • {date_str}\n\n"
        if len(purchases) > 10:
            msg += "_(Showing latest 10)_\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━"
        await update.message.reply_text(
            msg,
            reply_markup=ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ---------- HANDLE CUSTOM AMOUNT ----------
    if context.user_data.get("payment_state") == "custom_amount":
        try:
            amount = float(text)
            if amount < 10 or amount > 10000:
                await update.message.reply_text("❌ Amount must be between ₹10 and ₹10,000.", parse_mode=ParseMode.MARKDOWN)
                return
            context.user_data.pop("payment_state", None)
            await generate_payment_qr(update, context, amount)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please send a number.", parse_mode=ParseMode.MARKDOWN)
        return

    # ---------- ADMIN INPUT HANDLING ----------
    state = context.user_data.get("admin_state")
    if state:
        await handle_admin_input(update, context, text)
        return

    # ---------- DEFAULT ----------
    admins = await db.get_admins()
    reply_markup = get_admin_reply_keyboard() if user_id in admins else get_main_reply_keyboard()
    await update.message.reply_text(
        "Please use the buttons.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# ACCOUNT SERVICES LISTING – 3 BUTTONS PER SERVICE
# ============================================================
async def show_account_services_from_message(update, context, platform="telegram"):
    page = context.user_data.get("acc_page", 0)
    per_page = 5
    services = await db.get_all_account_services(platform=platform)
    if not services:
        await update.message.reply_text(
            f"📭 No {platform} services available.",
            reply_markup=ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(services)
    start = page * per_page
    end = start + per_page
    current = services[start:end]

    emoji = "📱" if platform == "telegram" else "💬"
    text = f"{emoji} **Available {platform.capitalize()} Services**\n━━━━━━━━━━━━━━━━━━━━━━━\n"

    keyboard = []
    for s in current:
        sid = str(s["_id"])
        avail = await db.get_account_service_available_count(sid)
        country = s['name'][:15]
        price = f"₹{format_price(s['price'])}"
        stock = f"[{avail}]"
        row = [
            InlineKeyboardButton(country, callback_data=f"acc_service_{sid}", style="primary"),
            InlineKeyboardButton(price, callback_data=f"acc_service_{sid}", style="primary"),
            InlineKeyboardButton(stock, callback_data=f"acc_service_{sid}", style="primary")
        ]
        keyboard.append(row)

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc_page_{page+1}"))
    if nav:
        keyboard.append(nav)
        text += f"\nPage {page+1}/{ (total+per_page-1)//per_page }"

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")])
    context.user_data["current_platform"] = platform
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_account_services(query, context, platform="telegram"):
    page = context.user_data.get("acc_page", 0)
    per_page = 5
    services = await db.get_all_account_services(platform=platform)
    if not services:
        await query.edit_message_text(
            f"📭 No {platform} services available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(services)
    start = page * per_page
    end = start + per_page
    current = services[start:end]

    emoji = "📱" if platform == "telegram" else "💬"
    text = f"{emoji} **Available {platform.capitalize()} Services**\n━━━━━━━━━━━━━━━━━━━━━━━\n"

    keyboard = []
    for s in current:
        sid = str(s["_id"])
        avail = await db.get_account_service_available_count(sid)
        country = s['name'][:15]
        price = f"₹{format_price(s['price'])}"
        stock = f"[{avail}]"
        row = [
            InlineKeyboardButton(country, callback_data=f"acc_service_{sid}", style="primary"),
            InlineKeyboardButton(price, callback_data=f"acc_service_{sid}", style="primary"),
            InlineKeyboardButton(stock, callback_data=f"acc_service_{sid}", style="primary")
        ]
        keyboard.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc_page_{page+1}"))
    if nav:
        keyboard.append(nav)
        text += f"\nPage {page+1}/{ (total+per_page-1)//per_page }"

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")])
    context.user_data["current_platform"] = platform
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# SESSION SERVICES LISTING – NOW ALSO 3 BUTTONS PER SERVICE
# ============================================================
async def show_session_services_from_message(update, context):
    page = context.user_data.get("sess_page", 0)
    per_page = 5
    services = await db.get_all_session_services()
    if not services:
        await update.message.reply_text(
            "📭 No session services available.",
            reply_markup=ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(services)
    start = page * per_page
    end = start + per_page
    current = services[start:end]

    text = "🔐 **Available Session Services**\n━━━━━━━━━━━━━━━━━━━━━━━\n"

    keyboard = []
    for s in current:
        sid = str(s["_id"])
        avail = await db.get_session_service_available_count(sid)
        name = s['name'][:15]
        price = f"₹{format_price(s['price'])}"
        stock = f"[{avail}]"
        row = [
            InlineKeyboardButton(name, callback_data=f"sess_service_{sid}", style="primary"),
            InlineKeyboardButton(price, callback_data=f"sess_service_{sid}", style="primary"),
            InlineKeyboardButton(stock, callback_data=f"sess_service_{sid}", style="primary")
        ]
        keyboard.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sess_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"sess_page_{page+1}"))
    if nav:
        keyboard.append(nav)
        text += f"\nPage {page+1}/{ (total+per_page-1)//per_page }"

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")])
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_session_services(query, context):
    page = context.user_data.get("sess_page", 0)
    per_page = 5
    services = await db.get_all_session_services()
    if not services:
        await query.edit_message_text(
            "📭 No session services available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(services)
    start = page * per_page
    end = start + per_page
    current = services[start:end]

    text = "🔐 **Available Session Services**\n━━━━━━━━━━━━━━━━━━━━━━━\n"

    keyboard = []
    for s in current:
        sid = str(s["_id"])
        avail = await db.get_session_service_available_count(sid)
        name = s['name'][:15]
        price = f"₹{format_price(s['price'])}"
        stock = f"[{avail}]"
        row = [
            InlineKeyboardButton(name, callback_data=f"sess_service_{sid}", style="primary"),
            InlineKeyboardButton(price, callback_data=f"sess_service_{sid}", style="primary"),
            InlineKeyboardButton(stock, callback_data=f"sess_service_{sid}", style="primary")
        ]
        keyboard.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sess_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"sess_page_{page+1}"))
    if nav:
        keyboard.append(nav)
        text += f"\nPage {page+1}/{ (total+per_page-1)//per_page }"

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="start_back")])
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# SERVICE DETAIL (Accounts & Sessions) – unchanged
# ============================================================
async def show_account_service_detail(query, context, service_id):
    service = await db.get_account_service(service_id)
    if not service or not service.get("is_active"):
        await query.answer("⚠️ Service unavailable", alert=True)
        return
    avail = await db.get_account_service_available_count(service_id)
    if avail == 0:
        await query.edit_message_text(
            f"📭 **{service['name']}** - Out of stock!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Services", callback_data="back_to_acc_services")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    text = (f"{'📱' if service['platform']=='telegram' else '💬'} **{service['name']}**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price: ₹{format_price(service['price'])}\n"
            f"📦 Stock: {avail}\n"
            f"📝 {service.get('description', '')}\n━━━━━━━━━━━━━━━━━━━━━━━")
    keyboard = [
        [InlineKeyboardButton(f"✅ Buy Now - ₹{format_price(service['price'])}", callback_data=f"buy_acc_{service_id}", style="success")],
        [InlineKeyboardButton("🔙 Back to Services", callback_data="back_to_acc_services")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def show_session_service_detail(query, context, service_id):
    service = await db.get_session_service(service_id)
    if not service or not service.get("is_active"):
        await query.answer("⚠️ Service unavailable", alert=True)
        return
    avail = await db.get_session_service_available_count(service_id)
    if avail == 0:
        await query.edit_message_text(
            f"📭 **{service['name']}** - Out of stock!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Services", callback_data="back_to_sess_services")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    text = (f"🔐 **{service['name']}**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price: ₹{format_price(service['price'])}\n"
            f"📦 Stock: {avail}\n"
            f"📝 {service.get('description', '')}\n━━━━━━━━━━━━━━━━━━━━━━━")
    keyboard = [
        [InlineKeyboardButton(f"✅ Buy Now - ₹{format_price(service['price'])}", callback_data=f"buy_sess_{service_id}", style="success")],
        [InlineKeyboardButton("🔙 Back to Services", callback_data="back_to_sess_services")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

# ============================================================
# PURCHASE HANDLERS (Accounts & Sessions) – unchanged
# ============================================================
async def handle_account_purchase(query, context, service_id):
    user_id = query.from_user.id
    service = await db.get_account_service(service_id)
    if not service:
        await query.answer("Service not found", alert=True)
        return
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    if balance < price:
        keyboard = [
            [InlineKeyboardButton("💰 Add Balance", callback_data="add_balance", style="success")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"acc_service_{service_id}")]
        ]
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\nNeed ₹{format_price(price)}, you have ₹{format_price(balance)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_acc_{service_id}", style="success")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation", style="danger")]
    ]
    await query.edit_message_text(
        f"🧾 **Confirm Purchase**\nService: {service['name']}\nPrice: ₹{format_price(price)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_account_purchase(query, context, service_id):
    user_id = query.from_user.id
    service = await db.get_account_service(service_id)
    if not service:
        await query.answer("Service not found", alert=True)
        return
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    if balance < price:
        await query.answer("Insufficient balance", alert=True)
        return
    account = await db.purchase_account_from_service(service_id, user_id, price)
    if not account:
        await query.edit_message_text(
            "❌ No accounts available. Try another service.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Services", callback_data="buy_account")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    phone = account["phone"]
    session_string = account.get("session_string")
    two_fa_password = account.get("two_fa_password")

    text = (f"✅ **Purchase Successful!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'📱' if service['platform']=='telegram' else '💬'} Service: {service['name']}\n"
            f"📱 Account: `{phone}`\n"
            f"💰 Price: ₹{format_price(price)}\n"
            f"🔑 2FA Password: `{two_fa_password or 'Not set'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📩 Waiting for OTP...\n"
            f"Once OTP arrives, you will get a logout button.")
    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="buy_account", style="primary")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    if session_string:
        asyncio.create_task(start_otp_forwarding(phone, user_id, session_string, account["_id"], two_fa_password))

async def handle_session_purchase(query, context, service_id):
    user_id = query.from_user.id
    service = await db.get_session_service(service_id)
    if not service:
        await query.answer("Service not found", alert=True)
        return
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    if balance < price:
        keyboard = [
            [InlineKeyboardButton("💰 Add Balance", callback_data="add_balance", style="success")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"sess_service_{service_id}")]
        ]
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\nNeed ₹{format_price(price)}, you have ₹{format_price(balance)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_sess_{service_id}", style="success")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation", style="danger")]
    ]
    await query.edit_message_text(
        f"🧾 **Confirm Purchase**\nService: {service['name']}\nPrice: ₹{format_price(price)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_session_purchase(query, context, service_id):
    user_id = query.from_user.id
    service = await db.get_session_service(service_id)
    if not service:
        await query.answer("Service not found", alert=True)
        return
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    if balance < price:
        await query.answer("Insufficient balance", alert=True)
        return
    item = await db.purchase_session_from_service(service_id, user_id, price)
    if not item:
        await query.edit_message_text(
            "❌ No sessions available. Try another service.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Services", callback_data="buy_session")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    session_data = item.get("session_string", "")
    if session_data:
        session_file = BytesIO()
        session_file.write(session_data.encode())
        session_file.name = f"session_{item['_id']}.session"
        session_file.seek(0)
        await query.message.reply_document(
            document=session_file,
            caption=f"🔐 Session file for {service['name']}"
        )

    text = (f"✅ **Purchase Successful!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔐 Service: {service['name']}\n"
            f"💰 Price: ₹{format_price(price)}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Session file sent above.")
    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="buy_session", style="primary")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

# ============================================================
# OTP FORWARDING – Logout after first OTP
# ============================================================
async def start_otp_forwarding(phone, user_id, session_string, account_id, two_fa_password):
    if phone in active_otp_clients:
        return

    client = TelegramClient(None, API_ID, API_HASH)
    try:
        await client.start(session_string=session_string)
    except Exception as e:
        logger.error(f"Failed to start client for {phone}: {e}")
        # Send error to user
        try:
            await context.bot.send_message(
                user_id,
                f"❌ Failed to connect to account `{phone}`.\nPlease contact support.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        return

    active_otp_clients[phone] = {
        "client": client,
        "user_id": user_id,
        "account_id": account_id,
        "first_otp_sent": False
    }

    @client.on(events.NewMessage(from_users=777000))
    async def otp_handler(event):
        clean_otp = event.raw_text
        otp_ui = (
            f"📩 **NEW OTP RECEIVED**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Account: `{phone}`\n\n"
            f"{clean_otp}\n━━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            # Send OTP message
            await client.send_message(user_id, otp_ui, parse_mode='markdown')
            logger.info(f"Forwarded OTP for {phone}")

            # Send logout button only once
            if not active_otp_clients[phone]["first_otp_sent"]:
                active_otp_clients[phone]["first_otp_sent"] = True
                await client.send_message(
                    user_id,
                    "🔐 **You can now logout and remove this account from stock.**\n"
                    "Click the button below after you have saved the OTP.",
                    reply_markup=get_logout_inline_keyboard(account_id),
                    parse_mode='markdown'
                )
        except Exception as e:
            logger.error(f"Failed to send OTP to {user_id}: {e}")

    try:
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"OTP client for {phone} disconnected: {e}")
    finally:
        await client.disconnect()
        active_otp_clients.pop(phone, None)

# ============================================================
# LOGOUT & REMOVE
# ============================================================
async def handle_logout(query, context):
    account_id = query.data.split("_")[2]
    user_id = query.from_user.id

    account = await db.db.accounts.find_one({"_id": account_id})
    if not account:
        await query.answer("Account not found.", alert=True)
        return

    phone = account.get("phone")
    if phone in active_otp_clients:
        client_data = active_otp_clients.pop(phone, None)
        if client_data:
            try:
                await client_data["client"].disconnect()
            except:
                pass

    session_file = os.path.join(SESSIONS_DIR, phone.replace("+", ""))
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except:
            pass

    await db.db.accounts.update_one(
        {"_id": account_id},
        {"$set": {"status": "deleted", "updated_at": datetime.utcnow()}}
    )

    await query.answer("✅ Logged out and removed from stock.", show_alert=True)
    await query.edit_message_text(
        "✅ **Logged out and removed from stock.**\n\n"
        "The account session has been revoked.\n"
        "You can now safely use the account.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="start_back", style="primary")]]),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# PAYMENT FUNCTIONS
# ============================================================
async def generate_payment_qr(source, context, amount):
    if hasattr(source, 'effective_user'):  # Update
        user_id = source.effective_user.id
        message = source.message
        edit_func = None
        reply_func = message.reply_text
        reply_photo_func = message.reply_photo
    else:  # CallbackQuery
        user_id = source.from_user.id
        message = source.message
        edit_func = source.edit_message_text
        reply_func = message.reply_text
        reply_photo_func = message.reply_photo

    upi_id = MERCHANT_UPI
    result = await generate_fampay_qr(upi_id, amount)

    if not result.get("success"):
        order_id = f"LOCAL_{user_id}_{int(datetime.utcnow().timestamp())}"
        await db.create_payment(user_id, amount, order_id, upi_id)
        context.user_data["pending_payment"] = order_id
        text = (f"💳 **Payment Initiated**\nPay to UPI: `{upi_id}`\nAmount: ₹{format_price(amount)}\nOrder ID: `{order_id}`\nAfter payment click Verify.")
        if edit_func:
            await edit_func(text, reply_markup=get_payment_inline_keyboard(order_id), parse_mode=ParseMode.MARKDOWN)
        else:
            await reply_func(text, reply_markup=get_payment_inline_keyboard(order_id), parse_mode=ParseMode.MARKDOWN)
        return

    order_id = result["order_id"]
    qr_url = result.get("qr_url")
    await db.create_payment(user_id, amount, order_id, upi_id)
    context.user_data["pending_payment"] = order_id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(qr_url) as response:
                if response.status == 200:
                    qr_data = await response.read()
                    qr_bio = BytesIO(qr_data)
                    qr_bio.seek(0)
                    await reply_photo_func(
                        photo=qr_bio,
                        caption=f"💳 **Scan to Pay ₹{format_price(amount)}**\n\nUPI: `{upi_id}`\nOrder ID: `{order_id}`"
                    )
                else:
                    await reply_func(f"💳 **Payment Details**\n\nUPI: `{upi_id}`\nAmount: ₹{format_price(amount)}\nOrder ID: `{order_id}`\n\nPay to the UPI ID above and click Verify.")
    except Exception as e:
        logger.error(f"QR send failed: {e}")
        await reply_func(f"💳 **Payment Details**\n\nUPI: `{upi_id}`\nAmount: ₹{format_price(amount)}\nOrder ID: `{order_id}`\n\nPay to the UPI ID above and click Verify.")

    final_text = (f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                  f"💵 Amount: ₹{format_price(amount)}\n"
                  f"🆔 Order ID: `{order_id}`\n"
                  f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                  f"After payment, click 'Verify Payment'.")
    if edit_func:
        await edit_func(final_text, reply_markup=get_payment_inline_keyboard(order_id), parse_mode=ParseMode.MARKDOWN)
    else:
        await reply_func(final_text, reply_markup=get_payment_inline_keyboard(order_id), parse_mode=ParseMode.MARKDOWN)

async def verify_payment(query, context):
    user_id = query.from_user.id
    order_id = query.data.split("_")[2]
    if context.user_data.get("pending_payment") != order_id:
        await query.answer("Not your payment", alert=True)
        return

    payment = await db.get_payment(order_id)
    if not payment:
        await query.answer("Payment record not found", alert=True)
        return
    if payment.get("status") == "verified":
        await query.answer("✅ Already verified", alert=True)
        try:
            await query.edit_message_text(
                "✅ **This payment has already been verified.**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="start_back", style="primary")]]),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    result = await verify_payment_api(order_id)
    if not result.get("verified"):
        await query.answer("❌ Payment not verified. Try again later.", show_alert=True)
        try:
            await query.edit_message_text(
                f"❌ **Verification Failed**\nOrder ID: `{order_id}`\nReason: {result.get('message', 'Unknown error')}",
                reply_markup=get_payment_inline_keyboard(order_id),
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Edit error: {e}")
        return

    try:
        await db.verify_payment(order_id)
    except Exception as e:
        logger.error(f"Failed to mark payment verified: {e}")
        await query.answer("❌ Database error. Please contact support.", show_alert=True)
        return

    amount = result.get("amount", payment.get("amount", 0))
    try:
        await db.update_user_balance(user_id, amount)
    except Exception as e:
        logger.error(f"Failed to update balance: {e}")
        await query.answer("⚠️ Balance update failed. Please contact support.", show_alert=True)
        return

    balance = await db.get_user_balance(user_id)
    await query.answer(f"✅ Payment verified! ₹{format_price(amount)} added.", show_alert=True)

    try:
        await query.edit_message_text(
            f"✅ **Payment Verified!**\n💰 ₹{format_price(amount)} added.\n💳 New Balance: ₹{format_price(balance)}\n🆔 Order ID: `{order_id}`\n🔑 Transaction ID: `{result.get('transaction_id', 'N/A')}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="start_back", style="primary")]]),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Failed to edit message after verification: {e}")

    context.user_data.pop("pending_payment", None)

# ============================================================
# ADMIN PANEL (inline)
# ============================================================
async def show_admin_panel(query, context):
    user_id = query.from_user.id
    admins = await db.get_admins()
    if user_id not in admins:
        await query.answer("⛔ Unauthorized", alert=True)
        return
    user_count = await db.db.users.count_documents({})
    acc_services = await db.db.account_services.count_documents({"is_active": True, "type": "account"})
    sess_services = await db.db.session_services.count_documents({"is_active": True, "type": "session"})
    total_acc = await db.db.accounts.count_documents({})
    avail_acc = await db.db.accounts.count_documents({"status": "available"})
    total_sess = await db.db.session_items.count_documents({})
    avail_sess = await db.db.session_items.count_documents({"status": "available"})
    text = (f"🔰 **Admin Dashboard**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Users: {user_count}\n"
            f"📋 Account Services: {acc_services}\n"
            f"📋 Session Services: {sess_services}\n"
            f"📦 Total Accounts: {total_acc} (Available: {avail_acc})\n"
            f"📦 Total Sessions: {total_sess} (Available: {avail_sess})")
    await query.edit_message_text(text, reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)

async def show_admin_panel_from_message(update, context):
    user_id = update.effective_user.id
    admins = await db.get_admins()
    if user_id not in admins:
        await update.message.reply_text("⛔ Unauthorized", parse_mode=ParseMode.MARKDOWN)
        return
    user_count = await db.db.users.count_documents({})
    acc_services = await db.db.account_services.count_documents({"is_active": True, "type": "account"})
    sess_services = await db.db.session_services.count_documents({"is_active": True, "type": "session"})
    total_acc = await db.db.accounts.count_documents({})
    avail_acc = await db.db.accounts.count_documents({"status": "available"})
    total_sess = await db.db.session_items.count_documents({})
    avail_sess = await db.db.session_items.count_documents({"status": "available"})
    text = (f"🔰 **Admin Dashboard**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Users: {user_count}\n"
            f"📋 Account Services: {acc_services}\n"
            f"📋 Session Services: {sess_services}\n"
            f"📦 Total Accounts: {total_acc} (Available: {avail_acc})\n"
            f"📦 Total Sessions: {total_sess} (Available: {avail_sess})")
    await update.message.reply_text(text, reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)

# ============================================================
# ADMIN CALLBACK HANDLER (full)
# ============================================================
async def handle_admin_callback(query, context):
    data = query.data
    user_id = query.from_user.id
    admins = await db.get_admins()
    if user_id not in admins:
        await query.answer("⛔ Unauthorized", alert=True)
        return

    # Account Services
    if data == "admin_account_services":
        await admin_show_account_services(query, context)
        return
    if data == "admin_new_account_service":
        context.user_data["admin_state"] = "new_acc_service_platform"
        await query.edit_message_text(
            "📋 **Create Account Service**\nChoose platform:\n\n"
            "Send `telegram` for Telegram accounts\n"
            "Send `whatsapp` for WhatsApp OTP accounts",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_edit_acc_service_"):
        service_id = data.split("_")[4]
        await admin_edit_account_service(query, context, service_id)
        return
    if data.startswith("admin_add_acc_phone_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "add_account_phone"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "📱 **Add Account**\nEnter phone with country code (e.g., +919876543210):",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_del_acc_service_"):
        service_id = data.split("_")[4]
        await admin_delete_account_service(query, context, service_id)
        return
    if data.startswith("admin_set_acc_price_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "set_acc_price"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "💰 Enter new price:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_set_acc_desc_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "set_acc_desc"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "📝 Enter new description:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Session Services
    if data == "admin_session_services":
        await admin_show_session_services(query, context)
        return
    if data == "admin_new_session_service":
        context.user_data["admin_state"] = "new_sess_service_name"
        await query.edit_message_text(
            "📋 **Create Session Service**\nEnter name:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_edit_sess_service_"):
        service_id = data.split("_")[4]
        await admin_edit_session_service(query, context, service_id)
        return
    if data.startswith("admin_add_sess_string_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "add_session_string"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "🔐 **Add Session**\nSend the session string:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_del_sess_service_"):
        service_id = data.split("_")[4]
        await admin_delete_session_service(query, context, service_id)
        return
    if data.startswith("admin_set_sess_price_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "set_sess_price"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "💰 Enter new price:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("admin_set_sess_desc_"):
        service_id = data.split("_")[4]
        context.user_data["admin_state"] = "set_sess_desc"
        context.user_data["service_id"] = service_id
        await query.edit_message_text(
            "📝 Enter new description:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ---------- SETTINGS BUTTONS ----------
    if data == "admin_settings":
        await admin_show_settings(query, context)
        return

    if data == "admin_set_default_price":
        context.user_data["admin_state"] = "set_default_price"
        await query.edit_message_text(
            "💰 Enter new default price:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "admin_set_support":
        context.user_data["admin_state"] = "set_support"
        await query.edit_message_text(
            "📞 Enter support username (without @):",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "admin_set_force":
        context.user_data["admin_state"] = "set_force"
        await query.edit_message_text(
            "📢 Enter channel ID or username (e.g., -1001234567890) or 'none' to disable:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ---------- Other Admin ----------
    if data == "admin_add_funds":
        context.user_data["admin_state"] = "add_funds_user"
        await query.edit_message_text(
            "💰 **Add Funds**\nEnter user ID:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "admin_stats":
        await show_admin_panel(query, context)
        return
    if data == "admin_announce":
        await query.edit_message_text(
            "📢 **Broadcast**\nUse the command `/broadcast Your message` to send to all users.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "admin_users":
        await admin_show_users(query, context)
        return
    if data == "admin_admins":
        await admin_show_admins(query, context)
        return
    if data == "admin_payments":
        await admin_show_payments(query, context)
        return
    if data == "admin_add_admin":
        context.user_data["admin_state"] = "add_admin"
        await query.edit_message_text(
            "🔑 Enter user ID to add as admin:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "admin_remove_admin":
        context.user_data["admin_state"] = "remove_admin"
        await query.edit_message_text(
            "🔑 Enter user ID to remove from admin:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

# -------- Admin service management functions (unchanged) --------
async def admin_show_account_services(query, context):
    services = await db.get_all_account_services()
    if not services:
        await query.edit_message_text(
            "No account services.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ New", callback_data="admin_new_account_service", style="success")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    keyboard = []
    for s in services:
        sid = str(s["_id"])
        avail = await db.get_account_service_available_count(sid)
        keyboard.append([InlineKeyboardButton(
            f"📱 {s['name']} - ₹{format_price(s['price'])} [{avail}]",
            callback_data=f"admin_edit_acc_service_{sid}"
        )])
    keyboard.append([InlineKeyboardButton("➕ New Account Service", callback_data="admin_new_account_service", style="success")])
    keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
    await query.edit_message_text("📋 **Account Services**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_edit_account_service(query, context, service_id):
    service = await db.get_account_service(service_id)
    if not service:
        await query.answer("Not found", alert=True)
        return
    avail = await db.get_account_service_available_count(service_id)
    total = service.get("total_items", 0)
    text = (f"📱 **{service['name']}**\n"
            f"💰 Price: ₹{format_price(service['price'])}\n"
            f"📦 Stock: {avail} / {total}\n"
            f"📝 {service.get('description', '')}")
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data=f"admin_add_acc_phone_{service_id}", style="success")],
        [InlineKeyboardButton("💰 Set Price", callback_data=f"admin_set_acc_price_{service_id}")],
        [InlineKeyboardButton("📝 Set Description", callback_data=f"admin_set_acc_desc_{service_id}")],
        [InlineKeyboardButton("❌ Delete Service", callback_data=f"admin_del_acc_service_{service_id}", style="danger")],
        [InlineKeyboardButton("🔙 Account Services", callback_data="admin_account_services")],
        [InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_delete_account_service(query, context, service_id):
    service = await db.get_account_service(service_id)
    if not service:
        await query.answer("Not found", alert=True)
        return
    if service.get("total_items", 0) > 0:
        await query.edit_message_text(
            "❌ Cannot delete: service has accounts.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"admin_edit_acc_service_{service_id}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    await db.delete_account_service(service_id)
    await query.edit_message_text("✅ Service deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Services", callback_data="admin_account_services")]]), parse_mode=ParseMode.MARKDOWN)

async def admin_show_session_services(query, context):
    services = await db.get_all_session_services()
    if not services:
        await query.edit_message_text(
            "No session services.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ New", callback_data="admin_new_session_service", style="success")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    keyboard = []
    for s in services:
        sid = str(s["_id"])
        avail = await db.get_session_service_available_count(sid)
        keyboard.append([InlineKeyboardButton(
            f"🔐 {s['name']} - ₹{format_price(s['price'])} [{avail}]",
            callback_data=f"admin_edit_sess_service_{sid}"
        )])
    keyboard.append([InlineKeyboardButton("➕ New Session Service", callback_data="admin_new_session_service", style="success")])
    keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
    await query.edit_message_text("📋 **Session Services**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_edit_session_service(query, context, service_id):
    service = await db.get_session_service(service_id)
    if not service:
        await query.answer("Not found", alert=True)
        return
    avail = await db.get_session_service_available_count(service_id)
    total = service.get("total_items", 0)
    text = (f"🔐 **{service['name']}**\n"
            f"💰 Price: ₹{format_price(service['price'])}\n"
            f"📦 Stock: {avail} / {total}\n"
            f"📝 {service.get('description', '')}")
    keyboard = [
        [InlineKeyboardButton("➕ Add Session", callback_data=f"admin_add_sess_string_{service_id}", style="success")],
        [InlineKeyboardButton("💰 Set Price", callback_data=f"admin_set_sess_price_{service_id}")],
        [InlineKeyboardButton("📝 Set Description", callback_data=f"admin_set_sess_desc_{service_id}")],
        [InlineKeyboardButton("❌ Delete Service", callback_data=f"admin_del_sess_service_{service_id}", style="danger")],
        [InlineKeyboardButton("🔙 Session Services", callback_data="admin_session_services")],
        [InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_delete_session_service(query, context, service_id):
    service = await db.get_session_service(service_id)
    if not service:
        await query.answer("Not found", alert=True)
        return
    if service.get("total_items", 0) > 0:
        await query.edit_message_text(
            "❌ Cannot delete: service has sessions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"admin_edit_sess_service_{service_id}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    await db.delete_session_service(service_id)
    await query.edit_message_text("✅ Service deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Services", callback_data="admin_session_services")]]), parse_mode=ParseMode.MARKDOWN)

# -------- Admin OTP flows (unchanged) --------
async def admin_add_account_phone(update, context, phone):
    service_id = context.user_data.get("service_id")
    if not service_id:
        await update.message.reply_text("❌ Session expired.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    existing = await db.db.accounts.find_one({"phone": phone})
    if existing:
        await update.message.reply_text(f"⚠️ Account {phone} already exists.", parse_mode=ParseMode.MARKDOWN)
        return

    session_file = os.path.join(SESSIONS_DIR, phone.replace("+", ""))
    client = TelegramClient(session_file, API_ID, API_HASH)

    try:
        await client.connect()
        if await client.is_user_authorized():
            session_string = client.session.save()
            await update.message.reply_text(
                "📱 Account already logged in. Please send the 2FA password (if any) or type `none` to skip:",
                reply_markup=get_cancel_inline_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data["otp_data"] = {
                "phone": phone,
                "client": client,
                "service_id": service_id,
                "session_string": session_string,
                "step": "2fa_password"
            }
            context.user_data["admin_state"] = "add_account_2fa_password"
            return

        sent = await client.send_code_request(phone)
        context.user_data["otp_data"] = {
            "phone": phone,
            "client": client,
            "phone_code_hash": sent.phone_code_hash,
            "service_id": service_id,
            "step": "otp"
        }
        context.user_data["admin_state"] = "add_account_otp"
        await update.message.reply_text(
            f"📩 OTP sent to {phone}.\nEnter the code:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        await client.disconnect()

async def admin_add_account_otp(update, context, otp):
    data = context.user_data.get("otp_data")
    if not data:
        await update.message.reply_text("❌ Session expired.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    client = data["client"]
    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    service_id = data["service_id"]

    try:
        await client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
        session_string = client.session.save()
        await update.message.reply_text(
            "✅ Logged in successfully. Please send the 2FA password (if any) or type `none` to skip:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["otp_data"] = {
            "phone": phone,
            "client": client,
            "service_id": service_id,
            "session_string": session_string,
            "step": "2fa_password"
        }
        context.user_data["admin_state"] = "add_account_2fa_password"
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 2FA enabled. Enter your cloud password:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["otp_data"]["step"] = "2fa_login"
        context.user_data["admin_state"] = "add_account_2fa_login"
    except Exception as e:
        await update.message.reply_text(f"❌ OTP error: {str(e)}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("otp_data", None)
        context.user_data.pop("service_id", None)
        await client.disconnect()

async def admin_add_account_2fa_login(update, context, password):
    data = context.user_data.get("otp_data")
    if not data:
        await update.message.reply_text("❌ Session expired.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return
    client = data["client"]
    phone = data["phone"]
    service_id = data["service_id"]

    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        await update.message.reply_text(
            "✅ Logged in with 2FA. Please send the 2FA password (if any) or type `none` to skip:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["otp_data"] = {
            "phone": phone,
            "client": client,
            "service_id": service_id,
            "session_string": session_string,
            "step": "2fa_password"
        }
        context.user_data["admin_state"] = "add_account_2fa_password"
    except Exception as e:
        await update.message.reply_text(f"❌ 2FA error: {str(e)}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("otp_data", None)
        context.user_data.pop("service_id", None)
        await client.disconnect()

async def admin_add_account_2fa_password(update, context, text):
    data = context.user_data.get("otp_data")
    if not data:
        await update.message.reply_text("❌ Session expired.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return
    client = data["client"]
    phone = data["phone"]
    service_id = data["service_id"]
    session_string = data["session_string"]
    two_fa_password = text if text.lower() != "none" else ""

    account = await db.add_account_to_service(service_id, phone)
    await db.db.accounts.update_one(
        {"_id": account["_id"]},
        {"$set": {"session_string": session_string, "two_fa_password": two_fa_password}}
    )
    service = await db.get_account_service(service_id)
    await update.message.reply_text(
        f"✅ Account {phone} added to {service['name']} with session and 2FA.",
        reply_markup=get_admin_inline_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data.pop("admin_state", None)
    context.user_data.pop("otp_data", None)
    context.user_data.pop("service_id", None)
    await client.disconnect()

# -------- Admin settings, users, admins, payments (unchanged) --------
async def admin_show_settings(query, context):
    default_price = await db.get_settings("default_price") or 100
    support_user = await db.get_settings("support_username") or "admin"
    force_channel = await db.get_settings("force_channel") or "Not set"
    text = (f"⚙️ **Settings**\n"
            f"💰 Default Price: ₹{format_price(default_price)}\n"
            f"📞 Support: @{support_user}\n"
            f"📢 Force Channel: {force_channel}")
    keyboard = [
        [InlineKeyboardButton("💰 Set Default Price", callback_data="admin_set_default_price")],
        [InlineKeyboardButton("📞 Set Support", callback_data="admin_set_support")],
        [InlineKeyboardButton("📢 Set Force Channel", callback_data="admin_set_force")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_show_users(query, context):
    users = await db.db.users.find({}).sort("created_at", -1).limit(10).to_list(length=10)
    lines = [f"• `{u['user_id']}` - ₹{format_price(u.get('balance',0))}" for u in users]
    text = "👥 **Recent Users**\n" + "\n".join(lines) + f"\nTotal: {await db.db.users.count_documents({})}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]), parse_mode=ParseMode.MARKDOWN)

async def admin_show_admins(query, context):
    admins = await db.get_admins()
    lines = [f"• `{a}` {'🔰' if a == OWNER_ID else ''}" for a in admins]
    text = "🔑 **Admins**\n" + "\n".join(lines) + "\n\n🔰 = Owner"
    keyboard = [
        [InlineKeyboardButton("➕ Add Admin", callback_data="admin_add_admin", style="success")],
        [InlineKeyboardButton("➖ Remove Admin", callback_data="admin_remove_admin", style="danger")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_show_payments(query, context):
    payments = await db.db.payments.find({"status": "pending"}).sort("created_at", -1).limit(10).to_list(length=10)
    if not payments:
        text = "No pending payments."
    else:
        lines = [f"• `{p['order_id']}` - ₹{format_price(p['amount'])} - User: `{p['user_id']}`" for p in payments]
        text = "💳 **Pending Payments**\n" + "\n".join(lines)
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")], [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]), parse_mode=ParseMode.MARKDOWN)

# ============================================================
# ADMIN INPUT HANDLER (unchanged)
# ============================================================
async def handle_admin_input(update, context, text):
    state = context.user_data.get("admin_state")
    service_id = context.user_data.get("service_id")

    # New Account Service - Platform
    if state == "new_acc_service_platform":
        platform = text.strip().lower()
        if platform not in ["telegram", "whatsapp"]:
            await update.message.reply_text(
                "❌ Invalid platform. Please send `telegram` or `whatsapp`.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        context.user_data["temp_acc_platform"] = platform
        context.user_data["admin_state"] = "new_acc_service_name"
        await update.message.reply_text(
            f"📋 Platform: {platform}\nEnter service name:",
            reply_markup=get_cancel_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # New Account Service - Name
    if state == "new_acc_service_name":
        name = text.strip()
        existing = await db.get_account_service_by_name(name)
        if existing:
            await update.message.reply_text("⚠️ Service already exists.", parse_mode=ParseMode.MARKDOWN)
            return
        context.user_data["temp_acc_service_name"] = name
        context.user_data["admin_state"] = "new_acc_service_price"
        await update.message.reply_text(f"📋 Service: {name}\nEnter price:", reply_markup=get_cancel_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    # New Account Service - Price
    if state == "new_acc_service_price":
        try:
            price = float(text)
            context.user_data["temp_acc_service_price"] = str(price)
            context.user_data["admin_state"] = "new_acc_service_desc"
            await update.message.reply_text("Enter description (or 'skip'):", reply_markup=get_cancel_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.", parse_mode=ParseMode.MARKDOWN)
        return

    # New Account Service - Description
    if state == "new_acc_service_desc":
        name = context.user_data.get("temp_acc_service_name")
        price = float(context.user_data.get("temp_acc_service_price", 100))
        platform = context.user_data.get("temp_acc_platform", "telegram")
        desc = text if text.lower() != "skip" else ""
        await db.create_account_service(name, price, platform, desc)
        await update.message.reply_text(
            f"✅ {platform.capitalize()} Service '{name}' created.",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        context.user_data.pop("temp_acc_service_name", None)
        context.user_data.pop("temp_acc_service_price", None)
        context.user_data.pop("temp_acc_platform", None)
        return

    # New Session Service
    if state == "new_sess_service_name":
        name = text.strip()
        existing = await db.get_session_service_by_name(name)
        if existing:
            await update.message.reply_text("⚠️ Service already exists.", parse_mode=ParseMode.MARKDOWN)
            return
        context.user_data["temp_sess_service_name"] = name
        context.user_data["admin_state"] = "new_sess_service_price"
        await update.message.reply_text(f"📋 Service: {name}\nEnter price:", reply_markup=get_cancel_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return
    if state == "new_sess_service_price":
        try:
            price = float(text)
            context.user_data["temp_sess_service_price"] = str(price)
            context.user_data["admin_state"] = "new_sess_service_desc"
            await update.message.reply_text("Enter description (or 'skip'):", reply_markup=get_cancel_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "new_sess_service_desc":
        name = context.user_data.get("temp_sess_service_name")
        price = float(context.user_data.get("temp_sess_service_price", 100))
        desc = text if text.lower() != "skip" else ""
        await db.create_session_service(name, price, desc)
        await update.message.reply_text(f"✅ Session Service '{name}' created.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("temp_sess_service_name", None)
        context.user_data.pop("temp_sess_service_price", None)
        return

    # Add account (OTP) – we already handle in separate functions
    if state == "add_account_phone":
        phone = text.strip().replace(" ", "")
        if not phone.startswith("+"):
            await update.message.reply_text("❌ Phone must start with + and country code.", parse_mode=ParseMode.MARKDOWN)
            return
        await admin_add_account_phone(update, context, phone)
        return
    if state == "add_account_otp":
        otp = text.strip()
        await admin_add_account_otp(update, context, otp)
        return
    if state == "add_account_2fa_login":
        password = text.strip()
        await admin_add_account_2fa_login(update, context, password)
        return
    if state == "add_account_2fa_password":
        await admin_add_account_2fa_password(update, context, text)
        return

    # Add session string
    if state == "add_session_string":
        service_id = context.user_data.get("service_id")
        if not service_id:
            await update.message.reply_text("❌ Session expired.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            return
        session_string = text.strip()
        existing = await db.db.session_items.find_one({"session_string": session_string})
        if existing:
            await update.message.reply_text("⚠️ Session string already exists.", parse_mode=ParseMode.MARKDOWN)
            return
        await db.add_session_item(service_id, session_string)
        service = await db.get_session_service(service_id)
        await update.message.reply_text(f"✅ Session added to {service['name']}.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        return

    # Set price / description
    if state == "set_acc_price":
        try:
            price = float(text)
            await db.update_account_service(service_id, {"price": price})
            await update.message.reply_text("✅ Price updated.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
            context.user_data.pop("service_id", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "set_acc_desc":
        desc = text.strip()
        await db.update_account_service(service_id, {"description": desc})
        await update.message.reply_text("✅ Description updated.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        return
    if state == "set_sess_price":
        try:
            price = float(text)
            await db.update_session_service(service_id, {"price": price})
            await update.message.reply_text("✅ Price updated.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
            context.user_data.pop("service_id", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "set_sess_desc":
        desc = text.strip()
        await db.update_session_service(service_id, {"description": desc})
        await update.message.reply_text("✅ Description updated.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        return

    # Add funds
    if state == "add_funds_user":
        try:
            target = int(text)
            context.user_data["fund_target"] = target
            context.user_data["admin_state"] = "add_funds_amount"
            await update.message.reply_text(f"Enter amount for user {target}:", reply_markup=get_cancel_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "add_funds_amount":
        try:
            amount = float(text)
            target = context.user_data.get("fund_target")
            await db.update_user_balance(target, amount)
            balance = await db.get_user_balance(target)
            await update.message.reply_text(f"✅ Added ₹{format_price(amount)} to user {target}. New balance: ₹{format_price(balance)}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
            context.user_data.pop("fund_target", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.", parse_mode=ParseMode.MARKDOWN)
        return

    # Settings
    if state == "set_default_price":
        try:
            price = float(text)
            await db.update_settings("default_price", price)
            await update.message.reply_text(f"✅ Default price set to ₹{format_price(price)}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "set_support":
        username = text.strip().replace("@", "")
        await db.update_settings("support_username", username)
        await update.message.reply_text(f"✅ Support username set to @{username}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        return
    if state == "set_force":
        if text.lower() == "none":
            await db.update_settings("force_channel", None)
            await update.message.reply_text("✅ Force channel disabled.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        else:
            await db.update_settings("force_channel", text)
            await update.message.reply_text(f"✅ Force channel set to {text}", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        return

    # Add/remove admin
    if state == "add_admin":
        try:
            target = int(text)
            if target == OWNER_ID:
                await update.message.reply_text("⚠️ Cannot add owner.", parse_mode=ParseMode.MARKDOWN)
                return
            await db.add_admin(target)
            await update.message.reply_text(f"✅ Admin {target} added.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.", parse_mode=ParseMode.MARKDOWN)
        return
    if state == "remove_admin":
        try:
            target = int(text)
            if target == OWNER_ID:
                await update.message.reply_text("⚠️ Cannot remove owner.", parse_mode=ParseMode.MARKDOWN)
                return
            await db.remove_admin(target)
            await update.message.reply_text(f"✅ Admin {target} removed.", reply_markup=get_admin_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.", parse_mode=ParseMode.MARKDOWN)
        return

# ============================================================
# MAIN
# ============================================================
async def main():
    Thread(target=run_web, daemon=True).start()
    try:
        await db.connect()
        logger.info("✅ Database connected successfully.")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("🤖 Bot starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("✅ Bot is polling.")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Stopping bot...")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("✅ Bot shut down gracefully.")

if __name__ == "__main__":
    asyncio.run(main())
