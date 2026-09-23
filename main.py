import asyncio
import logging
import sys
from pathlib import Path
import discord
from discord.ext import commands

import config
from database import DatabaseManager
from views import MainDashboardView, OwnerAdminPanelView

# Konfigurasi Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("StoreBot.Main")

class DiscordStoreBot(commands.Bot):
    """
    Subclass Discord Bot yang mengelola lifecycle database,
    registrasi Persistent Views, dan sinkronisasi Slash Commands.
    """
    def __init__(self):
        # Intents yang dibutuhkan bot
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

        # Inisialisasi Database Manager
        self.db = DatabaseManager(config.DATABASE_PATH)

    async def setup_hook(self):
        """
        Dijalankan sebelum bot terhubung ke gateway Discord.
        Sangat penting untuk registrasi Persistent Views dan koneksi DB.
        """
        logger.info("Menghubungkan & menginisialisasi database...")
        await self.db.init_db()

        # Seed data produk awal jika database masih kosong
        await self._seed_initial_products()

        # Registrasi PERSISTENT VIEW agar tombol dashboard tetap berfungsi setelah bot restart
        logger.info("Mendaftarkan Persistent Dashboard & Owner Views...")
        self.add_view(MainDashboardView(self.db))
        self.add_view(OwnerAdminPanelView(self.db))

        # Muat modul ekstensi (Cogs)
        cogs_list = ["cogs.admin", "cogs.store", "cogs.webhook"]
        for cog in cogs_list:
            try:
                await self.load_extension(cog)
                logger.info("Cog '%s' berhasil dimuat.", cog)
            except Exception as e:
                logger.error("Gagal memuat Cog '%s': %s", cog, str(e))

        # Sinkronisasi Slash Commands
        if config.GUILD_ID:
            guild_obj = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info("Sinkronisasi %d slash command secara instan ke Guild ID: %d", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            logger.info("Sinkronisasi %d slash command secara global.", len(synced))

    async def _seed_initial_products(self):
        """Menambahkan sample produk demo jika database belum memiliki data."""
        existing = await self.db.get_all_products()
        if not existing:
            sample_products = [
                {
                    "product_id": "script_bypass_v1",
                    "name": "⚡ Premium Optimization Script (.lua)",
                    "description": "Script optimasi performa dan bypass deteksi untuk server game. Include lifetime updates.",
                    "price": 25000,
                    "stock": 50,
                    "file_path": str(config.PRODUCTS_DIR / "premium_script.lua")
                },
                {
                    "product_id": "vip_license_key",
                    "name": "🔑 VIP Access License Key (.txt)",
                    "description": "Serial key aktivasi VIP membership akses fitur premium & support Discord 24/7.",
                    "price": 50000,
                    "stock": 25,
                    "file_path": str(config.PRODUCTS_DIR / "vip_license.txt")
                }
            ]

            for p in sample_products:
                await self.db.add_or_update_product(
                    product_id=p["product_id"],
                    name=p["name"],
                    description=p["description"],
                    price=p["price"],
                    stock=p["stock"],
                    file_path=p["file_path"]
                )
            logger.info("Data produk awal (seed) berhasil ditambahkan ke database.")

    async def on_ready(self):
        """Callback ketika bot berhasil login dan siap menerima interaksi."""
        logger.info("=" * 50)
        logger.info("🤖 Bot Berhasil Online!")
        logger.info("Logged in as: %s (ID: %d)", self.user.name, self.user.id)
        logger.info("Discord.py Version: %s", discord.__version__)
        logger.info("Connected to %d guilds.", len(self.guilds))
        logger.info("=" * 50)

        # Set bot status / activity
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="Automated Store 24/7 | Click to Buy"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)


def main():
    if not config.DISCORD_TOKEN or config.DISCORD_TOKEN == "your_discord_bot_token_here":
        logger.critical(
            "DISCORD_TOKEN belum dikonfigurasi! Silakan isi file '.env' dengan token bot Discord Anda."
        )
        sys.exit(1)

    bot = DiscordStoreBot()
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
