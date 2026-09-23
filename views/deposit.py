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
                    await ticket_inter.delete_original_response()
                except Exception as e:
                    logger.debug("Gagal menghapus ticket message: %s", e)

        # 2. Kirim pesan notifikasi Approved ke channel store tempat user melakukan deposit
        target_channel_id = session.get("channel_id") if session else (data.get("channel_id") if data else None)
        target_channel = interaction.client.get_channel(target_channel_id) if target_channel_id else None

        target_user = None
        try:
            target_user = await interaction.client.fetch_user(self.user_id)
        except Exception:
            pass

        if target_channel and target_user:
            embed_notif = discord.Embed(
                title="✅ Deposit Saldo Disetujui (APPROVED)",
                description=(
                    f"Halo {target_user.mention}, permintaan deposit saldo Anda sebesar **Rp {self.amount:,}** telah **DISETUJUI**!\n"
                    f"Saldo telah berhasil masuk ke akun Anda. Selamat berbelanja!"
                ),
                color=discord.Color.green()
            )
            embed_notif.set_footer(text=f"Deposit ID: {self.deposit_id} • Diproses oleh {interaction.user.display_name}")
            try:
                await target_channel.send(content=target_user.mention, embed=embed_notif)
            except Exception as e:
                logger.error("Gagal mengirim notifikasi channel: %s", e)

        # 3. Kirim notifikasi DM ke user
        if target_user:
            try:
                dm_embed = discord.Embed(
                    title="🎉 Deposit Anda Telah Disetujui!",
                    description=(
                        f"Deposit ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** telah berhasil ditambahkan ke saldo akun Anda!\n"
                        f"Silakan gunakan tombol **Cek Balance** atau **Beli Produk** di toko."
                    ),
                    color=discord.Color.green()
                )
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

        # 1. Hapus pesan formulir & tiket deposit dari layar user
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
                    await ticket_inter.delete_original_response()
                except Exception as e:
                    logger.debug("Gagal menghapus ticket message: %s", e)

        # 2. Kirim notifikasi pesan Rejected ke channel store tempat user melakukan deposit
        target_channel_id = session.get("channel_id") if session else (data.get("channel_id") if data else None)
        target_channel = interaction.client.get_channel(target_channel_id) if target_channel_id else None

        target_user = None
        try:
            target_user = await interaction.client.fetch_user(self.user_id)
        except Exception:
            pass

        if target_channel and target_user:
            embed_notif = discord.Embed(
                title="❌ Deposit Saldo Ditolak (REJECTED)",
                description=(
                    f"Halo {target_user.mention}, permintaan deposit saldo Anda sebesar **Rp {self.amount:,}** telah **DITOLAK** oleh admin.\n"
                    f"Pastikan bukti transfer valid atau silakan hubungi staff admin jika butuh bantuan."
                ),
                color=discord.Color.red()
            )
            embed_notif.set_footer(text=f"Deposit ID: {self.deposit_id} • Diproses oleh {interaction.user.display_name}")
            try:
                await target_channel.send(content=target_user.mention, embed=embed_notif)
            except Exception as e:
                logger.error("Gagal mengirim notifikasi channel: %s", e)

        # 3. Beritahu user via DM
        if target_user:
            try:
                dm_embed = discord.Embed(
                    title="⚠️ Deposit Anda Ditolak",
                    description=(
                        f"Permintaan deposit ID `{self.deposit_id}` sebesar **Rp {self.amount:,}** ditolak oleh admin.\n"
                        f"Pastikan bukti transfer valid atau hubungi staff support kami."
                    ),
                    color=discord.Color.red()
                )
                await target_user.send(embed=dm_embed)
            except Exception as e:
                logger.warning("Gagal mengirim DM penolakan ke user %d: %s", self.user_id, str(e))
