# bot.py - Main Bot File with Service-Based Account Management
import os
import asyncio
import logging
import base64
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, 
    MessageHandler, Filters, CallbackContext
)
from telegram import ParseMode

from database import db
from utils import (
    format_price, escape_markdown, get_main_keyboard, get_admin_keyboard,
    get_cancel_keyboard, get_payment_keyboard,
    generate_fampay_qr, verify_fampay_payment, generate_upi_qr, check_force_channel,
    verify_payment_api
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MERCHANT_UPI = os.getenv("MERCHANT_UPI")

# ============================================================
# START HANDLER
# ============================================================
def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    
    # Check if user exists, create if not
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def init_user():
        await db.connect()
        existing_user = await db.get_user(user_id)
        if not existing_user:
            await db.create_user(user_id, user.username, user.full_name)
        
        if not await check_force_channel(context, user_id):
            force_channel = os.getenv("FORCE_CHANNEL")
            try:
                chat = context.bot.get_chat(int(force_channel))
                channel_link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(force_channel)[4:]}"
                keyboard = [
                    [InlineKeyboardButton("📢 Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]
                ]
                update.message.reply_text(
                    f"🔒 **Please Join Our Channel First!**\n\nTo use this bot, you must join:\n{channel_link}\n\nAfter joining, click the button below.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            except:
                pass
        
        welcome_text = (
            f"🌟 **Welcome {escape_markdown(user.full_name)}!** 🌟\n\n"
            "Welcome to **Premium Account Store** - Your trusted source for Telegram accounts.\n\n"
            "🔹 **What we offer:**\n"
            "• 📱 Multiple Service Categories\n"
            "• 💳 Easy UPI Payments\n"
            "• 🚀 Instant Delivery\n\n"
            "Select an option below:"
        )
        
        update.message.reply_text(
            welcome_text,
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
    
    loop.run_until_complete(init_user())
    loop.close()

# ============================================================
# CALLBACK HANDLER
# ============================================================
def callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def handle_callback():
        await db.connect()
        
        if data == "cancel_operation":
            context.user_data.clear()
            query.edit_message_text(
                "❌ **Operation Cancelled**",
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if data == "check_join":
            if await check_force_channel(context, user_id):
                query.edit_message_text(
                    "✅ **Thanks for joining!**\n\nYou can now use the bot.",
                    reply_markup=get_main_keyboard(user_id),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                query.answer("❌ Please join the channel first!", alert=True)
            return
        
        if data == "start_back":
            query.edit_message_text(
                "🌟 **Main Menu**",
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if data == "buy_account":
            await show_services(query, context)
            return
        
        if data == "my_account":
            user = await db.get_user(user_id)
            balance = user.get("balance", 0) if user else 0
            purchases = user.get("total_purchases", 0) if user else 0
            
            query.edit_message_text(
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
        
        if data == "add_balance":
            await show_payment_options(query, context)
            return
        
        if data == "support":
            support_user = await db.get_settings("support_username") or "admin"
            query.edit_message_text(
                f"📞 **Support**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Need help? Contact our support:\n\n"
                f"• Telegram: @{support_user}\n"
                f"• Response time: Usually within 24 hours\n\n"
                f"We're here to help! 🤝",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if data == "about":
            query.edit_message_text(
                f"ℹ️ **About Premium Account Store**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Version: 2.0.0\n"
                f"Built with ❤️ using Python & MongoDB\n\n"
                f"**Features:**\n"
                f"• 🔒 Secure & Fast\n"
                f"• 💳 UPI Payments\n"
                f"• 📱 Multiple Service Categories\n"
                f"• 🤖 24/7 Automated\n\n"
                f"Thank you for using our service! 🌟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if data.startswith("service_"):
            service_id = data.split("_")[1]
            await show_service_details(query, context, service_id)
            return
        
        if data.startswith("buy_service_"):
            service_id = data.split("_")[2]
            await handle_service_purchase(query, context, service_id)
            return
        
        if data.startswith("confirm_buy_"):
            service_id = data.split("_")[2]
            await confirm_service_purchase(query, context, service_id)
            return
        
        if data.startswith("pay_"):
            await handle_payment_callback(query, context)
            return
        
        if data.startswith("verify_pay_"):
            await verify_payment(query, context)
            return
        
        if data == "admin_panel":
            await show_admin_panel(query, context)
            return
        
        if data.startswith("admin_"):
            await handle_admin_callback(query, context)
            return
    
    loop.run_until_complete(handle_callback())
    loop.close()

# ============================================================
# SERVICE DISPLAY FUNCTIONS
# ============================================================
async def show_services(query, context):
    services = await db.get_all_services()
    
    if not services:
        query.edit_message_text(
            "📭 **No Services Available**\n\nCheck back later for new services.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = []
    for service in services:
        service_id = str(service["_id"])
        available = await db.get_service_available_count(service_id)
        
        if available > 0:
            keyboard.append([
                InlineKeyboardButton(
                    f"📱 {service['name']} - ₹{format_price(service['price'])} [{available} available]",
                    callback_data=f"service_{service_id}"
                )
            ])
    
    if not keyboard:
        query.edit_message_text(
            "📭 **All Services Out of Stock!**\n\nCheck back later.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="start_back")])
    
    query.edit_message_text(
        "🛒 **Available Services**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a service to view details and purchase:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_service_details(query, context, service_id):
    service = await db.get_service(service_id)
    if not service or not service.get("is_active"):
        query.answer("⚠️ Service not available!", alert=True)
        return
    
    available = await db.get_service_available_count(service_id)
    
    if available == 0:
        query.edit_message_text(
            f"📭 **{service['name']} - Out of Stock!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price: ₹{format_price(service['price'])}\n"
            f"📝 Description: {service.get('description', 'No description')}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ No accounts available right now.\n"
            f"Check back later!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Services", callback_data="buy_account")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = [
        [InlineKeyboardButton(f"✅ Buy Now - ₹{format_price(service['price'])}", callback_data=f"buy_service_{service_id}")],
        [InlineKeyboardButton("🔙 Back to Services", callback_data="buy_account")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
    ]
    
    query.edit_message_text(
        f"📱 **{service['name']}**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Price: ₹{format_price(service['price'])}\n"
        f"📦 Available: {available} accounts\n"
        f"📝 Description: {service.get('description', 'No description')}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Click 'Buy Now' to purchase an account from this service.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_service_purchase(query, context, service_id):
    user_id = query.from_user.id
    
    service = await db.get_service(service_id)
    if not service or not service.get("is_active"):
        query.answer("⚠️ Service not available!", alert=True)
        return
    
    available = await db.get_service_available_count(service_id)
    if available == 0:
        query.answer("❌ Out of stock!", alert=True)
        return
    
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    
    if balance < price:
        keyboard = [
            [InlineKeyboardButton("💰 Add Balance", callback_data="add_balance")],
            [InlineKeyboardButton("🔙 Back to Service", callback_data=f"service_{service_id}")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
        ]
        query.edit_message_text(
            f"❌ **Insufficient Balance!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Service: {service['name']}\n"
            f"💰 Price: ₹{format_price(price)}\n"
            f"💳 Your Balance: ₹{format_price(balance)}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You need ₹{format_price(price - balance)} more.\n\n"
            f"Please add balance to continue.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_buy_{service_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")
        ]
    ]
    
    query.edit_message_text(
        f"🧾 **Purchase Confirmation**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Service: {service['name']}\n"
        f"💰 Price: ₹{format_price(price)}\n"
        f"💳 Your Balance: ₹{format_price(balance)}\n"
        f"📦 Available: {available} accounts\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"After purchase, account details will be sent.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_service_purchase(query, context, service_id):
    user_id = query.from_user.id
    
    service = await db.get_service(service_id)
    if not service or not service.get("is_active"):
        query.answer("⚠️ Service not available!", alert=True)
        return
    
    price = service["price"]
    balance = await db.get_user_balance(user_id)
    
    if balance < price:
        query.answer("❌ Insufficient balance!", alert=True)
        return
    
    account = await db.purchase_account_from_service(service_id, user_id, price)
    
    if not account:
        query.edit_message_text(
            "❌ **Purchase Failed!**\n\n"
            "No accounts available in this service.\n"
            "Please try another service.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 View Services", callback_data="buy_account")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    success_text = (
        f"✅ **Purchase Successful!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Service: {service['name']}\n"
        f"💰 Price: ₹{format_price(price)}\n"
        f"📱 Account: `{account['phone']}`\n"
        f"📩 OTP will be forwarded here automatically.\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Keep this chat open to receive OTP."
    )
    
    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="buy_account")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
    ]
    
    query.edit_message_text(
        success_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    if account.get("session_string"):
        session_file = BytesIO()
        session_file.write(account["session_string"].encode())
        session_file.name = f"account_{account['phone']}.session"
        session_file.seek(0)
        
        query.message.reply_document(
            document=session_file,
            caption=f"🔐 Session file for {account['phone']}"
        )
    
    logger.info(f"Service {service['name']} purchased by {user_id} - Account: {account['phone']}")

# ============================================================
# PAYMENT FUNCTIONS
# ============================================================
async def show_payment_options(query, context):
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
    
    query.edit_message_text(
        "💰 **Add Balance**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select amount to add:\n"
        "• Minimum: ₹50\n"
        "• Maximum: ₹10,000\n"
        "• UPI payment accepted\n"
        "• QR expires in 5 minutes\n\n"
        "Click an amount below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_payment_callback(query, context):
    data = query.data
    
    if data == "pay_custom":
        context.user_data["payment_state"] = "custom_amount"
        query.edit_message_text(
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
        query.answer("Invalid amount!", alert=True)

async def generate_payment_qr(query, context, amount):
    user_id = query.from_user.id
    upi_id = MERCHANT_UPI
    
    result = await generate_fampay_qr(upi_id, amount)
    
    if not result.get("success"):
        order_id = f"LOCAL_{user_id}_{int(datetime.utcnow().timestamp())}"
        await db.create_payment(user_id, amount, order_id, upi_id)
        context.user_data["pending_payment"] = order_id
        
        query.edit_message_text(
            f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Amount: ₹{format_price(amount)}\n"
            f"🆔 Order ID: `{order_id}`\n"
            f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Pay to UPI ID and click Verify.",
            reply_markup=get_payment_keyboard(order_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    order_id = result.get("order_id")
    qr_base64 = result.get("qr_image")
    expires_in = result.get("expires_in", 300)
    
    await db.create_payment(user_id, amount, order_id, upi_id)
    context.user_data["pending_payment"] = order_id
    
    query.edit_message_text(
        f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: ₹{format_price(amount)}\n"
        f"🆔 Order ID: `{order_id}`\n"
        f"📱 UPI: `{upi_id}`\n"
        f"⏱️ Expires in: {expires_in // 60} minutes\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Scan QR or pay to UPI ID.\n"
        f"After payment, click 'Verify Payment'.",
        reply_markup=get_payment_keyboard(order_id),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Send QR if available
    if qr_base64:
        try:
            if qr_base64.startswith("data:image"):
                qr_base64 = qr_base64.split(",")[1]
            qr_data = base64.b64decode(qr_base64)
            qr_bio = BytesIO(qr_data)
            qr_bio.seek(0)
            query.message.reply_photo(
                photo=qr_bio,
                caption=f"💳 **Scan to Pay ₹{format_price(amount)}**"
            )
        except Exception as e:
            logger.error(f"QR send error: {e}")

async def verify_payment(query, context):
    user_id = query.from_user.id
    order_id = query.data.split("_")[2]
    
    pending = context.user_data.get("pending_payment")
    if pending != order_id:
        query.answer("⚠️ This is not your pending payment!", alert=True)
        return
    
    payment = await db.get_payment(order_id)
    if not payment:
        query.answer("❌ Payment record not found!", alert=True)
        return
    
    if payment.get("status") == "verified":
        query.answer("✅ This payment is already verified!", alert=True)
        return
    
    result = await verify_payment_api(order_id)
    
    if result.get("verified"):
        await db.verify_payment(order_id)
        amount = result.get("amount", payment.get("amount", 0))
        await db.update_user_balance(user_id, amount)
        balance = await db.get_user_balance(user_id)
        
        transaction_id = result.get("transaction_id", "N/A")
        
        query.edit_message_text(
            f"✅ **Payment Verified Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 ₹{format_price(amount)} added to wallet\n"
            f"💳 New Balance: ₹{format_price(balance)}\n"
            f"🆔 Order ID: `{order_id}`\n"
            f"🔑 Transaction ID: `{transaction_id}`\n━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("pending_payment", None)
    else:
        query.edit_message_text(
            f"❌ **Payment Verification Failed**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Order ID: `{order_id}`\n"
            f"Status: {result.get('message', 'Payment not received')}\n\n"
            f"Please wait a few minutes and try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Retry", callback_data=f"verify_pay_{order_id}")],
                [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )

# ============================================================
# ADMIN FUNCTIONS
# ============================================================
async def show_admin_panel(query, context):
    user_id = query.from_user.id
    admins = await db.get_admins()
    
    if user_id not in admins:
        query.answer("⛔ Unauthorized!", alert=True)
        return
    
    user_count = await db.db.users.count_documents({})
    service_count = await db.db.services.count_documents({"is_active": True})
    total_accounts = await db.db.accounts.count_documents({})
    available_accounts = await db.db.accounts.count_documents({"status": "available"})
    
    stats_text = (
        f"🔰 **Admin Dashboard**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Users: {user_count}\n"
        f"📋 Services: {service_count}\n"
        f"📦 Total Accounts: {total_accounts}\n"
        f"✅ Available: {available_accounts}\n━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    query.edit_message_text(
        stats_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_admin_callback(query, context):
    data = query.data
    user_id = query.from_user.id
    
    admins = await db.get_admins()
    if user_id not in admins:
        query.answer("⛔ Unauthorized!", alert=True)
        return
    
    if data == "admin_services":
        await admin_show_services(query, context)
        return
    
    if data == "admin_new_service":
        context.user_data["admin_state"] = "new_service_name"
        query.edit_message_text(
            "📋 **Create New Service**\n\n"
            "Enter the service name:\n"
            "Example: `Russia TG Fresh`, `USA TG Old`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data.startswith("admin_edit_service_"):
        service_id = data.split("_")[3]
        await admin_edit_service(query, context, service_id)
        return
    
    if data.startswith("admin_add_account_"):
        service_id = data.split("_")[3]
        context.user_data["admin_state"] = "add_account"
        context.user_data["service_id"] = service_id
        query.edit_message_text(
            "📱 **Add Account to Service**\n\n"
            "Send the phone number with country code:\n"
            "Example: `+919876543210`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data.startswith("admin_delete_service_"):
        service_id = data.split("_")[3]
        await admin_delete_service(query, context, service_id)
        return
    
    if data.startswith("admin_set_price_"):
        service_id = data.split("_")[3]
        context.user_data["admin_state"] = "set_service_price"
        context.user_data["service_id"] = service_id
        query.edit_message_text(
            "💰 **Set Service Price**\n\n"
            "Enter the new price for this service:\n"
            "Example: `150`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data.startswith("admin_set_desc_"):
        service_id = data.split("_")[3]
        context.user_data["admin_state"] = "set_service_desc"
        context.user_data["service_id"] = service_id
        query.edit_message_text(
            "📝 **Set Service Description**\n\n"
            "Enter the description for this service:\n"
            "Example: `Fresh Russian Telegram accounts with 2FA`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_add_funds":
        context.user_data["admin_state"] = "add_funds_user"
        query.edit_message_text(
            "💰 **Add Funds**\n\n"
            "Send user ID to credit:\n"
            "Example: `123456789`\n\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_stats":
        await show_admin_panel(query, context)
        return
    
    if data == "admin_announce":
        context.user_data["admin_state"] = "announce"
        context.user_data["announce_messages"] = []
        query.edit_message_text(
            "📢 **Send Announcement**\n\n"
            "Send messages to broadcast.\n"
            "Send `/done` when finished.\n"
            "Send `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == "admin_settings":
        await admin_show_settings(query, context)
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

async def admin_show_services(query, context):
    services = await db.get_all_services()
    
    if not services:
        query.edit_message_text(
            "📋 **No Services Found**\n\n"
            "Create your first service using 'New Service' button.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ New Service", callback_data="admin_new_service")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = []
    for service in services:
        service_id = str(service["_id"])
        available = await db.get_service_available_count(service_id)
        keyboard.append([
            InlineKeyboardButton(
                f"📱 {service['name']} - ₹{format_price(service['price'])} [{available} accounts]",
                callback_data=f"admin_edit_service_{service_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("➕ New Service", callback_data="admin_new_service")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
    
    query.edit_message_text(
        "📋 **Service Management**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Click a service to manage it:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_edit_service(query, context, service_id):
    service = await db.get_service(service_id)
    if not service:
        query.answer("⚠️ Service not found!", alert=True)
        return
    
    available = await db.get_service_available_count(service_id)
    total = service.get("total_accounts", 0)
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data=f"admin_add_account_{service_id}")],
        [InlineKeyboardButton("💰 Set Price", callback_data=f"admin_set_price_{service_id}")],
        [InlineKeyboardButton("📝 Set Description", callback_data=f"admin_set_desc_{service_id}")],
        [InlineKeyboardButton("❌ Delete Service", callback_data=f"admin_delete_service_{service_id}")],
        [InlineKeyboardButton("🔙 Back to Services", callback_data="admin_services")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    
    query.edit_message_text(
        f"📱 **Service: {service['name']}**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Price: ₹{format_price(service['price'])}\n"
        f"📝 Description: {service.get('description', 'No description')}\n"
        f"📦 Total Accounts: {total}\n"
        f"✅ Available: {available}\n"
        f"❌ Sold: {total - available}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Select an action below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_delete_service(query, context, service_id):
    service = await db.get_service(service_id)
    if not service:
        query.answer("⚠️ Service not found!", alert=True)
        return
    
    total = service.get("total_accounts", 0)
    if total > 0:
        query.edit_message_text(
            f"❌ **Cannot Delete Service**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Service: {service['name']}\n"
            f"Total Accounts: {total}\n\n"
            f"Please delete all accounts first before deleting the service.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=f"admin_edit_service_{service_id}")],
                [InlineKeyboardButton("🔙 Services", callback_data="admin_services")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await db.delete_service(service_id)
    query.edit_message_text(
        f"✅ **Service Deleted!**\n\n"
        f"Service '{service['name']}' has been deleted.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Services", callback_data="admin_services")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_show_settings(query, context):
    default_price = await db.get_settings("default_price") or 100
    support_user = await db.get_settings("support_username") or "admin"
    force_channel = await db.get_settings("force_channel") or "Not set"
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Default Price", callback_data="admin_set_default_price"),
            InlineKeyboardButton("📞 Support", callback_data="admin_set_support")
        ],
        [
            InlineKeyboardButton("📢 Force Channel", callback_data="admin_set_force")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ]
    
    query.edit_message_text(
        f"⚙️ **Settings**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Default Price: ₹{format_price(default_price)}\n"
        f"📞 Support: @{support_user}\n"
        f"📢 Force Channel: {force_channel}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_show_users(query, context):
    users = await db.db.users.find({}).sort("created_at", -1).limit(10).to_list(length=10)
    
    user_list = []
    for user in users:
        user_list.append(f"• `{user['user_id']}` - ₹{format_price(user.get('balance', 0))}")
    
    user_text = "\n".join(user_list) if user_list else "No users yet"
    
    query.edit_message_text(
        f"👥 **Recent Users**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{user_text}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {await db.db.users.count_documents({})} users",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_show_admins(query, context):
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
    
    query.edit_message_text(
        f"🔑 **Admins**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{admin_text}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔰 = Permanent Owner",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_show_payments(query, context):
    payments = await db.db.payments.find({"status": "pending"}).sort("created_at", -1).limit(10).to_list(length=10)
    
    if not payments:
        payment_text = "No pending payments"
    else:
        payment_text = ""
        for p in payments:
            payment_text += f"• `{p['order_id']}` - ₹{format_price(p['amount'])} - User: `{p['user_id']}`\n"
    
    query.edit_message_text(
        f"💳 **Pending Payments**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{payment_text}\n━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
# MESSAGE HANDLER
# ============================================================
def message_handler(update: Update, context: CallbackContext):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "/cancel":
        context.user_data.clear()
        update.message.reply_text(
            "❌ **Cancelled**",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check admin state
    if context.user_data.get("admin_state"):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handle_admin_input(update, context, text))
        loop.close()
        return
    
    # Check payment state
    if context.user_data.get("payment_state") == "custom_amount":
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handle_custom_amount(update, context, text))
        loop.close()
        return
    
    update.message.reply_text(
        "Please use the buttons to navigate.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_admin_input(update, context, text):
    state = context.user_data.get("admin_state")
    service_id = context.user_data.get("service_id")
    
    if state == "new_service_name":
        name = text.strip()
        existing = await db.get_service_by_name(name)
        if existing:
            update.message.reply_text(
                "⚠️ **Service already exists!**\n\nPlease use a different name.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        context.user_data["temp_service_name"] = name
        context.user_data["admin_state"] = "new_service_price"
        update.message.reply_text(
            f"📋 **Service: {name}**\n\nEnter the price for this service:\nExample: `150`\n\nSend `/cancel` to cancel.",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if state == "new_service_price":
        try:
            price = float(text)
            name = context.user_data.get("temp_service_name")
            context.user_data["temp_service_price"] = str(price)
            context.user_data["admin_state"] = "new_service_desc"
            update.message.reply_text(
                f"📋 **Service: {name}**\n💰 Price: ₹{format_price(price)}\n\nEnter a description for this service (optional):\nExample: `Fresh Russian Telegram accounts`\n\nSend `skip` to skip description.",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        except ValueError:
            update.message.reply_text("❌ **Invalid Price**\n\nPlease enter a valid number.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "new_service_desc":
        name = context.user_data.get("temp_service_name")
        price = float(context.user_data.get("temp_service_price", 100))
        description = text if text.lower() != "skip" else ""
        
        service = await db.create_service(name, price, description)
        
        update.message.reply_text(
            f"✅ **Service Created Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Name: {name}\n💰 Price: ₹{format_price(price)}\n📝 Description: {description or 'No description'}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Now you can add accounts to this service.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account", callback_data=f"admin_add_account_{str(service['_id'])}")],
                [InlineKeyboardButton("📋 Services", callback_data="admin_services")],
                [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        context.user_data.pop("temp_service_name", None)
        context.user_data.pop("temp_service_price", None)
        return
    
    if state == "add_account":
        phone = text.strip().replace(" ", "")
        if not phone.startswith("+"):
            update.message.reply_text(
                "❌ **Invalid Phone**\n\nPhone must start with `+` and country code.\nExample: `+919876543210`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        existing = await db.db.accounts.find_one({"phone": phone})
        if existing:
            update.message.reply_text(f"⚠️ **Account {phone} already exists!**", parse_mode=ParseMode.MARKDOWN)
            return
        
        await db.add_account_to_service(service_id, phone)
        service = await db.get_service(service_id)
        
        update.message.reply_text(
            f"✅ **Account Added Successfully!**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Phone: `{phone}`\n📋 Service: {service['name']}\n💰 Price: ₹{format_price(service['price'])}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Add more accounts or go back.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Another", callback_data=f"admin_add_account_{service_id}")],
                [InlineKeyboardButton("🔙 Service Details", callback_data=f"admin_edit_service_{service_id}")],
                [InlineKeyboardButton("📋 Services", callback_data="admin_services")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        return
    
    if state == "set_service_price":
        try:
            price = float(text)
            await db.update_service(service_id, {"price": price})
            service = await db.get_service(service_id)
            update.message.reply_text(
                f"✅ **Price Updated!**\n━━━━━━━━━━━━━━━━━━━━━━━\n📋 Service: {service['name']}\n💰 New Price: ₹{format_price(price)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Service Details", callback_data=f"admin_edit_service_{service_id}")],
                    [InlineKeyboardButton("📋 Services", callback_data="admin_services")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("service_id", None)
        except ValueError:
            update.message.reply_text("❌ **Invalid Price**\n\nPlease enter a valid number.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "set_service_desc":
        description = text.strip()
        await db.update_service(service_id, {"description": description})
        service = await db.get_service(service_id)
        update.message.reply_text(
            f"✅ **Description Updated!**\n━━━━━━━━━━━━━━━━━━━━━━━\n📋 Service: {service['name']}\n📝 New Description: {description}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Service Details", callback_data=f"admin_edit_service_{service_id}")],
                [InlineKeyboardButton("📋 Services", callback_data="admin_services")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        context.user_data.pop("service_id", None)
        return
    
    if state == "add_funds_user":
        try:
            target_id = int(text)
            context.user_data["fund_target"] = target_id
            context.user_data["admin_state"] = "add_funds_amount"
            update.message.reply_text(
                f"💰 **Enter Amount**\n\nAmount to credit to `{target_id}`:",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        except ValueError:
            update.message.reply_text("❌ **Invalid User ID**\n\nSend a numeric ID.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "add_funds_amount":
        try:
            amount = float(text)
            target_id = context.user_data.get("fund_target")
            await db.update_user_balance(target_id, amount)
            balance = await db.get_user_balance(target_id)
            update.message.reply_text(
                f"✅ **Funds Added!**\n━━━━━━━━━━━━━━━━━━━━━━━\nUser: `{target_id}`\nAdded: ₹{format_price(amount)}\nNew Balance: ₹{format_price(balance)}",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("fund_target", None)
        except ValueError:
            update.message.reply_text("❌ **Invalid Amount**\n\nSend a valid number.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "announce":
        if text == "/done":
            messages = context.user_data.get("announce_messages", [])
            if not messages:
                update.message.reply_text("❌ No messages to broadcast!", parse_mode=ParseMode.MARKDOWN)
                return
            
            users = await db.db.users.find({}).to_list(length=None)
            success = 0
            progress = update.message.reply_text(f"⏳ Broadcasting to {len(users)} users...", parse_mode=ParseMode.MARKDOWN)
            
            for i, user in enumerate(users):
                try:
                    for msg in messages:
                        context.bot.send_message(user["user_id"], msg.text)
                    success += 1
                    if (i + 1) % 10 == 0:
                        progress.edit_text(f"⏳ Progress: {success}/{len(users)}", parse_mode=ParseMode.MARKDOWN)
                except:
                    continue
            
            progress.edit_text(
                f"✅ **Broadcast Complete!**\n\nSent to: {success}/{len(users)} users",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("announce_messages", None)
        else:
            context.user_data["announce_messages"].append(update.message)
            update.message.reply_text(
                f"📥 **Message Captured**\n\nMessages: {len(context.user_data['announce_messages'])}\nSend `/done` to broadcast.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    if state == "set_default_price":
        try:
            price = float(text)
            await db.update_settings("default_price", price)
            update.message.reply_text(
                f"✅ **Default Price Updated!**\n\nNew default price: ₹{format_price(price)}",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop("admin_state", None)
        except ValueError:
            update.message.reply_text("❌ **Invalid Price**\n\nSend a valid number.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "set_support":
        username = text.strip().replace("@", "")
        await db.update_settings("support_username", username)
        update.message.reply_text(
            f"✅ **Support Updated!**\n\nNew support: @{username}",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.pop("admin_state", None)
        return
    
    if state == "set_force":
        if text.lower() == "none":
            await db.update_settings("force_channel", None)
            update.message.reply_text("✅ **Force Channel Disabled**", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
        else:
            await db.update_settings("force_channel", text)
            update.message.reply_text(f"✅ **Force Channel Set**\n\nChannel: {text}", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop("admin_state", None)
        return
    
    if state == "add_admin":
        try:
            target_id = int(text)
            if target_id == OWNER_ID:
                update.message.reply_text("⚠️ This is the permanent owner!", parse_mode=ParseMode.MARKDOWN)
                return
            await db.add_admin(target_id)
            update.message.reply_text(f"✅ **Admin Added!**\n\nUser `{target_id}` is now an admin.", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
        except ValueError:
            update.message.reply_text("❌ **Invalid User ID**", parse_mode=ParseMode.MARKDOWN)
        return
    
    if state == "remove_admin":
        try:
            target_id = int(text)
            if target_id == OWNER_ID:
                update.message.reply_text("⚠️ Cannot remove permanent owner!", parse_mode=ParseMode.MARKDOWN)
                return
            await db.remove_admin(target_id)
            update.message.reply_text(f"✅ **Admin Removed!**\n\nUser `{target_id}` is no longer an admin.", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
            context.user_data.pop("admin_state", None)
        except ValueError:
            update.message.reply_text("❌ **Invalid User ID**", parse_mode=ParseMode.MARKDOWN)
        return

async def handle_custom_amount(update, context, text):
    try:
        amount = float(text)
        if amount < 50:
            update.message.reply_text("❌ **Minimum amount is ₹50**", parse_mode=ParseMode.MARKDOWN)
            return
        if amount > 10000:
            update.message.reply_text("❌ **Maximum amount is ₹10,000**", parse_mode=ParseMode.MARKDOWN)
            return
        
        context.user_data.pop("payment_state", None)
        
        # Generate payment with QR
        user_id = update.effective_user.id
        upi_id = MERCHANT_UPI
        
        result = await generate_fampay_qr(upi_id, amount)
        
        if not result.get("success"):
            order_id = f"LOCAL_{user_id}_{int(datetime.utcnow().timestamp())}"
            await db.create_payment(user_id, amount, order_id, upi_id)
            context.user_data["pending_payment"] = order_id
            
            update.message.reply_text(
                f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 Amount: ₹{format_price(amount)}\n"
                f"🆔 Order ID: `{order_id}`\n"
                f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Pay to UPI ID and click Verify.",
                reply_markup=get_payment_keyboard(order_id),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        order_id = result.get("order_id")
        qr_base64 = result.get("qr_image")
        
        await db.create_payment(user_id, amount, order_id, upi_id)
        context.user_data["pending_payment"] = order_id
        
        update.message.reply_text(
            f"💳 **Payment Initiated**\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Amount: ₹{format_price(amount)}\n"
            f"🆔 Order ID: `{order_id}`\n"
            f"📱 UPI: `{upi_id}`\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Scan QR or pay to UPI ID.",
            reply_markup=get_payment_keyboard(order_id),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send QR if available
        if qr_base64:
            try:
                if qr_base64.startswith("data:image"):
                    qr_base64 = qr_base64.split(",")[1]
                qr_data = base64.b64decode(qr_base64)
                qr_bio = BytesIO(qr_data)
                qr_bio.seek(0)
                update.message.reply_photo(
                    photo=qr_bio,
                    caption=f"💳 **Scan to Pay ₹{format_price(amount)}**"
                )
            except Exception as e:
                logger.error(f"QR send error: {e}")
                
    except ValueError:
        update.message.reply_text("❌ **Invalid Amount**\n\nSend a valid number.", parse_mode=ParseMode.MARKDOWN)

# ============================================================
# MAIN FUNCTION
# ============================================================
def main():
    # Connect to database
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.connect())
    loop.close()
    print("✅ Database connected successfully!")
    
    # Create updater
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Add handlers
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CallbackQueryHandler(callback_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    
    # Start bot
    logger.info("🤖 Bot started with Service-Based Account Management!")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
