import discord
from discord import ui
import os
import logging
from pathlib import Path
from typing import Dict, Any, List
import config

logger = logging.getLogger("StoreBot.Views.Catalog")

class ProductDropdown(ui.Select):
    """
    Select menu yang menampilkan daftar produk aktif yang stoknya tersedia.
    """
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        self.db = db_manager
        self.products_map = {p["product_id"]: p for p in products}

        options = []
        for p in products[:25]:  # Discord limit maksimal 25 opsi per select menu
            options.append(
                discord.SelectOption(
                    label=p["name"][:100],
                    value=p["product_id"],
                    description=f"Rp {p['price']:,} • Sisa Stok: {p['stock']}"[:100],
                    emoji="📦"
                )
            )

        super().__init__(
            placeholder="🔍 Pilih produk yang ingin Anda beli...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        product = self.products_map.get(selected_id)
        if not product:
            return await interaction.response.send_message(
                "❌ Produk tidak ditemukan atau telah diperbarui.", ephemeral=True
            )

        # Cek saldo user saat ini
        user_balance = await self.db.get_balance(interaction.user.id)

        # Tampilkan embed detail beserta tombol konfirmasi pembelian
        view = ConfirmPurchaseView(self.db, product)
        embed = view.build_embed(user_balance)
        await interaction.response.edit_message(embed=embed, view=view)


class ProductSelectView(ui.View):
    """
    Container View untuk ProductDropdown.
    """
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        super().__init__(timeout=120)
        self.add_item(ProductDropdown(db_manager, products))


class InputQuantityModal(ui.Modal, title="Tentukan Jumlah Pembelian"):
    """
    Modal untuk memasukkan Quantity (Qty) pesanan pembeli.
    """
    qty_input = ui.TextInput(
        label="Jumlah Pembelian (Qty)",
        placeholder="Contoh: 1, 2, 5 (Hanya angka bulat)",
        required=True,
        min_length=1,
        max_length=4
    )

    def __init__(self, parent_view: 'ConfirmPurchaseView'):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw_val = self.qty_input.value.strip()
        if not raw_val.isdigit() or int(raw_val) < 1:
            return await interaction.response.send_message(
                "❌ Masukkan jumlah (qty) angka bulat positif minimal 1!",
                ephemeral=True
            )

        new_qty = int(raw_val)
        stock = self.parent_view.product["stock"]
        if new_qty > stock:
            return await interaction.response.send_message(
                f"❌ Jumlah diminta (**{new_qty} unit**) melebihi sisa stok yang tersedia (**{stock} unit**)!",
                ephemeral=True
            )

        self.parent_view.quantity = new_qty
        self.parent_view.confirm_btn.label = f"Konfirmasi ({new_qty} unit)"
        user_balance = await self.parent_view.db.get_balance(interaction.user.id)
        embed = self.parent_view.build_embed(user_balance)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class ConfirmPurchaseView(ui.View):
    """
    View untuk verifikasi final pembelian produk oleh user dengan dukungan Quantity.
    """
    def __init__(self, db_manager, product: Dict[str, Any], initial_qty: int = 1):
        super().__init__(timeout=90)
        self.db = db_manager
        self.product = product
        self.quantity = initial_qty
        self.confirm_btn.label = f"Konfirmasi ({self.quantity} unit)" if self.quantity > 1 else "Konfirmasi Pembelian"

    def build_embed(self, user_balance: int) -> discord.Embed:
        """Membuat Embed Konfirmasi Produk & Rincian Total Harga."""
        price = self.product["price"]
        stock = self.product["stock"]
        total_price = price * self.quantity
        prod_type = self.product.get("product_type", "FILE")
        type_badge = "👤 Akun Digital (.txt)" if prod_type == "ACCOUNT" else "📁 File Digital"

        embed = discord.Embed(
            title=f"🛍️ Konfirmasi Produk: {self.product['name']}",
            description=self.product.get("description") or "Tidak ada deskripsi produk.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Tipe Produk", value=type_badge, inline=True)
        embed.add_field(name="Harga Satuan", value=f"Rp {price:,}", inline=True)
        embed.add_field(name="Sisa Stok", value=f"{stock} unit", inline=True)
        embed.add_field(name="Jumlah (Qty)", value=f"**{self.quantity} unit**", inline=True)
        embed.add_field(name="Total Tagihan", value=f"**Rp {total_price:,}**", inline=True)
        embed.add_field(name="Saldo Anda", value=f"Rp {user_balance:,}", inline=True)

        if user_balance < total_price:
            shortage = total_price - user_balance
            embed.set_footer(text=f"⚠️ Saldo tidak mencukupi (Kurang Rp {shortage:,}). Silakan deposit terlebih dahulu.")
        else:
            embed.set_footer(text="✅ Saldo mencukupi. Klik tombol konfirmasi untuk checkout.")

        return embed

    @ui.button(label="Konfirmasi Pembelian", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def confirm_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Nonaktifkan tombol agar tidak terjadi double-click
        button.disabled = True
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        product_id = self.product["product_id"]

        # Eksekusi transaksi atomik di database dengan parameter quantity
        success, message, order_info = await self.db.purchase_product(user_id, product_id, self.quantity)

        if not success:
            return await interaction.followup.send(
                f"❌ **Gagal Memproses Pembelian:**\n{message}",
                ephemeral=True
            )

        file_path_str = order_info.get("file_path", "")
        file_obj = Path(file_path_str)

        # Validasi ketersediaan file produk fisik di server
        if not file_obj.exists():
            logger.error("File produk tidak ditemukan di path: %s", file_path_str)
            return await interaction.followup.send(
                f"✅ **Pembayaran Berhasil!**\n"
                f"Namun terjadi kendala: File produk belum terunggah di storage server. "
                f"Silakan buat tiket support dengan melampirkan Order ID: `{order_info['order_id']}`.",
                ephemeral=True
            )

        # Nama file yang dikirimkan ke user
        custom_filename = file_obj.name
        if order_info.get("product_type") == "ACCOUNT":
            custom_filename = f"akun_{order_info['product_id']}_{order_info['order_id']}.txt"

        # Invoice Embed
        invoice_embed = discord.Embed(
            title="🎉 Pembelian Berhasil!",
            description=(
                f"Terima kasih telah membeli **{order_info['product_name']}**!\n"
                f"Data/File produk digital Anda telah disertakan di bawah ini."
            ),
            color=discord.Color.green()
        )
        invoice_embed.add_field(name="Order ID", value=f"`{order_info['order_id']}`", inline=True)
        invoice_embed.add_field(name="Jumlah (Qty)", value=f"{order_info['quantity']} unit", inline=True)
        invoice_embed.add_field(name="Total Terpotong", value=f"Rp {order_info['price_paid']:,}", inline=True)
        invoice_embed.add_field(name="Sisa Saldo", value=f"Rp {order_info['remaining_balance']:,}", inline=True)
        invoice_embed.set_footer(text="Automated Store Delivery System")

        # Pengiriman File: Coba ke Direct Message (DM) terlebih dahulu
        dm_sent = False
        try:
            discord_file_dm = discord.File(str(file_obj), filename=custom_filename)
            await interaction.user.send(embed=invoice_embed, file=discord_file_dm)
            dm_sent = True
        except discord.Forbidden:
            logger.warning("DM User %d terkunci/ditutup. Fallback ke Ephemeral.", user_id)
        except Exception as e:
            logger.error("Gagal mengirim DM produk ke %d: %s", user_id, str(e))

        # Hapus message konfirmasi pembelian agar otomatis hilang dari layar pembeli
        try:
            await interaction.delete_original_response()
        except Exception as e:
            logger.debug("Gagal menghapus pesan konfirmasi pembelian: %s", e)

        # Kirim konfirmasi transaksi sukses + lampirkan file produk secara privat (ephemeral)
        discord_file_ephemeral = discord.File(str(file_obj), filename=custom_filename)
        if dm_sent:
            await interaction.followup.send(
                content="✅ **Transaksi Sukses!** File produk telah kami lampirkan di bawah ini dan salinannya juga telah dikirimkan ke **DM** Anda:",
                embed=invoice_embed,
                file=discord_file_ephemeral,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                content="✅ **Transaksi Sukses!** (DM Anda tertutup). File produk kami lampirkan secara privat di bawah ini:",
                embed=invoice_embed,
                file=discord_file_ephemeral,
                ephemeral=True
            )

        # Kirim log transaksi ke channel staff/admin jika dikonfigurasi
        if config.TRANSACTION_LOG_CHANNEL_ID:
            log_channel = interaction.client.get_channel(config.TRANSACTION_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🛒 Log Transaksi Pembelian",
                    color=discord.Color.dark_teal()
                )
                log_embed.add_field(name="Buyer", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
                log_embed.add_field(name="Produk", value=order_info["product_name"], inline=True)
                log_embed.add_field(name="Jumlah (Qty)", value=f"{order_info['quantity']} unit", inline=True)
                log_embed.add_field(name="Total Bayar", value=f"Rp {order_info['price_paid']:,}", inline=True)
                log_embed.add_field(name="Order ID", value=f"`{order_info['order_id']}`", inline=True)
                await log_channel.send(embed=log_embed)

    @ui.button(label="Ubah Qty", style=discord.ButtonStyle.primary, emoji="🔢", row=0)
    async def change_qty_btn(self, interaction: discord.Interaction, button: ui.Button):
        """Membuka modal untuk mengatur jumlah pembelian."""
        await interaction.response.send_modal(InputQuantityModal(self))

    @ui.button(label="Batal", style=discord.ButtonStyle.secondary, emoji="❌", row=0)
    async def cancel_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass
