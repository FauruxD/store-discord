import discord
from discord import ui
import logging
from typing import Optional
import config

logger = logging.getLogger("StoreBot.Views.Review")

class ReviewModal(ui.Modal, title="Beri Ulasan & Testimoni"):
    rating_input = ui.TextInput(
        label="Rating Bintang (1 - 5)",
        placeholder="Ketik angka 1 sampai 5 (contoh: 5)",
        required=True,
        min_length=1,
        max_length=1
    )
    comment_input = ui.TextInput(
        label="Ulasan / Pengalaman Berbelanja",
        style=discord.TextStyle.paragraph,
        placeholder="Tuliskan ulasan Anda mengenai produk & layanan kami...",
        required=True,
        min_length=3,
        max_length=500
    )

    def __init__(self, db_manager, order_id: str, product_id: str, product_name: str):
        super().__init__()
        self.db = db_manager
        self.order_id = order_id
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        raw_rating = self.rating_input.value.strip()
        if not raw_rating.isdigit() or int(raw_rating) not in range(1, 6):
            return await interaction.response.send_message(
                "❌ Masukkan rating berupa angka 1 sampai 5!", ephemeral=True
            )

        rating = int(raw_rating)
        comment = self.comment_input.value.strip()

        success, msg = await self.db.record_review(
            self.order_id, interaction.user.id, self.product_id, rating, comment
        )
        if not success:
            return await interaction.response.send_message(f"⚠️ {msg}", ephemeral=True)

        # Broadcast ulasan ke channel testimoni jika dikonfigurasi
        if config.TESTIMONIAL_CHANNEL_ID:
            testi_channel = interaction.client.get_channel(config.TESTIMONIAL_CHANNEL_ID)
            if testi_channel:
                stars_text = "⭐" * rating
                embed = discord.Embed(
                    title=f"⭐ Testimoni Pelanggan: {self.product_name}",
                    description=f"\"{comment}\"",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Rating", value=f"{stars_text} ({rating}/5)", inline=True)
                embed.add_field(name="Pelanggan", value=interaction.user.mention, inline=True)
                embed.add_field(name="Order ID", value=f"`{self.order_id}`", inline=True)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                embed.set_footer(text="Terima kasih atas kepercayaannya berbelanja di store kami!")

                try:
                    await testi_channel.send(embed=embed)
                except Exception as e:
                    logger.error("Gagal mengirim embed testimoni ke channel %d: %s", config.TESTIMONIAL_CHANNEL_ID, e)

        await interaction.response.send_message(
            f"✅ **Terima kasih!** Ulasan Anda dengan rating **{'⭐' * rating}** berhasil disimpan dan dibagikan ke channel testimoni.",
            ephemeral=True
        )


class GiveReviewView(ui.View):
    """View berisi tombol untuk membuka ReviewModal setelah pembelian sukses."""
    def __init__(self, db_manager, order_id: str, product_id: str, product_name: str):
        super().__init__(timeout=180)
        self.db = db_manager
        self.order_id = order_id
        self.product_id = product_id
        self.product_name = product_name

    @ui.button(label="Beri Testimoni", style=discord.ButtonStyle.primary, emoji="⭐")
    async def review_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Cek apakah sudah pernah direview
        already_reviewed = await self.db.has_order_been_reviewed(self.order_id)
        if already_reviewed:
            button.disabled = True
            await interaction.response.edit_message(view=self)
            return await interaction.followup.send(
                "ℹ️ Anda sudah pernah memberikan ulasan untuk pesanan ini. Terima kasih!",
                ephemeral=True
            )

        await interaction.response.send_modal(
            ReviewModal(self.db, self.order_id, self.product_id, self.product_name)
        )
