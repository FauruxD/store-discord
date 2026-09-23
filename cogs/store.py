import discord
from discord.ext import commands
from discord import app_commands
import logging

import config

logger = logging.getLogger("StoreBot.Cogs.Store")

class StoreCog(commands.Cog):
    """
    Cog untuk menangani interaksi store publik, seperti slash command /deposit dengan upload gambar.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="deposit",
        description="Ajukan deposit saldo dengan langsung mengunggah foto/screenshot bukti transfer."
    )
    @app_commands.describe(
        nominal="Nominal transfer dalam Rupiah (contoh: 20000)",
        bukti="Upload foto / gambar screenshot bukti transfer Anda (JPG, PNG)"
    )
    async def deposit_slash(
        self,
        interaction: discord.Interaction,
        nominal: int,
        bukti: discord.Attachment
    ):
        """Mengajukan permintaan top-up saldo dengan file attachment gambar bukti transfer."""
        if nominal < 1000:
            return await interaction.response.send_message(
                "❌ **Minimal deposit adalah Rp 1.000!**",
                ephemeral=True
            )

        # Validasi file attachment adalah gambar
        if bukti.content_type and not bukti.content_type.startswith("image/"):
            return await interaction.response.send_message(
                "❌ **File yang diunggah harus berupa foto / gambar screenshot bukti transfer (JPG, PNG)!**",
                ephemeral=True
            )

        # Simpan tiket deposit ke database
        deposit_id = await self.bot.db.create_deposit_request(
            user_id=interaction.user.id,
            amount=nominal,
            proof_url=bukti.url,
            channel_id=interaction.channel_id
        )

        # Respon ephemeral (100% privat, hanya user yang melihat)
        embed_user = discord.Embed(
            title="📥 Tiket Deposit Berhasil Diajukan",
            description=(
                f"Permintaan deposit Anda telah dicatat dengan ID: `{deposit_id}`.\n"
                f"Staff admin kami akan segera memverifikasi bukti pembayaran Anda.\n"
                f"Notifikasi hasil approval akan dikirimkan langsung ke **Private Message (DM)** Anda."
            ),
            color=discord.Color.blue()
        )
        embed_user.add_field(name="Nominal", value=f"Rp {nominal:,}", inline=True)
        embed_user.add_field(name="Status", value="⏳ Menunggu Verifikasi", inline=True)
        embed_user.set_thumbnail(url=bukti.url)
        embed_user.set_footer(text="Saldo akan masuk otomatis setelah disetujui admin.")

        await interaction.response.send_message(embed=embed_user, ephemeral=True)

        # Simpan sesi interaksi di memory bot agar auto-delete saat admin approve/reject
        if not hasattr(interaction.client, "active_deposit_sessions"):
            interaction.client.active_deposit_sessions = {}

        interaction.client.active_deposit_sessions[deposit_id] = {
            "instruction_interaction": None,
            "ticket_interaction": interaction,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "amount": nominal
        }

        # Kirim notifikasi tiket ke channel log staff/admin
        if config.DEPOSIT_LOG_CHANNEL_ID:
            log_channel = interaction.client.get_channel(config.DEPOSIT_LOG_CHANNEL_ID)
            if log_channel:
                embed_admin = discord.Embed(
                    title="🔔 Tiket Deposit Baru (Upload Gambar)",
                    description=f"User {interaction.user.mention} (`{interaction.user.id}`) mengajukan deposit saldo.",
                    color=discord.Color.gold()
                )
                embed_admin.add_field(name="Deposit ID", value=f"`{deposit_id}`", inline=True)
                embed_admin.add_field(name="Nominal", value=f"**Rp {nominal:,}**", inline=True)
                embed_admin.add_field(name="File Bukti", value=f"[Lihat Gambar Full Resolusi]({bukti.url})", inline=False)
                embed_admin.set_image(url=bukti.url)
                embed_admin.set_footer(text=f"User ID: {interaction.user.id}")

                from views.deposit import AdminDepositApprovalView
                view = AdminDepositApprovalView(self.bot.db, deposit_id, interaction.user.id, nominal)
                await log_channel.send(embed=embed_admin, view=view)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global error handler untuk slash command."""
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message(
                "⛔ **Akses Ditolak!** Anda memerlukan izin Administrator untuk menjalankan perintah ini.",
                ephemeral=True
            )
        elif isinstance(error, app_commands.CommandOnCooldown):
            return await interaction.response.send_message(
                f"⏳ Mohon tunggu {error.retry_after:.1f} detik sebelum mencoba lagi.",
                ephemeral=True
            )

        logger.error("Terjadi error pada perintah %s: %s", interaction.command.name if interaction.command else "Unknown", str(error))
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Terjadi kesalahan saat mengeksekusi perintah. Silakan laporkan ke admin.",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(StoreCog(bot))
