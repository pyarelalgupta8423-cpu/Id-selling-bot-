# utils.py - Helper Functions & Handlers
import os
import asyncio
import aiohttp
import qrcode
from io import BytesIO
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
import logging

logger = logging.getLogger(__name__)

def format_price(amount: float) -> str:
    """Format price with Indian number system"""
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"

def escape_markdown(text: str) -> str:
    """Escape markdown characters"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Get main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("🛒 Buy Account", callback_data="buy_account"),
            InlineKeyboardButton("🛒 Buy Session", callback_data="buy_session")
        ],
        [
            InlineKeyboardButton("👤 My Account", callback_data="my_account"),
            InlineKeyboardButton("💰 Add Balance", callback_data="add_balance")
        ],
        [
            InlineKeyboardButton("📞 Support", callback_data="support"),
            InlineKeyboardButton("ℹ️ About", callback_data="about")
        ]
    ]
    
    if user_id == int(os.getenv("OWNER_ID")):
        keyboard.append([
            InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")
        ])
    
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Get admin panel keyboard with colored buttons"""
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Account", callback_data="admin_add_account"),
            InlineKeyboardButton("➕ Add Session", callback_data="admin_add_session")
        ],
        [
            InlineKeyboardButton("💰 Add Funds", callback_data="admin_add_funds"),
            InlineKeyboardButton("📊 Stats", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("📢 Announce", callback_data="admin_announce"),
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")
        ],
        [
            InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            InlineKeyboardButton("🔑 Admins", callback_data="admin_admins")
        ],
        [
            InlineKeyboardButton("📦 Stock", callback_data="admin_stock"),
            InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Get cancel keyboard"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]])

async def generate_upi_qr(upi_id: str, amount: float, transaction_id: str) -> BytesIO:
    """Generate UPI QR code"""
    upi_string = f"upi://pay?pa={upi_id}&pn=PremiumStore&am={amount}&cu=INR&tn={transaction_id}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_string)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

async def verify_payment_api(transaction_id: str) -> bool:
    """Call UPI payment verification API"""
    api_url = os.getenv("UPI_API_URL")
    api_key = os.getenv("UPI_API_KEY")
    
    if not api_url or not api_key:
        # For testing - auto verify if no API configured
        return True
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                json={"transaction_id": transaction_id},
                headers={"X-API-Key": api_key}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("verified", False)
                return False
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return False

async def check_force_channel(context, user_id: int) -> bool:
    """Check if user has joined force channel"""
    force_channel = os.getenv("FORCE_CHANNEL")
    if not force_channel:
        return True
    
    try:
        member = await context.bot.get_chat_member(int(force_channel), user_id)
        return member.status not in ["left", "kicked"]
    except:
        return False
