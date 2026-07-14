# database.py - MongoDB Connection & Operations
import os
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import uuid
from typing import Optional, Dict, List, Any

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_id_store")

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        
    async def connect(self):
        if not self.client:
            self.client = AsyncIOMotorClient(MONGODB_URI)
            self.db = self.client[DATABASE_NAME]
            
            # Create indexes
            await self.db.users.create_index("user_id", unique=True)
            await self.db.services.create_index("name", unique=True)
            await self.db.accounts.create_index("phone", unique=True)
            await self.db.accounts.create_index("service_id")
            await self.db.accounts.create_index("status")
            await self.db.payments.create_index("order_id", unique=True)
            await self.db.sessions.create_index("session_id", unique=True)
    
    # ============================================================
    # USER OPERATIONS
    # ============================================================
    async def get_user(self, user_id: int) -> Optional[Dict]:
        return await self.db.users.find_one({"user_id": user_id})
    
    async def create_user(self, user_id: int, username: str = "", full_name: str = "") -> Dict:
        user = {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "balance": 0.0,
            "is_owner": user_id == int(os.getenv("OWNER_ID")),
            "is_banned": False,
            "joined_channel": False,
            "total_purchases": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await self.db.users.insert_one(user)
        return user
    
    async def update_user_balance(self, user_id: int, amount: float) -> bool:
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": amount}, "$set": {"updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def get_user_balance(self, user_id: int) -> float:
        user = await self.get_user(user_id)
        return user.get("balance", 0.0) if user else 0.0
    
    # ============================================================
    # SERVICE OPERATIONS
    # ============================================================
    async def create_service(self, name: str, price: float, description: str = "") -> Dict:
        """Create a new service"""
        service = {
            "name": name,
            "price": price,
            "description": description,
            "is_active": True,
            "total_accounts": 0,
            "available_accounts": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        result = await self.db.services.insert_one(service)
        service["_id"] = str(result.inserted_id)
        return service
    
    async def get_all_services(self) -> List[Dict]:
        """Get all active services"""
        cursor = self.db.services.find({"is_active": True}).sort("name", 1)
        return await cursor.to_list(length=None)
    
    async def get_service(self, service_id: str) -> Optional[Dict]:
        """Get service by ID"""
        return await self.db.services.find_one({"_id": service_id})
    
    async def get_service_by_name(self, name: str) -> Optional[Dict]:
        """Get service by name"""
        return await self.db.services.find_one({"name": name})
    
    async def update_service(self, service_id: str, data: Dict) -> bool:
        """Update service details"""
        data["updated_at"] = datetime.utcnow()
        result = await self.db.services.update_one(
            {"_id": service_id},
            {"$set": data}
        )
        return result.modified_count > 0
    
    async def delete_service(self, service_id: str) -> bool:
        """Delete service (soft delete)"""
        result = await self.db.services.update_one(
            {"_id": service_id},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def get_service_accounts_count(self, service_id: str) -> int:
        """Get available accounts count for a service"""
        return await self.db.accounts.count_documents({
            "service_id": service_id,
            "status": "available"
        })
    
    # ============================================================
    # ACCOUNT OPERATIONS (Under Services)
    # ============================================================
    async def add_account_to_service(self, service_id: str, phone: str, session_string: str = None) -> Dict:
        """Add account to a service"""
        account = {
            "service_id": service_id,
            "phone": phone,
            "session_string": session_string,
            "status": "available",  # available, sold, pending
            "two_fa": False,
            "sold_to": None,
            "sold_at": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        result = await self.db.accounts.insert_one(account)
        account["_id"] = str(result.inserted_id)
        
        # Update service count
        await self.db.services.update_one(
            {"_id": service_id},
            {"$inc": {"total_accounts": 1, "available_accounts": 1}}
        )
        return account
    
    async def get_available_accounts(self, service_id: str, limit: int = 10) -> List[Dict]:
        """Get available accounts for a service"""
        cursor = self.db.accounts.find({
            "service_id": service_id,
            "status": "available"
        }).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def get_service_available_count(self, service_id: str) -> int:
        """Get available account count for service"""
        return await self.db.accounts.count_documents({
            "service_id": service_id,
            "status": "available"
        })
    
    async def purchase_account_from_service(self, service_id: str, user_id: int, price: float) -> Optional[Dict]:
        """Purchase an account from a service"""
        # Find available account
        account = await self.db.accounts.find_one_and_update(
            {
                "service_id": service_id,
                "status": "available"
            },
            {
                "$set": {
                    "status": "sold",
                    "sold_to": user_id,
                    "sold_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            },
            return_document=True
        )
        
        if not account:
            return None
        
        # Deduct user balance
        user_result = await self.db.users.update_one(
            {"user_id": user_id, "balance": {"$gte": price}},
            {"$inc": {"balance": -price, "total_purchases": 1}}
        )
        
        if user_result.modified_count == 0:
            # Revert account status
            await self.db.accounts.update_one(
                {"_id": account["_id"]},
                {"$set": {"status": "available", "sold_to": None, "sold_at": None}}
            )
            return None
        
        # Update service available count
        await self.db.services.update_one(
            {"_id": service_id},
            {"$inc": {"available_accounts": -1}}
        )
        
        return account
    
    # ============================================================
    # PAYMENT OPERATIONS
    # ============================================================
    async def create_payment(self, user_id: int, amount: float, order_id: str, upi_id: str) -> Dict:
        payment = {
            "user_id": user_id,
            "amount": amount,
            "upi_id": upi_id,
            "order_id": order_id,
            "status": "pending",
            "verified": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await self.db.payments.insert_one(payment)
        return payment
    
    async def get_payment(self, order_id: str) -> Optional[Dict]:
        return await self.db.payments.find_one({"order_id": order_id})
    
    async def verify_payment(self, order_id: str) -> bool:
        result = await self.db.payments.update_one(
            {"order_id": order_id},
            {"$set": {"status": "verified", "verified_at": datetime.utcnow(), "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    # ============================================================
    # ADMIN OPERATIONS
    # ============================================================
    async def get_admins(self) -> List[int]:
        cursor = self.db.users.find({"is_owner": True})
        admins = await cursor.to_list(length=None)
        return [admin["user_id"] for admin in admins]
    
    async def add_admin(self, user_id: int) -> bool:
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_owner": True, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def remove_admin(self, user_id: int) -> bool:
        if user_id == int(os.getenv("OWNER_ID")):
            return False
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_owner": False, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def update_settings(self, key: str, value: Any) -> bool:
        result = await self.db.settings.update_one(
            {"key": key},
            {"$set": {"value": value, "updated_at": datetime.utcnow()}},
            upsert=True
        )
        return True
    
    async def get_settings(self, key: str) -> Optional[Any]:
        setting = await self.db.settings.find_one({"key": key})
        return setting.get("value") if setting else None

db = Database()            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "balance": 0.0,
            "is_owner": user_id == int(os.getenv("OWNER_ID")),
            "is_banned": False,
            "joined_channel": False,
            "total_purchases": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await self.db.users.insert_one(user)
        return user
    
    async def update_user_balance(self, user_id: int, amount: float) -> bool:
        """Update user balance"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": amount}, "$set": {"updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def get_user_balance(self, user_id: int) -> float:
        """Get user balance"""
        user = await self.get_user(user_id)
        return user.get("balance", 0.0) if user else 0.0
    
    async def add_account(self, phone: str, price: float, session_string: Optional[str] = None) -> Dict:
        """Add new account"""
        account = {
            "phone": phone,
            "price": price,
            "status": "available",
            "session_string": session_string,
            "two_fa": False,
            "sold_to": None,
            "sold_at": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        result = await self.db.accounts.insert_one(account)
        account["_id"] = str(result.inserted_id)
        return account
    
    async def get_available_accounts(self, limit: int = 10, offset: int = 0) -> List[Dict]:
        """Get available accounts"""
        cursor = self.db.accounts.find({"status": "available"}).skip(offset).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def get_account_count(self) -> int:
        """Get total available accounts count"""
        return await self.db.accounts.count_documents({"status": "available"})
    
    async def purchase_account(self, account_id: str, user_id: int, price: float) -> bool:
        """Purchase an account"""
        # Update account
        account_result = await self.db.accounts.update_one(
            {"_id": account_id, "status": "available"},
            {"$set": {"status": "sold", "sold_to": user_id, "sold_at": datetime.utcnow()}}
        )
        
        if account_result.modified_count == 0:
            return False
        
        # Deduct user balance
        user_result = await self.db.users.update_one(
            {"user_id": user_id, "balance": {"$gte": price}},
            {"$inc": {"balance": -price, "total_purchases": 1}}
        )
        
        return user_result.modified_count > 0
    
    async def create_payment(self, user_id: int, amount: float, upi_id: str) -> Dict:
        """Create a payment record"""
        transaction_id = str(uuid.uuid4())[:8].upper()
        payment = {
            "user_id": user_id,
            "amount": amount,
            "upi_id": upi_id,
            "transaction_id": transaction_id,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await self.db.payments.insert_one(payment)
        return payment
    
    async def verify_payment(self, transaction_id: str) -> bool:
        """Verify payment"""
        payment = await self.db.payments.find_one({"transaction_id": transaction_id})
        if not payment:
            return False
        
        await self.db.payments.update_one(
            {"transaction_id": transaction_id},
            {"$set": {"status": "verified", "updated_at": datetime.utcnow()}}
        )
        return True
    
    async def get_admins(self) -> List[int]:
        """Get all admin user IDs"""
        cursor = self.db.users.find({"is_owner": True})
        admins = await cursor.to_list(length=None)
        return [admin["user_id"] for admin in admins]
    
    async def add_admin(self, user_id: int) -> bool:
        """Add new admin"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_owner": True, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def remove_admin(self, user_id: int) -> bool:
        """Remove admin (can't remove permanent owner)"""
        if user_id == int(os.getenv("OWNER_ID")):
            return False
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_owner": False, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def update_settings(self, key: str, value: Any) -> bool:
        """Update settings"""
        result = await self.db.settings.update_one(
            {"key": key},
            {"$set": {"value": value, "updated_at": datetime.utcnow()}},
            upsert=True
        )
        return True
    
    async def get_settings(self, key: str) -> Optional[Any]:
        """Get settings"""
        setting = await self.db.settings.find_one({"key": key})
        return setting.get("value") if setting else None

db = Database()
