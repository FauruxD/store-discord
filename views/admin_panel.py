import discord
from discord import ui
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import config

logger = logging.getLogger("StoreBot.Views.AdminPanel")

def is_authorized_admin(interaction: discord.Interaction) -> bool:
    """Helper untuk memeriksa apakah user adalah admin atau memiliki role staff."""
    if interaction.user.guild_permissions.administrator:
        return True
    if config.ADMIN_ROLE_ID and any(r.id == config.ADMIN_ROLE_ID for r in interaction.user.roles):
        return True
    return False


# =============================================================================
# MODAL UNTUK EDIT STOK DAN HARGA
# =============================================================================

class UpdateStockModal(ui.Modal, title="Update Stok Produk"):
    stock_input = ui.TextInput(
        label="Jumlah Stok Baru",
        placeholder="Contoh: 25 (Hanya angka)",
        required=True,
        min_length=1,
        max_length=6
    )

    def __init__(self, db_manager, product_id: str, product_name: str):
        super().__init__()
        self.db = db_manager
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.stock_input.value.strip()
        if not raw.isdigit():
            return await interaction.response.send_message(
                "❌ Masukkan angka bulat positif!", ephemeral=True
            )
        new_stock = int(raw)
        success = await self.db.update_stock(self.product_id, new_stock)
        if success:
            await interaction.response.send_message(
                f"✅ Stok untuk **{self.product_name}** (`{self.product_id}`) berhasil diubah menjadi **{new_stock}** unit.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Gagal memperbarui stok produk.", ephemeral=True)


class UpdatePriceModal(ui.Modal, title="Update Harga Produk"):
    price_input = ui.TextInput(
        label="Harga Baru (Rupiah)",
        placeholder="Contoh: 30000 (Hanya angka tanpa titik)",
        required=True,
        min_length=3,
        max_length=9
    )

    def __init__(self, db_manager, product_id: str, product_name: str):
        super().__init__()
        self.db = db_manager
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.price_input.value.strip().replace(".", "").replace(",", "")
        if not raw.isdigit():
            return await interaction.response.send_message(
                "❌ Masukkan nominal angka valid!", ephemeral=True
            )
        new_price = int(raw)
        success = await self.db.update_price(self.product_id, new_price)
        if success:
            await interaction.response.send_message(
                f"✅ Harga untuk **{self.product_name}** (`{self.product_id}`) berhasil diubah menjadi **Rp {new_price:,}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Gagal memperbarui harga produk.", ephemeral=True)


class RestockAccountModal(ui.Modal, title="Input Stok Akun"):
    accounts_input = ui.TextInput(
        label="Daftar Akun (1 Akun per Baris)",
        style=discord.TextStyle.paragraph,
        placeholder="email1:pass1\nemail2:pass2\nuser3:pass3...",
        required=True,
        min_length=3,
        max_length=4000
    )

    def __init__(self, db_manager, product_id: str, product_name: str):
        super().__init__()
        self.db = db_manager
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        lines = self.accounts_input.value.splitlines()
        added = await self.db.add_account_stock(self.product_id, lines)
        if added == 0:
            return await interaction.response.send_message(
                "⚠️ Tidak ada akun valid yang terdeteksi dalam input Anda.",
                ephemeral=True
            )
        prod = await self.db.get_product(self.product_id)
        current_stock = prod["stock"] if prod else added
        await interaction.response.send_message(
            f"✅ Berhasil menambahkan **{added} akun** ke produk **{self.product_name}** (`{self.product_id}`)!\n"
            f"📦 Total stok akun tersedia saat ini: **{current_stock} unit**.",
            ephemeral=True
        )


class ReplaceAccountModal(ui.Modal, title="Ganti Seluruh Stok Akun"):
    accounts_input = ui.TextInput(
        label="Daftar Akun Baru (1 Akun per Baris)",
        style=discord.TextStyle.paragraph,
        placeholder="Akun belum terjual lama akan dihapus dan diganti list ini.\nemail1:pass1\nemail2:pass2...",
        required=True,
        min_length=3,
        max_length=4000
    )

    def __init__(self, db_manager, product_id: str, product_name: str):
        super().__init__()
        self.db = db_manager
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        lines = self.accounts_input.value.splitlines()
        deleted_count, added_count = await self.db.replace_account_stock(self.product_id, lines)
        await interaction.response.send_message(
            f"🔄 **Stok Akun Berhasil Diganti!**\n"
            f"• Produk: **{self.product_name}** (`{self.product_id}`)\n"
            f"• Akun lama belum terjual yang dihapus: **{deleted_count} akun**\n"
            f"• Akun baru yang dimasukkan: **{added_count} akun**\n"
            f"📦 Total sisa stok sekarang: **{added_count} unit**.",
            ephemeral=True
        )


class ClearAccountConfirmView(ui.View):
    """View konfirmasi untuk mengosongkan sisa stok akun."""
    def __init__(self, db_manager, product_id: str, product_name: str):
        super().__init__(timeout=60)
        self.db = db_manager
        self.product_id = product_id
        self.product_name = product_name

    @ui.button(label="Ya, Kosongkan Akun Sisa", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_clear(self, interaction: discord.Interaction, button: ui.Button):
        deleted = await self.db.clear_unsold_accounts(self.product_id)
        await interaction.response.edit_message(
            content=f"✅ Sebanyak **{deleted} akun** yang belum terjual pada **{self.product_name}** (`{self.product_id}`) telah berhasil dikosongkan. Sisa stok sekarang: **0 unit**.",
            embed=None,
            view=None
        )

    @ui.button(label="Batal", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_clear(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


# =============================================================================
# VIEW DETAIL EDIT & HAPUS PRODUK
# =============================================================================

class AccountProductEditActionView(ui.View):
    """View tombol aksi khusus untuk produk bertipe ACCOUNT."""
    def __init__(self, db_manager, product: Dict[str, Any]):
        super().__init__(timeout=180)
        self.db = db_manager
        self.product = product

    @ui.button(label="Tambah Akun", style=discord.ButtonStyle.success, emoji="📥", row=0)
    async def restock_acc_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            RestockAccountModal(self.db, self.product["product_id"], self.product["name"])
        )

    @ui.button(label="Ganti Stok Akun", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def replace_acc_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            ReplaceAccountModal(self.db, self.product["product_id"], self.product["name"])
        )

    @ui.button(label="Kosongkan Akun", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def clear_acc_btn(self, interaction: discord.Interaction, button: ui.Button):
        unsold = await self.db.get_unsold_accounts_count(self.product["product_id"])
        embed = discord.Embed(
            title="⚠️ Konfirmasi Kosongkan Stok Akun",
            description=(
                f"Apakah Anda yakin ingin menghapus semua akun yang **belum terjual** pada produk **{self.product['name']}**?\n\n"
                f"• Jumlah akun yang akan dihapus: **{unsold} akun**\n"
                f"*(Akun yang sudah pernah laku dan riwayat pesanan pembeli TIDAK akan terhapus)*"
            ),
            color=discord.Color.red()
        )
        view = ClearAccountConfirmView(self.db, self.product["product_id"], self.product["name"])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(label="Unduh Akun Sisa", style=discord.ButtonStyle.secondary, emoji="👁️", row=1)
    async def view_acc_stock_btn(self, interaction: discord.Interaction, button: ui.Button):
        details = await self.db.get_account_stock_details(self.product["product_id"])
        unsold_count = details["unsold_count"]
        sold_count = details["sold_count"]
        total_count = details["total_count"]
        unsold_accounts = details["unsold_accounts"]

        embed = discord.Embed(
            title=f"📦 Sisa Stok Akun: {self.product['name']}",
            description=f"**ID Produk:** `{self.product['product_id']}`",
            color=discord.Color.teal()
        )
        embed.add_field(name="🟢 Sisa Stok Tersedia", value=f"**{unsold_count} unit**", inline=True)
        embed.add_field(name="🔴 Sudah Terjual", value=f"**{sold_count} unit**", inline=True)
        embed.add_field(name="📊 Total Pernah Diinput", value=f"**{total_count} unit**", inline=True)

        if unsold_count > 0:
            import io
            content = "\n".join(unsold_accounts)
            file_data = io.BytesIO(content.encode("utf-8"))
            discord_file = discord.File(file_data, filename=f"stok_tersisa_{self.product['product_id']}.txt")

            preview_lines = unsold_accounts[:5]
            preview_text = "\n".join(preview_lines)
            if unsold_count > 5:
                preview_text += f"\n... dan {unsold_count - 5} akun lainnya (unduh file terlampir)"
            embed.add_field(name="👁️ Pratinjau 5 Akun Teratas", value=f"```text\n{preview_text}\n```", inline=False)
            embed.set_footer(text="File daftar akun tersisa terlampir di bawah (hanya Anda yang dapat melihat ini).")
            await interaction.response.send_message(embed=embed, file=discord_file, ephemeral=True)
        else:
            embed.description += "\n\n⚠️ Stok akun ini sedang habis (0 unit)."
            embed.set_footer(text="Gunakan tombol Tambah Akun atau command /restock_accounts untuk mengisi stok.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Ubah Harga", style=discord.ButtonStyle.secondary, emoji="💰", row=1)
    async def edit_price_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            UpdatePriceModal(self.db, self.product["product_id"], self.product["name"])
        )

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


class FileProductEditActionView(ui.View):
    """View tombol aksi untuk produk bertipe FILE."""
    def __init__(self, db_manager, product: Dict[str, Any]):
        super().__init__(timeout=120)
        self.db = db_manager
        self.product = product

    @ui.button(label="Ubah Stok", style=discord.ButtonStyle.primary, emoji="📦")
    async def edit_stock_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            UpdateStockModal(self.db, self.product["product_id"], self.product["name"])
        )

    @ui.button(label="Ubah Harga", style=discord.ButtonStyle.success, emoji="💰")
    async def edit_price_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            UpdatePriceModal(self.db, self.product["product_id"], self.product["name"])
        )

    @ui.button(label="Tutup", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


class SelectProductToEditDropdown(ui.Select):
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        self.db = db_manager
        self.products_map = {p["product_id"]: p for p in products}

        options = []
        for p in products[:25]:
            ptype = p.get("product_type", "FILE")
            type_tag = "[AKUN]" if ptype == "ACCOUNT" else "[FILE]"
            options.append(
                discord.SelectOption(
                    label=f"{type_tag} {p['name']}"[:100],
                    value=p["product_id"],
                    description=f"Harga: Rp {p['price']:,} | Stok: {p['stock']}"[:100],
                    emoji="✏️"
                )
            )

        super().__init__(
            placeholder="Pilih produk yang ingin diedit / restock...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        product_id = self.values[0]
        product = self.products_map.get(product_id)
        if not product:
            return await interaction.response.send_message("❌ Produk tidak ditemukan.", ephemeral=True)

        prod_type = product.get("product_type", "FILE")
        type_str = "👤 Akun Digital (.txt)" if prod_type == "ACCOUNT" else "📁 File Digital"

        embed = discord.Embed(
            title=f"✏️ Kelola Produk: {product['name']}",
            description=f"**ID:** `{product['product_id']}`\n**Tipe:** {type_str}\n{product.get('description', '')}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Harga Saat Ini", value=f"Rp {product['price']:,}", inline=True)
        embed.add_field(name="Stok Saat Ini", value=f"{product['stock']} unit", inline=True)
        embed.add_field(name="File / Storage", value=f"`{Path(product['file_path']).name}`", inline=False)
        embed.set_footer(text="Klik tombol di bawah untuk mengelola stok, harga, atau akun.")

        if prod_type == "ACCOUNT":
            view = AccountProductEditActionView(self.db, product)
        else:
            view = FileProductEditActionView(self.db, product)

        await interaction.response.edit_message(embed=embed, view=view)


class ProductEditSelectView(ui.View):
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        self.add_item(SelectProductToEditDropdown(db_manager, products))


# =============================================================================
# VIEW HAPUS PRODUK
# =============================================================================

class ProductDeleteConfirmView(ui.View):
    """View konfirmasi penghapusan produk."""
    def __init__(self, db_manager, product: Dict[str, Any]):
        super().__init__(timeout=60)
        self.db = db_manager
        self.product = product

    @ui.button(label="Ya, Hapus Produk Ini", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
        button.disabled = True
        success = await self.db.delete_product(self.product["product_id"])
        if success:
            await interaction.response.edit_message(
                content=f"✅ Produk **{self.product['name']}** (`{self.product['product_id']}`) berhasil dihapus dari database!",
                embed=None,
                view=None
            )
        else:
            await interaction.response.edit_message(
                content="❌ Gagal menghapus produk atau produk sudah tidak ada.",
                embed=None,
                view=None
            )

    @ui.button(label="Batal", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


class SelectProductToDeleteDropdown(ui.Select):
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        self.db = db_manager
        self.products_map = {p["product_id"]: p for p in products}

        options = []
        for p in products[:25]:
            options.append(
                discord.SelectOption(
                    label=p["name"][:100],
                    value=p["product_id"],
                    description=f"Rp {p['price']:,} | Stok: {p['stock']}"[:100],
                    emoji="🗑️"
                )
            )

        super().__init__(
            placeholder="Pilih produk yang ingin dihapus...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        product_id = self.values[0]
        product = self.products_map.get(product_id)
        if not product:
            return await interaction.response.send_message("❌ Produk tidak ditemukan.", ephemeral=True)

        embed = discord.Embed(
            title="⚠️ Konfirmasi Hapus Produk",
            description=(
                f"Apakah Anda yakin ingin menghapus produk **{product['name']}** (`{product['product_id']}`)?\n\n"
                f"⚠️ *Produk yang dihapus tidak akan lagi muncul di katalog pembeli.*"
            ),
            color=discord.Color.red()
        )
        embed.add_field(name="Harga", value=f"Rp {product['price']:,}", inline=True)
        embed.add_field(name="Sisa Stok", value=f"{product['stock']} unit", inline=True)

        view = ProductDeleteConfirmView(self.db, product)
        await interaction.response.edit_message(embed=embed, view=view)


class ProductDeleteSelectView(ui.View):
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        self.add_item(SelectProductToDeleteDropdown(db_manager, products))


# =============================================================================
# PERSISTENT MAIN OWNER / ADMIN CONTROL PANEL VIEW
# =============================================================================

class OwnerAdminPanelView(ui.View):
    """
    Persistent View untuk Panel Khusus Owner / Admin Toko.
    Menyediakan aksi CRUD lengkap:
    - Create: Panduan upload file via /add_product
    - Read: Daftar produk lengkap dengan status stok & file
    - Update: Dropdown edit stok & harga
    - Delete: Dropdown hapus produk
    """
    def __init__(self, db_manager, target_channel_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.db = db_manager
        self.target_channel_id = target_channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Memastikan hanya admin berwenang di channel yang sesuai yang dapat menggunakan panel ini."""
        if not is_authorized_admin(interaction):
            await interaction.response.send_message(
                "⛔ **Akses Ditolak!** Panel ini hanya dapat dioperasikan oleh Owner / Admin Store.",
                ephemeral=True
            )
            return False

        if self.target_channel_id and interaction.channel_id != self.target_channel_id:
            await interaction.response.send_message(
                "⛔ Panel ini hanya dapat dioperasikan di channel admin yang telah ditentukan!",
                ephemeral=True
            )
            return False

        return True

    @ui.button(
        label="Daftar Produk (Read)",
        style=discord.ButtonStyle.primary,
        emoji="📋",
        custom_id="owner_panel_list_products_btn",
        row=0
    )
    async def list_products_btn(self, interaction: discord.Interaction, button: ui.Button):
        """[Read] Menampilkan daftar seluruh inventaris produk digital."""
        products = await self.db.get_all_products()
        if not products:
            return await interaction.response.send_message(
                "📦 Saat ini belum ada produk yang terdaftar di database katalog.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📋 Inventaris Produk Digital (Owner View)",
            color=discord.Color.blue()
        )

        for p in products:
            ptype = p.get("product_type", "FILE")
            type_str = "👤 Akun Digital (.txt)" if ptype == "ACCOUNT" else "📁 File Digital"
            file_exists = Path(p["file_path"]).exists()
            file_badge = "🟢 Ready" if file_exists else "🔴 File Hilang!"
            stock_badge = "🟢 Tersedia" if p["stock"] > 0 else "🔴 Habis"

            embed.add_field(
                name=f"{p['name']} (`{p['product_id']}`)",
                value=(
                    f"• Tipe: **{type_str}**\n"
                    f"• Harga: **Rp {p['price']:,}**\n"
                    f"• Stok: **{p['stock']} unit** ({stock_badge})\n"
                    f"• File / Data: `{Path(p['file_path']).name}` ({file_badge})"
                ),
                inline=False
            )

        embed.set_footer(text="Gunakan tombol Edit atau Hapus untuk memodifikasi produk.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(
        label="Tambah Produk (Create)",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="owner_panel_add_product_btn",
        row=0
    )
    async def add_product_btn(self, interaction: discord.Interaction, button: ui.Button):
        """[Create] Menampilkan panduan praktis menambah produk baru via slash command."""
        embed = discord.Embed(
            title="➕ Cara Menambahkan Produk Baru",
            description=(
                "Untuk mendaftarkan produk digital baru (`FILE` atau `ACCOUNT`):\n\n"
                "Ketik slash command di chat:\n"
                "👉 `/add_product`\n\n"
                "**Parameter yang diisi:**\n"
                "• `product_id`: ID unik tanpa spasi (contoh: `netflix_acc` atau `script_v1`)\n"
                "• `name`: Nama produk (contoh: `Akun Netflix 1 Bulan`)\n"
                "• `description`: Deskripsi singkat produk\n"
                "• `price`: Harga satuan produk (contoh: `30000`)\n"
                "• `product_type`: Pilih **`👤 Akun Digital`** atau **`📁 File Digital`**\n"
                "• `file`: **Upload file produk langsung dari HP/PC Anda!**\n"
                "  *(Jika Akun, upload file `.txt` berisi daftar akun 1 baris per akun)*"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="File / Data akun akan otomatis tersimpan di storage dan database.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(
        label="Edit / Restock (Update)",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="owner_panel_edit_product_btn",
        row=0
    )
    async def edit_product_btn(self, interaction: discord.Interaction, button: ui.Button):
        """[Update] Menampilkan dropdown untuk memilih produk yang ingin diedit harga / stoknya."""
        products = await self.db.get_all_products()
        if not products:
            return await interaction.response.send_message(
                "📦 Belum ada produk di database untuk diedit.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="✏️ Pilih Produk untuk Diedit / Di-restock",
            description="Pilih produk dari menu dropdown di bawah ini untuk mengubah stok, harga, atau input akun:",
            color=discord.Color.gold()
        )

        view = ProductEditSelectView(self.db, products)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(
        label="Restock Akun",
        style=discord.ButtonStyle.secondary,
        emoji="📥",
        custom_id="owner_panel_restock_accounts_btn",
        row=1
    )
    async def restock_accounts_guide_btn(self, interaction: discord.Interaction, button: ui.Button):
        """[Restock] Panduan praktis restock akun digital massal."""
        embed = discord.Embed(
            title="📥 Panduan Restock Akun Digital",
            description=(
                "Ada 2 metode mudah untuk menambah stok akun:\n\n"
                "**1️⃣ Menggunakan Slash Command (Upload File .txt):**\n"
                "👉 `/restock_accounts product_id:<ID_PRODUK> file:<UPLOAD_TXT>`\n"
                "*Cukup upload file .txt berisi daftar akun (1 akun per baris). Sistem langsung memasukkan semua akun ke stok!*\n\n"
                "**2️⃣ Paste Langsung via Pop-up Input:**\n"
                "1. Klik tombol **`✏️ Edit / Restock`** di panel ini.\n"
                "2. Pilih produk akun Anda dari menu dropdown.\n"
                "3. Klik tombol **`📥 Input Akun`** lalu paste baris akun Anda ke formulir pop-up!"
            ),
            color=discord.Color.teal()
        )
        embed.set_footer(text="Format akun bebas (contoh: email:password atau user | token)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(
        label="Hapus Produk (Delete)",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="owner_panel_delete_product_btn",
        row=1
    )
    async def delete_product_btn(self, interaction: discord.Interaction, button: ui.Button):
        """[Delete] Menampilkan dropdown untuk memilih produk yang ingin dihapus."""
        products = await self.db.get_all_products()
        if not products:
            return await interaction.response.send_message(
                "📦 Belum ada produk di database untuk dihapus.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🗑️ Pilih Produk yang Ingin Dihapus",
            description="Pilih produk dari dropdown di bawah. Anda akan dimintai konfirmasi sebelum produk dihapus permanen.",
            color=discord.Color.red()
        )

        view = ProductDeleteSelectView(self.db, products)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
