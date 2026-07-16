import os
import aiohttp
import base64
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging

logger = logging.getLogger(__name__)

def format_price(amount: float) -> str:
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"

def escape_markdown(text: str) -> str:
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

# ------------------ Keyboards ------------------
def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🛒 Buy Account", callback_data="buy_account")],
        [InlineKeyboardButton("🔐 Buy Session", callback_data="buy_session")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_account")],
        [InlineKeyboardButton("💰 Wallet", callback_data="add_balance")],
        [InlineKeyboardButton("📞 Support", callback_data="support")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    if user_id == int(os.getenv("OWNER_ID")):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Account Services", callback_data="admin_account_services")],
        [InlineKeyboardButton("📋 Session Services", callback_data="admin_session_services")],
        [InlineKeyboardButton("➕ New Account Service", callback_data="admin_new_account_service")],
        [InlineKeyboardButton("➕ New Session Service", callback_data="admin_new_session_service")],
        [InlineKeyboardButton("💰 Add Funds", callback_data="admin_add_funds")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Announce", callback_data="admin_announce")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("🔑 Admins", callback_data="admin_admins")],
        [InlineKeyboardButton("💳 Payments", callback_data="admin_payments")],
        [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]])

def get_payment_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Verify Payment", callback_data=f"verify_pay_{order_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ])

# ------------------ Fampay API ------------------
async def generate_fampay_qr(upi_id: str, amount: float) -> dict:
    api_url = os.getenv("FAMPAY_QR_URL")
    try:
        url = f"{api_url}?upi={upi_id}&amount={amount}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        qr_data = data.get("data", {})
                        return {
                            "success": True,
                            "order_id": qr_data.get("order_id"),
                            "qr_url": qr_data.get("qr_url"),   # <-- important
                            "upi_id": qr_data.get("upi_id"),
                            "amount": qr_data.get("amount"),
                            "expires_at": qr_data.get("expires_at_ist"),
                        }
                    else:
                        return {"success": False, "error": data.get("message", "QR generation failed")}
                else:
                    return {"success": False, "error": f"API Error: {response.status}"}
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return {"success": False, "error": str(e)}

async def verify_fampay_payment(order_id: str) -> dict:
    """Verify payment using Fampay API"""
    api_url = os.getenv("FAMPAY_VERIFY_URL")
    api_key = os.getenv("FAMPAY_API_KEY")
    try:
        url = f"{api_url}?order_id={order_id}&api_key={api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        return {
                            "verified": data.get("verified", False),
                            "amount": data.get("amount", 0),
                            "transaction_id": data.get("transaction_id"),
                            "message": data.get("message", "")
                        }
                    else:
                        return {"verified": False, "message": data.get("message", "Verification failed")}
                else:
                    return {"verified": False, "message": f"API Error: {response.status}"}
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return {"verified": False, "message": str(e)}

# Backward compatibility wrapper (used by bot.py)
async def verify_payment_api(order_id: str) -> dict:
    return await verify_fampay_payment(order_id)

async def check_force_channel(context, user_id: int) -> bool:
    force_channel = os.getenv("FORCE_CHANNEL")
    if not force_channel:
        return True
    try:
        member = await context.bot.get_chat_member(int(force_channel), user_id)
        return member.status not in ["left", "kicked"]
    except:
        return False
