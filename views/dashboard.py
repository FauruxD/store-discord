import discord
from discord import ui
import logging
from typing import Optional
import config
from .catalog import ProductSelectView
from .deposit import DepositModal

logger = logging.getLogger("StoreBot.Views.Dashboard")

class SetGrowIDModal(ui.Modal, title="Pengaturan GrowID (Growtopia)"):
    """Modal untuk mendaftarkan atau mengganti GrowID pengguna."""
    growid_input = ui.TextInput(
        label="Masukkan GrowID Akun Anda",
        placeholder="Contoh: FauruxD (Pastikan ejaan tepat)",
        required=True,
        min_length=3,
        max_length=18
    )

    def __init__(self, db_manager, on_success_callback=None):
        super().__init__()
        self.db = db_manager
        self.on_success_callback = on_success_callback

    async def on_submit(self, interaction: discord.Interaction):
        growid = self.growid_input.value.strip()
        success, msg = await self.db.set_growid(interaction.user.id, growid)
        if not success:
            return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

        if self.on_success_callback:
            await self.on_success_callback(interaction, growid)
        else:
            embed = discord.Embed(
                title="✅ GrowID Berhasil Disimpan!",
                description=(
                    f"GrowID Anda telah disetel ke: **`{growid}`**.\n\n"
                    f"Setiap kali Anda mendepositkan World Lock, Diamond Lock, atau Blue Gem Lock ke donation box "
                    f"di world **`{config.GROWTOPIA_WORLD}`**, saldo WL Anda akan otomatis bertambah!"
                ),
                color=discord.Color.green()
            )
            view = WorldDepositView(self.db, growid)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class WorldDepositView(ui.View):
    """View panduan deposit World Growtopia dengan tombol Cek Saldo dan Ganti GrowID."""
    def __init__(self, db_manager, current_growid: str):
        super().__init__(timeout=300)
        self.db = db_manager
        self.current_growid = current_growid

    @ui.button(label="Ganti GrowID", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def change_growid_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SetGrowIDModal(self.db))

    @ui.button(label="Cek Saldo WL", style=discord.ButtonStyle.primary, emoji="💰", row=0)
    async def check_wl_btn(self, interaction: discord.Interaction, button: ui.Button):
        balance_wl = await self.db.get_balance_wl(interaction.user.id)
        dl_part = balance_wl // 100
        wl_part = balance_wl % 100
        if balance_wl >= 100:
            wl_str = f"**{balance_wl:,} WL** ({dl_part} DL {wl_part} WL)"
        else:
            wl_str = f"**{balance_wl:,} WL**"

        await interaction.response.send_message(
            f"🔒 **Saldo World Lock Anda:** {wl_str}\n👤 **GrowID Terdaftar:** `{self.current_growid}`",
            ephemeral=True
        )

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️", row=0)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


