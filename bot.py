# bot.py - Main Bot File (All Logic Combined)
import os
import asyncio
import logging
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# Import modules
from database import db
from utils import (
    format_price, escape_markdown, get_main_keyboard, get_admin_keyboard,
    get_cancel_keyboard, generate_upi_qr, verify_payment_api, check_force_channel
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
(
    SELECT_PRODUCT, AWAITING_UPI_PAYMENT, AWAITING_PHONE,
    AWAITING_OTP, AWAITING_2FA, AWAITING_SESSION, AWAITING_AMOUNT,
    AWAITING_USER_ID, AWAITING_PRICE, AWAITING_ANNOUNCE
) = range(10)

# Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

# ============================================================
# START HANDLER
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    await db.connect()
    
    # Check if user exists
    existing_user = await db.get_user(user.id)
    if not existing_user:
        await db.create_user(user.id, user.username, user.full_name)
    
    # Check force channel
    if not await check_force_channel(context, user.id):
        force_channel = os.getenv("FORCE_CHANNEL")
        try:
            chat = await context.bot.get_chat(int(force_channel))
            channel_link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(force_channel)[4:]}"
            
            keyboard = [
                [InlineKeyboardButton("📢 Join Channel", url=channel_link)],
                [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]
            ]
            
            await update.message.reply_text(
                f"🔒 **Please Join Our Channel First!**\n\n"
                f"To use this bot, you must join:\n{channel_link}\n\n"
                f"After joining, click the button below.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        except:
            pass
    
    # Welcome message
    welcome_text = (
        f"🌟 **Welcome {escape_markdown(user.full_name)}!** 🌟\n\n"
        "Welcome to **Premium Account Store** - Your trusted source for Telegram accounts and sessions.\n\n"
        "🔹 **What we offer:**\n"
        "• 📱 Telegram Accounts (with OTP)\n"
        "• 🔐 Session Files (with 2FA support)\n"
        "• 💳 Easy UPI Payments\n"
        "• 🚀 Instant Delivery\n\n"
        "Select an option below:"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(user.id),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# CALLBACK HANDLER
# ============================================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    await db.connect()
    
    # Cancel operation
    if data == "cancel_operation":
        context.user_data.clear()
        await query.edit_message_text(
            "❌ **Operation Cancelled**",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check join
    if data == "check_join":
        if await check_force_channel(context, user_id):
            await query.edit_message_text(
                "✅ **Thanks for joining!**\n\nYou can now use the bot.",
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.answer("❌ Please join the channel first!", alert=True)
        return
    
    # Back to start
    if data == "start_back":
        await query.edit_message_text(
            "🌟 **Main Menu**",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # ==========================================================
    # USER FEATURES
    # ==========================================================
    
    # Buy Account
    if data == "buy_account":
        await show_accounts(query, context)
        return
    
    # Buy Session
    if data == "buy_session":
        await show_sessions(query, context)
        return
    
    # My Account
    if data == "my_account":
        user = await db.get_user(user_id)
        balance = user.get("balance", 0) if user else 0
        purchases = user.get("total_purchases", 0) if user else 0
        
        await query.edit_message_text(
            f"👤 **My Account**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 User ID: `{user_id}`\n"
            f"👤 Username: @{query.from_user.username or 'N/A'}\n"
            f"💰 Balance: ₹{format_price(balance)}\n"
            f"📦 Purchases: {purchases}\n━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Add Balance", callback_data="add_balance")],
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add Balance
    if data == "add_balance":
        await show_payment_options(query, context)
        return
    
    # Support
    if data == "support":
        support_user = await db.get_settings("support_username") or "admin"
        await query.edit_message_text(
            f"📞 **Support**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Need help? Contact our support:\n\n"
            f"• Telegram: @{support_user}\n"
            f"• Response time: Usually within 24 hours\n"
            f"• For payment issues, send your transaction ID\n\n"
            f"We're here to help! 🤝",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # About
    if data == "about":
        await query.edit_message_text(
            f"ℹ️ **About Premium Account Store**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Version: 2.0.0\n"
            f"Built with ❤️ using Python & MongoDB\n\n"
            f"**Features:**\n"
            f"• 🔒 Secure & Fast\n"
            f"• 💳 UPI Payments\n"
            f"• 📱 Account Delivery\n"
            f"• 🔐 Session Delivery\n"
            f"• 🤖 24/7 Automated\n\n"
            f"Thank you for using our service! 🌟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # ==========================================================
    # ACCOUNT PURCHASE
    # ==========================================================
    if data.startswith("buy_acc_"):
        await handle_account_purchase(query, context)
        return
    
    # ==========================================================
    # SESSION PURCHASE
    # ==========================================================
    if data.startswith("buy_sess_"):
        await handle_session_purchase(query, context)
        return
    
    # ==========================================================
    # PAYMENT HANDLERS
    # ==========================================================
    if data.startswith("pay_"):
        await handle_payment_callback(query, context)
        return
    
    if data == "verify_payment":
        await verify_payment(query, context)
        return
    
    # ==========================================================
    # ADMIN FEATURES
    # ==========================================================
    if data == "admin_panel":
        await show_admin_panel(query, context)
        return
    
    # Admin callbacks
    if data.startswith("admin_"):
        await handle_admin_callback(query, context)
        return
    
    # ==========================================================
    # PAGINATION
    # ==========================================================
    if data.startswith("page_"):
        await handle_pagination(query, context)
        return

# ============================================================
# ACCOUNT FUNCTIONS
# ============================================================
async def show_accounts(query, context):
    """Show available accounts with pagination"""
    page = context.user_data.get("account_page", 0)
    limit = 5
    offset = page * limit
    
    accounts = await db.get_available_accounts(limit, offset)
    total = await db.get_account_count()
    
    if not accounts:
        await query.edit_message_text(
            "📭 **No Accounts Available**\n\nCheck back later.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = []
    for acc in accounts:
        keyboard.append([
            InlineKeyboardButton(
                f"📱 {acc['phone']} - ₹{format_price(acc['price'])}",
                callback_data=f"buy_acc_{str(acc['_id'])}"
            )
        ])
    
    # Pagination
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))
    if offset + limit < total:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="start_back")])
    
    await query.edit_message_text(
        f"🛒 **Available Accounts**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {total} accounts available\n"
        f"Page: {page + 1}\n\n"
        f"Select an account to purchase:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_account_purchase(query, context):
    """Handle account purchase"""
    account_id = query.data.split("_")[2]
    user_id = query.from_user.id
    
    account = await db.db.accounts.find_one({"_id": account_id})
    if not account or account.get("status") != "available":
        await query.answer("⚠️ Account already sold!", alert=True)
        return
    
    price = account.get("price", 100)
    balance = await db.get_user_balance(user_id)
    
    if balance < price:
        await query.answer(f"❌ Insufficient balance! Need ₹{format_price(price)}", alert=True)
        return
    
    # Show confirmation
    confirm_keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_acc_{account_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")
        ]
    ]
    
    await query.edit_message_text(
        f"🧾 **Purchase Confirmation**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Phone: `{account['phone']}`\n"
        f"💰 Price: ₹{format_price(price)}\n"
        f"💳 Your Balance: ₹{format_price(balance)}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"After purchase, OTP will be auto-forwarded.",
        reply_markup=InlineKeyboardMarkup(confirm_keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_account_purchase(query, context):
    """Confirm account purchase"""
    account_id = query.data.split("_")[2]
    user_id = query.from_user.id
    
    account = await db.db.accounts.find_one({"_id": account_id})
    if not account or account.get("status") != "available":
        await query.answer("⚠️ Account already sold!", alert=True)
        return
    
    price = account.get("price", 100)
    
    # Process purchase
    success = await db.purchase_account(account_id, user_id, price)
    
    if success:
        await query.edit_message_text(
            f"✅ **Purchase Successful!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Account: `{account['phone']}`\n"
            f"💰 Price: ₹{format_price(price)}\n"
            f"📩 OTP will be forwarded here automatically.\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Keep this chat open to receive OTP.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Start OTP forwarding (simplified - actual implementation would use telethon/pyrogram)
        logger.info(f"Account {account['phone']} purchased by {user_id}")
    else:
        await query.edit_message_text(
            "❌ **Purchase Failed!**\n\nPlease try again or contact support.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )

# ============================================================
# SESSION FUNCTIONS
# ============================================================
async def show_sessions(query, context):
    """Show available sessions"""
    sessions = await db.db.sessions.find({"is_active": True}).to_list(length=10)
    
    if not sessions:
        await query.edit_message_text(
            "📭 **No Sessions Available**\n\nCheck back later.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = []
    for sess in sessions:
        price = sess.get("price", 100)
        keyboard.append([
            InlineKeyboardButton(
                f"🔐 Session #{str(sess['_id'])[:8]} - ₹{format_price(price)}",
                callback_data=f"buy_sess_{str(sess['_id'])}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="start_back")])
    
    await query.edit_message_text(
        "🔐 **Available Sessions**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a session to purchase:\n"
        "• Session file will be sent\n"
        "• 2FA supported\n"
        "• Instant delivery",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_session_purchase(query, context):
    """Handle session purchase"""
    session_id = query.data.split("_")[2]
    user_id = query.from_user.id
    
    session = await db.db.sessions.find_one({"_id": session_id})
    if not session or not session.get("is_active"):
        await query.answer("⚠️ Session already sold!", alert=True)
        return
    
    price = session.get("price", 100)
    balance = await db.get_user_balance(user_id)
    
    if balance < price:
        await query.answer(f"❌ Insufficient balance! Need ₹{format_price(price)}", alert=True)
        return
    
    # Confirm
    confirm_keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_sess_{session_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")
        ]
    ]
    
    await query.edit_message_text(
        f"🧾 **Session Purchase Confirmation**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Session ID: #{str(session_id)[:8]}\n"
        f"💰 Price: ₹{format_price(price)}\n"
        f"💳 Your Balance: ₹{format_price(balance)}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup(confirm_keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_session_purchase(query, context):
    """Confirm session purchase"""
    session_id = query.data.split("_")[2]
    user_id = query.from_user.id
    
    session = await db.db.sessions.find_one({"_id": session_id})
    if not session or not session.get("is_active"):
        await query.answer("⚠️ Session already sold!", alert=True)
        return
    
    price = session.get("price", 100)
    balance = await db.get_user_balance(user_id)
    
    if balance < price:
        await query.answer("❌ Insufficient balance!", alert=True)
        return
    
    # Process purchase
    await db.db.sessions.update_one(
        {"_id": session_id},
        {"$set": {"is_active": False, "sold_to": user_id, "sold_at": datetime.utcnow()}}
    )
    await db.update_user_balance(user_id, -price)
    
    # Create session file
    session_data = session.get("session_string", "")
    session_file = BytesIO()
    session_file.write(session_data.encode())
    session_file.name = f"session_{str(session_id)[:8]}.session"
    session_file.seek(0)
    
    await query.edit_message_text(
        f"✅ **Session Purchased Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Price: ₹{format_price(price)}\n"
        f"📤 Session file sent below\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Keep the file secure!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Send file
    await query.message.reply_document(
        document=session_file,
        caption=f"🔐 Session #{str(session_id)[:8]}"
    )

# ============================================================
# PAYMENT FUNCTIONS
# ============================================================
async def show_payment_options(query, context):
    """Show payment options"""
    keyboard = [
        [
            InlineKeyboardButton("₹100", callback_data="pay_100"),
            InlineKeyboardButton("₹200", callback_data="pay_200"),
            InlineKeyboardButton("₹500", callback_data="pay_500")
        ],
        [
            InlineKeyboardButton("₹1000", callback_data="pay_1000"),
            InlineKeyboardButton("Custom", callback_data="pay_custom")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
    ]
    
    await query.edit_message_text(
        "💰 **Add Balance**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select amount to add:\n"
        "• Minimum: ₹50\n"
        "• Maximum: ₹10,000\n"
        "• UPI payment accepted\n\n"
        "Click an amount below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_payment_callback(query, context):
    """Handle payment amount selection"""
    data = query.data
    
    if data == "pay_custom":
        context.user_data["payment_state"] = "custom_amount"
        await query.edit_message_text(
            "💳 **Custom Amount**\n\n"
            "Enter the amount you want to add:\n"
            "Example: `250`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        amount = float(data.split("_")[1])
        await generate_payment_qr(query, context, amount)
    except:
        await query.answer("Invalid amount!", alert=True)

async def generate_payment_qr(query, context, amount):
    """Generate payment QR code"""
    user_id = query.from_user.id
    upi_id = os.getenv("MERCHANT_UPI")
    
    # Create payment record
    payment = await db.create_payment(user_id, amount, upi_id)
    context.user_data["pending_payment"] = payment["transaction_id"]
    
    # Generate QR
    qr_bio = await generate_upi_qr(upi_id, amount, payment["transaction_id"])
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Verify Payment", callback_data="verify_payment"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")
        ]
    ]
    
    await query.edit_message_text(
        f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: ₹{format_price(amount)}\n"
        f"🆔 Txn ID: `{payment['transaction_id']}`\n"
        f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Scan QR or pay to UPI ID.\n"
        f"Click 'Verify Payment' after paying.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Send QR
    await query.message.reply_photo(
        photo=qr_bio,
        caption=f"💳 **Scan to Pay ₹{format_price(amount)}**"
    )

async def verify_payment(query, context):
    """Verify payment"""
    user_id = query.from_user.id
    transaction_id = context.user_data.get("pending_payment")
    
    if not transaction_id:
        await query.answer("No pending payment!", alert=True)
        return
    
    # Verify via API
    verified = await verify_payment_api(transaction_id)
    
    if verified:
        await db.verify_payment(transaction_id)
        payment = await db.db.payments.find_one({"transaction_id": transaction_id})
        amount = payment.get("amount", 0)
        
        await db.update_user_balance(user_id, amount)
        balance = await db.get_user_balance(user_id)
        
        await query.edit_message_text(
            f"✅ **Payment Verified Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 ₹{format_price(amount)} added to wallet\n"
            f"💳 New Balance: ₹{format_price(balance)}\n"
            f"🆔 Txn: `{transaction_id}`\n━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("pending_payment", None)
    else:
        await query.answer("❌ Payment not verified! Try again.", alert=True)

# ============================================================
# ADMIN FUNCTIONS
# ============================================================
async def show_admin_panel(query, context):
    """Show admin panel"""
    user_id = query.from_user.id
    admins = await db.get_admins()
    
    if user_id not in admins:
        await query.answer("⛔ Unauthorized!", alert=True)
        return
    
    # Get stats
    user_count = await db.db.users.count_documents({})
    account_count = await db.get_account_count()
    payment_count = await db.db.payments.count_documents({"status": "pending"})
    
    # Get total revenue
    pipeline = [
        {"$match": {"status": "sold"}},
        {"$group": {"_id": None, "total": {"$sum": "$price"}}}
    ]
    revenue_result = await db.db.accounts.aggregate(pipeline).to_list(1)
    total_revenue = revenue_result[0]["total"] if revenue_result else 0
    
    stats_text = (
        f"🔰 **Admin Dashboard**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Users: {user_count}\n"
        f"📦 Available: {account_count}\n"
        f"💰 Pending Payments: {payment_count}\n"
        f"💵 Revenue: ₹{format_price(total_revenue)}\n━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    await query.edit_message_text(
        stats_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_admin_callback(query, context):
    """Handle admin callback"""
    data = query.data
    user_id = query.from_user.id
    
    # Check admin
    admins = await db.get_admins()
    if user_id not in admins:
        await query.answer("⛔ Unauthorized!", alert=True)
        return
    
    # Add Account
    if data == "admin_add_account":
        context.user_data["admin_state"] = "add_account"
        await query.edit_message_text(
            "📱 **Add Account**\n\n"
            "Send phone number with country code:\n"
            "Example: `+919876543210`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add Session
    if data == "admin_add_session":
        context.user_data["admin_state"] = "add_session"
        await query.edit_message_text(
            "🔐 **Add Session**\n\n"
            "Send the session string:\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add Funds
    if data == "admin_add_funds":
        context.user_data["admin_state"] = "add_funds_user"
        await query.edit_message_text(
            "💰 **Add Funds**\n\n"
            "Send user ID to credit:\n"
            "Example: `123456789`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Stats
    if data == "admin_stats":
        await show_admin_panel(query, context)
        return
    
    # Announce
    if data == "admin_announce":
        context.user_data["admin_state"] = "announce"
        context.user_data["announce_messages"] = []
        await query.edit_message_text(
            "📢 **Send Announcement**\n\n"
            "Send messages to broadcast.\n"
            "Send `/done` when finished.\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Settings
    if data == "admin_settings":
        await show_admin_settings(query, context)
        return
    
    # Users
    if data == "admin_users":
        await show_admin_users(query, context)
        return
    
    # Admins
    if data == "admin_admins":
        await show_admin_admins(query, context)
        return
    
    # Stock
    if data == "admin_stock":
        await show_admin_stock(query, context)
        return
    
    # Payments
    if data == "admin_payments":
        await show_admin_payments(query, context)
        return
    
    # Setting callbacks
    if data == "admin_set_price":
        context.user_data["admin_state"] = "set_price"
        await query.edit_message_text(
            "💰 **Set Default Price**\n\n"
            "Enter new default price:\n"
            "Example: `150`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_set_support":
        context.user_data["admin_state"] = "set_support"
        await query.edit_message_text(
            "📞 **Set Support Username**\n\n"
            "Enter support username (without @):\n"
            "Example: `support_bot`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_set_force":
        context.user_data["admin_state"] = "set_force"
        await query.edit_message_text(
            "📢 **Set Force Channel**\n\n"
            "Enter channel ID or username:\n"
            "Example: `-1001234567890`\n\n"
            "Send `none` to disable.\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_add_admin":
        context.user_data["admin_state"] = "add_admin"
        await query.edit_message_text(
            "🔑 **Add Admin**\n\n"
            "Send user ID to add as admin:\n"
            "Example: `123456789`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_remove_admin":
        context.user_data["admin_state"] = "remove_admin"
        await query.edit_message_text(
            "🔑 **Remove Admin**\n\n"
            "Send user ID to remove from admin:\n"
            "Example: `123456789`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

# ============================================================
# ADMIN SETTINGS & MANAGEMENT
# ============================================================
async def show_admin_settings(query, context):
    """Show admin settings panel"""
    default_price = await db.get_settings("default_price") or 100
    support_user = await db.get_settings("support_username") or "admin"
    force_channel = await db.get_settings("force_channel") or "Not set"
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Price", callback_data="admin_set_price"),
            InlineKeyboardButton("📞 Support", callback_data="admin_set_support")
        ],
        [
            InlineKeyboardButton("📢 Force Channel", callback_data="admin_set_force")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        f"⚙️ **Settings**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Default Price: ₹{format_price(default_price)}\n"
        f"📞 Support: @{support_user}\n"
        f"📢 Force Channel: {force_channel}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_users(query, context):
    """Show user management"""
    # Get last 10 users
    users = await db.db.users.find({}).sort("created_at", -1).limit(10).to_list(length=10)
    
    user_list = []
    for user in users:
        user_list.append(f"• `{user['user_id']}` - ₹{format_price(user.get('balance', 0))}")
    
    user_text = "\n".join(user_list) if user_list else "No users yet"
    
    await query.edit_message_text(
        f"👥 **Recent Users**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{user_text}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {await db.db.users.count_documents({})} users",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_admins(query, context):
    """Show admin management"""
    admins = await db.get_admins()
    admin_list = []
    for admin in admins:
        if admin == OWNER_ID:
            admin_list.append(f"• `{admin}` 🔰 (Owner)")
        else:
            admin_list.append(f"• `{admin}`")
    
    admin_text = "\n".join(admin_list) if admin_list else "No admins"
    
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Admin", callback_data="admin_add_admin"),
            InlineKeyboardButton("➖ Remove Admin", callback_data="admin_remove_admin")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        f"🔑 **Admins**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{admin_text}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔰 = Permanent Owner",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_stock(query, context):
    """Show stock management"""
    available = await db.get_account_count()
    sold = await db.db.accounts.count_documents({"status": "sold"})
    total = await db.db.accounts.count_documents({})
    
    await query.edit_message_text(
        f"📦 **Stock Report**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Available: {available}\n"
        f"❌ Sold: {sold}\n"
        f"📊 Total: {total}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_payments(query, context):
    """Show payment management"""
    payments = await db.db.payments.find({"status": "pending"}).sort("created_at", -1).limit(10).to_list(length=10)
    
    if not payments:
        payment_text = "No pending payments"
    else:
        payment_text = ""
        for p in payments:
            payment_text += f"• `{p['transaction_id']}` - ₹{format_price(p['amount'])} - User: `{p['user_id']}`\n"
    
    await query.edit_message_text(
        f"💳 **Pending Payments**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{payment_text}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# MESSAGE HANDLER (Admin Inputs)
# ============================================================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    text = update.message.text
    user_id = update.effective_user.id
    await db.connect()
    
    # Cancel command
    if text == "/cancel":
        context.user_data.clear()
        await update.message.reply_text(
            "❌ **Cancelled**",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Admin state handling
    admin_state = context.user_data.get("admin_state")
    if admin_state:
        await handle_admin_input(update, context, text)
        return
    
    # Payment state handling
    payment_state = context.user_data.get("payment_state")
    if payment_state == "custom_amount":
        await handle_custom_amount(update, context, text)
        return
    
    # Default response
    await update.message.reply_text(
        "Please use the buttons to navigate.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_admin_input(update, context, text):
    """Handle admin input states"""
    state = context.user_data.get("admin_state")
    user_id = update.effective_user.id
    
    # Add Account - Phone
    if state == "add_account":
        phone = text.strip().replace(" ", "")
        if not phone.startswith("+"):
            await update.message.reply_text(
                "❌ **Invalid Phone**\n\n"
                "Phone must start with `+` and country code.\n"
                "Example: `+919876543210`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Check if account exists
        existing = await db.db.accounts.find_one({"phone": phone})
        if existing:
            await update.message.reply_text(
                f"⚠️ Account `{phone}` already exists!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Add account
        default_price = await db.get_settings("default_price") or 100
        await db.add_account(phone, default_price)
        
        await update.message.reply_text(
            f"✅ **Account Added Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Phone: `{phone}`\n"
            f"💰 Price: ₹{format_price(default_price)}\n\n"
            f"Account is now available for purchase.",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        return
    
    # Add Session
    if state == "add_session":
        session_string = text.strip()
        
        # Check if exists
        existing = await db.db.sessions.find_one({"session_string": session_string})
        if existing:
            await update.message.reply_text(
                "⚠️ Session already exists!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Add session
        default_price = await db.get_settings("default_price") or 100
        session_data = {
            "session_string": session_string,
            "price": default_price,
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        await db.db.sessions.insert_one(session_data)
        
        await update.message.reply_text(
            f"✅ **Session Added Successfully!**\n\n"
            f"Price: ₹{format_price(default_price)}",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        return
    
    # Add Funds - User ID
    if state == "add_funds_user":
        try:
            target_id = int(text)
            context.user_data["fund_target"] = target_id
            context.user_data["admin_state"] = "add_funds_amount"
            await update.message.reply_text(
                f"💰 **Enter Amount**\n\n"
                f"Amount to credit to `{target_id}`:",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid User ID**\n\n"
                "Send a numeric ID.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Add Funds - Amount
    if state == "add_funds_amount":
        try:
            amount = float(text)
            target_id = context.user_data.get("fund_target")
            
            await db.update_user_balance(target_id, amount)
            balance = await db.get_user_balance(target_id)
            
            await update.message.reply_text(
                f"✅ **Funds Added!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"User: `{target_id}`\n"
                f"Added: ₹{format_price(amount)}\n"
                f"New Balance: ₹{format_price(balance)}",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("fund_target", None)
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid Amount**\n\n"
                "Send a valid number.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Announce
    if state == "announce":
        if text == "/done":
            messages = context.user_data.get("announce_messages", [])
            if not messages:
                await update.message.reply_text(
                    "❌ No messages to broadcast!",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Broadcast
            users = await db.db.users.find({}).to_list(length=None)
            success = 0
            progress = await update.message.reply_text(
                f"⏳ Broadcasting to {len(users)} users...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            for i, user in enumerate(users):
                try:
                    for msg in messages:
                        await msg.copy(user["user_id"])
                    success += 1
                    if (i + 1) % 10 == 0:
                        await progress.edit_text(
                            f"⏳ Progress: {success}/{len(users)}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                except:
                    continue
            
            await progress.edit_text(
                f"✅ **Broadcast Complete!**\n\n"
                f"Sent to: {success}/{len(users)} users",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("announce_messages", None)
        else:
            context.user_data["announce_messages"].append(update.message)
            await update.message.reply_text(
                f"📥 **Message Captured**\n\n"
                f"Messages: {len(context.user_data['announce_messages'])}\n"
                f"Send `/done` to broadcast.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Set Price
    if state == "set_price":
        try:
            price = float(text)
            await db.update_settings("default_price", price)
            await update.message.reply_text(
                f"✅ **Price Updated!**\n\n"
                f"New default price: ₹{format_price(price)}",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid Price**\n\n"
                "Send a valid number.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Set Support
    if state == "set_support":
        username = text.strip().replace("@", "")
        await db.update_settings("support_username", username)
        await update.message.reply_text(
            f"✅ **Support Updated!**\n\n"
            f"New support: @{username}",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        return
    
    # Set Force Channel
    if state == "set_force":
        if text.lower() == "none":
            await db.update_settings("force_channel", None)
            await update.message.reply_text(
                "✅ **Force Channel Disabled**",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await db.update_settings("force_channel", text)
            await update.message.reply_text(
                f"✅ **Force Channel Set**\n\n"
                f"Channel: {text}",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        context.user_data.pop("admin_state", None)
        return
    
    # Add Admin
    if state == "add_admin":
        try:
            target_id = int(text)
            if target_id == OWNER_ID:
                await update.message.reply_text(
                    "⚠️ This is the permanent owner!",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            await db.add_admin(target_id)
            await update.message.reply_text(
                f"✅ **Admin Added!**\n\n"
                f"User `{target_id}` is now an admin.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid User ID**",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Remove Admin
    if state == "remove_admin":
        try:
            target_id = int(text)
            if target_id == OWNER_ID:
                await update.message.reply_text(
                    "⚠️ Cannot remove permanent owner!",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            await db.remove_admin(target_id)
            await update.message.reply_text(
                f"✅ **Admin Removed!**\n\n"
                f"User `{target_id}` is no longer an admin.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid User ID**",
                parse_mode=ParseMode.MARKDOWN
            )
        return

# ============================================================
# CUSTOM AMOUNT HANDLER
# ============================================================
async def handle_custom_amount(update, context, text):
    """Handle custom payment amount"""
    try:
        amount = float(text)
        if amount < 50:
            await update.message.reply_text(
                "❌ **Minimum amount is ₹50**",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        if amount > 10000:
            await update.message.reply_text(
                "❌ **Maximum amount is ₹10,000**",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        context.user_data.pop("payment_state", None)
        await generate_payment_qr_from_message(update, context, amount)
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid Amount**\n\n"
            "Send a valid number.",
            parse_mode=ParseMode.MARKDOWN
        )

async def generate_payment_qr_from_message(update, context, amount):
    """Generate payment QR from message"""
    user_id = update.effective_user.id
    upi_id = os.getenv("MERCHANT_UPI")
    
    payment = await db.create_payment(user_id, amount, upi_id)
    context.user_data["pending_payment"] = payment["transaction_id"]
    
    qr_bio = await generate_upi_qr(upi_id, amount, payment["transaction_id"])
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Verify Payment", callback_data="verify_payment"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")
        ]
    ]
    
    await update.message.reply_text(
        f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: ₹{format_price(amount)}\n"
        f"🆔 Txn ID: `{payment['transaction_id']}`\n"
        f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    await update.message.reply_photo(
        photo=qr_bio,
        caption=f"💳 **Scan to Pay ₹{format_price(amount)}**"
    )

# ============================================================
# PAGINATION HANDLER
# ============================================================
async def handle_pagination(query, context):
    """Handle pagination for accounts"""
    data = query.data
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        context.user_data["account_page"] = page
        await show_accounts(query, context)

# ============================================================
# MAIN FUNCTION
# ============================================================
async def main():
    """Main bot function"""
    # Connect to database
    await db.connect()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Add conversation handler for confirmations
    application.add_handler(CallbackQueryHandler(confirm_account_purchase, pattern="^confirm_acc_"))
    application.add_handler(CallbackQueryHandler(confirm_session_purchase, pattern="^confirm_sess_"))
    
    # Start bot
    logger.info("Bot started!")
    
    # Use polling for Render
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
