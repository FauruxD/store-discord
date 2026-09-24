-- ==============================================================================
-- LUCIFER LUA v2.86 - AUTOMATED DONATION BOX DEPOSIT LISTENER (STABLE V4)
-- ==============================================================================
-- Script ini berjalan di executor Lucifer bot untuk mendeteksi deposit
-- World Lock, Diamond Lock, dan Blue Gem Lock via Donation Box in-game Growtopia.
-- Begitu lock masuk, bot akan langsung mengirimkan data ke Webhook Server Discord Store.
-- ==============================================================================

-- JADIKAN CONFIG GLOBAL agar tidak terjadi error: attempt to index a nil value (upvalue 'CONFIG')
CONFIG = {
    -- Nama world tempat bot stand-by menjaga donation box
    WORLD_NAME = "MEKAYAM",
    
    -- Door ID jika donation box berada di dalam pintu khusus (kosongkan jika tidak ada)
    DOOR_ID = "",

    -- URL Webhook Server Bot Discord
    API_URL = "https://discord.faru.web.id/gt-deposit",

    -- Token rahasia yang sama dengan GROWTOPIA_SECRET_TOKEN di file .env Discord Bot
    SECRET_TOKEN = "3212382761832",

    -- Apakah bot membalas via /msg privat in-game ke donatur setelah deposit diterima
    ENABLE_INGAME_MSG = true,

    -- (Opsional) Discord Webhook langsung untuk backup notifikasi ke channel Discord
    DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1552573711763120170/dN5tqH9OoQpynprLa3JHjbASqsh8v3MX-wbWYClmKGQuJP1mSEyI3WbDXHetbYzILoWN",

    -- Tampilkan seluruh teks chat yang masuk ke console Lucifer untuk kemudahan debugging
    DEBUG_MODE = true
}

-- Inisialisasi Bot
local bot = getBot()
if bot == nil then
    print("[ERROR] Script ini harus dijalankan di dalam konteks bot Lucifer!")
    return
end

print("==================================================")
print("  LUCIFER DONATION BOX AUTO-DEPOSIT v2.86 ACTIVE  ")
print("  Bot Name : " .. bot.name)
print("  Target   : World " .. CONFIG.WORLD_NAME)
print("  API URL  : " .. CONFIG.API_URL)
print("  Debug    : " .. tostring(CONFIG.DEBUG_MODE))
print("==================================================")

-- Aktifkan auto reconnect bawaan Lucifer
bot.auto_reconnect = true

-- Aktifkan console reader jika didukung
pcall(function()
    local c = getConsole()
    if c then
        c.enabled = true
        print("[INIT] Console reader diaktifkan (c.enabled = true).")
    end
end)

-- Cache memori untuk mencegah double-trigger jika game mengirimkan pesan duplikat
local recent_cache = {}

-- Fungsi untuk membersihkan cache lama dan cek duplikasi
local function isDuplicate(growid, count, item_name)
    local now = os.time()
    local key = string.lower(growid) .. ":" .. count .. ":" .. string.lower(item_name)

    -- Hapus cache yang lebih dari 15 detik
    for k, timestamp in pairs(recent_cache) do
        if now - timestamp > 15 then
            recent_cache[k] = nil
        end
    end

    if recent_cache[key] and (now - recent_cache[key] <= 8) then
        return true
    end

    recent_cache[key] = now
    return false
end

-- Fungsi menentukan rate konversi lock ke World Lock (WL)
local function getItemRate(raw_item_name)
    local lower = string.lower(raw_item_name)
    if string.find(lower, "world lock") then
        return 1, "World Lock"
    elseif string.find(lower, "diamond lock") then
        return 100, "Diamond Lock"
    elseif string.find(lower, "blue gem lock") then
        return 10000, "Blue Gem Lock"
    end
    return 0, nil
end

