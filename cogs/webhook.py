import logging
import re
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
import config

logger = logging.getLogger("StoreBot.Cogs.Webhook")

class WebhookCog(commands.Cog):
    """
    Cog yang menjalankan server HTTP mini untuk menerima notifikasi Webhook
    dari Saweria saat terjadi pembayaran QRIS / donasi.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.app = web.Application()
        self.app.router.add_get("/", self.health_check)
        self.app.router.add_get("/health", self.health_check)
        self.app.router.add_post("/saweria-webhook", self.handle_saweria)
        self.runner: web.AppRunner = None
        self.site: web.TCPSite = None

    async def cog_load(self):
        """Memulai HTTP Server Webhook saat cog dimuat."""
        port = config.WEBHOOK_PORT
        host = config.WEBHOOK_HOST
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, host, port)
            await self.site.start()
            logger.info("⚡ Webhook Server Saweria aktif di http://%s:%d/saweria-webhook", host, port)
        except Exception as e:
            logger.error("Gagal memulai Webhook Server pada port %d: %s", port, e)

    async def cog_unload(self):
        """Menghentikan HTTP Server saat cog di-unload."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Webhook Server Saweria telah dihentikan.")

    async def health_check(self, request: web.Request):
        """Endpoint status kesehatan untuk memastikan server webhook dapat dijangkau."""
        return web.json_response({
            "status": "online",
            "service": "Store Discord Saweria Webhook",
            "bot_user": str(self.bot.user) if self.bot.user else "Starting"
        })

    async def handle_saweria(self, request: web.Request):
        """Handler untuk request POST dari Webhook Saweria."""
        try:
            data = await request.json()
        except Exception as e:
            logger.warning("Request webhook bukan JSON valid: %s", e)
            return web.json_response({"status": "error", "message": "Invalid JSON"}, status=400)

        logger.info("Menerima notifikasi Saweria: %s", data)

        # Ekstrak data Saweria
        amount = int(data.get("amount_raw") or data.get("amount") or 0)
        donator_name = str(data.get("donator_name") or data.get("donator") or "Anonim").strip()
        message = str(data.get("message") or "").strip()
        payment_id = str(data.get("id") or "")

        if amount <= 0:
            return web.json_response({"status": "ignored", "message": "Amount is 0 or invalid"})

        # Cari Discord User ID dari pesan / nama donatur
        user_id = None

        # 1. Regex cari pola eksplisit seperti: "id 123456...", "discord: 123456...", "id: 123456..."
        explicit_match = (
            re.search(r'(?:id|discord|user|member)[\s:=#]+(\d{6,21})\b', message, re.IGNORECASE)
            or re.search(r'(?:id|discord|user|member)[\s:=#]+(\d{6,21})\b', donator_name, re.IGNORECASE)
        )
        if explicit_match:
            user_id = int(explicit_match.group(1))

        # 2. Regex cari standalone 17-21 digit angka (Standard Discord Snowflake ID)
        if not user_id:
            snowflake_match = re.search(r'\b\d{17,21}\b', message) or re.search(r'\b\d{17,21}\b', donator_name)
            if snowflake_match:
                user_id = int(snowflake_match.group(0))

        # 2. Cek jika pesan berisi kode tiket DEP-XXXXXXXX
        if not user_id:
            dep_match = re.search(r'\bDEP-[A-F0-9]{8}\b', message, re.IGNORECASE)
            if dep_match:
                dep_id = dep_match.group(0).upper()
                dep_data = await self.bot.db.get_deposit_request(dep_id)
                if dep_data:
                    user_id = dep_data["user_id"]
                    if dep_data["status"] == "PENDING":
                        # Auto-approve tiket deposit manual jika ada
                        await self.bot.db.process_deposit(dep_id, approved=True, reviewed_by=self.bot.user.id)

        # JIKA USER DITEMUKAN: Tambahkan saldo otomatis!
        if user_id:
            new_balance = await self.bot.db.add_balance(user_id, amount)
            logger.info("Saldo Rp %d berhasil ditambahkan otomatis ke user %d via Saweria.", amount, user_id)

            # Kirim notifikasi DM ke user
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    embed = discord.Embed(
                        title="⚡ Deposit Otomatis Berhasil (QRIS Saweria)!",
                        description=(
                            f"Halo **{user.name}**!\n"
                            f"Pembayaran deposit sebesar **Rp {amount:,}** telah berhasil kami terima via **Saweria QRIS**.\n\n"
                            f"💰 **Saldo Anda Saat Ini:** **Rp {new_balance:,}**\n"
                            f"Terima kasih telah melakukan top-up. Selamat berbelanja!"
                        ),
                        color=discord.Color.green()
                    )
                    embed.set_footer(text="Automated Instant Deposit • Powered by Saweria")
                    await user.send(embed=embed)
            except Exception as dm_err:
                logger.warning("Gagal mengirim DM konfirmasi deposit ke user %d: %s", user_id, dm_err)

            # Kirim log ke channel log deposit jika dikonfigurasi
            if config.DEPOSIT_LOG_CHANNEL_ID:
                ch = self.bot.get_channel(config.DEPOSIT_LOG_CHANNEL_ID)
                if ch:
                    log_embed = discord.Embed(
                        title="⚡ Deposit Otomatis Sukses (Saweria QRIS)",
                        color=discord.Color.green()
                    )
                    log_embed.add_field(name="Pelanggan", value=f"<@{user_id}> (`{user_id}`)", inline=True)
                    log_embed.add_field(name="Nominal Masuk", value=f"**Rp {amount:,}**", inline=True)
                    log_embed.add_field(name="Saldo Baru", value=f"Rp {new_balance:,}", inline=True)
                    log_embed.add_field(name="Nama Donatur", value=donator_name, inline=True)
                    log_embed.add_field(name="Pesan", value=message or "-", inline=False)
                    if payment_id:
                        log_embed.add_field(name="ID Transaksi Saweria", value=f"`{payment_id}`", inline=False)
                    log_embed.set_footer(text="100% Otomatis • Tanpa Verifikasi Manual")
                    await ch.send(embed=log_embed)

            return web.json_response({
                "status": "success",
                "user_id": user_id,
                "amount": amount,
                "balance": new_balance
            })

        # JIKA USER TIDAK DITEMUKAN (User lupa menuliskan Discord ID di pesan Saweria)
        logger.warning(
            "Saweria webhook masuk Rp %d dari '%s' tanpa Discord User ID! Pesan: '%s'",
            amount, donator_name, message
        )
        if config.DEPOSIT_LOG_CHANNEL_ID:
            ch = self.bot.get_channel(config.DEPOSIT_LOG_CHANNEL_ID)
            if ch:
                alert_embed = discord.Embed(
                    title="⚠️ Dana Saweria Masuk Tanpa Discord ID!",
                    description=(
                        f"Terdapat dana masuk sebesar **Rp {amount:,}** dari **{donator_name}**, "
                        f"tetapi sistem tidak menemukan Discord User ID pada kolom pesan.\n\n"
                        f"• **Pesan Donasi:** `{message}`\n"
                        f"• **ID Transaksi:** `{payment_id}`\n\n"
                        f"👉 *Admin dapat mencocokkan konfirmasi pembeli dan menambahkan saldo manual via `/add_balance`.*"
                    ),
                    color=discord.Color.orange()
                )
                await ch.send(embed=alert_embed)

        return web.json_response({
            "status": "received",
            "warning": "User ID not found in message",
            "amount": amount
        })

async def setup(bot: commands.Bot):
    await bot.add_cog(WebhookCog(bot))
