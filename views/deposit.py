import discord
from discord import ui
import logging
from typing import Optional
import config

logger = logging.getLogger("StoreBot.Views.Deposit")

class DepositModal(ui.Modal, title="Konfirmasi Pembayaran Deposit"):
    """
    Modal pop-up bagi user untuk memasukkan nominal transfer dan keterangan/link bukti transfer.
    """
    amount = ui.TextInput(
        label="Nominal Transfer (Rupiah)",
        placeholder="Contoh: 50000 (Hanya angka)",
        required=True,
        min_length=3,
        max_length=9
    )

    proof_info = ui.TextInput(
        label="Link Bukti / Catatan Transfer",
        placeholder="Link gambar (Imgur/Discord) atau nama rekening pengirim",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=250
    )

    def __init__(self, db_manager, instruction_interaction: Optional[discord.Interaction] = None):
        super().__init__()
        self.db = db_manager
        self.instruction_interaction = instruction_interaction

    async def on_submit(self, interaction: discord.Interaction):
        # Validasi nominal angka
        raw_amount = self.amount.value.strip().replace(".", "").replace(",", "")
        if not raw_amount.isdigit():
            return await interaction.response.send_message(
                "❌ **Nominal tidak valid!** Masukkan angka saja tanpa huruf atau simbol.",
                ephemeral=True
            )

        amount_val = int(raw_amount)
        if amount_val < 1000:
            return await interaction.response.send_message(
                "❌ **Minimal deposit adalah Rp 1.000!**",
                ephemeral=True
            )

        # Simpan tiket deposit ke database
        deposit_id = await self.db.create_deposit_request(
            user_id=interaction.user.id,
            amount=amount_val,
            proof_url=self.proof_info.value.strip(),
            channel_id=interaction.channel_id
        )

        # Respon ephemeral ke user
        embed_user = discord.Embed(
            title="📥 Tiket Deposit Telah Diajukan",
            description=(
                f"Permintaan deposit Anda telah dicatat dengan ID: `{deposit_id}`.\n"
                f"Staff admin kami akan segera memverifikasi bukti pembayaran Anda."
            ),
            color=discord.Color.blue()
        )
        embed_user.add_field(name="Nominal", value=f"Rp {amount_val:,}", inline=True)
        embed_user.add_field(name="Status", value="⏳ Menunggu Verifikasi", inline=True)
        embed_user.set_footer(text="Saldo akan masuk otomatis setelah disetujui admin.")
        await interaction.response.send_message(embed=embed_user, ephemeral=True)

        # Simpan sesi interaksi di memory bot agar pesan instruksi & tiket bisa langsung dihapus saat admin approve/reject
        if not hasattr(interaction.client, "active_deposit_sessions"):
            interaction.client.active_deposit_sessions = {}

        interaction.client.active_deposit_sessions[deposit_id] = {
            "instruction_interaction": self.instruction_interaction,
            "ticket_interaction": interaction,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "amount": amount_val
        }

        # Kirim notifikasi embed ke channel admin log
        if config.DEPOSIT_LOG_CHANNEL_ID:
            log_channel = interaction.client.get_channel(config.DEPOSIT_LOG_CHANNEL_ID)
            if log_channel:
                embed_admin = discord.Embed(
                    title="🔔 Tiket Deposit Baru Masuk",
                    description=f"User {interaction.user.mention} (`{interaction.user.id}`) mengajukan deposit saldo.",
                    color=discord.Color.gold()
                )
                embed_admin.add_field(name="Deposit ID", value=f"`{deposit_id}`", inline=True)
                embed_admin.add_field(name="Nominal", value=f"**Rp {amount_val:,}**", inline=True)
                embed_admin.add_field(name="Bukti / Keterangan", value=self.proof_info.value.strip(), inline=False)
                if self.proof_info.value.strip().startswith("http"):
                    embed_admin.set_image(url=self.proof_info.value.strip())
                embed_admin.set_footer(text=f"User ID: {interaction.user.id}")

                view = AdminDepositApprovalView(self.db, deposit_id, interaction.user.id, amount_val)
                await log_channel.send(embed=embed_admin, view=view)


