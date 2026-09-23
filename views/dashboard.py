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
    Menyediakan tombol untuk memunculkan Modal Formulir Konfirmasi Deposit.
    """
    def __init__(self, db_manager, instruction_interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.db = db_manager
        self.instruction_interaction = instruction_interaction

    @ui.button(label="Formulir Manual (Link/Teks)", style=discord.ButtonStyle.primary, emoji="📝")
    async def open_modal_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(DepositModal(self.db, instruction_interaction=self.instruction_interaction))

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️")
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
        """Handler saat tombol 'Deposit' ditekan: menampilkan panduan transfer & QRIS statis."""
        embed = discord.Embed(
            title="💳 Panduan & Rekening Deposit",
            description=(
                "Silakan lakukan pembayaran sesuai dengan nominal yang Anda inginkan menggunakan salah satu metode di bawah ini:\n\n"
                f"{config.BANK_TRANSFER_INFO}\n\n"
                "**📸 Cara Konfirmasi Deposit Praktis (Upload Foto Langsung):**\n"
                "Ketik slash command di chat:\n"
                "👉 `/deposit` lalu masukkan nominal & pilih foto screenshot bukti transfer langsung dari galeri HP / file PC Anda!\n"
                "*(100% privat, foto Anda hanya dapat dilihat oleh Admin)*\n\n"
                "**📝 Menggunakan Formulir Manual:**\n"
                "Jika bukti transfer berupa link atau nama rekening pengirim, klik tombol **'Formulir Manual'** di bawah."
            ),
            color=discord.Color.gold()
        )
        if config.QRIS_IMAGE_URL:
            embed.set_image(url=config.QRIS_IMAGE_URL)
        embed.set_footer(text="Verifikasi manual oleh admin biasanya memakan waktu 1-10 menit.")

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
