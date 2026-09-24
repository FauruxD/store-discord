-- Tabel Pengguna & Saldo
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    balance_wl INTEGER NOT NULL DEFAULT 0 CHECK(balance_wl >= 0),
    growid TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Tabel Katalog Produk Digital
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    price INTEGER NOT NULL CHECK(price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
    file_path TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'FILE', -- FILE atau ACCOUNT
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabel Riwayat Pembelian (Orders)
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    price_paid INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    delivered_data TEXT,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);

-- Tabel Permintaan Deposit / Top-up
CREATE TABLE IF NOT EXISTS deposits (
    deposit_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    proof_url TEXT,
    channel_id INTEGER,
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED
    reviewed_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

-- Tabel Stok Akun Digital (Per Baris)
CREATE TABLE IF NOT EXISTS product_accounts (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    account_data TEXT NOT NULL,
    is_sold INTEGER NOT NULL DEFAULT 0, -- 0 = Tersedia, 1 = Terjual
    order_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sold_at TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- Tabel Voucher / Kode Promo
CREATE TABLE IF NOT EXISTS vouchers (
    code TEXT PRIMARY KEY,
    discount_type TEXT NOT NULL CHECK(discount_type IN ('PERCENT', 'FLAT')), -- PERCENT (1-100) atau FLAT (Rupiah)
    discount_value INTEGER NOT NULL CHECK(discount_value > 0),
    min_spend INTEGER NOT NULL DEFAULT 0 CHECK(min_spend >= 0),
    max_uses INTEGER NOT NULL DEFAULT 0 CHECK(max_uses >= 0), -- 0 = Unlimited
    current_uses INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabel Riwayat Penggunaan Voucher
CREATE TABLE IF NOT EXISTS voucher_usages (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    order_id TEXT NOT NULL,
    discount_applied INTEGER NOT NULL,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(code) REFERENCES vouchers(code) ON DELETE CASCADE
);

-- Tabel Ulasan / Testimoni Pelanggan
CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);

-- Tabel Riwayat Deposit World Growtopia (Donation Box / Lucifer Bot)
CREATE TABLE IF NOT EXISTS gt_deposits (
    deposit_id TEXT PRIMARY KEY,
    user_id INTEGER,
    growid TEXT NOT NULL,
    item_name TEXT NOT NULL,
    count INTEGER NOT NULL CHECK(count > 0),
    amount_wl INTEGER NOT NULL CHECK(amount_wl > 0),
    world TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SUCCESS', -- SUCCESS, UNCLAIMED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);