-- Fungsi mem-parsing teks donasi dari berbagai format Growtopia
local function parseDonation(raw_text)
    local raw_str = tostring(raw_text)

    -- [SECURITY 1] Tolak jika teks mengandung tanda chat pemain (<GrowID>, : bicara, **, dll)
    if string.find(raw_str, "<") or string.find(raw_str, ">") or string.find(raw_str, ":%s") or string.find(raw_str, "%*%*") then
        return nil, nil, nil, raw_str
    end

    -- 1. Hapus kode warna bawaan Lucifer jika ada
    local clean = removeColor(raw_str)

    -- 2. Hapus semua backtick color code Growtopia (`0, `1, `2, `w, `b, `p, `c, `^, dll)
    clean = string.gsub(clean, "`.", "")
    clean = string.gsub(clean, "`", "")

    -- 3. Hapus timestamp [04:03:02] di awal teks jika ada
    clean = string.gsub(clean, "^%[%d+:%d+:%d+%]%s*", "")
    clean = string.gsub(clean, "^%s*(.-)%s*$", "%1")

    local lower = string.lower(clean)

    -- [SECURITY 2] Cek kata kunci wajib donasi
    if not (string.find(lower, "donation box") or string.find(lower, "display box") or string.find(lower, "has donated")) then
        return nil, nil, nil, clean
    end

    local growid, count_str, item_name = nil, nil, nil

    -- [SECURITY 3] Format 1 (Standar Sistem Growtopia Resmi):
    -- Pesan sistem GT WAJIB diawali kurung siku ganda [[ dan diakhiri into the Donation/Display Box]]
    -- Contoh: "[[FaruuXes places 193 World Lock into the Donation Box]]"
    growid, count_str, item_name = string.match(clean, "^%[%[([%w_]+)%s+places%s+(%d+)%s+(.-)%s+into the Donation Box%]%]$")

    if not growid then
        growid, count_str, item_name = string.match(clean, "^%[%[([%w_]+)%s+places%s+(%d+)%s+(.-)%s+into the Display Box%]%]$")
    end

    -- Format 2 (Standar Sistem Alternatif Resmi GT):
    -- Contoh: "FaruuXes has donated 1 World Lock."
    if not growid then
        growid, count_str, item_name = string.match(clean, "^([%w_]+)%s+has%s+donated%s+(%d+)%s+(.-)%.$")
    end

    if growid and count_str and item_name then
        local count = tonumber(count_str)
        if count and count > 0 then
            item_name = string.gsub(item_name, "%(s%)", "")
            item_name = string.gsub(item_name, "%.+$", "")
            item_name = string.gsub(item_name, "^%s*(.-)%s*$", "%1")

            -- [SECURITY 4] Validasi ketat nama item hanya Lock yang didukung
            local rate, valid_item_name = getItemRate(item_name)
            if rate > 0 and valid_item_name then
                return growid, count, valid_item_name, clean
            end
        end
    end

    return nil, nil, nil, clean
end

-- Fungsi mengirim data deposit ke Webhook Server Bot Discord
local function notifyServer(growid, count, item_name, amount_wl)
    -- 1. Backup: Kirim notifikasi langsung via Discord Webhook jika ada
    if CONFIG.DISCORD_WEBHOOK_URL and CONFIG.DISCORD_WEBHOOK_URL ~= "" then
        pcall(function()
            local hook = Webhook.new(CONFIG.DISCORD_WEBHOOK_URL)
            hook.username = "Lucifer GT Deposit"
            hook.content = string.format("🎉 **Deposit Terdeteksi!**\n👤 GrowID: **`%s`**\n📦 Item: **%d %s** (+%d WL)\n🌍 World: **`%s`**", growid, count, item_name, amount_wl, CONFIG.WORLD_NAME)
            hook:send()
        end)
    end

    -- 2. Kirim ke Server Bot Discord API
    local client = HttpClient.new()
    client.url = CONFIG.API_URL
    client:setMethod(Method.post)
    client.headers["Content-Type"] = "application/json"
    client.headers["User-Agent"] = "Mozilla/5.0"
    client.headers["X-GT-Token"] = CONFIG.SECRET_TOKEN

    local payload = string.format(
        '{"growid":"%s","item_name":"%s","count":%d,"amount_wl":%d,"world":"%s"}',
        growid, item_name, count, amount_wl, CONFIG.WORLD_NAME
    )
    client.content = payload
    client.timeout = 8

    print("[HTTP] Mengirim deposit ke: " .. CONFIG.API_URL)
    local result = client:request()
    if result.error == 0 and result.status == 200 then
        print(string.format("[SUCCESS] Terverifikasi: %s mendepositkan %d %s (+%d WL)", growid, count, item_name, amount_wl))
        
        -- Cek apakah user unclaimed atau sukses
        if string.find(result.body or "", "unclaimed") then
            if CONFIG.ENABLE_INGAME_MSG then
                bot:say("/msg " .. growid .. " [STORE] GrowID kamu belum disetting di Discord! Ketik /setgrowid di bot Discord.")
            end
        else
            if CONFIG.ENABLE_INGAME_MSG then
                bot:say("/msg " .. growid .. " [STORE] Deposit " .. count .. "x " .. item_name .. " (+" .. amount_wl .. " WL) BERHASIL masuk!")
            end
        end
        return true
    else
        print(string.format("[ERROR] Gagal mengirim deposit ke server. Status: %s, Error: %s, Body: %s", tostring(result.status), tostring(result.error), tostring(result.body)))
        return false
    end