class AdminDepositApprovalView(ui.View):
    """
    View dengan tombol Approve dan Reject untuk diproses oleh Admin/Staff di channel log.
    """
    def __init__(self, db_manager, deposit_id: str, user_id: int, amount: int):
        super().__init__(timeout=None)
        self.db = db_manager
        self.deposit_id = deposit_id
        self.user_id = user_id
        self.amount = amount

        # Custom ID dinamis untuk persistent tracking
        self.approve_btn.custom_id = f"dep_approve_{deposit_id}"
        self.reject_btn.custom_id = f"dep_reject_{deposit_id}"

    @ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Validasi role admin jika di-set
        if config.ADMIN_ROLE_ID and not any(r.id == config.ADMIN_ROLE_ID for r in interaction.user.roles):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Anda tidak memiliki izin untuk menyetujui deposit ini!",
                    ephemeral=True
                )

        success, msg, data = await self.db.process_deposit(
            deposit_id=self.deposit_id,
            approved=True,
            reviewed_by=interaction.user.id
        )

        if not success:
            return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

        # Nonaktifkan tombol setelah diproses
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Deposit Disetujui (APPROVED)"
        embed.add_field(name="Diverifikasi Oleh", value=interaction.user.mention, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        # 1. Hapus pesan formulir & tiket deposit dari layar user
        # 1. Update pesan tiket di layar user menjadi Private Message "Deposit Berhasil"
        session = getattr(interaction.client, "active_deposit_sessions", {}).pop(self.deposit_id, None)
        if session:
            inst_inter = session.get("instruction_interaction")
            if inst_inter:
                try:
                    await inst_inter.delete_original_response()
                except Exception as e:
                    logger.debug("Gagal menghapus instruction message: %s", e)

            ticket_inter = session.get("ticket_interaction")
            if ticket_inter:
                try:
                    user_ok_embed = discord.Embed(
                        title="✅ Deposit Berhasil Disetujui!",
                        description=(
                            f"Permintaan deposit saldo ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** "
                            f"telah **DISETUJUI** oleh admin.\n\n"
                            f"Saldo Anda telah berhasil ditambahkan. Silakan buka menu **Beli Produk** untuk berbelanja!"
                        ),
                        color=discord.Color.green()
                    )
                    user_ok_embed.set_footer(text="Hanya Anda yang dapat melihat pesan ini • Store Bot")
                    await ticket_inter.edit_original_response(embed=user_ok_embed, view=None)
                except Exception as e:
                    logger.debug("Gagal mengupdate ticket message: %s", e)

        # 2. Kirim notifikasi secara PRIVAT (DM / Private Message) ke user
        try:
            target_user = await interaction.client.fetch_user(self.user_id)
            if target_user:
                dm_embed = discord.Embed(
                    title="✅ Deposit Saldo Disetujui (APPROVED)!",
                    description=(
                        f"Halo {target_user.name}!\n"
                        f"Permintaan deposit saldo ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** telah **DISETUJUI** oleh admin.\n\n"
                        f"Saldo telah berhasil masuk ke akun Anda. Selamat berbelanja di toko!"
                    ),
                    color=discord.Color.green()
                )
                dm_embed.set_footer(text="Automated Digital Store System • Private Notification")
                await target_user.send(embed=dm_embed)
        except Exception as e:
            logger.warning("Gagal mengirim DM notifikasi ke user %d: %s", self.user_id, str(e))

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Validasi role admin jika di-set
        if config.ADMIN_ROLE_ID and not any(r.id == config.ADMIN_ROLE_ID for r in interaction.user.roles):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Anda tidak memiliki izin untuk menolak deposit ini!",
                    ephemeral=True
                )

        success, msg, data = await self.db.process_deposit(
            deposit_id=self.deposit_id,
            approved=False,
            reviewed_by=interaction.user.id
        )

        if not success:
            return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Deposit Ditolak (REJECTED)"
        embed.add_field(name="Ditolak Oleh", value=interaction.user.mention, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        # 1. Update pesan tiket di layar user menjadi Private Message "Deposit Ditolak"
        session = getattr(interaction.client, "active_deposit_sessions", {}).pop(self.deposit_id, None)
        if session:
            inst_inter = session.get("instruction_interaction")
            if inst_inter:
                try:
                    await inst_inter.delete_original_response()
                except Exception as e:
                    logger.debug("Gagal menghapus instruction message: %s", e)

            ticket_inter = session.get("ticket_interaction")
            if ticket_inter:
                try:
                    user_fail_embed = discord.Embed(
                        title="❌ Deposit Ditolak (REJECTED)",
                        description=(
                            f"Permintaan deposit saldo ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** "
                            f"telah **DITOLAK** oleh admin.\n\n"
                            f"Alasan: Bukti transfer tidak valid atau dana belum masuk.\n"
                            f"Silakan hubungi staff admin jika butuh bantuan."
                        ),
                        color=discord.Color.red()
                    )
                    user_fail_embed.set_footer(text="Hanya Anda yang dapat melihat pesan ini • Store Bot")
                    await ticket_inter.edit_original_response(embed=user_fail_embed, view=None)
                except Exception as e:
                    logger.debug("Gagal mengupdate ticket message: %s", e)

        # 2. Kirim notifikasi penolakan secara PRIVAT (DM / Private Message) ke user
        try:
            target_user = await interaction.client.fetch_user(self.user_id)
            if target_user:
                dm_embed = discord.Embed(
                    title="❌ Deposit Saldo Ditolak (REJECTED)",
                    description=(
                        f"Halo {target_user.name}!\n"
                        f"Permintaan deposit saldo ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** telah **DITOLAK** oleh admin.\n\n"
                        f"Pastikan bukti transfer Anda valid atau silakan hubungi staff admin jika butuh bantuan."
                    ),
                    color=discord.Color.red()
                )
                dm_embed.set_footer(text="Automated Digital Store System • Private Notification")
                await target_user.send(embed=dm_embed)
        except Exception as e:
            logger.warning("Gagal mengirim DM penolakan ke user %d: %s", self.user_id, str(e))
