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
        self.app.router.add_post("/gt-deposit", self.handle_gt_deposit)
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

    async def handle_gt_deposit(self, request: web.Request) -> web.Response:
        """
        Handler API endpoint untuk menerima notifikasi deposit World Lock / Diamond Lock / BGL
        dari script executor Lucifer Lua v2.86.
        """
        # Verifikasi Token Rahasia (X-GT-Token atau Authorization)
        expected_token = getattr(config, "GROWTOPIA_SECRET_TOKEN", None)
        if expected_token:
            provided_token = request.headers.get("X-GT-Token")
            if not provided_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    provided_token = auth_header[7:].strip()
                else:
                    provided_token = auth_header.strip()

            if provided_token != expected_token:
                logger.warning("Akses ditolak pada /gt-deposit: Token tidak valid.")
                return web.json_response({"error": "Unauthorized: Token tidak valid"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Bad Request: Body harus berupa JSON"}, status=400)

        growid = str(payload.get("growid", "")).strip()
        item_name = str(payload.get("item_name", "")).strip()
        try:
            count = int(payload.get("count", 0))
            amount_wl = int(payload.get("amount_wl", 0))
        except (ValueError, TypeError):
            return web.json_response({"error": "Bad Request: count dan amount_wl harus integer"}, status=400)

        world = str(payload.get("world", config.GROWTOPIA_WORLD or "STOREDEP")).strip()

        if not growid or count <= 0 or amount_wl <= 0:
            return web.json_response({"error": "Bad Request: Parameter growid, count, atau amount_wl tidak valid"}, status=400)

        logger.info(
            "Menerima deposit GT dari GrowID '%s': %d %s (=%d WL) di world '%s'",
            growid, count, item_name, amount_wl, world
        )

        # Cari user berdasarkan GrowID (case-insensitive)
        user = await self.bot.db.get_user_by_growid(growid)

        if not user:
            # Catat sebagai UNCLAIMED agar admin dapat memeriksa dan menambahkannya jika diperlukan
            dep_id = await self.bot.db.record_gt_deposit(
                user_id=None,
                growid=growid,
                item_name=item_name,
                count=count,
                amount_wl=amount_wl,
                world=world,
                status="UNCLAIMED"
            )
            logger.warning("Deposit GT dari GrowID '%s' belum terdaftar pada akun Discord manapun! DepID: %s", growid, dep_id)

            # Kirim peringatan ke Channel Order / Deposit Log
            target_ch_id = getattr(config, "ORDER_CHANNEL_ID", None) or config.DEPOSIT_LOG_CHANNEL_ID
            if target_ch_id:
                ch = self.bot.get_channel(target_ch_id)
                if ch:
                    unclaimed_embed = discord.Embed(
                        title="⚠️ Deposit World Lock Belum Terdaftar",
                        description=(
                            f"Terdeteksi donasi **{count}x {item_name}** (**+{amount_wl:,} WL**) dari GrowID **`{growid}`** di world **`{world}`**, "
                            f"tetapi **GrowID tersebut belum didaftarkan** oleh pengguna manapun di Discord!\n\n"
                            f"👉 **Bagi Pemilik GrowID `{growid}`:**\n"
                            f"Segera jalankan perintah `/setgrowid {growid}` di server ini, lalu hubungi admin beserta ID Deposit: `{dep_id}`."
                        ),
                        color=discord.Color.orange()
                    )
                    unclaimed_embed.set_footer(text="ID Transaksi: " + dep_id)
                    await ch.send(embed=unclaimed_embed)

            return web.json_response({
                "status": "unclaimed",
                "message": f"GrowID '{growid}' belum terdaftar di Discord bot.",
                "deposit_id": dep_id
            }, status=200)

        # User terdaftar! Tambahkan saldo WL
        user_id = user["user_id"]
        new_balance_wl = await self.bot.db.add_balance_wl(user_id, amount_wl)
        dep_id = await self.bot.db.record_gt_deposit(
            user_id=user_id,
            growid=growid,
            item_name=item_name,
            count=count,
            amount_wl=amount_wl,
            world=world,
            status="SUCCESS"
        )

        logger.info("Berhasil menambahkan %d WL ke user %d. Saldo WL sekarang: %d", amount_wl, user_id, new_balance_wl)

        # 1. Kirim Direct Message (DM) ke Pembeli
        try:
            discord_user = await self.bot.fetch_user(user_id)
            if discord_user:
                dm_embed = discord.Embed(
                    title="🎉 Deposit World Lock Berhasil!",
                    description=(
                        f"Halo {discord_user.mention}, deposit in-game Growtopia kamu telah berhasil diverifikasi dan saldo WL otomatis ditambahkan!\n\n"
                        f"📦 **Item Donasi:** `{count}x {item_name}`\n"
                        f"💎 **World Lock Masuk:** **+{amount_wl:,} WL**\n"
                        f"💰 **Total Saldo WL Kamu:** **{new_balance_wl:,} WL**\n"
                        f"🌍 **World:** `{world}`\n"
                        f"👤 **GrowID Terdaftar:** `{growid}`\n"
                        f"🆔 **ID Transaksi:** `{dep_id}`"
                    ),
                    color=discord.Color.green()
                )
                if discord_user.display_avatar:
                    dm_embed.set_thumbnail(url=discord_user.display_avatar.url)
                dm_embed.set_footer(text="100% Otomatis • Lucifer Bot Integration")
                await discord_user.send(embed=dm_embed)
        except Exception as e:
            logger.warning("Gagal mengirim DM notifikasi GT ke user %d: %s", user_id, e)

        # 2. Kirim Notifikasi Publik di Order Channel
        order_ch_id = getattr(config, "ORDER_CHANNEL_ID", None)
        if order_ch_id:
            ch = self.bot.get_channel(order_ch_id)
            if ch:
                pub_embed = discord.Embed(
                    title="⚡ Deposit World Lock Berhasil!",
                    description=(
                        f"Selamat, pembeli <@{user_id}> telah berhasil melakukan deposit in-game via Donation Box!\n\n"
                        f"👤 **GrowID:** `{growid}`\n"
                        f"💎 **Nominal Masuk:** **+{amount_wl:,} World Lock** ({count}x {item_name})\n"
                        f"💰 **Saldo WL Terbaru:** **{new_balance_wl:,} WL**\n"
                        f"🌍 **World:** `{world}`"
                    ),
                    color=discord.Color.green()
                )
                discord_user = self.bot.get_user(user_id)
                if discord_user and discord_user.display_avatar:
                    pub_embed.set_thumbnail(url=discord_user.display_avatar.url)
                pub_embed.set_footer(text="Donation Box Auto-Detector • Instan")
                await ch.send(content=f"<@{user_id}>", embed=pub_embed)

        # 3. Kirim Log Transaksi di Channel Audit/Deposit Log
        log_ch_id = config.DEPOSIT_LOG_CHANNEL_ID
        if log_ch_id:
            ch = self.bot.get_channel(log_ch_id)
            if ch:
                log_embed = discord.Embed(
                    title="📝 [LOG] GT World Lock Deposit Sukses",
                    description=(
                        f"• **User:** <@{user_id}> (`{user_id}`)\n"
                        f"• **GrowID:** `{growid}`\n"
                        f"• **Item:** {count}x {item_name}\n"
                        f"• **WL Masuk:** +{amount_wl:,} WL\n"
                        f"• **Saldo WL:** {new_balance_wl:,} WL\n"
                        f"• **World:** `{world}`\n"
                        f"• **ID Transaksi:** `{dep_id}`"
                    ),
                    color=discord.Color.blue()
                )
                await ch.send(embed=log_embed)

        return web.json_response({
            "status": "success",
            "user_id": user_id,
            "growid": growid,
            "amount_wl": amount_wl,
            "balance_wl": new_balance_wl,
            "deposit_id": dep_id
        })

async def setup(bot: commands.Bot):
    await bot.add_cog(WebhookCog(bot))

