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
    @app_commands.choices(
        product_type=[
            app_commands.Choice(name="📁 File Digital (.lua, .zip, dll)", value="FILE"),
            app_commands.Choice(name="👤 Akun Digital / Combo List (.txt)", value="ACCOUNT"),
        ]
    )
    @app_commands.describe(
        product_id="ID unik produk (tanpa spasi, contoh: netflix_acc)",
        name="Nama produk",
        description="Deskripsi singkat produk",
        price="Harga satuan produk dalam Rupiah",
        stock="Jumlah stok (diabaikan/otomatis dihitung jika mengupload list akun)",
        product_type="Pilih tipe produk: File statis biasa atau Akun per baris",
        file="Upload file produk (.lua, .zip) atau file .txt list akun awal",
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
        stock: int = 0,
        product_type: str = "FILE",
        file: Optional[discord.Attachment] = None,
        file_name: Optional[str] = None
    ):
        """Mendaftarkan produk digital ke database dengan dukungan tipe File dan Akun."""
        if price < 0 or stock < 0:
            return await interaction.response.send_message("❌ Harga dan stok tidak boleh negatif!", ephemeral=True)

        destination_path = None
        account_lines = []

        # Jika admin mengunggah file attachment langsung di Discord
        if file is not None:
            config.PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
            destination_path = config.PRODUCTS_DIR / file.filename
            try:
                # Jika tipe akun, baca isinya untuk initial stock
                if product_type == "ACCOUNT":
                    raw_bytes = await file.read()
                    text_content = raw_bytes.decode("utf-8", errors="ignore")
                    account_lines = text_content.splitlines()

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
            if product_type == "ACCOUNT":
                try:
                    with open(destination_path, "r", encoding="utf-8", errors="ignore") as f:
                        account_lines = f.read().splitlines()
                except Exception:
                    pass
        else:
            if product_type == "ACCOUNT":
                # Produk akun bisa dibuat tanpa file fisik awal (stok awal 0)
                dummy_file = config.PRODUCTS_DIR / f"{product_id}.txt"
                dummy_file.touch(exist_ok=True)
                destination_path = dummy_file
            else:
                return await interaction.response.send_message(
                    "⚠️ Harap lampirkan file produk melalui parameter `file` (upload langsung) atau sebutkan `file_name`!",
                    ephemeral=True
                )

        clean_prod_id = product_id.lower().strip()
        await self.bot.db.add_or_update_product(
            product_id=clean_prod_id,
            name=name,
            description=description,
            price=price,
            stock=stock,
            file_path=str(destination_path),
            product_type=product_type
        )

        added_accounts = 0
        if product_type == "ACCOUNT" and account_lines:
            added_accounts = await self.bot.db.add_account_stock(clean_prod_id, account_lines)

        updated_prod = await self.bot.db.get_product(clean_prod_id)
        final_stock = updated_prod["stock"] if updated_prod else stock

        embed = discord.Embed(
            title="✅ Produk Berhasil Disimpan!",
            color=discord.Color.green()
        )
        embed.add_field(name="Product ID", value=f"`{clean_prod_id}`", inline=True)
        embed.add_field(name="Nama", value=name, inline=True)
        embed.add_field(name="Tipe", value="👤 Akun Digital (.txt)" if product_type == "ACCOUNT" else "📁 File Digital", inline=True)
        embed.add_field(name="Harga", value=f"Rp {price:,}", inline=True)
        embed.add_field(name="Total Stok", value=f"**{final_stock} unit**" + (f" ({added_accounts} akun terinput)" if added_accounts else ""), inline=True)
        embed.add_field(name="File / Data Path", value=f"`{destination_path.name}`", inline=False)
        embed.set_footer(text="Produk sekarang aktif dan siap dibeli di katalog!")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="restock_accounts",
        description="[Admin] Tambahkan stok akun baru ke produk bertipe ACCOUNT (1 baris per akun)."
    )
    @app_commands.describe(
        product_id="ID produk akun yang ingin di-restock",
        file="[Paling Mudah] Upload file .txt berisi daftar akun (1 akun per baris)",
        accounts_text="Atau paste teks akun di sini jika tidak menggunakan file"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def restock_accounts(
        self,
        interaction: discord.Interaction,
        product_id: str,
        file: Optional[discord.Attachment] = None,
        accounts_text: Optional[str] = None
    ):
        """Menambahkan akun digital secara massal ke produk."""
        clean_id = product_id.lower().strip()
        prod = await self.bot.db.get_product(clean_id)
        if not prod:
            return await interaction.response.send_message(
                f"❌ Produk dengan ID `{product_id}` tidak ditemukan!",
                ephemeral=True
            )

        account_lines = []
        if file is not None:
            try:
                raw_bytes = await file.read()
                text_content = raw_bytes.decode("utf-8", errors="ignore")
                account_lines = text_content.splitlines()
            except Exception as e:
                return await interaction.response.send_message(
                    f"❌ Gagal membaca file attachment: {str(e)}",
                    ephemeral=True
                )
        elif accounts_text:
            account_lines = accounts_text.splitlines()
        else:
            return await interaction.response.send_message(
                "⚠️ Harap upload file `.txt` berisi list akun atau masukkan teks akun pada parameter `accounts_text`!",
                ephemeral=True
            )

        added = await self.bot.db.add_account_stock(clean_id, account_lines)
        if added == 0:
            return await interaction.response.send_message(
                "⚠️ Tidak ada data akun valid yang ditemukan dalam input Anda (pastikan tidak hanya baris kosong).",
                ephemeral=True
            )

        updated_prod = await self.bot.db.get_product(clean_id)
        embed = discord.Embed(
            title="📥 Restock Akun Berhasil!",
            description=(
                f"Berhasil menambahkan **{added} akun** ke produk **{updated_prod['name']}**!\n"
                f"Total stok tersedia saat ini: **{updated_prod['stock']} unit**"
            ),
            color=discord.Color.green()
        )
        embed.add_field(name="Product ID", value=f"`{clean_id}`", inline=True)
        embed.add_field(name="Harga Satuan", value=f"Rp {updated_prod['price']:,}", inline=True)
        embed.set_footer(text="Stok katalog otomatis ter-update dan siap dibeli pembeli.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set_stock",
        description="[Admin] Perbarui jumlah stok produk File secara cepat."
    )
    @app_commands.describe(
        product_id="ID produk yang ingin diubah stoknya",
        stock="Jumlah stok baru"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_stock(self, interaction: discord.Interaction, product_id: str, stock: int):
        """Memperbarui stok produk File."""
        if stock < 0:
            return await interaction.response.send_message("❌ Stok tidak boleh negatif!", ephemeral=True)

        clean_id = product_id.lower().strip()
        prod = await self.bot.db.get_product(clean_id)
        if not prod:
            return await interaction.response.send_message(f"❌ Produk `{product_id}` tidak ditemukan.", ephemeral=True)

        if prod.get("product_type") == "ACCOUNT":
            return await interaction.response.send_message(
                "⚠️ **Produk ini bertipe Akun Digital!**\n"
                "Stok produk akun dihitung otomatis dari jumlah akun yang ada di database.\n"
                "• Untuk menambah stok akun: gunakan `/restock_accounts`\n"
                "• Untuk mengganti semua akun sisa: gunakan `/replace_accounts`\n"
                "• Untuk mengosongkan sisa akun: gunakan `/clear_account_stock`\n"
                "• Atau buka menu `[✏️ Edit / Restock]` di `/setup_owner_panel`.",
                ephemeral=True
            )

        success = await self.bot.db.update_stock(clean_id, stock)
        if success:
            await interaction.response.send_message(
                f"✅ Stok produk `{product_id}` berhasil diperbarui menjadi **{stock}** unit.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Gagal memperbarui stok produk `{product_id}`.",
                ephemeral=True
            )

    @app_commands.command(
        name="replace_accounts",
        description="[Admin] Ganti seluruh stok akun yang belum terjual dengan daftar akun baru."
    )
    @app_commands.describe(
        product_id="ID produk akun yang ingin diganti stoknya",
        file="[Opsional] Upload file .txt berisi daftar akun baru (1 akun per baris)",
        accounts_text="[Opsional] Atau paste teks daftar akun baru di sini"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def replace_accounts(
        self,
        interaction: discord.Interaction,
        product_id: str,
        file: Optional[discord.Attachment] = None,
        accounts_text: Optional[str] = None
    ):
        """Mengganti seluruh akun yang belum terjual dengan daftar akun baru."""
        clean_id = product_id.lower().strip()
        prod = await self.bot.db.get_product(clean_id)
        if not prod:
            return await interaction.response.send_message(
                f"❌ Produk `{product_id}` tidak ditemukan!", ephemeral=True
            )

        account_lines = []
        if file is not None:
            try:
                raw_bytes = await file.read()
                text_content = raw_bytes.decode("utf-8", errors="ignore")
                account_lines = text_content.splitlines()
            except Exception as e:
                return await interaction.response.send_message(
                    f"❌ Gagal membaca file attachment: {str(e)}", ephemeral=True
                )
        elif accounts_text:
            account_lines = accounts_text.splitlines()
        else:
            return await interaction.response.send_message(
                "⚠️ Harap upload file .txt baru atau masukkan teks akun pada parameter `accounts_text`!",
                ephemeral=True
            )

        deleted_old, added_new = await self.bot.db.replace_account_stock(clean_id, account_lines)
        embed = discord.Embed(
            title="🔄 Stok Akun Berhasil Diganti!",
            description=(
                f"Stok akun belum terjual untuk **{prod['name']}** telah diperbarui.\n\n"
                f"• Akun lama yang dihapus: **{deleted_old} akun**\n"
                f"• Akun baru yang dimasukkan: **{added_new} akun**\n"
                f"• Total sisa stok saat ini: **{added_new} unit**"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Akun yang sudah terjual sebelumnya tetap aman dan tidak terhapus.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="clear_account_stock",
        description="[Admin] Hapus/kosongkan seluruh akun yang belum terjual (stok menjadi 0)."
    )
    @app_commands.describe(product_id="ID produk akun yang ingin dikosongkan sisa stoknya")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_account_stock(self, interaction: discord.Interaction, product_id: str):
        """Mengosongkan semua akun belum terjual untuk produk tertentu."""
        clean_id = product_id.lower().strip()
        prod = await self.bot.db.get_product(clean_id)
        if not prod:
            return await interaction.response.send_message(
                f"❌ Produk `{product_id}` tidak ditemukan!", ephemeral=True
            )

        deleted = await self.bot.db.clear_unsold_accounts(clean_id)
        embed = discord.Embed(
            title="🗑️ Stok Akun Dikosongkan!",
            description=(
                f"Sebanyak **{deleted} akun** yang belum terjual pada produk **{prod['name']}** (`{clean_id}`) telah berhasil dihapus.\n\n"
                f"• Sisa stok saat ini: **0 unit**\n"
                f"*(Riwayat order dan akun pembeli sebelumnya tidak terpengaruh)*"
            ),
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="delete_account",
        description="[Admin] Hapus 1 baris akun spesifik yang belum terjual jika akun tersebut mati/rusak."
    )
    @app_commands.describe(
        product_id="ID produk akun",
        account_text="Teks akun yang ingin dihapus persis seperti yang diinput (misal user:pass)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_account(self, interaction: discord.Interaction, product_id: str, account_text: str):
        """Menghapus satu akun tertentu yang belum terjual."""
        clean_id = product_id.lower().strip()
        prod = await self.bot.db.get_product(clean_id)
        if not prod:
            return await interaction.response.send_message(f"❌ Produk `{product_id}` tidak ditemukan!", ephemeral=True)

        deleted = await self.bot.db.delete_specific_account(clean_id, account_text)
        if deleted:
            updated_prod = await self.bot.db.get_product(clean_id)
            new_stock = updated_prod["stock"] if updated_prod else 0
            await interaction.response.send_message(
                f"✅ Akun `{account_text.strip()}` berhasil dihapus dari produk **{prod['name']}**.\n"
                f"📦 Sisa stok sekarang: **{new_stock} unit**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Akun `{account_text.strip()}` tidak ditemukan dalam daftar akun yang belum terjual pada produk ini.",
                ephemeral=True
            )

    @app_commands.command(
        name="check_stock",
        description="[Admin] Cek sisa stok produk atau unduh/lihat daftar akun yang belum terjual."
    )
    @app_commands.describe(product_id="ID produk yang ingin dicek stoknya")
    @app_commands.checks.has_permissions(administrator=True)
    async def check_stock(self, interaction: discord.Interaction, product_id: str):
        """Memeriksa sisa stok dan mengekspor akun yang belum terjual."""
        clean_id = product_id.lower().strip()
        product = await self.bot.db.get_product(clean_id)
        if not product:
            return await interaction.response.send_message(
                f"❌ Produk dengan ID `{product_id}` tidak ditemukan di database.",
                ephemeral=True
            )

        prod_type = product.get("product_type", "FILE")
        if prod_type == "ACCOUNT":
            details = await self.bot.db.get_account_stock_details(clean_id)
            unsold_count = details["unsold_count"]
            sold_count = details["sold_count"]
            total_count = details["total_count"]
            unsold_accounts = details["unsold_accounts"]

            embed = discord.Embed(
                title=f"📦 Rincian Stok Akun: {product['name']}",
                description=f"**Product ID:** `{clean_id}`\n**Harga Satuan:** Rp {product['price']:,}",
                color=discord.Color.green() if unsold_count > 0 else discord.Color.red()
            )
            embed.add_field(name="🟢 Sisa Stok Tersedia", value=f"**{unsold_count} akun**", inline=True)
            embed.add_field(name="🔴 Sudah Terjual", value=f"**{sold_count} akun**", inline=True)
            embed.add_field(name="📊 Total Pernah Diinput", value=f"**{total_count} akun**", inline=True)

            if unsold_count > 0:
                import io
                content = "\n".join(unsold_accounts)
                file_data = io.BytesIO(content.encode("utf-8"))
                discord_file = discord.File(file_data, filename=f"stok_tersisa_{clean_id}.txt")

                preview_lines = unsold_accounts[:5]
                preview_text = "\n".join(preview_lines)
                if unsold_count > 5:
                    preview_text += f"\n... dan {unsold_count - 5} akun lainnya (lihat file terlampir)"
                embed.add_field(name="👁️ Pratinjau Akun Tersisa", value=f"```text\n{preview_text}\n```", inline=False)
                embed.set_footer(text="File daftar akun tersisa terlampir di bawah (hanya Anda yang dapat melihat ini).")

                await interaction.response.send_message(embed=embed, file=discord_file, ephemeral=True)
            else:
                embed.set_footer(text="Stok akun sedang habis. Silakan gunakan /restock_accounts untuk mengisi ulang.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            file_exists = Path(product["file_path"]).exists()
            file_status = "🟢 Ready di Server" if file_exists else "🔴 File Tidak Ditemukan!"
            embed = discord.Embed(
                title=f"📦 Rincian Stok Produk: {product['name']}",
                description=f"**Product ID:** `{clean_id}`\n**Tipe:** 📁 File Digital\n**Harga Satuan:** Rp {product['price']:,}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Sisa Stok", value=f"**{product['stock']} unit**", inline=True)
            embed.add_field(name="File Fisik", value=f"`{Path(product['file_path']).name}` ({file_status})", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

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
            ptype = p.get("product_type", "FILE")
            type_str = "👤 Akun Digital (.txt)" if ptype == "ACCOUNT" else "📁 File Digital"
            file_exists = Path(p["file_path"]).exists()
            file_status = "🟢 File Ready" if file_exists else "🔴 File Hilang!"
            embed.add_field(
                name=f"{p['name']} (`{p['product_id']}`)",
                value=(
                    f"• Tipe: **{type_str}**\n"
                    f"• Harga: Rp {p['price']:,}\n"
                    f"• Stok: **{p['stock']} unit**\n"
                    f"• File / Data: `{Path(p['file_path']).name}` ({file_status})"
                ),
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
