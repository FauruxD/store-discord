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

        # Buat Embed Detail Produk
        embed = discord.Embed(
            title=f"🛍️ Konfirmasi Produk: {product['name']}",
            description=product.get("description") or "Tidak ada deskripsi produk.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Harga", value=f"**Rp {product['price']:,}**", inline=True)
        embed.add_field(name="Sisa Stok", value=f"{product['stock']} unit", inline=True)
        embed.add_field(name="Saldo Anda", value=f"Rp {user_balance:,}", inline=True)

        if user_balance < product["price"]:
            embed.set_footer(text="⚠️ Peringatan: Saldo Anda tidak mencukupi untuk membeli produk ini.")
        else:
            embed.set_footer(text="✅ Saldo mencukupi. Klik 'Konfirmasi Pembelian' untuk checkout.")

        # Tampilkan embed detail beserta tombol konfirmasi pembelian
        view = ConfirmPurchaseView(self.db, product)
        await interaction.response.edit_message(embed=embed, view=view)


class ProductSelectView(ui.View):
    """
    Container View untuk ProductDropdown.
    """
    def __init__(self, db_manager, products: List[Dict[str, Any]]):
        super().__init__(timeout=120)
        self.add_item(ProductDropdown(db_manager, products))


class ConfirmPurchaseView(ui.View):
    """
    View untuk verifikasi final pembelian produk oleh user.
    Mencegah spam klik dengan menonaktifkan tombol secara instan saat ditekan.
    """
    def __init__(self, db_manager, product: Dict[str, Any]):
        super().__init__(timeout=60)
        self.db = db_manager
        self.product = product

    @ui.button(label="Konfirmasi Pembelian", style=discord.ButtonStyle.success, emoji="⚡")
    async def confirm_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Nonaktifkan tombol agar tidak terjadi double-click
        button.disabled = True
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        product_id = self.product["product_id"]

        # Eksekusi transaksi atomik di database
        success, message, order_info = await self.db.purchase_product(user_id, product_id)

        if not success:
            return await interaction.followup.send(
                f"❌ **Gagal Memproses Pembelian:**\n{message}",
                ephemeral=True
            )

        file_path_str = order_info.get("file_path", "")
        file_obj = Path(file_path_str)

        # Validasi ketersediaan file produk fisik di server
        if not file_obj.exists():
            logger.error("File produk fisik tidak ditemukan: %s", file_path_str)
            return await interaction.followup.send(
                f"✅ **Pembayaran Berhasil!**\n"
                f"Namun terjadi kendala: File produk belum terunggah di storage server. "
                f"Silakan buat tiket support dengan melampirkan Order ID: `{order_info['order_id']}`.",
                ephemeral=True
            )

        # Invoice Embed
        invoice_embed = discord.Embed(
            title="🎉 Pembelian Berhasil!",
            description=(
                f"Terima kasih telah membeli **{order_info['product_name']}**!\n"
                f"File produk digital Anda telah disertakan di bawah ini."
            ),
            color=discord.Color.green()
        )
        invoice_embed.add_field(name="Order ID", value=f"`{order_info['order_id']}`", inline=True)
        invoice_embed.add_field(name="Total Terpotong", value=f"Rp {order_info['price_paid']:,}", inline=True)
        invoice_embed.add_field(name="Sisa Saldo", value=f"Rp {order_info['remaining_balance']:,}", inline=True)
        invoice_embed.set_footer(text="Automated Store Delivery System")

        # Pengiriman File: Coba ke Direct Message (DM) terlebih dahulu
        dm_sent = False
        try:
            discord_file_dm = discord.File(str(file_obj), filename=file_obj.name)
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
        discord_file_ephemeral = discord.File(str(file_obj), filename=file_obj.name)
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
                log_embed.add_field(name="Harga", value=f"Rp {order_info['price_paid']:,}", inline=True)
                log_embed.add_field(name="Order ID", value=f"`{order_info['order_id']}`", inline=True)
                await log_channel.send(embed=log_embed)

    @ui.button(label="Batal", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass
