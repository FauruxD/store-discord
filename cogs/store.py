import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger("StoreBot.Cogs.Store")

class StoreCog(commands.Cog):
    """
    Cog untuk menangani event umum dan error handling pada interaksi store.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
