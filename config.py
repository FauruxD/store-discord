import os
from pathlib import Path
from dotenv import load_dotenv

# Muat environment variables dari file .env
load_dotenv()

# Direktori Dasar
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
PRODUCTS_DIR = ASSETS_DIR / "products"

# Pastikan direktori asset & produk tersedia
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

# Token dan Server
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", 0)) if os.getenv("GUILD_ID") else None

# Role & Channel IDs
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0)) if os.getenv("ADMIN_ROLE_ID") else None
CUSTOMER_ROLE_ID = int(os.getenv("CUSTOMER_ROLE_ID", 0)) if os.getenv("CUSTOMER_ROLE_ID") else None
DEPOSIT_LOG_CHANNEL_ID = int(os.getenv("DEPOSIT_LOG_CHANNEL_ID", 0)) if os.getenv("DEPOSIT_LOG_CHANNEL_ID") else None
TRANSACTION_LOG_CHANNEL_ID = int(os.getenv("TRANSACTION_LOG_CHANNEL_ID", 0)) if os.getenv("TRANSACTION_LOG_CHANNEL_ID") else None
TESTIMONIAL_CHANNEL_ID = int(os.getenv("TESTIMONIAL_CHANNEL_ID", 0)) if os.getenv("TESTIMONIAL_CHANNEL_ID") else None
ORDER_CHANNEL_ID = int(os.getenv("ORDER_CHANNEL_ID", 0)) if os.getenv("ORDER_CHANNEL_ID") else None

# Pengaturan QRIS & Rekening
QRIS_IMAGE_URL = os.getenv(
    "QRIS_IMAGE_URL",
    "https://dummyimage.com/600x600/0f172a/38bdf8&text=SCAN+QRIS+UNTUK+DEPOSIT"
)
BANK_TRANSFER_INFO = os.getenv(
    "BANK_TRANSFER_INFO",
    "• Bank BCA: 123-456-7890 (A/N STORE)\n• DANA / GoPay: 0812-3456-7890\n• QRIS: Scan kode di atas"
)

# Integrasi Saweria QRIS Otomatis
SAWERIA_URL = os.getenv("SAWERIA_URL", "https://saweria.co")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")

# Database
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "database/store.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
