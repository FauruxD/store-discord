-- Tabel Pengguna & Saldo
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
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
