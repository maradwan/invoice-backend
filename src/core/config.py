import os
import logging
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
DB_NAME = os.getenv("DB_NAME", "image_db")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Collections
collection_images = db[os.getenv("COLLECTION_IMAGES", "images")]
collection_users = db[os.getenv("COLLECTION_USERS", "users")]

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
