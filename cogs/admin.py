import discord
from discord.ext import commands
from discord import app_commands
import os
import logging
from pathlib import Path
from typing import Optional
import config
from views.dashboard import MainDashboardView
from views.admin_panel import OwnerAdminPanelView

logger = logging.getLogger("StoreBot.Cogs.Admin")

class AdminCog(commands.Cog):
    """
    Kumpulan Slash Commands khusus Admin untuk manajemen toko, setup dashboard,
    penambahan produk digital, dan penyesuaian saldo manual.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_admin_or_has_role(self, interaction: discord.Interaction) -> bool:
        """Helper untuk memeriksa izin admin atau role staff."""
        if interaction.user.guild_permissions.administrator:
            return True
        if config.ADMIN_ROLE_ID and any(r.id == config.ADMIN_ROLE_ID for r in interaction.user.roles):
            return True
        return False

    @app_commands.command(
        name="setup_store",
        description="[Admin] Memunculkan panel dashboard utama toko dengan Persistent Buttons."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_store(self, interaction: discord.Interaction):
        """Mengirimkan Embed Utama Toko dan menyematkan Persistent View."""
        embed = discord.Embed(
            title="🏪 AUTOMATED DIGITAL STORE",
            description=(
                "Selamat datang di store resmi server kami!\n\n"
                "Semua transaksi di sini berjalan **100% otomatis 24/7**.\n"
                "Produk langsung dikirimkan ke DM Anda detik itu juga setelah pembayaran berhasil!\n\n"
                "**Menu Cepat:**\n"
                "• 🛒 **Beli Produk** - Buka katalog dan checkout\n"
                "• 💳 **Deposit Saldo** - Panduan & formulir top-up saldo akun\n"
                "• 💰 **Cek Balance** - Periksa sisa saldo akun Anda\n"
                "• 📖 **Tutorial** - Panduan langkah demi langkah penggunaan"
            ),
            color=discord.Color.brand_red()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_image(url="https://dummyimage.com/1200x400/1e293b/38bdf8&text=AUTOMATED+STORE+DASHBOARD")
        embed.set_footer(text="Sistem Store Aman & Terpercaya • Powered by discord.py")

        # Pasang Persistent View
        view = MainDashboardView(self.bot.db)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Panel dashboard toko berhasil dipasang di channel ini!", ephemeral=True)

    @app_commands.command(
        name="add_product",
        description="[Admin] Tambahkan atau perbarui produk digital ke katalog toko."
    )
    @app_commands.describe(
        product_id="ID unik produk (tanpa spasi, contoh: script_v1)",
        name="Nama produk",
        description="Deskripsi singkat produk",
        price="Harga produk dalam Rupiah",
        stock="Jumlah stok yang tersedia",
        file="[Paling Mudah] Upload file produk langsung di Discord (.lua, .zip, .txt)",
        file_name="[Opsional] Nama file yang sudah ada di folder assets/products/ di server"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_product(
        self,
        interaction: discord.Interaction,
        product_id: str,
        name: str,
        description: str,
        price: int,
        stock: int,
        file: Optional[discord.Attachment] = None,
        file_name: Optional[str] = None
    ):
        """Mendaftarkan produk digital ke database dengan opsi upload file langsung."""
        if price < 0 or stock < 0:
            return await interaction.response.send_message("❌ Harga dan stok tidak boleh negatif!", ephemeral=True)

        destination_path = None

        # Jika admin mengunggah file attachment langsung di Discord
        if file is not None:
            config.PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
            destination_path = config.PRODUCTS_DIR / file.filename
            try:
                await file.save(destination_path)
                logger.info("File produk '%s' berhasil diunggah & disimpan ke %s", file.filename, destination_path)
            except Exception as e:
                logger.error("Gagal menyimpan file attachment: %s", str(e))
                return await interaction.response.send_message(
                    f"❌ Gagal menyimpan file produk yang diunggah: {str(e)}",
                    ephemeral=True
                )
        elif file_name:
            destination_path = config.PRODUCTS_DIR / file_name
            if not destination_path.exists():
                return await interaction.response.send_message(
                    f"⚠️ File `{file_name}` tidak ditemukan di folder `{config.PRODUCTS_DIR}`!\n"
                    f"Silakan gunakan parameter `file` untuk mengunggah file langsung dari Discord.",
                    ephemeral=True
                )
        else:
            return await interaction.response.send_message(
                "⚠️ Harap lampirkan file produk melalui parameter `file` (upload langsung) atau sebutkan `file_name`!",
                ephemeral=True
            )

        await self.bot.db.add_or_update_product(
            product_id=product_id.lower().strip(),
            name=name,
            description=description,
            price=price,
            stock=stock,
            file_path=str(destination_path)
        )

        embed = discord.Embed(
            title="✅ Produk Berhasil Disimpan!",
            color=discord.Color.green()
        )
        embed.add_field(name="Product ID", value=f"`{product_id.lower().strip()}`", inline=True)
        embed.add_field(name="Nama", value=name, inline=True)
        embed.add_field(name="Harga", value=f"Rp {price:,}", inline=True)
        embed.add_field(name="Stok", value=f"{stock} unit", inline=True)
        embed.add_field(name="File Produk", value=f"`{destination_path.name}`", inline=False)
        embed.set_footer(text="Produk sekarang aktif dan siap dibeli di katalog!")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set_stock",
        description="[Admin] Perbarui jumlah stok produk secara cepat tanpa re-upload."
    )
    @app_commands.describe(
        product_id="ID produk yang ingin diubah stoknya",
        stock="Jumlah stok baru"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_stock(self, interaction: discord.Interaction, product_id: str, stock: int):
        """Memperbarui stok produk."""
        if stock < 0:
            return await interaction.response.send_message("❌ Stok tidak boleh negatif!", ephemeral=True)

        success = await self.bot.db.update_stock(product_id.lower().strip(), stock)
        if success:
            await interaction.response.send_message(
                f"✅ Stok produk `{product_id}` berhasil diperbarui menjadi **{stock}** unit.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Produk dengan ID `{product_id}` tidak ditemukan.",
                ephemeral=True
            )

    @app_commands.command(
        name="delete_product",
        description="[Admin] Hapus produk dari katalog toko."
    )
    @app_commands.describe(product_id="ID produk yang ingin dihapus")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_product(self, interaction: discord.Interaction, product_id: str):
        """Menghapus produk dari katalog."""
        success = await self.bot.db.delete_product(product_id.lower().strip())
        if success:
            await interaction.response.send_message(
                f"✅ Produk dengan ID `{product_id}` berhasil dihapus dari katalog.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Produk dengan ID `{product_id}` tidak ditemukan di database.",
                ephemeral=True
            )

    @app_commands.command(
        name="add_balance",
        description="[Admin] Tambahkan atau kurangi saldo user secara langsung."
    )
    @app_commands.describe(
        target_user="User yang ingin diubah saldonya",
        amount="Nominal yang ingin ditambahkan (gunakan tanda minus '-' untuk mengurangi)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_balance(
        self,
        interaction: discord.Interaction,
        target_user: discord.User,
        amount: int
    ):
        """Memodifikasi saldo pengguna."""
        new_balance = await self.bot.db.add_balance(target_user.id, amount)

        action_text = "ditambahkan ke" if amount >= 0 else "dikurangi dari"
        embed = discord.Embed(
            title="💰 Update Saldo Pengguna",
            description=(
                f"Saldo sebesar **Rp {abs(amount):,}** telah berhasil {action_text} akun {target_user.mention}.\n"
                f"Sisa saldo {target_user.name} saat ini: **Rp {new_balance:,}**"
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="list_products",
        description="[Admin] Menampilkan semua produk di database beserta status stok & filenya."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_products(self, interaction: discord.Interaction):
        """Melihat inventaris lengkap produk."""
        products = await self.bot.db.get_all_products()
        if not products:
            return await interaction.response.send_message("Belum ada produk di database.", ephemeral=True)

        embed = discord.Embed(
            title="📋 Daftar Semua Produk Digital",
            color=discord.Color.blue()
        )

        for p in products:
            file_exists = Path(p["file_path"]).exists()
            file_status = "🟢 File Ready" if file_exists else "🔴 File Hilang!"
            embed.add_field(
                name=f"{p['name']} (`{p['product_id']}`)",
                value=f"• Harga: Rp {p['price']:,}\n• Stok: {p['stock']}\n• File: `{Path(p['file_path']).name}` ({file_status})",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="setup_owner_panel",
        description="[Owner/Admin] Pasang panel khusus kontrol CRUD produk di channel ini."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_owner_panel(self, interaction: discord.Interaction):
        """Memasang panel kontrol khusus Owner/Admin di channel khusus."""
        embed = discord.Embed(
            title="🛠️ OWNER & ADMIN CONTROL PANEL",
            description=(
                "Panel kontrol manajemen inventaris & produk digital store.\n"
                "Semua perubahan di sini akan langsung berdampak ke katalog pembeli secara realtime.\n\n"
                "**Fitur & Aksi CRUD:**\n"
                "• 📋 **Daftar Produk (Read)** - Pantau semua produk, stok, dan kesiapan file\n"
                "• ➕ **Tambah Produk (Create)** - Panduan & tambah produk via `/add_product`\n"
                "• ✏️ **Edit / Restock (Update)** - Ubah harga atau tambah stok via menu dropdown\n"
                "• 🗑️ **Hapus Produk (Delete)** - Hapus produk yang tidak lagi dijual"
            ),
            color=discord.Color.dark_grey()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text="Panel Khusus Owner • Hanya dapat diakses di channel ini oleh Staff")

        view = OwnerAdminPanelView(self.bot.db, target_channel_id=interaction.channel_id)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"✅ Panel khusus Owner berhasil dipasang di channel {interaction.channel.mention}!",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