class DepositInstructionsView(ui.View):
    """
    Sub-view ephemeral yang muncul saat user menekan tombol 'Deposit Saldo'.
    Menyediakan tombol untuk QRIS Otomatis (Saweria), Deposit World (Growtopia), dan Modal Formulir Manual.
    """
    def __init__(self, db_manager, instruction_interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.db = db_manager
        self.instruction_interaction = instruction_interaction

    @ui.button(label="QRIS Otomatis (Saweria)", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def saweria_qris_btn(self, interaction: discord.Interaction, button: ui.Button):
        saweria_url = config.SAWERIA_URL
        embed = discord.Embed(
            title="⚡ Deposit Otomatis via QRIS Saweria (100% Instan)",
            description=(
                "Top-up saldo otomatis masuk detik itu juga tanpa perlu verifikasi admin:\n\n"
                f"**1️⃣ Buka Halaman Saweria Toko:**\n"
                f"👉 [**Klik di Sini untuk Membuka Saweria**]({saweria_url})\n\n"
                "**2️⃣ Masukkan Nominal & ID Discord:**\n"
                "• Masukkan nominal saldo yang ingin Anda top-up (min. Rp 1.000).\n"
                "• **WAJIB:** Pada kolom **Pesan / Message** di Saweria, masukkan **ID Discord** Anda:\n"
                f"```{interaction.user.id}```\n"
                "*(Klik angka di atas untuk menyalin ID Discord Anda)*\n\n"
                "**3️⃣ Bayar via QRIS:**\n"
                "• Pilih metode pembayaran **QRIS** (bisa scan via DANA, GoPay, OVO, ShopeePay, BCA, dll).\n\n"
                "**4️⃣ Selesai!**\n"
                "Detik itu juga saldo akan otomatis masuk ke akun Discord Anda!"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Pesan ini akan otomatis hilang begitu saldo berhasil masuk.")

        view = ui.View(timeout=600)
        view.add_item(ui.Button(label="Buka Halaman Saweria", url=saweria_url, emoji="🔗"))

        close_btn = ui.Button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️")
        async def close_callback(close_inter: discord.Interaction):
            await close_inter.response.defer(ephemeral=True)
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
            if hasattr(interaction.client, "active_saweria_sessions"):
                interaction.client.active_saweria_sessions.pop(interaction.user.id, None)

        close_btn.callback = close_callback
        view.add_item(close_btn)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Simpan sesi aktif Saweria agar otomatis dihapus saat pembayaran sukses
        if not hasattr(interaction.client, "active_saweria_sessions"):
            interaction.client.active_saweria_sessions = {}

        interaction.client.active_saweria_sessions[interaction.user.id] = {
            "saweria_interaction": interaction,
            "instruction_interaction": self.instruction_interaction,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id
        }

    @ui.button(label="Deposit World (Growtopia)", style=discord.ButtonStyle.primary, emoji="🔒", row=0)
    async def world_deposit_btn(self, interaction: discord.Interaction, button: ui.Button):
        """Handler untuk panduan deposit in-game Growtopia via Donation Box."""
        growid = await self.db.get_growid(interaction.user.id)
        if not growid:
            # User belum mendaftarkan GrowID: tampilkan modal input
            async def after_set(inter: discord.Interaction, new_growid: str):
                embed = self._build_world_deposit_embed(new_growid)
                view = WorldDepositView(self.db, new_growid)
                await inter.response.send_message(embed=embed, view=view, ephemeral=True)

            return await interaction.response.send_modal(
                SetGrowIDModal(self.db, on_success_callback=after_set)
            )

        embed = self._build_world_deposit_embed(growid)
        view = WorldDepositView(self.db, growid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _build_world_deposit_embed(self, growid: str) -> discord.Embed:
        world_name = config.GROWTOPIA_WORLD
        door_id = config.GROWTOPIA_DOOR_ID
        bot_name = config.GROWTOPIA_BOT_NAME

        door_text = f" (Door: `{door_id}`)" if door_id else ""
        desc = (
            "Top-up saldo **World Lock (WL)** otomatis via Donation Box in-game Growtopia:\n\n"
            f"🌍 **Nama World:** **`{world_name}`**{door_text}\n"
            f"🤖 **Bot Penjaga:** **`{bot_name}`**\n"
            f"👤 **GrowID Terdaftar Anda:** **`{growid}`**\n\n"
            "💎 **Rate & Lock yang Diterima:**\n"
            "• **World Lock (WL):** 1 WL = **1 WL**\n"
            "• **Diamond Lock (DL):** 1 DL = **100 WL**\n"
            "• **Blue Gem Lock (BGL):** 1 BGL = **10.000 WL** (100 DL)\n\n"
            "📝 **Cara Deposit:**\n"
            f"1. Masuk ke world **`{world_name}`** di Growtopia.\n"
            f"2. Pastikan Anda menggunakan akun GrowID: **`{growid}`**.\n"
            f"3. Masukkan lock ke dalam **Donation Box** di dekat bot `{bot_name}`.\n"
            "4. Sistem akan mendeteksi donasi secara instan dan saldo WL Anda otomatis bertambah!"
        )
        embed = discord.Embed(
            title="🔒 Panduan Deposit World (Growtopia Donation Box)",
            description=desc,
            color=discord.Color.blue()
        )
        embed.set_footer(text="PENTING: Hanya berdonasi menggunakan akun GrowID terdaftar di atas.")
        return embed

    @ui.button(label="Formulir Manual (Link/Teks)", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def open_modal_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(DepositModal(self.db, instruction_interaction=self.instruction_interaction))

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.instruction_interaction.delete_original_response()
        except Exception:
            pass


class MainDashboardView(ui.View):
    """
    Persistent View Utama untuk Dashboard Toko Discord.
    View ini memiliki timeout=None dan setiap tombol menggunakan custom_id statis
    sehingga tombol tetap berfungsi selamanya meskipun bot direstart.
    """
    def __init__(self, db_manager):
        super().__init__(timeout=None)
        self.db = db_manager

    @ui.button(
        label="Beli Produk",
        style=discord.ButtonStyle.primary,
        emoji="🛒",
        custom_id="store_dashboard_buy_btn"
    )
    async def buy_button(self, interaction: discord.Interaction, button: ui.Button):
        """Handler saat tombol 'Beli Produk' ditekan."""
        products = await self.db.get_available_products()
        if not products:
            return await interaction.response.send_message(
                "📦 **Katalog Kosong!**\nSaat ini belum ada produk digital yang tersedia atau semua stok sedang habis. Silakan cek lagi nanti!",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🛒 Katalog Produk Tersedia",
            description="Pilih produk yang ingin Anda beli dari dropdown menu di bawah ini:",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Pilih produk untuk melihat rincian harga & konfirmasi.")

        view = ProductSelectView(self.db, products)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(
        label="Deposit Saldo",
        style=discord.ButtonStyle.success,
        emoji="💳",
        custom_id="store_dashboard_deposit_btn"
    )
    async def deposit_button(self, interaction: discord.Interaction, button: ui.Button):
        """Handler saat tombol 'Deposit' ditekan: menampilkan opsi QRIS instan, World Deposit, & transfer manual."""
        embed = discord.Embed(
            title="💳 Panduan & Metode Deposit Saldo",
            description=(
                "Pilih salah satu metode deposit saldo di bawah ini:\n\n"
                "⚡ **1. QRIS Otomatis (Saweria) - 100% INSTAN (Direkomendasikan)**\n"
                "• Pembayaran langsung via scan QRIS (GoPay, DANA, OVO, ShopeePay, BCA, dll).\n"
                "• Saldo otomatis masuk dalam beberapa detik tanpa perlu tunggu admin!\n"
                "• Klik tombol **`[⚡ QRIS Otomatis (Saweria)]`** di bawah.\n\n"
                "🔒 **2. Deposit World (Growtopia Donation Box) - 100% INSTAN:**\n"
                f"• Donasi langsung via Donation Box di world **`{config.GROWTOPIA_WORLD}`**.\n"
                "• Menerima World Lock (WL), Diamond Lock (DL), dan Blue Gem Lock (BGL).\n"
                "• Wajib mendaftarkan GrowID Anda terlebih dahulu.\n"
                "• Klik tombol **`[🔒 Deposit World (Growtopia)]`** di bawah.\n\n"
                "🏛️ **3. Transfer Manual (Bank & E-Wallet):**\n"
                f"{config.BANK_TRANSFER_INFO}\n"
                "• Konfirmasi via upload screenshot: ketik `/deposit` di chat.\n"
                "• Konfirmasi via link: klik tombol **`[📝 Formulir Manual]`** di bawah."
            ),
            color=discord.Color.gold()
        )
        if config.QRIS_IMAGE_URL:
            embed.set_image(url=config.QRIS_IMAGE_URL)
        embed.set_footer(text="Deposit Otomatis 24/7 (Saweria & In-Game World Lock)")

        view = DepositInstructionsView(self.db, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(
        label="Cek Balance",
        style=discord.ButtonStyle.secondary,
        emoji="💰",
        custom_id="store_dashboard_balance_btn"
    )
    async def balance_button(self, interaction: discord.Interaction, button: ui.Button):
        """Handler untuk cek saldo pengguna secara privat (ephemeral)."""
        user = await self.db.get_or_create_user(interaction.user.id)
        balance = int(user.get("balance", 0))
        balance_wl = int(user.get("balance_wl", 0))
        growid = user.get("growid")

        if balance_wl >= 100:
            dl_part = balance_wl // 100
            wl_part = balance_wl % 100
            wl_str = f"**{balance_wl:,} WL** ({dl_part} DL {wl_part} WL)"
        else:
            wl_str = f"**{balance_wl:,} WL**"

        embed = discord.Embed(
            title="💰 Informasi Saldo Akun",
            color=discord.Color.teal()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="🇮🇩 Saldo Rupiah (IDR)", value=f"**Rp {balance:,}**", inline=True)
        embed.add_field(name="🔒 Saldo World Lock", value=wl_str, inline=True)
        embed.add_field(
            name="👤 GrowID Terdaftar",
            value=f"`{growid}`" if growid else "*Belum disetel (Ketik `/setgrowid`)*",
            inline=False
        )
        embed.set_footer(text="Gunakan tombol 'Deposit' jika ingin menambah saldo IDR atau World Lock.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @ui.button(
        label="Tutorial",
        style=discord.ButtonStyle.secondary,
        emoji="📖",
        custom_id="store_dashboard_tutorial_btn"
    )
    async def tutorial_button(self, interaction: discord.Interaction, button: ui.Button):
        """Handler untuk menampilkan panduan penggunaan toko."""
        embed = discord.Embed(
            title="📖 Panduan Pembelian Produk Otomatis",
            description=(
                "Selamat datang di **Automated Store**! Berikut alur mudah untuk berbelanja produk digital:\n\n"
                "**1️⃣ Top-up / Deposit Saldo**\n"
                "Tekan tombol **'Deposit Saldo'**, transfer ke QRIS/Bank yang tersedia, lalu isi formulir konfirmasi pembayaran. Tunggu sebentar hingga admin menyetujui tiket Anda.\n\n"
                "**2️⃣ Pilih Produk Digital**\n"
                "Tekan tombol **'Beli Produk'**, lalu pilih item yang diinginkan melalui dropdown menu yang muncul.\n\n"
                "**3️⃣ Konfirmasi Pembelian & Terima File**\n"
                "Klik tombol **'Konfirmasi Pembelian'**. Saldo Anda akan otomatis terpotong dan file produk digital (`.lua`, `.zip`, `.txt`) akan dikirimkan **langsung ke DM Discord Anda** secara instan!\n\n"
                "⚠️ *Catatan: Pastikan opsi 'Direct Messages' di privasi server Anda dalam keadaan aktif agar bot dapat mengirimkan file produk ke DM Anda.*"
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text="Butuh bantuan lebih lanjut? Silakan hubungi staff admin server.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