end

-- Handler utama saat ada teks/pesan dari server Growtopia
local function handleMessage(raw_message, source_tag)
    if not raw_message or raw_message == "" then
        return
    end

    local growid, count, raw_item, clean_text = parseDonation(raw_message)
    local lower = string.lower(clean_text)

    -- Debug: Tampilkan pesan apapun yang masuk ke log Lucifer
    if CONFIG.DEBUG_MODE then
        -- Saring spam umum seperti ping/pong/action agar tidak terlalu bising
        if not string.find(lower, "ping") and not string.find(lower, "action|") then
            print(string.format("[DEBUG][%s] %s", source_tag or "CHAT", clean_text))
        end
    end

    -- Jika donasi terverifikasi sah
    if growid and count and raw_item then
        local rate, valid_item_name = getItemRate(raw_item)
        if rate > 0 and valid_item_name then
            -- Cegah pemrosesan ganda
            if not isDuplicate(growid, count, valid_item_name) then
                local total_wl = count * rate
                print(string.format(">>> [AUTHENTIC DONATION DETECTED] %s -> %d %s (=%d WL) <<<", growid, count, valid_item_name, total_wl))
                -- Eksekusi langsung pengiriman
                notifyServer(growid, count, valid_item_name, total_wl)
            else
                print("[DUPLICATE] Pesan donasi diabaikan karena baru saja diproses.")
            end
        else
            print("[DONATION IGNORED] Item '" .. tostring(raw_item) .. "' bukan WL/DL/BGL.")
        end
    end
end

-- 1. Daftarkan event game_message (Pesan sistem server)
addEvent(Event.game_message, function(msg)
    if CONFIG.DEBUG_MODE then
        print("[RAW game_message] " .. tostring(msg))
    end
    handleMessage(msg, "game_message")
end)

-- 2. Daftarkan event generic_text
addEvent(Event.generic_text, function(text)
    if CONFIG.DEBUG_MODE then
        print("[RAW generic_text] " .. tostring(text))
    end
    handleMessage(text, "generic_text")
end)

-- 3. Daftarkan event variantlist (HANYA OnConsoleMessage)
-- [SECURITY 5] JANGAN dengarkan OnTalkBubble karena OnTalkBubble adalah gelembung chat pemain!
addEvent(Event.variantlist, function(varlist, net_id)
    pcall(function()
        local v0 = tostring(varlist[0] or "")
        local v1 = tostring(varlist[1] or "")
        local v2 = tostring(varlist[2] or "")

        if CONFIG.DEBUG_MODE then
            print(string.format("[RAW variantlist netid=%s] v0=%s | v1=%s | v2=%s", tostring(net_id), v0, v1, v2))
        end

        -- Hanya terima OnConsoleMessage, buang semua OnTalkBubble
        if v0 == "OnConsoleMessage" then
            handleMessage(v1, "OnConsoleMessage")
        elseif v1 == "OnConsoleMessage" then
            handleMessage(v2, "OnConsoleMessage")
        end
    end)
    -- Fallback sol2 userdata: varlist:get(0)
    pcall(function()
        if varlist.get then
            local g0 = varlist:get(0):getString()
            if g0 == "OnConsoleMessage" then
                local g1 = varlist:get(1):getString()
                if CONFIG.DEBUG_MODE then
                    print("[RAW varlist:get] OnConsoleMessage: " .. tostring(g1))
                end
                handleMessage(g1, "OnConsoleMessage")
            end
        end
    end)
end)

-- Callback saat script dihentikan
function on_stop(err)
    if err ~= "" and not string.find(string.lower(err), "exit_mode") then
        print("[LUCIFER STOPPED WITH ERROR] " .. err)
    else
        print("[LUCIFER STOPPED] Script dihentikan secara normal.")
    end
end

