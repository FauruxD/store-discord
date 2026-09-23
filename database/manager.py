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
        self, product_id: str, name: str, description: str, price: int, stock: int, file_path: str
    ) -> None:
        """Menambahkan produk baru atau memperbarui produk yang ada."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO products (product_id, name, description, price, stock, file_path)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    price = excluded.price,
                    stock = excluded.stock,
                    file_path = excluded.file_path
                """,
                (product_id, name, description, price, stock, file_path)
            )
            await db.commit()
            logger.info("Produk '%s' (%s) berhasil disimpan.", name, product_id)

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
        self, user_id: int, product_id: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Menjalankan transaksi pembelian secara ATOMIC:
        1. Memeriksa keberadaan user & produk.
        2. Memastikan stok produk > 0.
        3. Memastikan saldo user mencukupi (balance >= price).
        4. Memotong saldo user.
        5. Mengurangi stok produk sebanyak 1.
        6. Mencatat riwayat pesanan (orders).
        Semua step di atas dieksekusi dalam satu transaksi database untuk mencegah double-spend.
        """
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

                # Validasi stok
                if stock <= 0:
                    await db.rollback()
                    return False, f"Maaf, stok untuk produk **{product['name']}** sedang habis!", None

                # Validasi saldo
                if current_balance < price:
                    await db.rollback()
                    shortage = price - current_balance
                    return False, (
                        f"Saldo Anda tidak mencukupi!\n"
                        f"• Harga Produk: **Rp {price:,}**\n"
                        f"• Saldo Anda: **Rp {current_balance:,}**\n"
                        f"• Kekurangan: **Rp {shortage:,}**\n"
                        f"Silakan lakukan **Deposit** terlebih dahulu."
                    ), None

                # Generate Order ID
                order_id = f"INV-{uuid.uuid4().hex[:10].upper()}"

                # 1. Potong Saldo
                await db.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                    (price, user_id)
                )

                # 2. Kurangi Stok
                await db.execute(
                    "UPDATE products SET stock = stock - 1 WHERE product_id = ?",
                    (product_id,)
                )

                # 3. Catat Order
                await db.execute(
                    """
                    INSERT INTO orders (order_id, user_id, product_id, price_paid, status)
                    VALUES (?, ?, ?, ?, 'COMPLETED')
                    """,
                    (order_id, user_id, product_id, price)
                )

                await db.commit()

                order_info = {
                    "order_id": order_id,
                    "user_id": user_id,
                    "product_id": product_id,
                    "product_name": product["name"],
                    "price_paid": price,
                    "remaining_balance": current_balance - price,
                    "file_path": product["file_path"],
                }

                logger.info(
                    "Pembelian Sukses: %s oleh User %d untuk Produk %s (Rp %s)",
                    order_id, user_id, product["name"], f"{price:,}"
                )
                return True, "Pembelian berhasil diproses!", order_info

            except Exception as e:
                await db.rollback()
                logger.error("Terjadi error transaksi pembelian: %s", str(e))
                return False, f"Terjadi kesalahan sistem saat memproses transaksi: {str(e)}", None
