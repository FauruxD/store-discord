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

    print("\n=== [10] Pengujian Produk Akun & Pembelian Multi-Qty (.txt delivery) ===")
    # Tambah produk tipe ACCOUNT
    acc_dummy_path = BASE_DIR / "assets" / "products" / "test_accounts.txt"
    acc_dummy_path.touch(exist_ok=True)
    await db.add_or_update_product(
        product_id="test_acc",
        name="Akun Streaming Premium",
        description="Akun streaming 1 bulan",
        price=10000,
        stock=0,
        file_path=str(acc_dummy_path),
        product_type="ACCOUNT"
    )

    # Restock 5 akun
    account_pool = [
        "user1@mail.com:pass123",
        "user2@mail.com:secret456",
        "user3@mail.com:qwerty789",
        "user4@mail.com:letmein10",
        "user5@mail.com:pass5555"
    ]
    added = await db.add_account_stock("test_acc", account_pool)
    assert added == 5
    prod_acc = await db.get_product("test_acc")
    assert prod_acc["stock"] == 5
    assert prod_acc["product_type"] == "ACCOUNT"
    print(f"-> 5 Akun berhasil di-restock ke produk '{prod_acc['name']}' (Stok: {prod_acc['stock']})")

    # Siapkan balance user untuk beli 2 akun (Rp 20,000)
    buyer_id = 8888888888
    await db.add_balance(buyer_id, 50000)

    # Pembelian Qty = 2
    success_buy_acc, msg_acc, order_acc = await db.purchase_product(buyer_id, "test_acc", quantity=2)
    assert success_buy_acc is True
    assert order_acc["quantity"] == 2
    assert order_acc["price_paid"] == 20000  # 10000 * 2
    assert order_acc["remaining_balance"] == 30000
    print(f"-> Pembelian 2 akun sukses! Total terpotong: Rp {order_acc['price_paid']:,}")

    # Verifikasi file .txt yang digenerate
    delivered_file = Path(order_acc["file_path"])
    assert delivered_file.exists(), f"File {delivered_file} harus digenerate!"
    with open(delivered_file, "r", encoding="utf-8") as f:
        file_lines = f.read().splitlines()

    assert len(file_lines) == 2, f"Harus ada 2 akun di file, didapat: {len(file_lines)}"
    assert file_lines[0] == "user1@mail.com:pass123"
    assert file_lines[1] == "user2@mail.com:secret456"
    print(f"-> File .txt berhasil digenerate ({delivered_file.name}):")
    for line in file_lines:
        print(f"   {line}")

    # Verifikasi sisa stok akun di database (harus 3)
    prod_acc_after = await db.get_product("test_acc")
    assert prod_acc_after["stock"] == 3
    unsold_count = await db.get_unsold_accounts_count("test_acc")
    assert unsold_count == 3

    # Verifikasi detail akun tersisa dan statistik stok
    stock_details = await db.get_account_stock_details("test_acc")
    assert stock_details["unsold_count"] == 3
    assert stock_details["sold_count"] == 2
    assert stock_details["total_count"] == 5
    assert len(stock_details["unsold_accounts"]) == 3
    assert stock_details["unsold_accounts"][0] == "user3@mail.com:qwerty789"
    print(f"-> Sisa stok akun setelah pembelian: {prod_acc_after['stock']} unit (Unsold: {stock_details['unsold_count']}, Sold: {stock_details['sold_count']})")

    # Coba beli Qty = 4 (Stok hanya 3, harus ditolak)
    fail_qty_success, fail_qty_msg, _ = await db.purchase_product(buyer_id, "test_acc", quantity=4)
    assert fail_qty_success is False
    assert "tidak mencukupi" in fail_qty_msg
    print(f"-> Pembelian melebihi sisa stok berhasil dicegah: {fail_qty_msg.splitlines()[0]}")

    # Beli sisa 3 akun
    buy_all_success, _, order_all = await db.purchase_product(buyer_id, "test_acc", quantity=3)
    assert buy_all_success is True
    assert order_all["quantity"] == 3
    prod_acc_empty = await db.get_product("test_acc")
    assert prod_acc_empty["stock"] == 0
    print(f"-> Pembelian sisa 3 akun sukses! Stok sekarang: {prod_acc_empty['stock']} unit")

    # Cleanup file order test
    if delivered_file.exists():
        delivered_file.unlink()
    order_all_file = Path(order_all["file_path"])
    if order_all_file.exists():
        order_all_file.unlink()
    if acc_dummy_path.exists():
        acc_dummy_path.unlink()

    # Cleanup DB
    if test_db_path.exists():
        test_db_path.unlink()
    print("\n✅ SEMUA PENGUJIAN DATABASE & TRANSAKSI STORE LOLOS 100%!")

if __name__ == "__main__":
    asyncio.run(run_tests())
