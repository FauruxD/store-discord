# 🏪 Discord Automated Store Bot (Persistent UI & Auto-Delivery)

Bot Discord Store modern yang berjalan **100% otomatis 24/7** dengan arsitektur **Persistent UI (Buttons & Select Menus)**, database transaksi aman (**ACID SQLite** via `aiosqlite`), serta pengiriman file digital instan (`.lua`, `.zip`, `.txt`) langsung ke DM pelanggan.

---

## 🌟 Fitur Utama

1. **Persistent Dashboard UI**:
   - Tombol utama tidak pernah mati/kadaluarsa meskipun bot direstart (`timeout=None` & static `custom_id`).
   - Tombol:
     - 🛒 **Beli Produk**: Membuka katalog dropdown menu produk.
     - 💳 **Deposit Saldo**: Menampilkan instruksi pembayaran, rekening, QRIS statis, dan modal konfirmasi pembayaran.
     - 💰 **Cek Balance**: Menampilkan saldo akun pengguna secara privat (ephemeral).
     - 📖 **Tutorial**: Panduan cara belanja step-by-step.
2. **Sistem Saldo & Deposit Terverifikasi**:
   - User mengisi nominal transfer dan link/catatan bukti via Modal form.
   - Panel khusus Admin dikirim ke channel log dengan tombol interaktif: `[✅ Approve]` dan `[❌ Reject]`.
   - Notifikasi otomatis dikirim ke DM user saat deposit disetujui.
3. **Katalog Dinamis & Checkout Otomatis (Anti-Race Condition)**:
   - Menampilkan dropdown produk yang memiliki stok > 0.
   - Pengecekan saldo dan stok dilakukan dalam **satu transaksi atomic database** (`BEGIN IMMEDIATE` -> `COMMIT`), mencegah double-spending atau saldo minus.
4. **Auto-Send File Digital Produk**:
   - File fisik (`.lua`, `.zip`, `.txt`) langsung dikirimkan ke **Direct Message (DM)** pembeli beserta embed invoice resmi.
   - **Fallback Mechanism**: Jika DM pembeli dalam keadaan tertutup/terkunci, bot otomatis mengirimkan file secara **Ephemeral** di channel server sehingga file tidak pernah hilang.
5. **Panel Manajemen Admin**:
   - `/setup_store`: Pasang embed dashboard toko di channel publik server.
   - `/add_product`: Daftarkan produk digital baru dengan stok dan tautan file.
   - `/add_balance`: Tambahkan/kurangi saldo user secara manual.
   - `/list_products`: Tinjau status seluruh inventaris produk dan kesiapan file.

---

## 📁 Struktur Direktori

```
Gabut 8 - Bot Discord Auto Store/
├── assets/
│   ├── qris_sample.png            # Gambar QRIS statis untuk instruksi pembayaran
│   └── products/                  # Direktori file digital produk (.lua, .zip, .txt)
│       ├── premium_script.lua
│       └── vip_license.txt
├── database/
│   ├── __init__.py
│   ├── schema.sql                 # Skema DDL: users, products, orders, deposits
│   └── manager.py                 # Async Database Manager (CRUD & Atomic Transactions)
├── views/
│   ├── __init__.py
│   ├── dashboard.py               # Main Persistent Dashboard View (Buy, Deposit, Balance, Help)
│   ├── catalog.py                 # Dynamic Product Dropdown & Confirmation View
│   └── deposit.py                 # Modal form & Admin confirmation views (Approve/Reject)
├── cogs/
│   ├── __init__.py
│   ├── store.py                   # Event handler & UI routing
│   └── admin.py                   # Slash commands: /setup_store, /add_product, /deposit_action
├── config.py                      # Konfigurasi Environment & Bot Constants
├── main.py                        # Entry point bot, registration of persistent views
├── requirements.txt               # Dependencies: discord.py, aiosqlite, python-dotenv
├── .env.example                   # Template credential Discord token, guild ID, admin role ID
└── README.md                      # Dokumentasi & panduan setup
```

---

## 🚀 Panduan Instalasi & Menjalankan Bot

### 1. Prasyarat
- **Python 3.10** atau lebih baru.
- Akun Discord & Bot Application dari [Discord Developer Portal](https://discord.com/developers/applications).

### 2. Aktifkan Intents di Discord Developer Portal
Pada tab **Bot** di aplikasi Discord Developer Portal Anda, pastikan untuk mengaktifkan:
- **Server Members Intent** (ON)
- **Message Content Intent** (ON)

### 3. Install Dependensi
Buka terminal/PowerShell di folder proyek ini dan jalankan:
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment (`.env`)
Salin file `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```
Buka `.env` dan sesuaikan nilainya:
```env
DISCORD_TOKEN=OTkxMjM... (Token bot Discord Anda)
GUILD_ID=123456789012345678 (ID Server Discord Anda untuk sinkronisasi slash command instan)

ADMIN_ROLE_ID=123456789012345678 (ID Role admin/staff verifikasi deposit)
DEPOSIT_LOG_CHANNEL_ID=123456789012345678 (ID Channel log tiket deposit admin)
TRANSACTION_LOG_CHANNEL_ID=123456789012345678 (ID Channel log transaksi pembelian)

QRIS_IMAGE_URL=https://dummyimage.com/600x600/0f172a/38bdf8&text=SCAN+QRIS+UNTUK+DEPOSIT
BANK_TRANSFER_INFO=• Bank BCA: 123-456-7890 (A/N STORE)\n• DANA / GoPay: 0812-3456-7890
```

### 5. Jalankan Bot
```bash
python main.py
```

---

## 🛠️ Panduan Penggunaan di Server Discord

1. **Pasang Dashboard Store:**
   Ketik slash command di channel yang diinginkan (misal `#store`):
   ```
   /setup_store
   ```
   Bot akan mengirimkan embed interaktif dengan tombol **Beli Produk**, **Deposit Saldo**, **Cek Balance**, dan **Tutorial**.

2. **Menambahkan Produk Baru:**
   - Letakkan file digital Anda di folder `assets/products/` (misal: `cheat_v2.lua` atau `config.zip`).
   - Jalankan perintah slash command:
     ```
     /add_product product_id:cheat_v2 name:Cheat V2 VIP price:35000 stock:10 file_name:cheat_v2.lua description:Script bypass anti-cheat versi terbaru
     ```

3. **Alur Deposit Pengguna:**
   - Pengguna menekan tombol **💳 Deposit Saldo**.
   - Pengguna melakukan transfer ke QRIS/Bank yang tertera, lalu mengklik tombol **Isi Formulir Konfirmasi Deposit**.
   - Admin menerima tiket di channel log deposit, lalu menekan **[✅ Approve]**.
   - Saldo pengguna otomatis bertambah dan pengguna menerima notifikasi DM.

4. **Alur Pembelian Otomatis:**
   - Pengguna menekan **🛒 Beli Produk**.
   - Pengguna memilih produk dari dropdown.
   - Pengguna menekan **⚡ Konfirmasi Pembelian**.
   - Saldo dipotong, stok dikurangi, dan file produk langsung dikirimkan ke DM pembeli secara instan!