-- ==============================================================================
-- INITIAL SETUP & WARP
-- ==============================================================================
if not bot:isInWorld(CONFIG.WORLD_NAME) then
    print("[INFO] Bot belum berada di world " .. CONFIG.WORLD_NAME .. ". Memulai warp...")
    if CONFIG.DOOR_ID ~= "" then
        bot:warp(CONFIG.WORLD_NAME, CONFIG.DOOR_ID)
    else
        bot:warp(CONFIG.WORLD_NAME)
    end
    sleep(4000)
end

print("[INFO] Bot siap! Mendengarkan donation box di world " .. CONFIG.WORLD_NAME .. "...")

-- Cetak status diagnostik awal
pcall(function()
    local c = getConsole()
    print("[DIAGNOSTIC] getConsole(): " .. (c and "AVAILABLE" or "NIL") .. " | Content length: " .. (c and string.len(c.contents or "") or "0"))
    local l = getLog()
    print("[DIAGNOSTIC] getLog(): " .. (l and "AVAILABLE" or "NIL") .. " | Content length: " .. (l and string.len(l.content or "") or "0"))
    print("[DIAGNOSTIC] bot.history: " .. (bot.history and tostring(#bot.history) or "NIL"))
end)

-- ==============================================================================
-- UNIFIED MAIN LOOP (Watchdog + Event Listener + Console & Log Scanner)
-- ==============================================================================
-- Semua berjalan di thread utama sehingga BEBAS DARI ERROR upvalue / cross-thread!
local last_warp_check = os.time()
local last_heartbeat = os.time()
local last_scanned_console = ""
local last_scanned_log = ""
local scanned_history_set = {}

while true do
    local now = os.time()

    -- Cetak detak jantung setiap 10 detik agar terlihat aktif di console Lucifer
    if now - last_heartbeat >= 10 then
        last_heartbeat = now
        if CONFIG.DEBUG_MODE then
            local w_name = bot:getWorld() and bot:getWorld().name or "Unknown"
            print(string.format("[HEARTBEAT] Bot %s aktif menjaga world %s", bot.name, w_name))
        end
    end

    -- 1. Watchdog: Pastikan bot selalu berada di world target setiap 5 detik
    if now - last_warp_check >= 5 then
        last_warp_check = now
        if bot.status == BotStatus.online and not bot:isInWorld(CONFIG.WORLD_NAME) then
            print("[WATCHDOG] Bot tidak berada di world " .. CONFIG.WORLD_NAME .. ". Melakukan warp...")
            if CONFIG.DOOR_ID ~= "" then
                bot:warp(CONFIG.WORLD_NAME, CONFIG.DOOR_ID)
            else
                bot:warp(CONFIG.WORLD_NAME)
            end
            sleep(3000)
        end
    end

    -- 2. Pump Events (1 detik) - memanggil callback addEvent secara otomatis
    pcall(function()
        listenEvents(1)
    end)

    -- 3. Scan Console (getConsole)
    pcall(function()
        local c = getConsole()
        if c and c.contents and c.contents ~= "" and c.contents ~= last_scanned_console then
            local full_text = c.contents
            last_scanned_console = full_text
            for line in string.gmatch(full_text, "[^\r\n]+") do
                local lower = string.lower(line)
                if string.find(lower, "places") or string.find(lower, "donat") or string.find(lower, "deposit") then
                    handleMessage(line, "Console")
                end
            end
        end
    end)

    -- 4. Scan Log (getLog)
    pcall(function()
        local l = getLog()
        if l and l.content and l.content ~= "" and l.content ~= last_scanned_log then
            local full_text = l.content
            last_scanned_log = full_text
            for line in string.gmatch(full_text, "[^\r\n]+") do
                local lower = string.lower(line)
                if string.find(lower, "places") or string.find(lower, "donat") or string.find(lower, "deposit") then
                    handleMessage(line, "Log")
                end
            end
        end
    end)

    -- 5. Scan Bot History
    pcall(function()
        if bot and bot.history then
            for _, hist_entry in ipairs(bot.history) do
                local h_str = tostring(hist_entry)
                if not scanned_history_set[h_str] then
                    scanned_history_set[h_str] = true
                    local lower = string.lower(h_str)
                    if string.find(lower, "places") or string.find(lower, "donat") or string.find(lower, "deposit") then
                        handleMessage(h_str, "BotHistory")
                    end
                end
            end
        end
    end)

    sleep(50)
end




