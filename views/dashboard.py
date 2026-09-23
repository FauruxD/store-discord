import discord
from discord import ui
import logging
from typing import Optional
import config
from .catalog import ProductSelectView
from .deposit import DepositModal

logger = logging.getLogger("StoreBot.Views.Dashboard")

class DepositInstructionsView(ui.View):
    """
    Sub-view ephemeral yang muncul saat user menekan tombol 'Deposit Saldo'.
    Menyediakan tombol untuk QRIS Otomatis (Saweria) dan Modal Formulir Manual.
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

    @ui.button(label="Formulir Manual (Link/Teks)", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def open_modal_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(DepositModal(self.db, instruction_interaction=self.instruction_interaction))

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️", row=0)
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
        """Handler saat tombol 'Deposit' ditekan: menampilkan opsi QRIS instan & transfer manual."""
        embed = discord.Embed(
            title="💳 Panduan & Metode Deposit Saldo",
            description=(
                "Pilih salah satu metode deposit saldo di bawah ini:\n\n"
                "⚡ **1. QRIS Otomatis (Saweria) - 100% INSTAN (Direkomendasikan)**\n"
                "• Pembayaran langsung via scan QRIS (GoPay, DANA, OVO, ShopeePay, BCA, dll).\n"
                "• Saldo otomatis masuk dalam beberapa detik tanpa perlu tunggu admin!\n"
                "• Klik tombol **`[⚡ QRIS Otomatis (Saweria)]`** di bawah.\n\n"
                "🏛️ **2. Transfer Manual (Bank & E-Wallet):**\n"
                f"{config.BANK_TRANSFER_INFO}\n"
                "• Konfirmasi via upload screenshot: ketik `/deposit` di chat.\n"
                "• Konfirmasi via link: klik tombol **`[📝 Formulir Manual]`** di bawah."
            ),
            color=discord.Color.gold()
        )
        if config.QRIS_IMAGE_URL:
            embed.set_image(url=config.QRIS_IMAGE_URL)
        embed.set_footer(text="Deposit QRIS Otomatis 24/7 • Tanpa Biaya Tambahan")

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
        balance = await self.db.get_balance(interaction.user.id)

        embed = discord.Embed(
            title="💰 Informasi Saldo Akun",
            description=f"Saldo Anda saat ini: **Rp {balance:,}**",
            color=discord.Color.teal()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(
            name="Status Akun",
            value="🟢 Terverifikasi" if balance > 0 else "⚪ Belum Ada Saldo",
            inline=True
        )
        embed.set_footer(text="Gunakan tombol 'Deposit' jika ingin menambah saldo Anda.")

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
