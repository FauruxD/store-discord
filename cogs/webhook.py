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

    def normalize_saweria_amount(self, raw_amount: int) -> int:
        """
        Menghilangkan fee QRIS Saweria (0.7% - 0.8% atau pembulatan unik)
        agar saldo yang masuk ke user tepat berupa angka bulat (contoh: 1008 -> 1000, 10070 -> 10000).
        """
        if raw_amount <= 0:
            return 0

        # Cek jika dibagi faktor fee QRIS (1.007 atau 1.008) menghasilkan angka bulat
        for factor in (1.007, 1.008, 1.0075):
            base = round(raw_amount / factor)
            if 0 < (raw_amount - base) <= max(10, round(raw_amount * 0.015)):
                if base % 100 == 0 or base % 500 == 0 or base % 1000 == 0:
                    return base

        # Cek selisih fee terhadap kelipatan 1000 terdekat
        base_1000 = (raw_amount // 1000) * 1000
        if base_1000 > 0 and 0 < (raw_amount - base_1000) <= max(15, round(base_1000 * 0.01)):
            return base_1000

        # Cek selisih fee terhadap kelipatan 500 terdekat
        base_500 = (raw_amount // 500) * 500
        if base_500 > 0 and 0 < (raw_amount - base_500) <= max(15, round(base_500 * 0.01)):
            return base_500

        return raw_amount

    async def handle_saweria(self, request: web.Request):
        """Handler untuk request POST dari Webhook Saweria."""
        try:
            data = await request.json()
        except Exception as e:
            logger.warning("Request webhook bukan JSON valid: %s", e)
            return web.json_response({"status": "error", "message": "Invalid JSON"}, status=400)

        logger.info("Menerima notifikasi Saweria: %s", data)

        # Ekstrak data Saweria
        raw_amount = int(data.get("amount_raw") or data.get("amount") or 0)
        amount = self.normalize_saweria_amount(raw_amount)
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

            # 1. Ubah pesan panduan QRIS Saweria menjadi Private Message "Deposit Berhasil" di layar user
            session = getattr(self.bot, "active_saweria_sessions", {}).pop(user_id, None)
            if session:
                saweria_inter = session.get("saweria_interaction")
                if saweria_inter:
                    try:
                        success_ephemeral_embed = discord.Embed(
                            title="✅ Deposit Berhasil Masuk (QRIS Saweria)!",
                            description=(
                                f"🎉 Pembayaran via **Saweria QRIS** sebesar **Rp {amount:,}** telah berhasil kami terima!\n\n"
                                f"💰 **Saldo Terbaru Anda:** **Rp {new_balance:,}**\n\n"
                                f"Saldo Anda sudah bertambah. Silakan tekan tombol **'Beli Produk'** di dashboard toko untuk mulai berbelanja!"
                            ),
                            color=discord.Color.green()
                        )
                        success_ephemeral_embed.set_footer(text="100% Otomatis • Hanya Anda yang dapat melihat pesan ini")
                        await saweria_inter.edit_original_response(embed=success_ephemeral_embed, view=None)
                    except Exception as e:
                        logger.debug("Gagal mengupdate pesan saweria ephemeral: %s", e)

                inst_inter = session.get("instruction_interaction")
                if inst_inter:
                    try:
                        await inst_inter.delete_original_response()
                    except Exception as e:
                        logger.debug("Gagal menghapus instruction interaction: %s", e)

            # 2. Kirim notifikasi privat ke DM user
            user = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    embed_dm = discord.Embed(
                        title="⚡ Deposit Otomatis Berhasil (QRIS Saweria)!",
                        description=(
                            f"Halo **{user.name}**!\n"
                            f"Pembayaran deposit sebesar **Rp {amount:,}** telah berhasil kami terima via **Saweria QRIS**.\n\n"
                            f"💰 **Saldo Anda Saat Ini:** **Rp {new_balance:,}**\n"
                            f"Terima kasih telah melakukan top-up. Selamat berbelanja!"
                        ),
                        color=discord.Color.green()
                    )
                    embed_dm.set_footer(text="Automated Instant Deposit • Powered by Saweria")
                    await user.send(embed=embed_dm)
            except Exception as dm_err:
                logger.warning("Gagal mengirim DM konfirmasi deposit ke user %d: %s", user_id, dm_err)

            # 3. Kirim log ke channel log deposit admin jika dikonfigurasi
            if config.DEPOSIT_LOG_CHANNEL_ID:
                ch = self.bot.get_channel(config.DEPOSIT_LOG_CHANNEL_ID)
                if ch:
                    log_embed = discord.Embed(
                        title="⚡ Deposit Otomatis Sukses (Saweria QRIS)",
                        color=discord.Color.green()
                    )
                    nom_display = f"**Rp {amount:,}**"
                    if raw_amount != amount:
                        nom_display += f" *(Dari Saweria: Rp {raw_amount:,})*"
                    log_embed.add_field(name="Nominal Masuk", value=nom_display, inline=True)
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
        target_ch_id = getattr(config, "ORDER_CHANNEL_ID", None) or config.DEPOSIT_LOG_CHANNEL_ID
        if target_ch_id:
            ch = self.bot.get_channel(target_ch_id)
            if ch:
                fail_embed = discord.Embed(
                    title="⚠️ Deposit Gagal Diproses Otomatis",
                    description=(
                        f"Pembayaran sebesar **Rp {amount:,}** dari **{donator_name}** diterima, "
                        f"tetapi **ID Discord tidak ditemukan** pada pesan donasi Saweria.\n\n"
                        f"• **Pesan Donatur:** `{message or '-'}`\n"
                        f"• **ID Transaksi:** `{payment_id or '-'}`\n\n"
                        f"👉 **Bagi Pembeli:** Silakan hubungi admin dengan bukti transfer di atas agar saldo dapat ditambahkan manual via `/add_balance`."
                    ),
                    color=discord.Color.orange()
                )
                fail_embed.set_footer(text="Sistem Store • ID Discord Tidak Ditemukan")
                await ch.send(embed=fail_embed)

        return web.json_response({
            "status": "received",
            "warning": "User ID not found in message",
            "amount": amount
        })

async def setup(bot: commands.Bot):
    await bot.add_cog(WebhookCog(bot))
