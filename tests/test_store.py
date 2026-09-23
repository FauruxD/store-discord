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

    print("\n=== [11] Pengujian Edit, Replace, Hapus Spesifik & Kosongkan Akun ===")
    # 1. Tambah 3 akun baru
    await db.add_account_stock("test_acc", ["accA:passA", "accB:passB", "accC:passC"])
    stat1 = await db.get_account_stock_details("test_acc")
    assert stat1["unsold_count"] == 3
    print("-> 3 Akun awal diinput (A, B, C)")

    # 2. Hapus 1 akun spesifik (misal accB rusak)
    deleted_specific = await db.delete_specific_account("test_acc", "accB:passB")
    assert deleted_specific is True
    stat2 = await db.get_account_stock_details("test_acc")
    assert stat2["unsold_count"] == 2
    assert "accB:passB" not in stat2["unsold_accounts"]
    print("-> Berhasil menghapus 1 akun spesifik (accB). Sisa stok: 2")

    # 3. Replace seluruh sisa akun dengan kumpulan akun baru (X, Y, Z, W)
    del_old, add_new = await db.replace_account_stock("test_acc", ["accX:1", "accY:2", "accZ:3", "accW:4"])
    assert del_old == 2  # accA dan accC dihapus
    assert add_new == 4  # X, Y, Z, W dimasukkan
    stat3 = await db.get_account_stock_details("test_acc")
    assert stat3["unsold_count"] == 4
    print(f"-> Berhasil replace akun: {del_old} dihapus, {add_new} akun baru dimasukkan. Sisa stok: 4")

    # 4. Kosongkan semua sisa akun (clear_unsold_accounts)
    cleared = await db.clear_unsold_accounts("test_acc")
    assert cleared == 4
    stat4 = await db.get_account_stock_details("test_acc")
    assert stat4["unsold_count"] == 0
    assert stat4["sold_count"] == 5  # 5 akun yang terjual di step 10 tetap utuh!
    prod_acc_cleared = await db.get_product("test_acc")
    assert prod_acc_cleared["stock"] == 0
    print(f"-> Berhasil kosongkan {cleared} akun belum terjual. Sisa stok: 0, Riwayat terjual: {stat4['sold_count']} (Aman)")

    print("\n=== [12] Pengujian Sistem Voucher Diskon ===")
    # Buat voucher FLAT 5000 (Min spend 20000, max uses 2)
    ok_v1, _ = await db.create_voucher("HEMAT5K", "FLAT", 5000, min_spend=20000, max_uses=2)
    assert ok_v1 is True

    # Buat voucher PERCENT 20% (Tanpa min spend, max uses 1)
    ok_v2, _ = await db.create_voucher("DISKON20", "PERCENT", 20, min_spend=0, max_uses=1)
    assert ok_v2 is True
    print("-> 2 Voucher (HEMAT5K & DISKON20) berhasil dibuat")

    # Siapkan produk & stok untuk tes voucher (tambah 10 akun)
    await db.add_account_stock("test_acc", [f"v_user_{i}@mail.com:pass" for i in range(10)])
    v_buyer_1 = 3333333333
    await db.add_balance(v_buyer_1, 50000)

    # Cek syarat min spend: beli 1 unit (10.000) dengan HEMAT5K (min 20.000) -> harus gagal
    valid_min, min_err, _, _ = await db.validate_voucher("HEMAT5K", v_buyer_1, 10000)
    assert valid_min is False
    print(f"-> Validasi syarat minimum belanja dicegah: {min_err.splitlines()[0]}")

    # Beli 2 unit (20.000) dengan HEMAT5K -> diskon 5000, bayar 15000
    buy_v_ok, _, order_v = await db.purchase_product(v_buyer_1, "test_acc", quantity=2, voucher_code="HEMAT5K")
    assert buy_v_ok is True
    assert order_v["subtotal"] == 20000
    assert order_v["discount_amount"] == 5000
    assert order_v["price_paid"] == 15000
    assert order_v["remaining_balance"] == 35000
    print(f"-> Pembelian dengan voucher HEMAT5K sukses! Bayar Rp {order_v['price_paid']:,} (Hemat Rp {order_v['discount_amount']:,})")

    # Coba pakai ulang HEMAT5K oleh user yang sama -> harus ditolak
    reuse_ok, reuse_err, _, _ = await db.validate_voucher("HEMAT5K", v_buyer_1, 30000)
    assert reuse_ok is False
    assert "sudah pernah menggunakan" in reuse_err
    print(f"-> Validasi pemakaian ganda voucher dicegah: {reuse_err}")

    # User 2 beli dengan DISKON20 (20% dari 30.000 = 6.000 diskon)
    v_buyer_2 = 4444444444
    await db.add_balance(v_buyer_2, 50000)
    buy_pct_ok, _, order_pct = await db.purchase_product(v_buyer_2, "test_acc", quantity=3, voucher_code="DISKON20")
    assert buy_pct_ok is True
    assert order_pct["subtotal"] == 30000
    assert order_pct["discount_amount"] == 6000
    assert order_pct["price_paid"] == 24000
    print(f"-> Pembelian persen DISKON20 sukses! Bayar Rp {order_pct['price_paid']:,} (Diskon 20% = Rp {order_pct['discount_amount']:,})")

    # Cek kuota DISKON20 habis (max_uses = 1)
    v_buyer_3 = 5555555555
    quota_ok, quota_err, _, _ = await db.validate_voucher("DISKON20", v_buyer_3, 20000)
    assert quota_ok is False
    assert "habis" in quota_err
    print(f"-> Validasi kuota voucher habis berhasil dicegah: {quota_err}")

    print("\n=== [13] Pengujian Sistem Ulasan & Testimoni ===")
    # Simpan ulasan untuk order_v
    review_ok, review_msg = await db.record_review(
        order_id=order_v["order_id"],
        user_id=v_buyer_1,
        product_id="test_acc",
        rating=5,
        comment="Pengiriman super cepat dan akun langsung login!"
    )
    assert review_ok is True
    assert await db.has_order_been_reviewed(order_v["order_id"]) is True
    print(f"-> Ulasan bintang 5 berhasil disimpan untuk {order_v['order_id']}")

    # Coba beri ulasan kedua kali untuk order yang sama -> harus ditolak
    dup_rev_ok, dup_rev_err = await db.record_review(
        order_id=order_v["order_id"],
        user_id=v_buyer_1,
        product_id="test_acc",
        rating=4,
        comment="Ulasan duplikat"
    )
    assert dup_rev_ok is False
    assert "sudah pernah" in dup_rev_err
    print(f"-> Ulasan ganda untuk order yang sama dicegah: {dup_rev_err}")

    # Cek rata-rata rating produk
    rating_stat = await db.get_product_rating("test_acc")
    assert rating_stat["total_reviews"] == 1
    assert rating_stat["average_rating"] == 5.0
    print(f"-> Statistik rating produk: ⭐ {rating_stat['average_rating']} ({rating_stat['total_reviews']} ulasan)")

    print("\n=== [14] Pengujian Integrasi Saweria Webhook ===")
    from cogs.webhook import WebhookCog
    from aiohttp.test_utils import TestServer, TestClient

    class MockUser:
        def __init__(self, uid, name):
            self.id = uid
            self.name = name
            self.dms_received = []

        async def send(self, *args, **kwargs):
            self.dms_received.append((args, kwargs))

    class MockChannel:
        def __init__(self):
            self.messages = []

        async def send(self, *args, **kwargs):
            self.messages.append((args, kwargs))

    mock_channel = MockChannel()
    mock_customer = MockUser(test_user_id, "FauruxTester")

    class MockDiscordBot:
        def __init__(self, database):
            self.db = database
            self.user = MockUser(9999999999, "AutoStoreBot")

        async def fetch_user(self, uid):
            if uid == test_user_id:
                return mock_customer
            return None

        def get_channel(self, cid):
            return mock_channel

    mock_bot = MockDiscordBot(db)
    webhook_cog = WebhookCog(mock_bot)

    client = TestClient(TestServer(webhook_cog.app))
    await client.start_server()

    # 1. Health check
    resp = await client.get("/health")
    assert resp.status == 200
    health_data = await resp.json()
    assert health_data["status"] == "online"
    print("-> Health check endpoint responding 200 OK.")

    # 2. Saweria notification with Discord User ID in message
    bal_before = await db.get_balance(test_user_id)
    saweria_payload = {
        "amount_raw": 25000,
        "donator_name": "Budi Santoso",
        "message": f"Topup saldo store bot id {test_user_id} makasih min",
        "id": "saweria-tx-12345"
    }
    resp = await client.post("/saweria-webhook", json=saweria_payload)
    assert resp.status == 200
    res_json = await resp.json()
    assert res_json["status"] == "success"
    assert res_json["amount"] == 25000
    bal_after = await db.get_balance(test_user_id)
    assert bal_after == bal_before + 25000
    assert len(mock_customer.dms_received) > 0
    print(f"-> Webhook Saweria dengan Discord ID berhasil: Saldo bertambah Rp 25,000 (Total: Rp {bal_after:,})")

    # 3. Saweria notification with DEP ticket
    dep_saweria = await db.create_deposit_request(test_user_id, 15000, "saweria_auto")
    resp_ticket = await client.post("/saweria-webhook", json={
        "amount_raw": 15000,
        "donator_name": "Andi",
        "message": f"Bayar deposit tiket {dep_saweria}",
        "id": "saweria-tx-67890"
    })
    assert resp_ticket.status == 200
    dep_checked = await db.get_deposit_request(dep_saweria)
    assert dep_checked["status"] == "APPROVED"
    print(f"-> Webhook Saweria dengan Tiket {dep_saweria} berhasil: Tiket ter-approve otomatis!")

    # 4. Saweria notification without Discord ID (fallback safety)
    resp_anon = await client.post("/saweria-webhook", json={
        "amount_raw": 50000,
        "donator_name": "Anonim Tanpa ID",
        "message": "Semangat ya min!",
        "id": "saweria-tx-99999"
    })
    assert resp_anon.status == 200
    anon_json = await resp_anon.json()
    assert anon_json["status"] == "received"
    assert "warning" in anon_json
    print("-> Webhook Saweria tanpa Discord ID ditangani dengan aman (status received, admin alerted).")

    await client.close()

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
