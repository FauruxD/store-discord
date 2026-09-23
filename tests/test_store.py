import asyncio
import os
import sys
from pathlib import Path

# Tambahkan direktori root proyek ke sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from database.manager import DatabaseManager

async def run_tests():
    test_db_path = BASE_DIR / "tests" / "test_store.db"
    if test_db_path.exists():
        test_db_path.unlink()

    print("=== [1] Inisialisasi Database Test ===")
    db = DatabaseManager(test_db_path)
    await db.init_db()
    print("-> Database berhasil diinisialisasi.")

    test_user_id = 9988776655
    admin_id = 1122334455

    print("\n=== [2] Pengujian User & Saldo ===")
    user = await db.get_or_create_user(test_user_id)
    assert user["balance"] == 0, f"Saldo awal harus 0, didapat: {user['balance']}"
    print("-> User baru otomatis dibuat dengan saldo Rp 0.")

    print("\n=== [3] Pengujian Tiket Deposit & Approval Admin ===")
    dep_id = await db.create_deposit_request(test_user_id, 50000, "https://imgur.com/sample_proof")
    print(f"-> Tiket deposit dibuat: {dep_id}")
    dep_data = await db.get_deposit_request(dep_id)
    assert dep_data["status"] == "PENDING"
    assert dep_data["amount"] == 50000

    # Approve deposit
    success, msg, processed = await db.process_deposit(dep_id, approved=True, reviewed_by=admin_id)
    assert success is True
    assert processed["status"] == "APPROVED"

    balance_after = await db.get_balance(test_user_id)
    assert balance_after == 50000, f"Saldo setelah approval harus 50000, didapat: {balance_after}"
    print(f"-> Deposit disetujui, saldo sekarang: Rp {balance_after:,}")

    print("\n=== [4] Pengujian Penambahan Produk ===")
    sample_file = BASE_DIR / "assets" / "products" / "premium_script.lua"
    await db.add_or_update_product(
        product_id="test_script",
        name="Test Premium Script",
        description="Script uji coba",
        price=30000,
        stock=1,  # Hanya 1 stok untuk tes habis
        file_path=str(sample_file)
    )
    products = await db.get_available_products()
    assert len(products) == 1
    assert products[0]["product_id"] == "test_script"
    print(f"-> Produk berhasil ditambahkan: {products[0]['name']} (Stok: {products[0]['stock']})")

    print("\n=== [5] Pengujian Pembelian Saat Saldo Kurang ===")
    poor_user_id = 1111111111
    fail_success, fail_msg, _ = await db.purchase_product(poor_user_id, "test_script")
    assert fail_success is False
    assert "tidak mencukupi" in fail_msg
    print(f"-> Validasi saldo kurang berhasil dicegah: {fail_msg.splitlines()[0]}")

    print("\n=== [6] Pengujian Transaksi Pembelian Berhasil ===")
    buy_success, buy_msg, order_info = await db.purchase_product(test_user_id, "test_script")
    assert buy_success is True
    assert order_info is not None
    assert order_info["remaining_balance"] == 20000
    assert order_info["product_name"] == "Test Premium Script"
    print(f"-> Pembelian sukses! Order ID: {order_info['order_id']}, Sisa Saldo: Rp {order_info['remaining_balance']:,}")

    # Cek sisa stok produk (harus 0)
    prod = await db.get_product("test_script")
    assert prod["stock"] == 0
    print(f"-> Sisa stok produk di database berkurang menjadi: {prod['stock']}")

    print("\n=== [7] Pengujian Pembelian Saat Stok Habis ===")
    rich_user_id = 2222222222
    await db.add_balance(rich_user_id, 100000)
    oos_success, oos_msg, _ = await db.purchase_product(rich_user_id, "test_script")
    assert oos_success is False
    assert "sedang habis" in oos_msg
    print(f"-> Validasi stok habis berhasil dicegah: {oos_msg}")

    print("\n=== [8] Pengujian Restock Produk ===")
    restock_success = await db.update_stock("test_script", 15)
    assert restock_success is True
    prod_restocked = await db.get_product("test_script")
    assert prod_restocked["stock"] == 15
    print(f"-> Berhasil restock produk menjadi: {prod_restocked['stock']} unit")

    print("\n=== [9] Pengujian Hapus Produk ===")
    delete_success = await db.delete_product("test_script")
    assert delete_success is True
    prod_deleted = await db.get_product("test_script")
    assert prod_deleted is None
    print("-> Produk berhasil dihapus dari database.")

    # Cleanup
    if test_db_path.exists():
        test_db_path.unlink()
    print("\n✅ SEMUA PENGUJIAN DATABASE & TRANSAKSI STORE LOLOS 100%!")

if __name__ == "__main__":
    asyncio.run(run_tests())
