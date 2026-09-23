import aiosqlite
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("StoreBot.Database")

class DatabaseManager:
    """
    Mengelola seluruh operasi I/O database secara asinkron menggunakan aiosqlite.
    Menjamin integritas data saldo dan stok produk dengan transaksi atomik (ACID).
    """

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)

    async def init_db(self, schema_file: Optional[Path | str] = None) -> None:
        """Inisialisasi tabel SQLite berdasarkan file schema.sql."""
        if schema_file is None:
            schema_file = Path(__file__).resolve().parent / "schema.sql"

        with open(schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.executescript(schema_sql)
            try:
                await db.execute("ALTER TABLE deposits ADD COLUMN channel_id INTEGER;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE products ADD COLUMN product_type TEXT NOT NULL DEFAULT 'FILE';")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN delivered_data TEXT;")
            except Exception:
                pass
            await db.commit()
            logger.info("Database berhasil diinisialisasi pada: %s", self.db_path)

    # =========================================================================
    # USER & SALDO
    # =========================================================================

    async def get_or_create_user(self, user_id: int) -> Dict[str, Any]:
        """Mengambil data pengguna atau membuat pengguna baru jika belum terdaftar."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT user_id, balance, created_at FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)

            # Insert pengguna baru dengan saldo 0
            await db.execute(
                "INSERT INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,)
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT user_id, balance, created_at FROM users WHERE user_id = ?",
                (user_id,)
            )
            new_row = await cursor.fetchone()
            return dict(new_row) if new_row else {"user_id": user_id, "balance": 0}

    async def get_balance(self, user_id: int) -> int:
        """Mengambil sisa saldo pengguna."""
        user = await self.get_or_create_user(user_id)
        return int(user.get("balance", 0))

    async def add_balance(self, user_id: int, amount: int) -> int:
        """
        Menambahkan atau mengurangi saldo pengguna secara langsung.
        Nilai amount negatif berarti pengurangan saldo.
        """
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()
            
            cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    # =========================================================================
    # SISTEM DEPOSIT / TOP-UP
    # =========================================================================

    async def create_deposit_request(
        self, user_id: int, amount: int, proof_url: str = "", channel_id: Optional[int] = None
    ) -> str:
        """Membuat tiket permintaan top-up baru."""
        deposit_id = f"DEP-{uuid.uuid4().hex[:8].upper()}"
        await self.get_or_create_user(user_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO deposits (deposit_id, user_id, amount, proof_url, channel_id, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
                """,
                (deposit_id, user_id, amount, proof_url, channel_id)
            )
            await db.commit()

        logger.info("Permintaan deposit dibuat: %s oleh User %d (Rp %s)", deposit_id, user_id, f"{amount:,}")
        return deposit_id

    async def get_deposit_request(self, deposit_id: str) -> Optional[Dict[str, Any]]:
        """Mengambil detail permintaan deposit."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM deposits WHERE deposit_id = ?",
                (deposit_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def process_deposit(
        self, deposit_id: str, approved: bool, reviewed_by: int
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Memproses persetujuan atau penolakan deposit oleh Admin.
        Jika disetujui, saldo user otomatis bertambah dalam 1 transaksi atomik.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM deposits WHERE deposit_id = ?", (deposit_id,))
            row = await cursor.fetchone()

            if not row:
                return False, "Tiket deposit tidak ditemukan.", None

            deposit = dict(row)
            if deposit["status"] != "PENDING":
                return False, f"Deposit sudah diproses sebelumnya dengan status: {deposit['status']}.", None

            new_status = "APPROVED" if approved else "REJECTED"

            try:
                await db.execute("BEGIN IMMEDIATE;")
                # Update status deposit
                await db.execute(
                    """
                    UPDATE deposits
                    SET status = ?, reviewed_by = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE deposit_id = ?
                    """,
                    (new_status, reviewed_by, deposit_id)
                )

                # Jika disetujui, tambahkan saldo pengguna
                if approved:
                    await db.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                        (deposit["amount"], deposit["user_id"])
                    )

                await db.commit()
                deposit["status"] = new_status
                deposit["reviewed_by"] = reviewed_by
                return True, f"Deposit {deposit_id} berhasil di-{new_status.lower()}.", deposit
            except Exception as e:
                await db.rollback()
                logger.error("Gagal memproses deposit %s: %s", deposit_id, str(e))
                return False, f"Terjadi kesalahan database: {str(e)}", None

    # =========================================================================
    # PRODUK & KATALOG
    # =========================================================================

    async def add_or_update_product(
        self, product_id: str, name: str, description: str, price: int, stock: int, file_path: str, product_type: str = "FILE"
    ) -> None:
        """Menambahkan produk baru atau memperbarui produk yang ada."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO products (product_id, name, description, price, stock, file_path, product_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    price = excluded.price,
                    stock = excluded.stock,
                    file_path = excluded.file_path,
                    product_type = excluded.product_type
                """,
                (product_id, name, description, price, stock, file_path, product_type)
            )
            await db.commit()
            logger.info("Produk '%s' (%s - %s) berhasil disimpan.", name, product_id, product_type)

    async def add_account_stock(self, product_id: str, account_lines: List[str]) -> int:
        """
        Menambahkan daftar akun digital (1 baris per akun) ke database.
        Otomatis meng-update stok produk berdasarkan jumlah akun yang belum terjual.
        """
        valid_lines = [line.strip() for line in account_lines if line.strip()]
        if not valid_lines:
            return 0

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE;")
            for line in valid_lines:
                await db.execute(
                    "INSERT INTO product_accounts (product_id, account_data, is_sold) VALUES (?, ?, 0)",
                    (product_id, line)
                )

            # Hitung total stok akun yang belum terjual
            cursor = await db.execute(
                "SELECT COUNT(*) FROM product_accounts WHERE product_id = ? AND is_sold = 0",
                (product_id,)
            )
            row = await cursor.fetchone()
            total_unsold = row[0] if row else 0

            # Update jumlah stok di tabel products & pastikan tipe produk adalah ACCOUNT
            await db.execute(
                "UPDATE products SET stock = ?, product_type = 'ACCOUNT' WHERE product_id = ?",
                (total_unsold, product_id)
            )
            await db.commit()

        logger.info("Berhasil menambahkan %d akun ke produk %s. Total stok sekarang: %d", len(valid_lines), product_id, total_unsold)
        return len(valid_lines)

    async def get_unsold_accounts_count(self, product_id: str) -> int:
        """Mengambil jumlah akun yang belum terjual untuk produk tertentu."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM product_accounts WHERE product_id = ? AND is_sold = 0",
                (product_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def delete_product(self, product_id: str) -> bool:
        """Menghapus produk dari database."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_stock(self, product_id: str, new_stock: int) -> bool:
        """Memperbarui stok produk."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("UPDATE products SET stock = ? WHERE product_id = ?", (new_stock, product_id))
            await db.commit()
            return cursor.rowcount > 0

    async def update_price(self, product_id: str, new_price: int) -> bool:
        """Memperbarui harga produk."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("UPDATE products SET price = ? WHERE product_id = ?", (new_price, product_id))
            await db.commit()
            return cursor.rowcount > 0

    async def get_available_products(self) -> List[Dict[str, Any]]:
        """Mengambil seluruh daftar produk yang memiliki stok > 0."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM products WHERE stock > 0 ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_all_products(self) -> List[Dict[str, Any]]:
        """Mengambil seluruh daftar produk (termasuk yang stoknya 0) untuk manajemen admin."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM products ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Mengambil detail satu produk berdasarkan ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    # =========================================================================
    # CHECKOUT & TRANSAKSI PEMBELIAN (ATOMIC)
    # =========================================================================

    async def purchase_product(
        self, user_id: int, product_id: str, quantity: int = 1
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Menjalankan transaksi pembelian secara ATOMIC dengan dukungan Quantity & Akun per baris:
        1. Memeriksa keberadaan user & produk.
        2. Memastikan stok produk >= quantity.
        3. Memastikan saldo user mencukupi (balance >= price * quantity).
        4. Jika produk bertipe 'ACCOUNT', mengambil N baris akun unik yang belum terjual,
           lalu membuat file order .txt secara otomatis (1 baris per akun).
        5. Memotong saldo user.
        6. Mengurangi stok produk sebanyak quantity.
        7. Mencatat riwayat pesanan (orders).
        Semua step di atas dieksekusi dalam satu transaksi database untuk mencegah double-spend & double-delivery.
        """
        quantity = max(1, int(quantity))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                await db.execute("BEGIN IMMEDIATE;")

                # Ambil atau buat data user
                cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_row = await cursor.fetchone()
                if not user_row:
                    await db.execute("INSERT INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
                    current_balance = 0
                else:
                    current_balance = user_row["balance"]

                # Ambil data produk
                cursor = await db.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
                prod_row = await cursor.fetchone()

                if not prod_row:
                    await db.rollback()
                    return False, "Produk yang dipilih tidak ditemukan atau telah dihapus.", None

                product = dict(prod_row)
                price = product["price"]
                stock = product["stock"]
                product_type = product.get("product_type", "FILE")
                total_price = price * quantity

                # Validasi stok
                if stock <= 0:
                    await db.rollback()
                    return False, f"Maaf, stok untuk produk **{product['name']}** sedang habis!", None

                if stock < quantity:
                    await db.rollback()
                    return False, (
                        f"Maaf, stok untuk produk **{product['name']}** tidak mencukupi!\n"
                        f"• Sisa Stok: **{stock} unit**\n"
                        f"• Diminta: **{quantity} unit**"
                    ), None

                # Validasi saldo
                if current_balance < total_price:
                    await db.rollback()
                    shortage = total_price - current_balance
                    return False, (
                        f"Saldo Anda tidak mencukupi!\n"
                        f"• Harga Satuan: **Rp {price:,}** (Qty: {quantity})\n"
                        f"• Total Tagihan: **Rp {total_price:,}**\n"
                        f"• Saldo Anda: **Rp {current_balance:,}**\n"
                        f"• Kekurangan: **Rp {shortage:,}**\n"
                        f"Silakan lakukan **Deposit** terlebih dahulu."
                    ), None

                # Generate Order ID
                order_id = f"INV-{uuid.uuid4().hex[:10].upper()}"
                delivered_file_path = product["file_path"]
                delivered_data_str = ""
                delivered_lines = []

                # JIKA PRODUK BERUPA AKUN: Ambil akun unik dari product_accounts
                if product_type == "ACCOUNT":
                    acc_cursor = await db.execute(
                        """
                        SELECT account_id, account_data FROM product_accounts
                        WHERE product_id = ? AND is_sold = 0
                        LIMIT ?
                        """,
                        (product_id, quantity)
                    )
                    acc_rows = await acc_cursor.fetchall()
                    if len(acc_rows) < quantity:
                        await db.rollback()
                        return False, f"Maaf, akun yang tersedia tidak mencukupi permintaan ({len(acc_rows)}/{quantity})!", None

                    account_ids = [r["account_id"] for r in acc_rows]
                    delivered_lines = [r["account_data"] for r in acc_rows]
                    delivered_data_str = "\n".join(delivered_lines)

                    # Tandai akun sebagai terjual
                    for aid in account_ids:
                        await db.execute(
                            """
                            UPDATE product_accounts
                            SET is_sold = 1, order_id = ?, sold_at = CURRENT_TIMESTAMP
                            WHERE account_id = ?
                            """,
                            (order_id, aid)
                        )

                    # Buat file .txt pengiriman
                    orders_dir = Path(__file__).resolve().parent.parent / "assets" / "orders"
                    orders_dir.mkdir(parents=True, exist_ok=True)
                    account_file = orders_dir / f"{order_id}.txt"
                    with open(account_file, "w", encoding="utf-8") as f:
                        f.write(delivered_data_str)

                    delivered_file_path = str(account_file)

                # 1. Potong Saldo
                await db.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                    (total_price, user_id)
                )

                # 2. Kurangi Stok
                await db.execute(
                    "UPDATE products SET stock = stock - ? WHERE product_id = ?",
                    (quantity, product_id)
                )

                # 3. Catat Order
                await db.execute(
                    """
                    INSERT INTO orders (order_id, user_id, product_id, price_paid, quantity, delivered_data, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED')
                    """,
                    (order_id, user_id, product_id, total_price, quantity, delivered_data_str)
                )

                await db.commit()

                order_info = {
                    "order_id": order_id,
                    "user_id": user_id,
                    "product_id": product_id,
                    "product_name": product["name"],
                    "product_type": product_type,
                    "quantity": quantity,
                    "unit_price": price,
                    "price_paid": total_price,
                    "remaining_balance": current_balance - total_price,
                    "file_path": delivered_file_path,
                    "delivered_lines": delivered_lines
                }

                logger.info(
                    "Pembelian Sukses: %s oleh User %d untuk Produk %s (Qty: %d, Total: Rp %s)",
                    order_id, user_id, product["name"], quantity, f"{total_price:,}"
                )
                return True, "Pembelian berhasil diproses!", order_info

            except Exception as e:
                await db.rollback()
                logger.error("Terjadi error transaksi pembelian: %s", str(e))
                return False, f"Terjadi kesalahan sistem saat memproses transaksi: {str(e)}", None
